from __future__ import annotations

import json
from typing import Any, Optional

# ============================================================================
# IDE Bridge Tools
# ============================================================================
# These tools communicate with the Bob app_server to read IDE state.
# Requires the IDE extension (VS Code/JetBrains) to be running and connected.

# ============================================================================
# ide_get_open_files tool
# ============================================================================

IDE_GET_OPEN_FILES_DESCRIPTION = (
    "Get a list of files currently open in the IDE (VS Code or JetBrains). "
    "Returns file paths and optionally their active/visible state. "
    "Requires the Bob IDE extension to be running."
)

IDE_GET_OPEN_FILES_SCHEMA = {
    "type": "object",
    "properties": {
        "include_unsaved": {
            "type": "boolean",
            "description": "Include unsaved/dirty files. Default: true.",
        },
    },
}


async def ide_get_open_files_handler(tool_input: dict, context: Any) -> str:
    """
    Get list of open files from IDE via app_server.
    
    In a full implementation, this would:
    1. Connect to the app_server JSON-RPC endpoint
    2. Send an 'ide/getOpenFiles' request
    3. Parse and return the file list
    """
    include_unsaved: bool = tool_input.get("include_unsaved", True)
    
    # Check if app_server connection is available
    app_server = getattr(context, '_app_server_client', None)
    if app_server is None:
        return (
            "Error: IDE bridge not available\n\n"
            "The IDE extension is not connected. To use IDE bridge tools:\n"
            "1. Install the Bob extension in VS Code or JetBrains\n"
            "2. Ensure the app_server is running\n"
            "3. Connect the IDE extension to Bob\n\n"
            "For now, use file system tools (list_dir, glob_files) to discover files."
        )
    
    # Placeholder for actual implementation
    try:
        # In real implementation:
        # response = await app_server.request('ide/getOpenFiles', {
        #     'includeUnsaved': include_unsaved
        # })
        # return format_open_files(response)
        
        return (
            "IDE Bridge: Get Open Files\n\n"
            "Status: Not yet implemented\n"
            "This tool requires:\n"
            "  - Bob IDE extension installed and running\n"
            "  - app_server JSON-RPC connection\n"
            "  - Full protocol implementation\n\n"
            "Use list_dir() or glob_files() as alternatives for now."
        )
    except Exception as exc:
        return f"Error communicating with IDE: {exc}"


# ============================================================================
# ide_get_selection tool
# ============================================================================

IDE_GET_SELECTION_DESCRIPTION = (
    "Get the currently selected text in the IDE, along with file path and location. "
    "Useful for understanding what the user is actively working on. "
    "Requires the Bob IDE extension to be running."
)

IDE_GET_SELECTION_SCHEMA = {
    "type": "object",
    "properties": {
        "include_context": {
            "type": "boolean",
            "description": "Include surrounding lines for context. Default: false.",
        },
        "context_lines": {
            "type": "integer",
            "description": "Number of context lines before/after selection. Default: 3.",
        },
    },
}


async def ide_get_selection_handler(tool_input: dict, context: Any) -> str:
    """
    Get current selection from IDE via app_server.
    
    Returns:
    - File path
    - Start line/column
    - End line/column
    - Selected text
    - Optional context lines
    """
    include_context: bool = tool_input.get("include_context", False)
    context_lines: int = tool_input.get("context_lines", 3)
    
    # Check if app_server connection is available
    app_server = getattr(context, '_app_server_client', None)
    if app_server is None:
        return (
            "Error: IDE bridge not available\n\n"
            "The IDE extension is not connected. To use IDE bridge tools:\n"
            "1. Install the Bob extension in VS Code or JetBrains\n"
            "2. Ensure the app_server is running\n"
            "3. Connect the IDE extension to Bob\n\n"
            "For now, ask the user to specify the file and location manually."
        )
    
    try:
        # In real implementation:
        # response = await app_server.request('ide/getSelection', {
        #     'includeContext': include_context,
        #     'contextLines': context_lines
        # })
        # return format_selection(response)
        
        return (
            "IDE Bridge: Get Selection\n\n"
            "Status: Not yet implemented\n"
            "This tool requires:\n"
            "  - Bob IDE extension installed and running\n"
            "  - app_server JSON-RPC connection\n"
            "  - Full protocol implementation\n\n"
            "Ask the user to specify the file and line range manually."
        )
    except Exception as exc:
        return f"Error communicating with IDE: {exc}"


