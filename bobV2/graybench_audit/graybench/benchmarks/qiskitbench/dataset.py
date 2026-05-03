"""QiskitBench dataset loader – HumanEval for Qiskit (Hard and Normal variants).

Downloads from HuggingFace on first use, caches locally.
"""

import json
import logging
from pathlib import Path
from typing import Optional, Literal

from ..base import BenchmarkTask

log = logging.getLogger(__name__)

CACHE_DIR = Path(__file__).resolve().parent.parent.parent.parent / "data" / "datasets" / "qiskitbench"

# HuggingFace dataset identifiers for each variant
# Official Qiskit HumanEval: https://huggingface.co/datasets/Qiskit/qiskit_humaneval
HF_DATASETS = {
    "hard": "Qiskit/qiskit_humaneval_hard",
    "normal": "Qiskit/qiskit_humaneval",
}

Variant = Literal["hard", "normal"]


def load_dataset(variant: Variant = "hard", limit: Optional[int] = None) -> list[BenchmarkTask]:
    """Load QiskitBench tasks, downloading from HuggingFace if needed.

    Args:
        variant: Which dataset variant to load ("hard" or "normal")
        limit: Maximum number of tasks to return

    Returns:
        List of BenchmarkTask objects
    """
    if variant not in HF_DATASETS:
        raise ValueError(f"Unknown variant '{variant}'. Must be one of: {list(HF_DATASETS.keys())}")

    cache_file = CACHE_DIR / f"tasks_{variant}.json"

    if cache_file.exists():
        log.info("Loading QiskitBench (%s) from cache: %s", variant, cache_file)
        tasks_data = json.loads(cache_file.read_text(encoding="utf-8"))
    else:
        log.info("Downloading QiskitBench (%s) dataset from HuggingFace...", variant)
        tasks_data = _download_dataset(variant)
        # Cache locally
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps(tasks_data, indent=2), encoding="utf-8")
        log.info("Cached %d tasks to %s", len(tasks_data), cache_file)

    tasks = []
    for item in tasks_data:
        tasks.append(BenchmarkTask(
            task_id=item["task_id"],
            task_name=item.get("task_name", item["task_id"]),
            prompt=item["prompt"],
            expected=item.get("expected"),
            metadata={
                "entry_point": item.get("entry_point", ""),
                "test_code": item.get("test_code", ""),
                "canonical_solution": item.get("canonical_solution", ""),
                "variant": variant,
            },
        ))

    if limit:
        tasks = tasks[:limit]

    log.info("Loaded %d QiskitBench (%s) tasks", len(tasks), variant)
    return tasks


def _download_dataset(variant: Variant) -> list[dict]:
    """Download dataset from HuggingFace."""
    hf_dataset = HF_DATASETS[variant]
    try:
        from datasets import load_dataset as hf_load
        ds = hf_load(hf_dataset, split="test")
        tasks = []
        for row in ds:
            tasks.append({
                "task_id": row.get("task_id", row.get("id", "")),
                "task_name": row.get("task_name", ""),
                "prompt": row.get("prompt", row.get("problem", "")),
                "expected": row.get("expected", row.get("canonical_solution", "")),
                "entry_point": row.get("entry_point", ""),
                "test_code": row.get("test", row.get("test_code", "")),
                "canonical_solution": row.get("canonical_solution", ""),
            })
        return tasks
    except Exception as e:
        log.warning("Failed to download from HuggingFace (%s): %s", hf_dataset, e)
        log.info("Using built-in sample tasks for %s variant", variant)
        return _builtin_sample_tasks(variant)


def _builtin_sample_tasks(variant: Variant) -> list[dict]:
    """Minimal sample tasks for testing when dataset unavailable."""
    # Both variants share similar sample structure, but hard has more complex tasks
    base_tasks = [
        {
            "task_id": f"qiskit_{variant}_sample_1",
            "task_name": "Bell State Circuit",
            "prompt": (
                "Write a Python function called `create_bell_state` that uses "
                "Qiskit to create a Bell state circuit. The function should take "
                "no arguments and return a QuantumCircuit with 2 qubits that "
                "prepares the |Φ+⟩ Bell state (H on q0, CNOT q0→q1)."
            ),
            "expected": None,
            "entry_point": "create_bell_state",
            "test_code": (
                "from qiskit import QuantumCircuit\n"
                "qc = create_bell_state()\n"
                "assert isinstance(qc, QuantumCircuit)\n"
                "assert qc.num_qubits == 2\n"
                "print('PASS')\n"
            ),
        },
        {
            "task_id": f"qiskit_{variant}_sample_2",
            "task_name": "GHZ State",
            "prompt": (
                "Write a Python function called `create_ghz_state` that takes "
                "an integer `n` (number of qubits) and returns a Qiskit "
                "QuantumCircuit that prepares an n-qubit GHZ state."
            ),
            "expected": None,
            "entry_point": "create_ghz_state",
            "test_code": (
                "from qiskit import QuantumCircuit\n"
                "qc = create_ghz_state(3)\n"
                "assert isinstance(qc, QuantumCircuit)\n"
                "assert qc.num_qubits == 3\n"
                "print('PASS')\n"
            ),
        },
    ]

    if variant == "hard":
        # Add more complex sample tasks for the hard variant
        base_tasks.append({
            "task_id": "qiskit_hard_sample_3",
            "task_name": "Quantum Fourier Transform",
            "prompt": (
                "Write a Python function called `create_qft_circuit` that takes "
                "an integer `n` (number of qubits) and returns a Qiskit "
                "QuantumCircuit implementing the Quantum Fourier Transform (QFT). "
                "Include the swap operations at the end to reverse the qubit order."
            ),
            "expected": None,
            "entry_point": "create_qft_circuit",
            "test_code": (
                "from qiskit import QuantumCircuit\n"
                "import numpy as np\n"
                "qc = create_qft_circuit(4)\n"
                "assert isinstance(qc, QuantumCircuit)\n"
                "assert qc.num_qubits == 4\n"
                "print('PASS')\n"
            ),
        })

    return base_tasks
