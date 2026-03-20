"""Shell command execution in a macOS Seatbelt sandbox.

Integration module — auto-discovered by the integration loader.
Self-contained: no imports from superagent package.

Two functions are injected into the agent's sandbox namespace:
  shell_run(command, ...)     — run a command, return formatted output
  shell_run_raw(command, ...) — run a command, return a dict with all fields

Every command is wrapped with /usr/bin/sandbox-exec and a dynamically
generated Seatbelt profile.  The kernel enforces:
  - Full disk read (except ~/Library and ~/.dotfiles)
  - Writes only within workspace, /tmp, $TMPDIR
  - .git and .superagent inside workspace are read-only by default
  - Network blocked by default
  - Child processes inherit all restrictions

Inspired by Codex CLI (codex-rs/core/src/seatbelt.rs).
macOS only — requires /usr/bin/sandbox-exec (ships with macOS).
"""

from __future__ import annotations

import ctypes
import ctypes.util
import logging
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

log = logging.getLogger(__name__)

_workspace: Path = Path.cwd()

_SANDBOX_EXEC = "/usr/bin/sandbox-exec"

_DENIAL_KEYWORDS = (
    "operation not permitted",
    "permission denied",
    "read-only file system",
    "sandbox",
)


# ── Result ────────────────────────────────────────────────────────────────


@dataclass
class _ShellResult:
    stdout: str
    stderr: str
    exit_code: int
    duration_seconds: float
    sandbox_enforced: bool
    sandbox_denied: bool
    sandbox_denial_detail: str
    effective_command: list[str]

    @property
    def ok(self) -> bool:
        return self.exit_code == 0

    def for_llm(self) -> str:
        parts: list[str] = []
        if self.sandbox_denied:
            parts.append(
                f"SANDBOX DENIED: {self.sandbox_denial_detail}\n"
                "The command was blocked by the macOS sandbox. "
                "If this operation is needed, re-run with the appropriate "
                "permission flag (e.g. allow_git_write=True for git "
                "operations, allow_network=True for network access)."
            )
        if self.exit_code != 0:
            parts.append(f"Exit code: {self.exit_code}")
        if self.stdout.strip():
            parts.append(f"stdout:\n{self.stdout.strip()}")
        if self.stderr.strip():
            parts.append(f"stderr:\n{self.stderr.strip()}")
        if not self.stdout.strip() and not self.stderr.strip():
            if self.exit_code == 0:
                parts.append("(command succeeded with no output)")
            else:
                parts.append("(command failed with no output)")
        parts.append(f"[{self.duration_seconds:.1f}s]")
        return "\n\n".join(parts)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "exit_code": self.exit_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "duration": self.duration_seconds,
            "sandbox_denied": self.sandbox_denied,
            "sandbox_detail": self.sandbox_denial_detail,
        }


# ── Sandbox runner ────────────────────────────────────────────────────────


def _canonicalize(p: Path) -> str:
    try:
        return str(p.resolve())
    except OSError:
        return str(p)


def _resolve_git_pointer(git_file: Path) -> str | None:
    try:
        content = git_file.read_text().strip()
        if content.startswith("gitdir: "):
            gitdir_path = (git_file.parent / content[len("gitdir: "):]).resolve()
            if gitdir_path.is_dir():
                return str(gitdir_path)
    except OSError:
        pass
    return None


def _get_darwin_user_cache_dir() -> str | None:
    try:
        libc = ctypes.CDLL(ctypes.util.find_library("c"))
        buf = ctypes.create_string_buffer(1024)
        length = libc.confstr(65538, buf, 1024)  # _CS_DARWIN_USER_CACHE_DIR
        if length > 0:
            return str(Path(buf.value.decode("utf-8")).resolve())
    except Exception:
        pass
    return None


