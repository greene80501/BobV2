"""Abstract base types for all benchmarks."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from graybench.environments import ExecutionEnvironment


@dataclass
class BenchmarkTask:
    """A single benchmark task to evaluate."""
    task_id: str
    task_name: str
    prompt: str
    expected: Optional[str] = None
    metadata: dict = field(default_factory=dict)


@dataclass
class TaskResult:
    """Result of evaluating a single benchmark task."""
    task_id: str
    passed: bool
    score: float  # 0.0 to 1.0
    generated_code: str = ""
    actual_output: str = ""
    error: Optional[str] = None
    tokens_used: int = 0
    cost_usd: float = 0.0
    duration_s: float = 0.0
    attempts: int = 1
    metadata: dict = field(default_factory=dict)
    raw_response: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    reasoning_tokens: int = 0
    failure_category: Optional[str] = None


class Benchmark(ABC):
    """Base class for all benchmarks.
    
    Benchmarks can optionally provide an execution environment for running
generated code safely. Override get_execution_environment() to return
    a custom environment, or return None to use system Python.
    """

    @abstractmethod
    def name(self) -> str:
        """Unique benchmark identifier (e.g., 'qiskitbench', 'critpt')."""
        ...

    @abstractmethod
    def display_name(self) -> str:
        """Human-readable name."""
        ...

    @abstractmethod
    def load_tasks(self, limit: Optional[int] = None) -> list[BenchmarkTask]:
        """Load benchmark tasks. Downloads dataset on first call if needed."""
        ...

    @abstractmethod
    def evaluate_task(self, task: BenchmarkTask, llm) -> TaskResult:
        """Evaluate a single task using the given LLM provider."""
        ...

    def get_execution_environment(self) -> Optional["ExecutionEnvironment"]:
        """Return the execution environment for this benchmark.
        
        Returns:
            An ExecutionEnvironment instance for running generated code,
            or None to use system Python directly.
            
        Example:
            def get_execution_environment(self):
                from mybench.environment import MyEnvironment
                return MyEnvironment()
        """
        return None

    def aggregate_results(self, results: list[TaskResult]) -> dict:
        """Compute aggregate metrics from task results."""
        if not results:
            return {"total": 0, "passed": 0, "failed": 0, "score": 0.0}

        passed = sum(1 for r in results if r.passed)
        total = len(results)
        avg_score = sum(r.score for r in results) / total
        total_cost = sum(r.cost_usd for r in results)
        total_tokens = sum(r.tokens_used for r in results)
        total_duration = sum(r.duration_s for r in results)

        return {
            "total": total,
            "passed": passed,
            "failed": total - passed,
            "score": round(avg_score, 4),
            "total_cost_usd": round(total_cost, 6),
            "total_tokens": total_tokens,
            "total_duration_s": round(total_duration, 2),
        }


# Registry of available benchmarks
_BENCHMARKS: dict[str, type[Benchmark]] = {}


def register_benchmark(cls: type[Benchmark]) -> type[Benchmark]:
    """Decorator to register a benchmark class."""
    instance = cls()
    _BENCHMARKS[instance.name()] = cls
    return cls


def get_benchmark(name: str) -> Benchmark:
    """Get a benchmark instance by name."""
    if name not in _BENCHMARKS:
        # Try lazy imports
        _try_import_benchmarks()
    if name not in _BENCHMARKS:
        available = ", ".join(sorted(_BENCHMARKS.keys()))
        raise ValueError(f"Unknown benchmark '{name}'. Available: {available}")
    return _BENCHMARKS[name]()


def list_benchmarks() -> list[str]:
    """List all available benchmark names."""
    _try_import_benchmarks()
    return sorted(_BENCHMARKS.keys())


def _try_import_benchmarks():
    """Try to import all benchmark modules to populate registry."""
    try:
        from graybench.benchmarks import qiskitbench  # noqa: F401
    except ImportError:
        pass
    try:
        from graybench.benchmarks import critpt  # noqa: F401
    except ImportError:
        pass
