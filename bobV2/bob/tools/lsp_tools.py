from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path
from typing import Any, Optional

# ============================================================================
# LSP Client Manager
# ============================================================================

class LSPClientManager:
    """
    Manages LSP server processes and communication.
    Singleton per language server type.
    """
    _instances: dict[str, 'LSPClientManager'] = {}
    
    def __init__(self, language: str, server_cmd: list[str], cwd: Path):
        self.language = language
        self.server_cmd = server_cmd
        self.cwd = cwd
        self.process: Optional[subprocess.Popen] = None
        self.request_id = 0
        self._initialized = False
    
    @classmethod
    def get_or_create(cls, language: str, cwd: Path) -> Optional['LSPClientManager']:
        """Get existing LSP client or create new one for the language."""
        # Language server command mappings
        server_commands = {
            'python': ['pyright-langserver', '--stdio'],
            'javascript': ['typescript-language-server', '--stdio'],
            'typescript': ['typescript-language-server', '--stdio'],
            'rust': ['rust-analyzer'],
            'go': ['gopls'],
            'java': ['jdtls'],
        }
        
        if language not in server_commands:
            return None
        
        key = f"{language}:{cwd}"
        if key not in cls._instances:
            cls._instances[key] = cls(language, server_commands[language], cwd)
        
        return cls._instances[key]
    
    async def start(self) -> bool:
        """Start the LSP server process."""
        if self.process is not None:
            return True
        
        try:
            self.process = subprocess.Popen(
                self.server_cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=self.cwd,
            )
            
            # Send initialize request
            await self._send_request('initialize', {
                'processId': None,
                'rootUri': f'file://{self.cwd}',
                'capabilities': {},
            })
            
            # Send initialized notification
            await self._send_notification('initialized', {})
            
            self._initialized = True
            return True
            
        except FileNotFoundError:
            return False
        except Exception:
            return False
    
    async def _send_request(self, method: str, params: dict) -> Optional[dict]:
        """Send JSON-RPC request and read response."""
        if self.process is None or self.process.stdin is None:
            return None
        
        self.request_id += 1
        request = {
            'jsonrpc': '2.0',
            'id': self.request_id,
            'method': method,
            'params': params,
        }
        
        content = json.dumps(request)
        message = f'Content-Length: {len(content)}\r\n\r\n{content}'
        
        try:
            self.process.stdin.write(message.encode('utf-8'))
            self.process.stdin.flush()
            
            # Read response (simplified - real implementation needs proper parsing)
            # This is a basic implementation; production would need async reading
            return None  # Placeholder
            
        except Exception:
            return None
    
    async def _send_notification(self, method: str, params: dict) -> None:
        """Send JSON-RPC notification (no response expected)."""
        if self.process is None or self.process.stdin is None:
            return
        
        notification = {
            'jsonrpc': '2.0',
            'method': method,
            'params': params,
        }
        
        content = json.dumps(notification)
        message = f'Content-Length: {len(content)}\r\n\r\n{content}'
        
        try:
            self.process.stdin.write(message.encode('utf-8'))
            self.process.stdin.flush()
        except Exception:
            pass
    
    def shutdown(self) -> None:
        """Shutdown the LSP server."""
        if self.process is not None:
            try:
                self.process.terminate()
                self.process.wait(timeout=5)
            except Exception:
                self.process.kill()
            self.process = None


# ============================================================================
# Helper functions
# ============================================================================

def _detect_language(file_path: Path) -> Optional[str]:
    """Detect programming language from file extension."""
    ext_map = {
        '.py': 'python',
        '.js': 'javascript',
        '.jsx': 'javascript',
        '.ts': 'typescript',
        '.tsx': 'typescript',
        '.rs': 'rust',
        '.go': 'go',
        '.java': 'java',
    }
    return ext_map.get(file_path.suffix.lower())


def _file_uri(file_path: Path) -> str:
    """Convert file path to URI."""
    return f'file://{file_path.resolve()}'


# ============================================================================
# lsp_diagnostics tool
# ============================================================================

