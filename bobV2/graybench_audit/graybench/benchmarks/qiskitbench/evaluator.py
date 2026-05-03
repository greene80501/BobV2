"""QiskitBench evaluator – runs generated code using execution environment.

This module provides code extraction and evaluation for QiskitBench.
Code execution is delegated to the QiskitEnvironment for proper isolation.
"""

import re
import logging
from typing import Optional, TYPE_CHECKING

from graybench.environments import ExecutionResult

if TYPE_CHECKING:
    from graybench.environments import ExecutionEnvironment

log = logging.getLogger(__name__)


def run_code(
    code: str,
    test_code: str = "",
    entry_point: str = "",
    timeout: int = 120,
    environment: Optional["ExecutionEnvironment"] = None,
    env_vars: Optional[dict[str, str]] = None,
) -> ExecutionResult:
    """Execute generated code using the provided environment.

    If test_code is provided, it's appended after the generated code.
    The code runs in the specified environment (defaults to QiskitEnvironment).

    Args:
        code: The generated Python code to execute
        test_code: Optional test harness code to append
        entry_point: Optional entry point function name
        timeout: Maximum execution time in seconds
        environment: Execution environment to use (defaults to QiskitEnvironment)
        env_vars: Extra environment variables to inject into the subprocess

    Returns:
        ExecutionResult with pass/fail status, stdout, stderr
    """
    # Build the script
    script = code.strip() + "\n"
    if test_code:
        script += "\n# --- Test harness ---\n"
        script += test_code.strip() + "\n"

    # Use provided environment or create default
    if environment is None:
        from .environment import QiskitEnvironment
        environment = QiskitEnvironment()
        environment.ensure_exists()

    # Delegate execution to the environment
    return environment.run_code(script, timeout=timeout, env_vars=env_vars)


def extract_code(response: str) -> str:
    """Extract Python code from an LLM response.

    Handles markdown code fences, bare code, etc.
    """
    # Try to extract from ```python ... ``` blocks
    pattern = r"```(?:python)?\s*\n(.*?)```"
    matches = re.findall(pattern, response, re.DOTALL)
    if matches:
        # Return the last match – LLMs typically put the final solution last
        return matches[-1].strip()

    # If no fences, try to find contiguous code (imports + function defs).
    # Stop collecting when we hit a non-code, non-blank line after code started
    # (e.g. natural language explanation following the code).
    lines = response.strip().split("\n")
    code_lines = []
    in_code = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("def ") or stripped.startswith("import ") or stripped.startswith("from "):
            in_code = True
        if in_code:
            # A blank line or indented/code-like line continues the block
            if stripped == "" or line[0:1] in (" ", "\t") or stripped.startswith(("def ", "import ", "from ", "class ", "return ", "#", "@")):
                code_lines.append(line)
            else:
                # Non-code line (likely natural language) – stop
                break

    if code_lines:
        return "\n".join(code_lines).rstrip()

    # Last resort: only return raw text if it looks like Python code.
    # If the LLM returned pure reasoning/LaTeX with no code at all,
    # return empty string so the failure is clean (no code generated).
    raw = response.strip()
    python_starters = ("import ", "from ", "def ", "class ", "#!", "#")
    for line in raw.split("\n"):
        stripped = line.strip()
        if stripped and any(stripped.startswith(s) for s in python_starters):
            return raw
    return ""