# ============================================================================
# ide_get_diagnostics tool
# ============================================================================

IDE_GET_DIAGNOSTICS_DESCRIPTION = (
    "Get diagnostics (errors, warnings, hints) from the IDE's problems panel. "
    "Returns issues detected by the IDE's language server or linters. "
    "Requires the Bob IDE extension to be running."
)

IDE_GET_DIAGNOSTICS_SCHEMA = {
    "type": "object",
    "properties": {
        "file": {
            "type": "string",
            "description": "Optional: Filter diagnostics to a specific file path.",
        },
        "severity": {
            "type": "string",
            "enum": ["error", "warning", "info", "hint"],
            "description": "Optional: Filter by severity level.",
        },
        "max_results": {
            "type": "integer",
            "description": "Maximum number of diagnostics to return. Default: 50.",
        },
    },
}


async def ide_get_diagnostics_handler(tool_input: dict, context: Any) -> str:
    """
    Get diagnostics from IDE via app_server.
    
    Returns list of:
    - File path
    - Line/column
    - Severity (error/warning/info/hint)
    - Message
    - Source (e.g., 'typescript', 'eslint')
    """
    file_filter: Optional[str] = tool_input.get("file")
    severity_filter: Optional[str] = tool_input.get("severity")
    max_results: int = tool_input.get("max_results", 50)
    
    # Check if app_server connection is available
    app_server = getattr(context, '_app_server_client', None)
    if app_server is None:
        return (
            "Error: IDE bridge not available\n\n"
            "The IDE extension is not connected. To use IDE bridge tools:\n"
            "1. Install the Bob extension in VS Code or JetBrains\n"
            "2. Ensure the app_server is running\n"
            "3. Connect the IDE extension to Bob\n\n"
            "For now, use lsp_diagnostics() or run linters manually via shell()."
        )
    
    try:
        # In real implementation:
        # response = await app_server.request('ide/getDiagnostics', {
        #     'file': file_filter,
        #     'severity': severity_filter,
        #     'maxResults': max_results
        # })
        # return format_diagnostics(response)
        
        return (
            "IDE Bridge: Get Diagnostics\n\n"
            "Status: Not yet implemented\n"
            "This tool requires:\n"
            "  - Bob IDE extension installed and running\n"
            "  - app_server JSON-RPC connection\n"
            "  - Full protocol implementation\n\n"
            "Alternatives:\n"
            "  - Use lsp_diagnostics() for LSP-based analysis\n"
            "  - Run linters via shell() (e.g., 'pylint', 'eslint')\n"
            "  - Use grep_files() to search for common error patterns"
        )
    except Exception as exc:
        return f"Error communicating with IDE: {exc}"


# ============================================================================
# ide_get_active_file tool (bonus)
# ============================================================================

IDE_GET_ACTIVE_FILE_DESCRIPTION = (
    "Get the currently active/focused file in the IDE. "
    "Returns the file path and optionally cursor position. "
    "Requires the Bob IDE extension to be running."
)

IDE_GET_ACTIVE_FILE_SCHEMA = {
    "type": "object",
    "properties": {
        "include_cursor": {
            "type": "boolean",
            "description": "Include cursor position. Default: true.",
        },
    },
}


async def ide_get_active_file_handler(tool_input: dict, context: Any) -> str:
    """Get the currently active file from IDE."""
    include_cursor: bool = tool_input.get("include_cursor", True)
    
    app_server = getattr(context, '_app_server_client', None)
    if app_server is None:
        return (
            "Error: IDE bridge not available\n\n"
            "The IDE extension is not connected.\n"
            "Ask the user which file they're working on."
        )
    
    return (
        "IDE Bridge: Get Active File\n\n"
        "Status: Not yet implemented\n"
        "Ask the user which file they're currently working on."
    )