def _build_policy(
    cwd: Path,
    *,
    allow_network: bool,
    allow_git_write: bool,
) -> tuple[str, list[str]]:
    home = Path.home()
    home_str = _canonicalize(home)
    cwd_str = _canonicalize(cwd)

    sections: list[str] = []
    params: list[str] = []

    # Base
    sections.append(_BASE_POLICY)

    # Read: full disk minus sensitive paths
    read_section = [
        "; full disk read",
        "(allow file-read*)",
        "",
        "; block all dotfiles in home (secrets: .ssh, .aws, .gnupg, .config, .docker, etc.)",
        f'(deny file-read* (regex #"^{home_str}/[.][^/]"))',
        "",
        "; re-allow safe dotfiles (git config, gitignore - not secrets)",
        f'(allow file-read* (regex #"^{home_str}/[.]gitconfig"))',
        f'(allow file-read* (regex #"^{home_str}/[.]gitignore"))',
        "",
        "; block ~/Library (keychains, cookies, app tokens)",
        '(deny file-read* (subpath (param "DENY_LIBRARY")))',
        "",
        "; re-allow safe ~/Library subdirs",
        '(allow file-read* (subpath (param "ALLOW_LIBRARY_CACHES")))',
        '(allow file-read* (subpath (param "ALLOW_LIBRARY_DEVELOPER")))',
        '(allow file-read* (subpath (param "ALLOW_LIBRARY_LOGS")))',
    ]
    params.extend([
        f"-DDENY_LIBRARY={_canonicalize(home / 'Library')}",
        f"-DALLOW_LIBRARY_CACHES={_canonicalize(home / 'Library' / 'Caches')}",
        f"-DALLOW_LIBRARY_DEVELOPER={_canonicalize(home / 'Library' / 'Developer')}",
        f"-DALLOW_LIBRARY_LOGS={_canonicalize(home / 'Library' / 'Logs')}",
    ])
    sections.append("\n".join(read_section))

    # Write: CWD + /tmp + $TMPDIR, with .git/.superagent read-only
    writable_roots: list[tuple[str, str]] = [("WRITABLE_ROOT_0", cwd_str)]
    readonly_exclusions: list[tuple[str, str, str]] = []

    ro_index = 0
    if not allow_git_write:
        git_dir = cwd / ".git"
        if git_dir.exists():
            readonly_exclusions.append(("WRITABLE_ROOT_0", f"WRITABLE_ROOT_0_RO_{ro_index}", _canonicalize(git_dir)))
            ro_index += 1
            if git_dir.is_file():
                gitdir_target = _resolve_git_pointer(git_dir)
                if gitdir_target:
                    readonly_exclusions.append(("WRITABLE_ROOT_0", f"WRITABLE_ROOT_0_RO_{ro_index}", gitdir_target))
                    ro_index += 1

    sa_dir = cwd / ".superagent"
    if sa_dir.exists():
        readonly_exclusions.append(("WRITABLE_ROOT_0", f"WRITABLE_ROOT_0_RO_{ro_index}", _canonicalize(sa_dir)))
        ro_index += 1

    tmp_path = Path("/tmp")
    if tmp_path.is_dir():
        writable_roots.append(("WRITABLE_ROOT_1", _canonicalize(tmp_path)))

    tmpdir_env = os.environ.get("TMPDIR", "")
    tmpdir_idx = 2
    if tmpdir_env:
        tmpdir_path = Path(tmpdir_env)
        if tmpdir_path.is_dir():
            writable_roots.append((f"WRITABLE_ROOT_{tmpdir_idx}", _canonicalize(tmpdir_path)))
            tmpdir_idx += 1

    write_parts: list[str] = []
    for param_name, path in writable_roots:
        ro_for_root = [r for r in readonly_exclusions if r[0] == param_name]
        if ro_for_root:
            rp = [f'(subpath (param "{param_name}"))']
            for _, ro_param, _ in ro_for_root:
                rp.append(f'(require-not (subpath (param "{ro_param}")))')
            write_parts.append(f'(require-all {" ".join(rp)} )')
        else:
            write_parts.append(f'(subpath (param "{param_name}"))')
        params.append(f"-D{param_name}={path}")

    for _, ro_param, ro_path in readonly_exclusions:
        params.append(f"-D{ro_param}={ro_path}")

    if write_parts:
        sections.append("(allow file-write*\n" + " ".join(write_parts) + "\n)")

    # Network
    if allow_network:
        sections.append(_NETWORK_POLICY)

    # Platform defaults
    sections.append(_PLATFORM_DEFAULTS)

    # Darwin cache dir
    cache_dir = _get_darwin_user_cache_dir()
    if cache_dir:
        params.append(f"-DDARWIN_USER_CACHE_DIR={cache_dir}")

    return "\n\n".join(sections), params


