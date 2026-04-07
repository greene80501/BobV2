from __future__ import annotations
from enum import Enum
from dataclasses import dataclass
from typing import Optional
from rapidfuzz import fuzz, process as fuzz_process


class SlashCommand(str, Enum):
    # Ordered by frequency — exactly matches Codex slash_command.rs enum order
    MODEL = "model"
    FAST = "fast"
    APPROVALS = "approvals"
    PERMISSIONS = "permissions"
    SETUP_DEFAULT_SANDBOX = "setup-default-sandbox"
    SANDBOX_READ_ROOT = "sandbox-add-read-dir"
    EXPERIMENTAL = "experimental"
    SKILLS = "skills"
    REVIEW = "review"
    RENAME = "rename"
    NEW = "new"
    RESUME = "resume"
    FORK = "fork"
    INIT = "init"
    COMPACT = "compact"
    PLAN = "plan"
    COLLAB = "collab"
    AGENT = "agent"
    DIFF = "diff"
    COPY = "copy"
    MENTION = "mention"
    STATUS = "status"
    DEBUG_CONFIG = "debug-config"
    TITLE = "title"
    STATUSLINE = "statusline"
    THEME = "theme"
    MCP = "mcp"
    APPS = "apps"
    PLUGINS = "plugins"
    LOGOUT = "logout"
    QUIT = "quit"
    EXIT = "exit"
    FEEDBACK = "feedback"
    ROLLOUT = "rollout"
    PS = "ps"
    STOP = "stop"
    CLEAR = "clear"
    PERSONALITY = "personality"
    REALTIME = "realtime"
    SETTINGS = "settings"
    SUBAGENTS = "subagents"
    DEBUG_M_DROP = "debug-m-drop"
    DEBUG_M_UPDATE = "debug-m-update"
    # Phase 1 additions
    HELP = "help"
    EFFORT = "effort"
    COST = "cost"
    USAGE = "usage"
    # Phase 3 additions
    COMMIT = "commit"
    BRANCH = "branch"
    EXPORT = "export"
    REWIND = "rewind"
    SUMMARY = "summary"
    DOCTOR = "doctor"
    CONTEXT = "context"
    OUTPUT_STYLE = "output-style"
    # Phase 5 additions
    VI = "vi"
    HOOKS = "hooks"
    THINK = "think"
    BRIEF = "brief"
    TASKS = "tasks"


COMMAND_DESCRIPTIONS: dict[SlashCommand, str] = {
    SlashCommand.MODEL: "choose what model and reasoning effort to use",
    SlashCommand.FAST: "toggle Fast mode to enable fastest inference",
    SlashCommand.APPROVALS: "choose what bob is allowed to do",
    SlashCommand.PERMISSIONS: "choose what bob is allowed to do",
    SlashCommand.SETUP_DEFAULT_SANDBOX: "set up elevated agent sandbox",
    SlashCommand.SANDBOX_READ_ROOT: "let sandbox read a directory: /sandbox-add-read-dir <path>",
    SlashCommand.EXPERIMENTAL: "toggle experimental features",
    SlashCommand.SKILLS: "use skills to improve how bob performs specific tasks",
    SlashCommand.REVIEW: "review my current changes and find issues",
    SlashCommand.RENAME: "rename the current thread",
    SlashCommand.NEW: "start a new chat during a conversation",
    SlashCommand.RESUME: "resume a saved chat",
    SlashCommand.FORK: "fork the current chat",
    SlashCommand.INIT: "create an AGENTS.md file with instructions for bob",
    SlashCommand.COMPACT: "summarize conversation to prevent hitting the context limit",
    SlashCommand.PLAN: "switch to Plan mode",
    SlashCommand.COLLAB: "change collaboration mode (experimental)",
    SlashCommand.AGENT: "switch the active agent thread",
    SlashCommand.DIFF: "show git diff (including untracked files)",
    SlashCommand.COPY: "copy the latest bob output to your clipboard",
    SlashCommand.MENTION: "mention a file",
    SlashCommand.STATUS: "show current session configuration and token usage",
    SlashCommand.DEBUG_CONFIG: "show config layers and requirement sources for debugging",
    SlashCommand.TITLE: "configure which items appear in the terminal title",
    SlashCommand.STATUSLINE: "configure which items appear in the status line",
    SlashCommand.THEME: "choose a syntax highlighting theme",
    SlashCommand.MCP: "list configured MCP tools",
    SlashCommand.APPS: "manage apps",
    SlashCommand.PLUGINS: "browse plugins",
    SlashCommand.LOGOUT: "log out of bob",
    SlashCommand.QUIT: "exit bob",
    SlashCommand.EXIT: "exit bob",
    SlashCommand.FEEDBACK: "send logs to maintainers",
    SlashCommand.ROLLOUT: "print the rollout file path",
    SlashCommand.PS: "list background terminals",
    SlashCommand.STOP: "stop all background terminals",
    SlashCommand.CLEAR: "clear the terminal and start a new chat",
    SlashCommand.PERSONALITY: "choose a communication style for bob",
    SlashCommand.REALTIME: "toggle realtime voice mode (experimental)",
    SlashCommand.SETTINGS: "configure realtime microphone/speaker",
    SlashCommand.SUBAGENTS: "switch the active agent thread",
    SlashCommand.DEBUG_M_DROP: "drop all memories (debug)",
    SlashCommand.DEBUG_M_UPDATE: "update memories (debug)",
    # Phase 1
    SlashCommand.HELP: "show all available slash commands",
    SlashCommand.EFFORT: "set reasoning effort: low, medium, or high",
    SlashCommand.COST: "show estimated token cost for this session",
    SlashCommand.USAGE: "show token usage breakdown for the last turn",
    # Phase 3
    SlashCommand.COMMIT: "generate a commit message and commit staged changes",
    SlashCommand.BRANCH: "create and checkout a new git branch: /branch <name>",
    SlashCommand.EXPORT: "export conversation to a Markdown file",
    SlashCommand.REWIND: "undo the last N turns: /rewind [N]",
    SlashCommand.SUMMARY: "summarize what has been accomplished this session",
    SlashCommand.DOCTOR: "run system health checks",
    SlashCommand.CONTEXT: "add a URL or file as context for the next message",
    SlashCommand.OUTPUT_STYLE: "set response style: brief, normal, or verbose",
    # Phase 5
    SlashCommand.VI: "toggle vi input mode",
    SlashCommand.HOOKS: "list configured hooks",
    SlashCommand.THINK: "set thinking budget for next turn: /think [tokens]",
    SlashCommand.BRIEF: "alias for /output-style brief",
    SlashCommand.TASKS: "list all tasks or filter by status: /tasks [status]",
}

