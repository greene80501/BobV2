from __future__ import annotations

import re
from bob.swarm.models import TaskComplexity


# Keywords that strongly suggest a complex, multi-agent task
_COMPLEX_KW = frozenset([
    "refactor", "migrate", "rewrite", "restructure", "overhaul",
    "redesign", "rearchitect", "modernize", "comprehensive",
    "entire codebase", "all files", "from scratch", "large-scale",
    "end-to-end", "full pipeline", "full test suite", "all tests",
    "build system", "upgrade entire", "convert entire", "replace entire",
])

# Keywords that suggest a moderately complex task
_MODERATE_KW = frozenset([
    "add tests", "write tests", "test coverage", "implement",
    "add feature", "create module", "new component", "build",
    "update multiple", "change across", "fix all", "replace",
    "convert", "transform", "analyze", "review all", "audit",
    "integrate", "deployment", "ci/cd", "pipeline",
])

_MULTI_FILE_RE = re.compile(
    r"\b(files?|modules?|classes?|components?|services?|endpoints?|packages?)\b",
    re.IGNORECASE,
)
_SEQUENTIAL_RE = re.compile(
    r"\b(then|also|additionally|furthermore|after that|next|finally|and then)\b",
    re.IGNORECASE,
)


class TaskComplexityAnalyzer:
    """Heuristic complexity classifier — no LLM call required."""

    def classify(self, task: str) -> tuple[TaskComplexity, str]:
        """Return (TaskComplexity, human-readable reason)."""
        lower = task.lower()
        words = task.split()
        wc = len(words)

        if wc > 120:
            return TaskComplexity.COMPLEX, f"task description is {wc} words"

        complex_hits = [kw for kw in _COMPLEX_KW if kw in lower]
        if complex_hits:
            return TaskComplexity.COMPLEX, f"complex keywords: {', '.join(complex_hits[:3])}"

        moderate_hits = [kw for kw in _MODERATE_KW if kw in lower]
        multi_file = len(_MULTI_FILE_RE.findall(lower)) >= 2
        sequential = len(_SEQUENTIAL_RE.findall(lower)) >= 2

        if moderate_hits and (multi_file or sequential or wc > 45):
            reason = ", ".join(moderate_hits[:2])
            if multi_file:
                reason += " · multi-file"
            if sequential:
                reason += " · multi-step"
            return TaskComplexity.MODERATE, reason

        if multi_file and sequential:
            return TaskComplexity.MODERATE, "multiple files with sequential steps"

        if wc > 60:
            return TaskComplexity.MODERATE, f"detailed task ({wc} words)"

        return TaskComplexity.SIMPLE, "focused single-step task"