def _discover_tool_paths() -> list[str]:
    """Auto-discover tool paths without sourcing rc files.

    Checks common install locations for conda, nvm, pyenv, rbenv, go, cargo,
    and adds their bin dirs to PATH if they exist.
    """
    home = Path.home()
    candidates = [
        # conda / miniconda / miniforge / anaconda
        home / "miniconda3" / "bin",
        home / "miniforge3" / "bin",
        home / "anaconda3" / "bin",
        home / "mambaforge" / "bin",
        # conda envs (condabin has the conda command for `conda run`)
        home / "miniconda3" / "condabin",
        home / "miniforge3" / "condabin",
        home / "anaconda3" / "condabin",
        # nvm default node
        home / ".nvm" / "versions" / "node",  # we check children below
        # go
        home / "go" / "bin",
        Path("/usr/local/go/bin"),
        # cargo (rust)
        home / ".cargo" / "bin",
        # pyenv
        home / ".pyenv" / "shims",
        # rbenv
        home / ".rbenv" / "shims",
    ]
    extra: list[str] = []
    for p in candidates:
        if p.is_dir():
            # Special case: nvm stores versions in subdirs
            if "nvm" in str(p) and p.name == "node":
                # Find the latest version dir
                versions = sorted(p.iterdir(), reverse=True)
                for v in versions:
                    bin_dir = v / "bin"
                    if bin_dir.is_dir():
                        extra.append(str(bin_dir))
                        break
            else:
                extra.append(str(p))
    return extra


# ── Profile management ────────────────────────────────────────────────────

_SYSTEM_PATH = [
    "/opt/homebrew/bin",
    "/opt/homebrew/sbin",
    "/usr/local/bin",
    "/usr/bin",
    "/bin",
    "/usr/sbin",
    "/sbin",
]


def _profile_path() -> Path:
    """Path to the profile file inside the agent data dir."""
    return _workspace / ".superagent" / "profile"


def _generate_profile(path: Path) -> None:
    """Auto-generate a profile from discovered tool paths."""
    discovered = _discover_tool_paths()
    lines = [
        "# Shell sandbox profile — auto-generated, safe to edit.",
        "# Paths listed here are added to PATH for sandboxed commands.",
        "# One path per line. Lines starting with # are comments.",
        "# Empty lines are ignored.",
        "",
        "# --- Auto-discovered tool paths ---",
    ]
    for p in discovered:
        lines.append(p)
    lines.extend([
        "",
        "# --- Add custom paths below ---",
        "# /path/to/custom/bin",
        "",
        "# --- Extra environment variables (KEY=VALUE) ---",
        "# GOPATH=/Users/you/go",
        "",
    ])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n")
    log.info("generated profile: %s (%d tool paths)", path, len(discovered))


def _load_profile() -> tuple[list[str], dict[str, str]]:
    """Load PATH entries and env vars from the profile file.

    Returns (extra_paths, extra_env). If no profile exists, generates one
    from auto-discovery first.
    """
    profile = _profile_path()
    if not profile.exists():
        _generate_profile(profile)

    extra_paths: list[str] = []
    extra_env: dict[str, str] = {}
    try:
        for line in profile.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line and not line.startswith("/"):
                # KEY=VALUE env var
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip()
                if key and value:
                    extra_env[key] = value
            else:
                # PATH entry
                if Path(line).is_dir():
                    extra_paths.append(line)
    except OSError:
        pass

    return extra_paths, extra_env


# Load profile once at module init (after register sets _workspace)
_profile_extra_paths: list[str] = []
_profile_extra_env: dict[str, str] = {}


def _init_profile() -> None:
    """Called after register() sets _workspace."""
    global _profile_extra_paths, _profile_extra_env
    _profile_extra_paths, _profile_extra_env = _load_profile()
    if _profile_extra_paths:
        log.info("profile: %d PATH entries loaded", len(_profile_extra_paths))


