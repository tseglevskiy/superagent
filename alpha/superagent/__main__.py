"""CLI entry point — python -m superagent

A readline loop that:
  1. Reads user input
  2. Appends it to the session JSONL on disk
  3. Runs the stateless engine turn (read disk → LLM → write disk)
  4. Prints the response
  5. Repeats

Special commands:
  /new     — archive current session, start fresh
  /status  — show session stats and config
  /quit    — exit
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from .bus import EventBus
from .config import load_config
from .engine import add_user_message, new_session, run_agent_turn, session_message_count, set_verbose
from .llm import make_client
from .memory import ensure_block_files
from .tools import build_registry


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="superagent",
        description="File workspace assistant with knowledge processing",
    )
    p.add_argument(
        "--workspace", "-w",
        type=Path,
        default=None,
        help="Workspace directory (default: cwd)",
    )
    p.add_argument(
        "--data-dir", "-d",
        type=Path,
        default=None,
        help="Data directory (default: ~/.superagent-sandbox)",
    )
    p.add_argument(
        "--provider", "-p",
        choices=["openrouter", "ollama"],
        default=None,
        help="LLM provider (default: from config or openrouter)",
    )
    p.add_argument(
        "--model", "-m",
        default=None,
        help="Override chat model name",
    )
    p.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable debug logging",
    )
    return p.parse_args()


def setup_logging(verbose: bool) -> None:
    # Suppress library noise, our debug goes through _dbg() in engine.py
    logging.basicConfig(
        level=logging.WARNING,
        format="%(name)s: %(message)s",
    )
    set_verbose(verbose)


def print_banner(cfg) -> None:
    provider = cfg.llm.provider
    if provider == "openrouter":
        model = cfg.llm.chat_model
    else:
        model = cfg.llm.ollama_model
    msgs = session_message_count(cfg)
    print(f"\033[1msuperagent alpha\033[0m")
    print(f"  workspace: {cfg.workspace}")
    print(f"  provider:  {provider}  model: {model}")
    print(f"  data:      {cfg.data_dir}")
    if msgs > 0:
        print(f"  session:   {msgs} messages (continuing)")
    print(f"  commands:  /new /status /quit")
    print()


def handle_slash_command(cmd: str, cfg, bus: EventBus) -> bool:
    """Handle slash commands.  Returns True if the command was handled."""
    cmd = cmd.strip().lower()

    if cmd == "/quit":
        print("bye")
        sys.exit(0)

    if cmd == "/new":
        new_session(cfg)
        print("[new session started]")
        return True

    if cmd == "/status":
        msgs = session_message_count(cfg)
        print(f"  messages:  {msgs}")
        print(f"  workspace: {cfg.workspace}")
        print(f"  provider:  {cfg.llm.provider}")
        print(f"  data:      {cfg.data_dir}")
        return True

    return False


def main() -> None:
    args = parse_args()
    setup_logging(args.verbose)

    # --- config ---
    cfg = load_config(
        workspace=args.workspace,
        data_dir=args.data_dir,
        provider=args.provider,
    )
    if args.model:
        if cfg.llm.provider == "ollama":
            cfg.llm.ollama_model = args.model
        else:
            cfg.llm.chat_model = args.model

    # --- init ---
    ensure_block_files(cfg.memory_dir)
    bus = EventBus()
    registry = build_registry(cfg.workspace, cfg.memory_dir)


    # --- LLM client ---
    try:
        client = make_client(cfg.llm)
    except ValueError as e:
        print(f"\033[31mError: {e}\033[0m", file=sys.stderr)
        sys.exit(1)

    # --- banner ---
    print_banner(cfg)

    # --- readline loop ---
    while True:
        try:
            user_input = input("\033[32m> \033[0m")
        except (EOFError, KeyboardInterrupt):
            print("\nbye")
            break

        user_input = user_input.strip()
        if not user_input:
            continue

        # slash commands
        if user_input.startswith("/"):
            if handle_slash_command(user_input, cfg, bus):
                continue
            print(f"[unknown command: {user_input}]")
            continue

        # --- the core loop: write to disk → call LLM → write to disk ---
        add_user_message(cfg, user_input)

        try:
            response = run_agent_turn(cfg, client, registry, bus)
        except KeyboardInterrupt:
            print("\n[interrupted]")
            continue
        except Exception as e:
            logging.getLogger(__name__).exception("turn failed")
            print(f"\033[31m[error: {e}]\033[0m")
            continue

        print()
        print(response)
        print()


if __name__ == "__main__":
    main()
