"""Smoke tests for shell_sandbox.py

Usage:
    python test_shell_sandbox.py /path/to/agent/workdir
    # or via the shell wrapper:
    bash superagent/alpha/test_shell_sandbox.sh
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Agent working directory — passed as argv[1]
if len(sys.argv) < 2:
    print("Usage: python test_shell_sandbox.py <agent_workdir>", file=sys.stderr)
    sys.exit(1)

AGENT_DIR = Path(sys.argv[1]).resolve()
AGENT_DIR.mkdir(parents=True, exist_ok=True)

# Ensure .git exists in the test dir so .git protection can be tested
git_dir = AGENT_DIR / ".git"
if not git_dir.exists():
    git_dir.mkdir()
    (git_dir / "HEAD").write_text("ref: refs/heads/main\n")

# Ensure .superagent exists so protection can be tested
sa_dir = AGENT_DIR / ".superagent"
sa_dir.mkdir(exist_ok=True)
(sa_dir / "config.yaml").write_text("test: true\n")

# Import directly from the self-contained integration file
import importlib.util
_spec = importlib.util.spec_from_file_location(
    "_shell_exec",
    str(Path(__file__).parent / "alpha" / "integration" / "shell_exec.py"),
)
_mod = importlib.util.module_from_spec(_spec)
sys.modules["_shell_exec"] = _mod
_spec.loader.exec_module(_mod)

# Use the internal _sandbox_run for direct testing (bypasses workspace global)
_sandbox_run = _mod._sandbox_run
def run(command, cwd=None, allow_network=False, allow_git_write=False, timeout=30.0):
    return _sandbox_run(
        command, cwd=cwd or AGENT_DIR, timeout=timeout,
        allow_network=allow_network, allow_git_write=allow_git_write,
    )


def header(name):
    print(f"\n{'='*60}")
    print(f"TEST: {name}")


def check(name, result, expect_ok=None, expect_denied=None):
    header(name)
    status = "PASS" if result.ok else "FAIL"
    denied = " [SANDBOX DENIED]" if result.sandbox_denied else ""
    print(f"  {status}{denied}  exit={result.exit_code}  time={result.duration_seconds:.2f}s")
    if result.stdout.strip():
        print(f"  stdout: {result.stdout.strip()[:200]}")
    if result.stderr.strip():
        print(f"  stderr: {result.stderr.strip()[:200]}")
    if result.sandbox_denial_detail:
        print(f"  denial: {result.sandbox_denial_detail}")

    ok = True
    if expect_ok is not None and result.ok != expect_ok:
        print(f"  ** UNEXPECTED: expected ok={expect_ok}, got ok={result.ok}")
        ok = False
    if expect_denied is not None and result.sandbox_denied != expect_denied:
        print(f"  ** UNEXPECTED: expected denied={expect_denied}, got denied={result.sandbox_denied}")
        ok = False
    return ok


# Track pass/fail
results = []

# ── Basic operations ──────────────────────────────────────────

results.append(check(
    "echo (basic command)",
    run("echo hello world", cwd=AGENT_DIR),
    expect_ok=True, expect_denied=False,
))

results.append(check(
    "write to CWD",
    run("echo test > sandbox_test.txt && cat sandbox_test.txt", cwd=AGENT_DIR),
    expect_ok=True, expect_denied=False,
))

results.append(check(
    "write to /tmp",
    run("echo ok > /tmp/shell_sandbox_test.txt && cat /tmp/shell_sandbox_test.txt", cwd=AGENT_DIR),
    expect_ok=True, expect_denied=False,
))

# ── Write protections ─────────────────────────────────────────

results.append(check(
    "write outside CWD (should be denied)",
    run("echo pwned > /Users/Shared/sandbox_escape.txt", cwd=AGENT_DIR),
    expect_ok=False, expect_denied=True,
))

results.append(check(
    "write to .git (should be denied)",
    run("echo pwned > .git/HEAD", cwd=AGENT_DIR),
    expect_ok=False, expect_denied=True,
))

results.append(check(
    "write to .superagent (should be denied)",
    run("echo pwned > .superagent/config.yaml", cwd=AGENT_DIR),
    expect_ok=False, expect_denied=True,
))

results.append(check(
    "write to .git with allow_git_write=True (should work)",
    run("echo '#!/bin/sh' > .git/test_hook && cat .git/test_hook", cwd=AGENT_DIR, allow_git_write=True),
    expect_ok=True, expect_denied=False,
))

# ── Read protections ──────────────────────────────────────────

results.append(check(
    "read ~/.ssh (should be denied)",
    run("ls ~/.ssh/", cwd=AGENT_DIR),
    expect_ok=False, expect_denied=True,
))

results.append(check(
    "read ~/Library/Keychains (should be denied)",
    run("ls ~/Library/Keychains/", cwd=AGENT_DIR),
    expect_ok=False, expect_denied=True,
))

results.append(check(
    "read /etc/hosts (should work - system path)",
    run("head -1 /etc/hosts", cwd=AGENT_DIR),
    expect_ok=True, expect_denied=False,
))

results.append(check(
    "read project files (should work)",
    run("ls .", cwd=AGENT_DIR),
    expect_ok=True, expect_denied=False,
))

# ── Network ───────────────────────────────────────────────────

results.append(check(
    "network blocked (default)",
    run("curl -s --connect-timeout 2 https://example.com", cwd=AGENT_DIR),
    expect_ok=False,
))

results.append(check(
    "network allowed",
    run("curl -s --connect-timeout 5 -o /dev/null -w '%{http_code}' https://example.com",
        cwd=AGENT_DIR, allow_network=True),
    expect_ok=True,
))

# ── for_llm() output ─────────────────────────────────────────

header("for_llm() output demo")
r = run("cat ~/.ssh/id_rsa", cwd=AGENT_DIR)
print(r.for_llm())

# ── Cleanup ───────────────────────────────────────────────────

import shutil
for f in [
    AGENT_DIR / "sandbox_test.txt",
    AGENT_DIR / ".git" / "test_hook",
    Path("/tmp/shell_sandbox_test.txt"),
]:
    try:
        f.unlink()
    except OSError:
        pass
# Remove test-created dirs (these are fake, not real git/superagent data)
for d in [AGENT_DIR / ".git", AGENT_DIR / ".superagent"]:
    try:
        shutil.rmtree(d)
    except OSError:
        pass

# ── Summary ───────────────────────────────────────────────────

print(f"\n{'='*60}")
passed = sum(1 for r in results if r)
total = len(results)
if passed == total:
    print(f"ALL {total} TESTS PASSED")
else:
    print(f"{passed}/{total} tests passed, {total - passed} FAILED")
    sys.exit(1)