def _build_safe_env(cwd: Path, *, allow_network: bool) -> dict[str, str]:
    # Build PATH: profile paths + system paths
    path_parts = _profile_extra_paths + _SYSTEM_PATH
    safe = {
        "PATH": ":".join(path_parts),
        "HOME": str(Path.home()),
        "USER": os.environ.get("USER", ""),
        "LANG": os.environ.get("LANG", "en_US.UTF-8"),
        "TERM": os.environ.get("TERM", "xterm-256color"),
        "PWD": str(cwd),
        "SHELL": "/bin/bash",
        "SUPERAGENT_SANDBOX": "seatbelt",
    }
    if not allow_network:
        safe["SUPERAGENT_SANDBOX_NETWORK_DISABLED"] = "1"
    tmpdir = os.environ.get("TMPDIR", "")
    if tmpdir:
        safe["TMPDIR"] = tmpdir
    ssh_auth = os.environ.get("SSH_AUTH_SOCK", "")
    if ssh_auth:
        safe["SSH_AUTH_SOCK"] = ssh_auth
    # Merge profile env vars (user-defined in .superagent/profile)
    safe.update(_profile_extra_env)
    return safe


def _detect_sandbox_denial(exit_code: int, stdout: str, stderr: str, timed_out: bool) -> tuple[bool, str]:
    if exit_code == 0 or timed_out:
        return False, ""
    combined = (stdout + "\n" + stderr).lower()
    for keyword in _DENIAL_KEYWORDS:
        if keyword in combined:
            for line in (stderr + "\n" + stdout).splitlines():
                if any(k in line.lower() for k in _DENIAL_KEYWORDS):
                    return True, line.strip()
            return True, f"sandbox denial detected (keyword: {keyword})"
    if "sandbox_apply" in combined or "sandbox-exec" in combined:
        for line in stderr.splitlines():
            if "sandbox" in line.lower():
                return True, f"sandbox setup failure: {line.strip()}"
        return True, "sandbox setup failure"
    return False, ""


def _sandbox_run(
    command: str,
    *,
    cwd: Path,
    timeout: float,
    allow_network: bool,
    allow_git_write: bool,
) -> _ShellResult:
    if not Path(_SANDBOX_EXEC).exists():
        return _ShellResult(
            stdout="", stderr="sandbox-exec not found. Requires macOS.",
            exit_code=-1, duration_seconds=0.0, sandbox_enforced=False,
            sandbox_denied=False, sandbox_denial_detail="", effective_command=[],
        )

    policy_text, policy_params = _build_policy(cwd, allow_network=allow_network, allow_git_write=allow_git_write)
    user_command = ["bash", "-c", command]
    full_args = [_SANDBOX_EXEC, "-p", policy_text] + policy_params + ["--"] + user_command
    safe_env = _build_safe_env(cwd, allow_network=allow_network)

    start = time.monotonic()
    timed_out = False
    try:
        proc = subprocess.run(
            full_args, cwd=str(cwd), env=safe_env,
            capture_output=True, timeout=timeout, stdin=subprocess.DEVNULL,
        )
        stdout = proc.stdout.decode("utf-8", errors="replace")
        stderr = proc.stderr.decode("utf-8", errors="replace")
        exit_code = proc.returncode
    except subprocess.TimeoutExpired as e:
        timed_out = True
        stdout = (e.stdout or b"").decode("utf-8", errors="replace")
        stderr = (e.stderr or b"").decode("utf-8", errors="replace")
        exit_code = -1
    except Exception as e:
        return _ShellResult(
            stdout="", stderr=f"Failed to execute sandbox-exec: {e}",
            exit_code=-1, duration_seconds=time.monotonic() - start,
            sandbox_enforced=False, sandbox_denied=False,
            sandbox_denial_detail=f"sandbox setup error: {e}", effective_command=full_args,
        )

    elapsed = time.monotonic() - start
    denied, detail = _detect_sandbox_denial(exit_code, stdout, stderr, timed_out)
    if timed_out and not detail:
        detail = f"command timed out after {timeout}s"

    return _ShellResult(
        stdout=stdout, stderr=stderr, exit_code=exit_code,
        duration_seconds=elapsed, sandbox_enforced=True,
        sandbox_denied=denied, sandbox_denial_detail=detail,
        effective_command=full_args,
    )


