"""CritPt dataset loader – research-level physics challenges.

Downloads from HuggingFace on first use, caches locally.
Dataset: CritPt-Benchmark/CritPt (71 challenges, 190 checkpoint tasks)
"""

import json
import logging
from pathlib import Path
from typing import Optional

from ..base import BenchmarkTask

log = logging.getLogger(__name__)

CACHE_DIR = Path(__file__).resolve().parent.parent.parent.parent / "data" / "datasets" / "critpt"
HF_DATASET = "CritPt-Benchmark/CritPt"


def load_dataset(limit: Optional[int] = None) -> list[BenchmarkTask]:
    """Load CritPt tasks, downloading from HuggingFace if needed."""
    cache_file = CACHE_DIR / "tasks.json"

    if cache_file.exists():
        log.info("Loading CritPt from cache: %s", cache_file)
        tasks_data = json.loads(cache_file.read_text(encoding="utf-8"))
    else:
        log.info("Downloading CritPt dataset from HuggingFace...")
        tasks_data = _download_dataset()
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps(tasks_data, indent=2), encoding="utf-8")
        log.info("Cached %d tasks to %s", len(tasks_data), cache_file)

    tasks = []
    for item in tasks_data:
        # Build the prompt from problem description + code template
        prompt_parts = []
        if item.get("problem_description"):
            prompt_parts.append(item["problem_description"])
        if item.get("code_template"):
            prompt_parts.append(
                "\n\nImplement the following function:\n\n"
                + item["code_template"]
            )
        prompt = "\n".join(prompt_parts) if prompt_parts else item.get("prompt", "")

        tasks.append(BenchmarkTask(
            task_id=item["task_id"],
            task_name=item.get("task_name", item["task_id"]),
            prompt=prompt,
            expected=item.get("answer_code"),
            metadata={
                "problem_type": item.get("problem_type", "main"),
                "challenge_id": item.get("challenge_id", ""),
                "code_template": item.get("code_template", ""),
                "notebook_path": item.get("metadata_notebook_path", ""),
            },
        ))

    if limit:
        tasks = tasks[:limit]

    log.info("Loaded %d CritPt tasks", len(tasks))
    return tasks


def _download_dataset() -> list[dict]:
    """Download CritPt dataset from HuggingFace."""
    try:
        from datasets import load_dataset as hf_load
        ds = hf_load(HF_DATASET, split="test")
        tasks = []
        for row in ds:
            task_id = row.get("problem_id", row.get("id", f"critpt_{len(tasks)}"))
            tasks.append({
                "task_id": task_id,
                "task_name": task_id.replace("_", " ").title(),
                "problem_description": row.get("problem_description", ""),
                "code_template": row.get("code_template", ""),
                "answer_code": row.get("answer_code", ""),
                "answer_only_code": row.get("answer_only_code", ""),
                "problem_type": row.get("problem_type", "main"),
                "challenge_id": task_id.rsplit("_", 1)[0] if "_" in task_id else task_id,
                "metadata_notebook_path": row.get("metadata_notebook_path", ""),
            })
        return tasks
    except Exception as e:
        log.warning("Failed to download CritPt from HuggingFace: %s", e)
        log.info("Using built-in sample tasks")
        return _builtin_sample_tasks()


def _builtin_sample_tasks() -> list[dict]:
    """Minimal sample tasks for testing when dataset unavailable."""
    return [
        {
            "task_id": "critpt_sample_1",
            "task_name": "Simple Physics Calculation",
            "problem_description": (
                "Calculate the de Broglie wavelength of an electron "
                "moving at 1% the speed of light. Return the wavelength "
                "in meters."
            ),
            "code_template": "def answer():\n    # Calculate de Broglie wavelength\n    return wavelength",
            "problem_type": "main",
            "challenge_id": "sample_1",
        },
    ]
