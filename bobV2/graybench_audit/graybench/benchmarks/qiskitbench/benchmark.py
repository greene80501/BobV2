"""QiskitBench – Qiskit HumanEval benchmarks (Hard and Normal variants)."""

import time
import logging
from typing import Optional, Literal, TYPE_CHECKING

from ..base import Benchmark, BenchmarkTask, TaskResult, register_benchmark
from .dataset import load_dataset, Variant
from .evaluator import run_code, extract_code

if TYPE_CHECKING:
    from graybench.environments import ExecutionEnvironment

log = logging.getLogger(__name__)


def _resolve_benchmark_env_vars() -> dict[str, str]:
    """Resolve API keys needed by benchmark code (e.g. IBM Quantum).

    Keys stored via ``graybench keys set`` are resolved and mapped to
    the environment variables that the SDKs expect.
    """
    env_vars: dict[str, str] = {}
    try:
        from graybench.db.api_keys import get_key
        ibm_token = get_key("ibm_quantum")
        if ibm_token:
            env_vars["QISKIT_IBM_TOKEN"] = ibm_token
    except Exception:
        pass
    return env_vars


def _fix_deprecated_channel(code: str) -> str:
    """Replace deprecated channel='ibm_quantum' with 'ibm_quantum_platform'.

    The Qiskit HumanEval dataset was written for qiskit-ibm-runtime <0.39
    which used channel='ibm_quantum'. SDK 0.39+ renamed it to
    'ibm_quantum_platform'. This fixup keeps both test harness code and
    LLM-generated code working with the current SDK.
    """
    import re
    return re.sub(
        r"""channel\s*=\s*(['"])ibm_quantum\1""",
        r'channel=\1ibm_quantum_platform\1',
        code,
    )

SYSTEM_PROMPT = """You are an expert quantum computing programmer using Qiskit.
Write Python code that solves the given task. Use Qiskit 2.0.0 APIs.
Return ONLY the Python code inside a single ```python code fence.
Include all necessary imports. Do not include any explanation outside the code fence."""


class QiskitBenchmarkBase(Benchmark):
    """Base class for Qiskit HumanEval benchmarks."""

    _variant: Variant = "hard"  # Override in subclasses
    _environment: Optional["ExecutionEnvironment"] = None

    def load_tasks(self, limit: Optional[int] = None) -> list[BenchmarkTask]:
        return load_dataset(variant=self._variant, limit=limit)

    def get_execution_environment(self) -> Optional["ExecutionEnvironment"]:
        """Return the Qiskit environment for executing generated code.
        
        This ensures code runs in an isolated venv with Qiskit 2.0.0.
        """
        if self._environment is None:
            from .environment import QiskitEnvironment
            self._environment = QiskitEnvironment()
        return self._environment

    def evaluate_task(self, task: BenchmarkTask, llm) -> TaskResult:
        """Direct LLM call + execution in isolated environment."""
        t0 = time.monotonic()

        # Get response with tracking if available
        input_tok = output_tok = cached_tok = reasoning_tok = 0
        if hasattr(llm, "generate_with_tracking"):
            # Pass canonical solution if available
            canonical = task.metadata.get('canonical_solution')
            if canonical:
                response = llm.generate_with_tracking(SYSTEM_PROMPT, task.prompt, canonical_solution=canonical)
            else:
                response = llm.generate_with_tracking(SYSTEM_PROMPT, task.prompt)
            raw_text = response.text
            tokens = response.input_tokens + response.output_tokens
            input_tok = response.input_tokens
            output_tok = response.output_tokens
            cached_tok = response.cached_tokens
            reasoning_tok = response.reasoning_tokens
            cost = 0.0  # Calculated by runner via cost_tracker
        else:
            raw_text = llm.generate(SYSTEM_PROMPT, task.prompt)
            tokens = 0
            cost = 0.0

        # Build task metadata
        test_code = task.metadata.get("test_code", "")
        meta = {
            "entry_point": task.metadata.get("entry_point", ""),
            "variant": self._variant,
            "has_test_code": bool(test_code),
            "requires_runtime": "QiskitRuntimeService" in task.prompt or "QiskitRuntimeService" in test_code,
        }

        # Extract code from response
        code = extract_code(raw_text)

        # If no code was extracted, fail immediately with a clear message
        if not code:
            duration = time.monotonic() - t0
            return TaskResult(
                task_id=task.task_id,
                passed=False,
                score=0.0,
                generated_code="",
                actual_output="",
                error="LLM response contained no extractable Python code",
                tokens_used=tokens,
                cost_usd=cost,
                duration_s=duration,
                metadata=meta,
                raw_response=raw_text,
                input_tokens=input_tok,
                output_tokens=output_tok,
                cached_tokens=cached_tok,
                reasoning_tokens=reasoning_tok,
            )

        # Get the execution environment
        environment = self.get_execution_environment()
        if environment:
            environment.ensure_exists()

        # Fix deprecated channel='ibm_quantum' → 'ibm_quantum_platform' (SDK 0.39+)
        code = _fix_deprecated_channel(code)
        test_code = _fix_deprecated_channel(test_code)

        # Run with test harness if available
        # QiskitRuntimeService takes ~60s per instantiation for auth + backend discovery.
        # Tasks with service calls in both solution and test harness need 600s.
        timeout = 600 if "QiskitRuntimeService" in code or "QiskitRuntimeService" in test_code else 120
        env_vars = _resolve_benchmark_env_vars()
        exec_result = run_code(code, test_code=test_code, timeout=timeout, environment=environment, env_vars=env_vars)

        duration = time.monotonic() - t0

        return TaskResult(
            task_id=task.task_id,
            passed=exec_result.passed,
            score=1.0 if exec_result.passed else 0.0,
            generated_code=code,
            actual_output=exec_result.stdout[:2000] if exec_result.stdout else exec_result.stderr[:2000],
            error=exec_result.stderr[:2000] if not exec_result.passed else None,
            tokens_used=tokens,
            cost_usd=cost,
            duration_s=duration,
            metadata=meta,
            raw_response=raw_text,
            input_tokens=input_tok,
            output_tokens=output_tok,
            cached_tokens=cached_tok,
            reasoning_tokens=reasoning_tok,
        )


@register_benchmark
class QiskitBenchmarkHard(QiskitBenchmarkBase):
    """Qiskit HumanEval-Hard benchmark.

    This variant contains more challenging quantum computing tasks that require
    deeper understanding of Qiskit APIs and quantum algorithms.
    """

    _variant: Variant = "hard"

    def name(self) -> str:
        return "qiskitbench-hard"

    def display_name(self) -> str:
        return "QiskitBench (HumanEval-Hard)"


@register_benchmark
class QiskitBenchmarkNormal(QiskitBenchmarkBase):
    """Qiskit HumanEval benchmark (standard difficulty).

    This variant contains standard quantum computing tasks suitable for
    evaluating basic Qiskit proficiency.
    """

    _variant: Variant = "normal"

    def name(self) -> str:
        return "qiskitbench"

    def display_name(self) -> str:
        return "QiskitBench (HumanEval)"
