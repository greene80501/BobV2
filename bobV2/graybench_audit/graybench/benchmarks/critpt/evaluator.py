"""CritPt evaluator – executes answer functions locally.

CritPt's official evaluation uses an external server. For local testing,
we run the generated code and check if it produces output without errors.
For official scoring, use the CritPt submission pipeline.
"""

import re
import logging
from dataclasses import dataclass
from typing import Optional

from graybench.environments import SYSTEM_PYTHON

log = logging.getLogger(__name__)


@dataclass
class CritPtResult:
    executed: bool
    output: str
    error: Optional[str]
    timeout: bool = False


def evaluate_locally(code: str, timeout: int = 120) -> CritPtResult:
    """Execute a CritPt answer function locally.

    Wraps the code with a call to answer() and captures the output.
    This is for local validation only – official grading requires
    submission to the CritPt evaluation server.
    """
    # Build script that calls answer() and prints result
    script = code.strip() + "\n\n"
    script += "if __name__ == '__main__':\n"
    script += "    result = answer()\n"
    script += "    print(repr(result))\n"

    result = SYSTEM_PYTHON.run_code(script, timeout=timeout)

    if result.timeout:
        return CritPtResult(
            executed=False,
            output="",
            error=f"Execution timed out after {timeout}s",
            timeout=True,
        )

    return CritPtResult(
        executed=result.passed,
        output=result.stdout.strip(),
        error=result.stderr.strip() if not result.passed else None,
    )


def extract_answer_function(response: str) -> str:
    """Extract the def answer() function from an LLM response."""
    # Try markdown code blocks
    pattern = r"```(?:python)?\s*\n(.*?)```"
    matches = re.findall(pattern, response, re.DOTALL)
    if matches:
        for match in matches:
            if "def answer" in match:
                return match.strip()
        # Return longest block as fallback
        return max(matches, key=len).strip()

    # Try to find bare function
    lines = response.strip().split("\n")
    code_lines = []
    capture = False
    for line in lines:
        if line.startswith("def answer"):
            capture = True
        if capture:
            code_lines.append(line)
            # Stop at next top-level definition or empty line after return
            if code_lines and line.strip().startswith("return ") and len(code_lines) > 1:
                # Capture through end of function
                pass

    if code_lines:
        return "\n".join(code_lines)

    return response.strip()