# ── Public API (injected into sandbox) ────────────────────────────────────


def shell_run(
    command: str,
    *,
    allow_network: bool = False,
    allow_git_write: bool = False,
    timeout: float = 30.0,
    cwd: str | None = None,
) -> str:
    """Run a shell command in a macOS kernel-enforced sandbox.

    The command runs with restricted permissions:
    - Can write to the workspace and /tmp only
    - Cannot read ~/.ssh, ~/.aws, ~/.gnupg, ~/Library (keychains, cookies, tokens)
    - Cannot write to .git/ or .superagent/ inside the workspace
    - Network access is blocked by default

    Returns a formatted string with stdout, stderr, exit code, and sandbox
    diagnostics. If the sandbox blocked an operation, the output explains
    what was denied and which flag to set.

    Args:
        command: Shell command to execute (passed to bash -c).
        allow_network: Allow outbound network access. Required for curl,
            pip install, npm install, git push/pull. Default False.
        allow_git_write: Allow writes to .git/ in the workspace. Required
            for git commit, git stash, git checkout. Default False.
        timeout: Max seconds before killing the command. Default 30.
        cwd: Working directory. Default: workspace root.

    Examples::

        print(shell_run("ls -la"))
        print(shell_run("git status"))
        print(shell_run("git log --oneline -5"))
        print(shell_run("git add -A && git commit -m 'fix'", allow_git_write=True))
        print(shell_run("pip install requests", allow_network=True))
    """
    work_dir = Path(cwd) if cwd else _workspace
    return _sandbox_run(
        command, cwd=work_dir, timeout=timeout,
        allow_network=allow_network, allow_git_write=allow_git_write,
    ).for_llm()


def shell_run_raw(
    command: str,
    *,
    allow_network: bool = False,
    allow_git_write: bool = False,
    timeout: float = 30.0,
    cwd: str | None = None,
) -> dict[str, Any]:
    """Run a shell command in sandbox and return structured result.

    Same sandbox restrictions as shell_run(). Returns a dict instead of
    a formatted string, for programmatic use.

    Args:
        command: Shell command to execute.
        allow_network: Allow network access. Default False.
        allow_git_write: Allow writes to .git/. Default False.
        timeout: Max seconds. Default 30.
        cwd: Working directory. Default: workspace root.

    Returns:
        Dict with keys: ok, exit_code, stdout, stderr, duration,
        sandbox_denied, sandbox_detail.

    Examples::

        r = shell_run_raw("python -c 'print(42)'")
        if r["ok"]:
            print(r["stdout"])
        else:
            print(f"Failed: {r['stderr']}")
    """
    work_dir = Path(cwd) if cwd else _workspace
    return _sandbox_run(
        command, cwd=work_dir, timeout=timeout,
        allow_network=allow_network, allow_git_write=allow_git_write,
    ).to_dict()


# ── System prompt ─────────────────────────────────────────────────────────

SYSTEM_PROMPT = """\
## Shell Execution (sandboxed)

Commands run in a macOS kernel-enforced sandbox. Restrictions:
- Write: workspace + /tmp only. .git/ and .superagent/ are read-only.
- Read: full disk EXCEPT ~/.dotfiles and ~/Library (keychains, cookies, tokens).
- Network: blocked by default.

shell_run(command, ...)          - Run shell command, return formatted output with diagnostics.
shell_run_raw(command, ...)      - Same, but returns dict with ok, exit_code, stdout, stderr, sandbox_denied.

Flags (both functions):
  allow_network=True   - for curl, pip/npm install, git push/pull
  allow_git_write=True - for git commit, git stash, git checkout
  timeout=30           - seconds before kill
  cwd="subdir"         - override working directory

Examples:
  print(shell_run("ls -la"))
  print(shell_run("git status"))
  print(shell_run("git diff HEAD~1"))
  print(shell_run("git add -A && git commit -m 'fix'", allow_git_write=True))
  print(shell_run("pip install requests", allow_network=True))
  r = shell_run_raw("python -c 'import sys; print(sys.version)'")
  if r["ok"]: print(r["stdout"])
"""


