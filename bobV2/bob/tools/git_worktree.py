from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

# ============================================================================
# enter_worktree tool
# ============================================================================

ENTER_WORKTREE_DESCRIPTION = (
    "Create a git worktree for isolated branch work. Creates a new worktree, "
    "checks out the specified branch, and switches the session's working directory "
    "to the new worktree. Useful for working on multiple branches simultaneously "
    "without affecting the main working directory."
)

ENTER_WORKTREE_SCHEMA = {
    "type": "object",
    "properties": {
        "branch_name": {
            "type": "string",
            "description": "Name of the branch to create/checkout in the worktree.",
        },
        "create_branch": {
            "type": "boolean",
            "description": "If true, create a new branch. If false, checkout existing branch. Default: true.",
        },
    },
    "required": ["branch_name"],
}


async def enter_worktree_handler(tool_input: dict, context: Any) -> str:
    """
    Create a git worktree and switch session cwd to it.
    
    Stores the original cwd in context so exit_worktree can restore it.
    """
    branch_name: str = tool_input.get("branch_name", "")
    if not branch_name:
        return "Error: branch_name is required"
    
    create_branch: bool = tool_input.get("create_branch", True)
    
    cwd = context.cwd
    
    # Verify we're in a git repository
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--git-dir"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return f"Error: Not in a git repository: {cwd}"
    except Exception as exc:
        return f"Error checking git repository: {exc}"
    
    # Create worktree path: .git/worktrees/<branch_name>
    # Use a dedicated worktrees directory in the repo root
    try:
        repo_root = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout.strip()
        
        worktree_path = Path(repo_root) / ".worktrees" / branch_name
        
        # Create worktree
        cmd = ["git", "worktree", "add"]
        if create_branch:
            cmd.extend(["-b", branch_name])
        cmd.append(str(worktree_path))
        if not create_branch:
            cmd.append(branch_name)
        
        result = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=30,
        )
        
        if result.returncode != 0:
            return f"Error creating worktree: {result.stderr.strip()}"
        
        # Store original cwd in context for later restoration
        if not hasattr(context, '_worktree_stack'):
            context._worktree_stack = []
        context._worktree_stack.append(str(cwd))
        
        # Update session cwd
        context.cwd = worktree_path.resolve()
        
        return (
            f"✓ Created worktree at: {worktree_path}\n"
            f"✓ Checked out branch: {branch_name}\n"
            f"✓ Session working directory updated to worktree\n"
            f"Use exit_worktree() to return to original directory"
        )
        
    except Exception as exc:
        return f"Error: {exc}"


# ============================================================================
# exit_worktree tool
# ============================================================================

EXIT_WORKTREE_DESCRIPTION = (
    "Exit the current git worktree and return to the original working directory. "
    "Removes the worktree and restores the session's cwd to what it was before "
    "enter_worktree was called."
)

EXIT_WORKTREE_SCHEMA = {
    "type": "object",
    "properties": {
        "force": {
            "type": "boolean",
            "description": "Force removal even if worktree has uncommitted changes. Default: false.",
        },
    },
}


async def exit_worktree_handler(tool_input: dict, context: Any) -> str:
    """
    Remove current worktree and restore original cwd.
    """
    force: bool = tool_input.get("force", False)
    
    # Check if we have a stored original cwd
    if not hasattr(context, '_worktree_stack') or not context._worktree_stack:
        return "Error: Not currently in a worktree (no original directory stored)"
    
    current_worktree = context.cwd
    original_cwd = Path(context._worktree_stack.pop())
    
    # Verify current directory looks like a worktree
    if ".worktrees" not in str(current_worktree):
        context.cwd = original_cwd  # Restore anyway
        return (
            f"Warning: Current directory doesn't appear to be a worktree\n"
            f"Restored to: {original_cwd}"
        )
    
    try:
        # Remove the worktree
        cmd = ["git", "worktree", "remove"]
        if force:
            cmd.append("--force")
        cmd.append(str(current_worktree))
        
        result = subprocess.run(
            cmd,
            cwd=original_cwd,
            capture_output=True,
            text=True,
            timeout=30,
        )
        
        # Restore original cwd regardless of removal success
        context.cwd = original_cwd
        
        if result.returncode != 0:
            stderr = result.stderr.strip()
            if "uncommitted changes" in stderr.lower() and not force:
                return (
                    f"Error: Worktree has uncommitted changes\n"
                    f"Restored to: {original_cwd}\n"
                    f"Worktree still exists at: {current_worktree}\n"
                    f"Use force=true to remove anyway, or commit/stash changes first"
                )
            return (
                f"Warning: Error removing worktree: {stderr}\n"
                f"Restored to: {original_cwd}\n"
                f"You may need to manually remove: {current_worktree}"
            )
        
        return (
            f"✓ Removed worktree: {current_worktree}\n"
            f"✓ Restored to: {original_cwd}"
        )
        
    except Exception as exc:
        # Always try to restore cwd
        context.cwd = original_cwd
        return f"Error: {exc}\nRestored to: {original_cwd}"