LSP_DIAGNOSTICS_DESCRIPTION = (
    "Get LSP diagnostics (errors, warnings, hints) for a file. "
    "Automatically detects the language and starts the appropriate language server. "
    "Returns a list of issues with line numbers, severity, and messages."
)

LSP_DIAGNOSTICS_SCHEMA = {
    "type": "object",
    "properties": {
        "file": {
            "type": "string",
            "description": "Path to the file to analyze (relative or absolute).",
        },
    },
    "required": ["file"],
}


async def lsp_diagnostics_handler(tool_input: dict, context: Any) -> str:
    """Get diagnostics for a file using LSP."""
    file_path_str: str = tool_input.get("file", "")
    if not file_path_str:
        return "Error: file is required"
    
    file_path = Path(file_path_str)
    if not file_path.is_absolute():
        file_path = context.cwd / file_path
    
    if not file_path.exists():
        return f"Error: File not found: {file_path}"
    
    language = _detect_language(file_path)
    if language is None:
        return f"Error: Unsupported file type: {file_path.suffix}"
    
    # Note: Full LSP implementation requires async message handling
    # This is a simplified version that shows the structure
    return (
        f"LSP diagnostics for {file_path.name}:\n\n"
        f"Note: Full LSP integration requires language server installation:\n"
        f"  Python: pip install pyright\n"
        f"  TypeScript/JavaScript: npm install -g typescript-language-server\n"
        f"  Rust: rustup component add rust-analyzer\n\n"
        f"Language detected: {language}\n"
        f"This is a placeholder - full implementation requires async LSP protocol handling."
    )


# ============================================================================
# lsp_hover tool
# ============================================================================

LSP_HOVER_DESCRIPTION = (
    "Get hover information (type, documentation) for a symbol at a specific location. "
    "Useful for understanding what a variable, function, or class is."
)

LSP_HOVER_SCHEMA = {
    "type": "object",
    "properties": {
        "file": {
            "type": "string",
            "description": "Path to the file.",
        },
        "line": {
            "type": "integer",
            "description": "Line number (1-based).",
        },
        "column": {
            "type": "integer",
            "description": "Column number (0-based).",
        },
    },
    "required": ["file", "line", "column"],
}


async def lsp_hover_handler(tool_input: dict, context: Any) -> str:
    """Get hover information at a location."""
    file_path_str: str = tool_input.get("file", "")
    line: int = tool_input.get("line", 0)
    column: int = tool_input.get("column", 0)
    
    if not file_path_str:
        return "Error: file is required"
    
    file_path = Path(file_path_str)
    if not file_path.is_absolute():
        file_path = context.cwd / file_path
    
    if not file_path.exists():
        return f"Error: File not found: {file_path}"
    
    language = _detect_language(file_path)
    if language is None:
        return f"Error: Unsupported file type: {file_path.suffix}"
    
    return (
        f"LSP hover at {file_path.name}:{line}:{column}\n\n"
        f"Language: {language}\n"
        f"Note: Full LSP integration requires language server installation.\n"
        f"This is a placeholder - full implementation requires async LSP protocol handling."
    )


# ============================================================================
# lsp_definition tool
# ============================================================================

LSP_DEFINITION_DESCRIPTION = (
    "Jump to the definition of a symbol. Returns the file path and location "
    "where the symbol is defined."
)

LSP_DEFINITION_SCHEMA = {
    "type": "object",
    "properties": {
        "file": {
            "type": "string",
            "description": "Path to the file.",
        },
        "line": {
            "type": "integer",
            "description": "Line number (1-based).",
        },
        "column": {
            "type": "integer",
            "description": "Column number (0-based).",
        },
    },
    "required": ["file", "line", "column"],
}