# ── Integration registration ─────────────────────────────────────────────


def register(workspace: Path) -> dict:
    global _workspace
    _workspace = Path(workspace).resolve()
    _init_profile()
    log.info("shell_exec integration: workspace=%s", _workspace)
    return {
        "name": "shell_exec",
        "functions": {
            "shell_run": shell_run,
            "shell_run_raw": shell_run_raw,
        },
        "system_prompt": SYSTEM_PROMPT,
    }


# ── Seatbelt policy fragments ────────────────────────────────────────────

_BASE_POLICY = """\
(version 1)

; deny everything by default — child processes inherit this
(deny default)

; allow process management (fork/exec inherit the sandbox)
(allow process-exec)
(allow process-fork)
(allow signal (target same-sandbox))
(allow process-info* (target same-sandbox))

; write to /dev/null
(allow file-write-data
  (require-all
    (path "/dev/null")
    (vnode-type CHARACTER-DEVICE)))

; sysctls needed by common tools (node, python, etc.)
(allow sysctl-read
  (sysctl-name "hw.activecpu")
  (sysctl-name "hw.busfrequency_compat")
  (sysctl-name "hw.byteorder")
  (sysctl-name "hw.cachelinesize_compat")
  (sysctl-name "hw.cpufamily")
  (sysctl-name "hw.cpufrequency_compat")
  (sysctl-name "hw.cputype")
  (sysctl-name "hw.logicalcpu_max")
  (sysctl-name "hw.logicalcpu")
  (sysctl-name "hw.machine")
  (sysctl-name "hw.model")
  (sysctl-name "hw.memsize")
  (sysctl-name "hw.ncpu")
  (sysctl-name "hw.nperflevels")
  (sysctl-name-prefix "hw.optional.arm.")
  (sysctl-name-prefix "hw.optional.armv8_")
  (sysctl-name "hw.packages")
  (sysctl-name "hw.pagesize_compat")
  (sysctl-name "hw.pagesize")
  (sysctl-name "hw.physicalcpu")
  (sysctl-name "hw.physicalcpu_max")
  (sysctl-name "hw.cpufrequency")
  (sysctl-name "hw.vectorunit")
  (sysctl-name "machdep.cpu.brand_string")
  (sysctl-name "kern.argmax")
  (sysctl-name "kern.hostname")
  (sysctl-name "kern.maxfilesperproc")
  (sysctl-name "kern.maxproc")
  (sysctl-name "kern.osproductversion")
  (sysctl-name "kern.osrelease")
  (sysctl-name "kern.ostype")
  (sysctl-name "kern.osvariant_status")
  (sysctl-name "kern.osversion")
  (sysctl-name "kern.secure_kernel")
  (sysctl-name "kern.usrstack64")
  (sysctl-name "kern.version")
  (sysctl-name "sysctl.proc_cputype")
  (sysctl-name "vm.loadavg")
  (sysctl-name-prefix "hw.perflevel")
  (sysctl-name-prefix "kern.proc.pgrp.")
  (sysctl-name-prefix "kern.proc.pid.")
  (sysctl-name-prefix "net.routetable."))

; Java CPU info (conceptually a read, classified as write by macOS)
(allow sysctl-write
  (sysctl-name "kern.grade_cputype"))

; IOKit
(allow iokit-open
  (iokit-registry-entry-class "RootDomainUserClient"))

; user info lookup
(allow mach-lookup
  (global-name "com.apple.system.opendirectoryd.libinfo"))

; Python multiprocessing SemLock
(allow ipc-posix-sem)

; power management
(allow mach-lookup
  (global-name "com.apple.PowerManagement.control"))

; PTY support
(allow pseudo-tty)
(allow file-read* file-write* file-ioctl (literal "/dev/ptmx"))
(allow file-read* file-write*
  (require-all
    (regex #"^/dev/ttys[0-9]+")
    (extension "com.apple.sandbox.pty")))
(allow file-ioctl (regex #"^/dev/ttys[0-9]+"))

; cfprefs
(allow ipc-posix-shm-read* (ipc-posix-name-prefix "apple.cfprefs."))
(allow mach-lookup
    (global-name "com.apple.cfprefsd.daemon")
    (global-name "com.apple.cfprefsd.agent")
    (local-name "com.apple.cfprefsd.agent"))
(allow user-preference-read)"""