AVAILABLE_DURING_TASK: set[SlashCommand] = {
    SlashCommand.DIFF, SlashCommand.COPY, SlashCommand.RENAME,
    SlashCommand.MENTION, SlashCommand.SKILLS, SlashCommand.STATUS,
    SlashCommand.DEBUG_CONFIG, SlashCommand.PS, SlashCommand.STOP,
    SlashCommand.MCP, SlashCommand.APPS, SlashCommand.PLUGINS,
    SlashCommand.FEEDBACK, SlashCommand.QUIT, SlashCommand.EXIT,
    SlashCommand.ROLLOUT, SlashCommand.REALTIME, SlashCommand.SETTINGS,
    SlashCommand.COLLAB, SlashCommand.AGENT, SlashCommand.SUBAGENTS,
}

SUPPORTS_INLINE_ARGS: set[SlashCommand] = {
    SlashCommand.REVIEW, SlashCommand.RENAME, SlashCommand.PLAN,
    SlashCommand.FAST, SlashCommand.SANDBOX_READ_ROOT,
    SlashCommand.MODEL, SlashCommand.EFFORT, SlashCommand.BRANCH,
    SlashCommand.EXPORT, SlashCommand.REWIND, SlashCommand.CONTEXT,
    SlashCommand.OUTPUT_STYLE, SlashCommand.THINK,
}


@dataclass
class CommandMatch:
    command: SlashCommand
    score: float


def get_all_commands() -> list[SlashCommand]:
    return list(SlashCommand)


def fuzzy_match_commands(query: str, task_running: bool = False) -> list[CommandMatch]:
    """Return commands matching the query, fuzzy-sorted by score."""
    if not query:
        cmds = get_all_commands()
        if task_running:
            cmds = [c for c in cmds if c in AVAILABLE_DURING_TASK]
        return [CommandMatch(c, 100.0) for c in cmds]

    candidates = {c.value: c for c in SlashCommand}
    if task_running:
        candidates = {v: c for v, c in candidates.items() if c in AVAILABLE_DURING_TASK}

    results = fuzz_process.extract(
        query, list(candidates.keys()), scorer=fuzz.partial_ratio, limit=20
    )
    matches = []
    for name, score, _ in results:
        if score >= 30:
            matches.append(CommandMatch(candidates[name], score))
    return matches


def parse_command(text: str) -> tuple[Optional[SlashCommand], str]:
    """Parse '/command args' -> (SlashCommand, args). Returns (None, text) if not a slash command."""
    if not text.startswith("/"):
        return None, text
    rest = text[1:]
    parts = rest.split(None, 1)
    if not parts:
        return None, ""
    cmd_str = parts[0].lower()
    args = parts[1] if len(parts) > 1 else ""
    try:
        return SlashCommand(cmd_str), args
    except ValueError:
        return None, args
