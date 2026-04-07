from __future__ import annotations

import re
from pathlib import Path

# ---------------------------------------------------------------------------
# Shell escalation patterns
# ---------------------------------------------------------------------------
# Commands that attempt privilege escalation or sandbox escape
ESCALATION_COMMANDS: frozenset[str] = frozenset([
    "sudo", "su", "doas", "pkexec",
    "chroot", "nsenter", "unshare",
    "docker", "podman", "systemd-run",
])

# Environment variables that can be used for code injection
DANGEROUS_ENV_VARS: frozenset[str] = frozenset([
    "LD_PRELOAD", "LD_LIBRARY_PATH", "DYLD_INSERT_LIBRARIES",
    "DYLD_LIBRARY_PATH", "PYTHONPATH", "NODE_PATH",
])

# ---------------------------------------------------------------------------
# Built-in safe commands
# ---------------------------------------------------------------------------
# Commands that are considered safe in UNLESS_TRUSTED mode and never require
# explicit approval.  The set contains both single-word commands and two-word
# prefixes (e.g. "git status") so that common read-only git operations are
# automatically trusted.

SAFE_COMMANDS: frozenset[str] = frozenset([
    # POSIX file/directory inspection
    "ls", "cat", "pwd", "echo", "which", "type", "file",
    "head", "tail", "wc", "sort", "uniq", "cut", "tr",
    # Search
    "grep", "rg", "ag", "fd", "find",
    # Git (read-only operations)
    "git status", "git log", "git diff", "git branch", "git show",
    "git remote", "git stash list", "git tag",
    # Runtime version checks
    "python --version", "python3 --version", "node --version",
    "npm --version", "yarn --version", "go version", "rustc --version",
    # Package inspection (read-only)
    "pip list", "pip show", "pip freeze",
    "npm list", "yarn list",
    # System info
    "uname", "hostname", "whoami", "id", "date",
    # Process inspection (non-mutating)
    "ps", "top", "htop",
    # Network inspection (non-mutating)
    "curl --version", "wget --version",
])


def is_safe_command(command: list[str]) -> bool:
    """Return True if *command* is in the built-in safe set.

    Checks both the first word alone and the first two words joined by a
    space, so both ``["ls", "-la"]`` and ``["git", "status"]`` are handled.
    """
    if not command:
        return False
    cmd0 = command[0]
    cmd2 = " ".join(command[:2])
    return cmd0 in SAFE_COMMANDS or cmd2 in SAFE_COMMANDS


def command_approval_key(command: list[str]) -> str:
    """Return a stable key used to cache per-session approval decisions.

    Uses the first two tokens of the command so that ``git commit -m "msg1"``
    and ``git commit -m "msg2"`` share the same approval key after the user
    grants session-wide approval.
    """
    return " ".join(command[:2]) if command else ""


def canonicalize_command(command: list[str]) -> list[str]:
    """Normalize a command for approval checking.
    
    Unwraps shell wrappers (cmd /c, powershell -Command, bash -c) and
    resolves relative paths to prevent approval bypasses.
    
    Args:
        command: Raw command list
        
    Returns:
        Canonicalized command list
    """
    if not command:
        return command
    
    # Unwrap Windows cmd.exe wrapper
    if len(command) >= 3 and command[0].lower() in ("cmd", "cmd.exe"):
        if command[1].lower() == "/c":
            # cmd /c <actual_command>
            return canonicalize_command(command[2:])
    
    # Unwrap PowerShell wrapper
    if len(command) >= 3 and command[0].lower() in ("powershell", "powershell.exe", "pwsh", "pwsh.exe"):
        if command[1].lower() in ("-command", "-c"):
            # powershell -Command <actual_command>
            return canonicalize_command(command[2:])
    
    # Unwrap bash -c wrapper
    if len(command) >= 3 and command[0] in ("bash", "sh", "zsh", "fish"):
        if command[1] == "-c":
            # bash -c "actual command" - parse the string
            shell_cmd = command[2]
            # Simple split on whitespace (not perfect but catches common cases)
            inner_parts = shell_cmd.split()
            if inner_parts:
                return canonicalize_command(inner_parts)
    
    # Resolve relative paths in first argument
    if command[0].startswith("./") or command[0].startswith("../"):
        try:
            resolved = str(Path(command[0]).resolve())
            return [resolved] + command[1:]
        except Exception:
            pass
    
    return command


def detect_escalation(command: list[str]) -> tuple[bool, str]:
    """Detect privilege escalation or sandbox escape attempts.
    
    Args:
        command: Command to check
        
    Returns:
        (is_escalation, reason) tuple
    """
    if not command:
        return False, ""
    
    canonical = canonicalize_command(command)
    cmd0 = canonical[0].lower()
    
    # Check for escalation commands
    base_cmd = Path(cmd0).name  # Handle /usr/bin/sudo -> sudo
    if base_cmd in ESCALATION_COMMANDS:
        return True, f"Privilege escalation command: {base_cmd}"
    
    # Check for dangerous environment variable injection
    for i, arg in enumerate(canonical):
        if "=" in arg:
            var_name = arg.split("=", 1)[0]
            if var_name in DANGEROUS_ENV_VARS:
                return True, f"Dangerous environment variable: {var_name}"
    
    # Check for shell metacharacters in trusted command paths
    # (e.g., trying to bypass approval with "ls; rm -rf /")
    if len(canonical) > 1:
        for arg in canonical[1:]:
            if any(char in arg for char in [";", "|", "&", "`", "$("]):
                return True, "Shell metacharacters detected in command arguments"
    
    return False, ""


def needs_approval(command: list[str], ask_for_approval: str, trusted_patterns: list = None) -> bool:
    """Determine if a command needs user approval.
    
    Args:
        command: Command to check
        ask_for_approval: Approval policy (ALWAYS, UNLESS_TRUSTED, NEVER)
        trusted_patterns: Optional list of trusted command patterns
        
    Returns:
        True if approval is required
    """
    if not command:
        return False
    
    # Canonicalize first to prevent bypasses
    canonical = canonicalize_command(command)
    
    # Always block escalation attempts
    is_escalation, reason = detect_escalation(canonical)
    if is_escalation:
        # Escalation always requires approval (or should be blocked entirely)
        return True
    
    if ask_for_approval == "NEVER":
        return False
    
    if ask_for_approval == "ALWAYS":
        return True
    
    # UNLESS_TRUSTED mode
    if is_safe_command(canonical):
        return False
    
    # Check trusted patterns if provided
    if trusted_patterns:
        cmd_str = " ".join(canonical)
        for pattern in trusted_patterns:
            if isinstance(pattern, dict):
                pat = pattern.get("pattern", "")
                use_regex = pattern.get("use_regex", False)
                if use_regex:
                    if re.match(pat, cmd_str):
                        return False
                else:
                    # Glob-style matching (simple * wildcard)
                    regex_pat = pat.replace("*", ".*")
                    if re.match(regex_pat, cmd_str):
                        return False
    
    return True