_NETWORK_POLICY = """\
; network access enabled
(allow network-outbound)
(allow network-inbound)

(allow system-socket
  (require-all
    (socket-domain AF_SYSTEM)
    (socket-protocol 2)))

(allow mach-lookup
    (global-name "com.apple.bsd.dirhelper")
    (global-name "com.apple.system.opendirectoryd.membership")
    (global-name "com.apple.SecurityServer")
    (global-name "com.apple.networkd")
    (global-name "com.apple.ocspd")
    (global-name "com.apple.trustd.agent")
    (global-name "com.apple.SystemConfiguration.DNSConfiguration")
    (global-name "com.apple.SystemConfiguration.configd"))

(allow sysctl-read
  (sysctl-name-regex #"^net.routetable"))

(allow file-write* (subpath (param "DARWIN_USER_CACHE_DIR")))"""

_PLATFORM_DEFAULTS = """\
; system paths
(allow file-read* file-test-existence
  (subpath "/Library/Apple")
  (subpath "/Library/Filesystems/NetFSPlugins")
  (subpath "/Library/Preferences/Logging")
  (subpath "/private/var/db/timezone")
  (subpath "/usr/lib")
  (subpath "/usr/share")
  (subpath "/Library/Preferences")
  (subpath "/var/db")
  (subpath "/private/var/db"))

(allow file-map-executable
  (subpath "/Library/Apple/System/Library/Frameworks")
  (subpath "/Library/Apple/System/Library/PrivateFrameworks")
  (subpath "/Library/Apple/usr/lib")
  (subpath "/System/Library/Extensions")
  (subpath "/System/Library/Frameworks")
  (subpath "/System/Library/PrivateFrameworks")
  (subpath "/System/Library/SubFrameworks")
  (subpath "/System/iOSSupport/System/Library/Frameworks")
  (subpath "/System/iOSSupport/System/Library/PrivateFrameworks")
  (subpath "/System/iOSSupport/System/Library/SubFrameworks")
  (subpath "/usr/lib"))

(allow system-mac-syscall (mac-policy-name "vnguard"))
(allow system-mac-syscall
  (require-all (mac-policy-name "Sandbox") (mac-syscall-number 67)))

(allow file-read-metadata file-test-existence
  (literal "/etc") (literal "/tmp") (literal "/var") (literal "/private/etc/localtime"))

(allow file-read-metadata file-test-existence
  (path-ancestors "/System/Volumes/Data/private"))

(allow file-read* file-test-existence (literal "/"))
(allow system-fsctl (fsctl-command FSIOC_CAS_BSDFLAGS))

(allow file-read* file-test-existence
  (literal "/dev/autofs_nowait") (literal "/dev/random") (literal "/dev/urandom")
  (literal "/private/etc/master.passwd") (literal "/private/etc/passwd")
  (literal "/private/etc/protocols") (literal "/private/etc/services"))

(allow file-read* file-test-existence file-write-data (literal "/dev/null") (literal "/dev/zero"))
(allow file-read-data file-test-existence file-write-data (subpath "/dev/fd"))
(allow file-read* file-test-existence file-write-data file-ioctl (literal "/dev/dtracehelper"))

(allow file-read* file-test-existence file-write* (subpath "/tmp"))
(allow file-read* file-write* (subpath "/private/tmp"))
(allow file-read* file-write* (subpath "/var/tmp"))
(allow file-read* file-write* (subpath "/private/var/tmp"))

(allow file-read* (subpath "/etc"))
(allow file-read* (subpath "/private/etc"))
(allow file-read-metadata (subpath "/var"))
(allow file-read-metadata (subpath "/private/var"))

(allow iokit-open (iokit-registry-entry-class "RootDomainUserClient"))
(allow mach-lookup (global-name "com.apple.system.opendirectoryd.libinfo"))

(allow mach-lookup
  (global-name "com.apple.analyticsd") (global-name "com.apple.analyticsd.messagetracer")
  (global-name "com.apple.appsleep") (global-name "com.apple.bsd.dirhelper")
  (global-name "com.apple.cfprefsd.agent") (global-name "com.apple.cfprefsd.daemon")
  (global-name "com.apple.diagnosticd") (global-name "com.apple.espd")
  (global-name "com.apple.logd") (global-name "com.apple.logd.events")
  (global-name "com.apple.runningboard") (global-name "com.apple.secinitd")
  (global-name "com.apple.system.DirectoryService.libinfo_v1")
  (global-name "com.apple.system.logger")
  (global-name "com.apple.system.notification_center")
  (global-name "com.apple.system.opendirectoryd.membership")
  (global-name "com.apple.trustd") (global-name "com.apple.trustd.agent")
  (global-name "com.apple.xpc.activity.unmanaged")
  (local-name "com.apple.cfprefsd.agent"))

(allow network-outbound (literal "/private/var/run/syslog"))
(allow ipc-posix-shm-read* (ipc-posix-name "apple.shm.notification_center"))
(allow file-read* (literal "/private/var/db/eligibilityd/eligibility.plist"))
(allow mach-lookup (global-name "com.apple.audio.audiohald"))
(allow mach-lookup (global-name "com.apple.audio.AudioComponentRegistrar"))
(allow mach-lookup (global-name "com.apple.PowerManagement.control"))

(allow file-read-data (subpath "/bin")) (allow file-read-metadata (subpath "/bin"))
(allow file-read-data (subpath "/sbin")) (allow file-read-metadata (subpath "/sbin"))
(allow file-read-data (subpath "/usr/bin")) (allow file-read-metadata (subpath "/usr/bin"))
(allow file-read-data (subpath "/usr/sbin")) (allow file-read-metadata (subpath "/usr/sbin"))
(allow file-read-data (subpath "/usr/libexec")) (allow file-read-metadata (subpath "/usr/libexec"))

(allow file-read* (subpath "/Library/Preferences"))
(allow file-read* (subpath "/opt/homebrew/lib"))
(allow file-read* (subpath "/opt/homebrew/bin"))
(allow file-read* (subpath "/opt/homebrew/Cellar"))
(allow file-read* (subpath "/opt/homebrew/opt"))
(allow file-read* (subpath "/usr/local/lib"))
(allow file-read* (subpath "/usr/local/bin"))
(allow file-read* (subpath "/Applications"))

(allow file-read* (regex "^/dev/fd/(0|1|2)$"))
(allow file-write* (regex "^/dev/fd/(1|2)$"))
(allow file-read* file-write* (literal "/dev/null"))
(allow file-read* file-write* (literal "/dev/tty"))
(allow file-read-metadata (literal "/dev"))
(allow file-read-metadata (regex "^/dev/.*$"))
(allow file-read-metadata (literal "/dev/stdin"))
(allow file-read-metadata (literal "/dev/stdout"))
(allow file-read-metadata (literal "/dev/stderr"))
(allow file-read-metadata (regex "^/dev/tty[^/]*$"))
(allow file-read-metadata (regex "^/dev/pty[^/]*$"))
(allow file-read* file-write* (regex "^/dev/ttys[0-9]+$"))
(allow file-read* file-write* (literal "/dev/ptmx"))
(allow file-ioctl (regex "^/dev/ttys[0-9]+$"))

(allow file-read-metadata (literal "/System/Volumes") (vnode-type DIRECTORY))
(allow file-read-metadata (literal "/System/Volumes/Data") (vnode-type DIRECTORY))
(allow file-read-metadata (literal "/System/Volumes/Data/Users") (vnode-type DIRECTORY))

(allow file-read* (extension "com.apple.app-sandbox.read"))
(allow file-read* file-write* (extension "com.apple.app-sandbox.read-write"))"""