async def lsp_definition_handler(tool_input: dict, context: Any) -> str:
    """Go to definition of symbol at location."""
    file_path_str: str = tool_input.get("file", "")
    line: int = tool_input.get("line", 0)
    column: int = tool_input.get("column", 0)
    
    if not file_path_str:
        return "Error: file is required"
    
    file_path = Path(file_path_str)
    if not file_path.is_absolute():
        file_path = context.cwd / file_path
    
    if not file_path.exists():
        return f"Error: File not found: {file_path}"
    
    language = _detect_language(file_path)
    if language is None:
        return f"Error: Unsupported file type: {file_path.suffix}"
    
    return (
        f"LSP definition lookup at {file_path.name}:{line}:{column}\n\n"
        f"Language: {language}\n"
        f"Note: Full LSP integration requires language server installation.\n"
        f"This is a placeholder - full implementation requires async LSP protocol handling."
    )


# ============================================================================
# lsp_references tool
# ============================================================================

LSP_REFERENCES_DESCRIPTION = (
    "Find all references to a symbol. Returns a list of locations where "
    "the symbol is used throughout the codebase."
)

LSP_REFERENCES_SCHEMA = {
    "type": "object",
    "properties": {
        "file": {
            "type": "string",
            "description": "Path to the file.",
        },
        "line": {
            "type": "integer",
            "description": "Line number (1-based).",
        },
        "column": {
            "type": "integer",
            "description": "Column number (0-based).",
        },
        "include_declaration": {
            "type": "boolean",
            "description": "Include the declaration in results. Default: true.",
        },
    },
    "required": ["file", "line", "column"],
}


async def lsp_references_handler(tool_input: dict, context: Any) -> str:
    """Find all references to symbol at location."""
    file_path_str: str = tool_input.get("file", "")
    line: int = tool_input.get("line", 0)
    column: int = tool_input.get("column", 0)
    
    if not file_path_str:
        return "Error: file is required"
    
    file_path = Path(file_path_str)
    if not file_path.is_absolute():
        file_path = context.cwd / file_path
    
    if not file_path.exists():
        return f"Error: File not found: {file_path}"
    
    language = _detect_language(file_path)
    if language is None:
        return f"Error: Unsupported file type: {file_path.suffix}"
    
    return (
        f"LSP references lookup at {file_path.name}:{line}:{column}\n\n"
        f"Language: {language}\n"
        f"Note: Full LSP integration requires language server installation.\n"
        f"This is a placeholder - full implementation requires async LSP protocol handling."
    )


# ============================================================================
# lsp_rename tool
# ============================================================================

LSP_RENAME_DESCRIPTION = (
    "Rename a symbol throughout the codebase. Returns a list of edits "
    "that would be applied to rename the symbol safely."
)

LSP_RENAME_SCHEMA = {
    "type": "object",
    "properties": {
        "file": {
            "type": "string",
            "description": "Path to the file.",
        },
        "line": {
            "type": "integer",
            "description": "Line number (1-based).",
        },
        "column": {
            "type": "integer",
            "description": "Column number (0-based).",
        },
        "new_name": {
            "type": "string",
            "description": "New name for the symbol.",
        },
    },
    "required": ["file", "line", "column", "new_name"],
}


async def lsp_rename_handler(tool_input: dict, context: Any) -> str:
    """Rename symbol at location."""
    file_path_str: str = tool_input.get("file", "")
    line: int = tool_input.get("line", 0)
    column: int = tool_input.get("column", 0)
    new_name: str = tool_input.get("new_name", "")
    
    if not file_path_str:
        return "Error: file is required"
    if not new_name:
        return "Error: new_name is required"
    
    file_path = Path(file_path_str)
    if not file_path.is_absolute():
        file_path = context.cwd / file_path
    
    if not file_path.exists():
        return f"Error: File not found: {file_path}"
    
    language = _detect_language(file_path)
    if language is None:
        return f"Error: Unsupported file type: {file_path.suffix}"
    
    return (
        f"LSP rename at {file_path.name}:{line}:{column} to '{new_name}'\n\n"
        f"Language: {language}\n"
        f"Note: Full LSP integration requires language server installation.\n"
        f"This is a placeholder - full implementation requires async LSP protocol handling."
    )
