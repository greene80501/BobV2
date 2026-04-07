"""Theme configuration for TUI color output."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ThemeName(str, Enum):
    """Available theme names."""
    DARK = "dark"
    LIGHT = "light"
    NO_COLOR = "no-color"


@dataclass(frozen=True)
class Theme:
    """Color theme for TUI output.
    
    Each field contains ANSI escape codes for styling.
    """
    # Primary brand color (for Bob's identity)
    BRAND: str
    
    # Text emphasis
    DIM: str
    BOLD: str
    ITALIC: str
    UNDERLINE: str
    
    # Semantic colors
    ERROR: str      # Red for errors
    WARNING: str    # Yellow for warnings
    SUCCESS: str    # Green for success
    INFO: str       # Blue/cyan for info
    
    # Syntax highlighting
    KEYWORD: str    # Language keywords
    STRING: str     # String literals
    NUMBER: str     # Numeric literals
    COMMENT: str    # Comments
    FUNCTION: str   # Function names
    
    # Diff colors
    DIFF_ADD: str       # + lines
    DIFF_REMOVE: str    # - lines
    DIFF_HEADER: str    # @@ headers
    
    # UI elements
    PROMPT: str         # User prompt
    SPINNER: str        # Loading spinner
    SEPARATOR: str      # Visual separators
    
    # Reset
    RESET: str


# Dark theme (default)
DARK_THEME = Theme(
    BRAND="\033[35m",           # Magenta
    DIM="\033[2m",              # Dim
    BOLD="\033[1m",             # Bold
    ITALIC="\033[3m",           # Italic
    UNDERLINE="\033[4m",        # Underline
    ERROR="\033[31m",           # Red
    WARNING="\033[33m",         # Yellow
    SUCCESS="\033[32m",         # Green
    INFO="\033[36m",            # Cyan
    KEYWORD="\033[35m",         # Magenta
    STRING="\033[32m",          # Green
    NUMBER="\033[33m",          # Yellow
    COMMENT="\033[2;37m",       # Dim white
    FUNCTION="\033[34m",        # Blue
    DIFF_ADD="\033[32m",        # Green
    DIFF_REMOVE="\033[31m",     # Red
    DIFF_HEADER="\033[36m",     # Cyan
    PROMPT="\033[1;36m",        # Bold cyan
    SPINNER="\033[2;37m",       # Dim white
    SEPARATOR="\033[2;37m",     # Dim white
    RESET="\033[0m",            # Reset
)


# Light theme (for light backgrounds)
LIGHT_THEME = Theme(
    BRAND="\033[35m",           # Magenta
    DIM="\033[2m",              # Dim
    BOLD="\033[1m",             # Bold
    ITALIC="\033[3m",           # Italic
    UNDERLINE="\033[4m",        # Underline
    ERROR="\033[31m",           # Red
    WARNING="\033[33m",         # Yellow
    SUCCESS="\033[32m",         # Green
    INFO="\033[34m",            # Blue
    KEYWORD="\033[35m",         # Magenta
    STRING="\033[32m",          # Green
    NUMBER="\033[33m",          # Yellow
    COMMENT="\033[2;30m",       # Dim black
    FUNCTION="\033[34m",        # Blue
    DIFF_ADD="\033[32m",        # Green
    DIFF_REMOVE="\033[31m",     # Red
    DIFF_HEADER="\033[36m",     # Cyan
    PROMPT="\033[1;34m",        # Bold blue
    SPINNER="\033[2;30m",       # Dim black
    SEPARATOR="\033[2;30m",     # Dim black
    RESET="\033[0m",            # Reset
)


# No-color theme (plain text)
NO_COLOR_THEME = Theme(
    BRAND="",
    DIM="",
    BOLD="",
    ITALIC="",
    UNDERLINE="",
    ERROR="",
    WARNING="",
    SUCCESS="",
    INFO="",
    KEYWORD="",
    STRING="",
    NUMBER="",
    COMMENT="",
    FUNCTION="",
    DIFF_ADD="",
    DIFF_REMOVE="",
    DIFF_HEADER="",
    PROMPT="",
    SPINNER="",
    SEPARATOR="",
    RESET="",
)


def get_theme(name: ThemeName | str, no_color: bool = False) -> Theme:
    """Get a theme by name.
    
    Args:
        name: Theme name (dark, light, no-color)
        no_color: If True, force no-color theme regardless of name
        
    Returns:
        Theme instance with appropriate color codes
    """
    if no_color:
        return NO_COLOR_THEME
    
    if isinstance(name, str):
        name = ThemeName(name.lower())
    
    if name == ThemeName.LIGHT:
        return LIGHT_THEME
    elif name == ThemeName.NO_COLOR:
        return NO_COLOR_THEME
    else:
        return DARK_THEME
