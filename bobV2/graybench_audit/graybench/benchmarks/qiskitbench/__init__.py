"""QiskitBench – Qiskit HumanEval benchmarks (Hard and Normal variants)."""

# Import environment first to ensure registration
from .environment import QiskitEnvironment, _register  # noqa: F401

# Import benchmark classes (triggers registration)
from .benchmark import (  # noqa: F401
    QiskitBenchmarkHard,
    QiskitBenchmarkNormal,
)

__all__ = [
    "QiskitBenchmarkHard",
    "QiskitBenchmarkNormal",
    "QiskitEnvironment",
]
