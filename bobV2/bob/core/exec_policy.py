from __future__ import annotations

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
