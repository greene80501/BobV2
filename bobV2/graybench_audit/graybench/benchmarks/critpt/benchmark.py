"""CritPt – Research-level physics benchmark."""

import time
import logging
from typing import Optional

from ..base import Benchmark, BenchmarkTask, TaskResult, register_benchmark
from .dataset import load_dataset
from .evaluator import evaluate_locally, extract_answer_function
from graybench.environments import SYSTEM_PYTHON

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are an expert physicist and programmer solving research-level physics problems.
You must implement the answer() function that returns the correct numerical or symbolic value.
You may use sympy and numpy for calculations.
Output ONLY the complete Python code including all imports and the def answer() function.
No explanations, no markdown fences."""


@register_benchmark
class CritPtBenchmark(Benchmark):
    """CritPt research-level physics benchmark."""

    def name(self) -> str:
        return "critpt"

    def display_name(self) -> str:
        return "CritPt (Physics Research)"

    def get_execution_environment(self):
        return SYSTEM_PYTHON

    def load_tasks(self, limit: Optional[int] = None) -> list[BenchmarkTask]:
        return load_dataset(limit=limit)

    def evaluate_task(self, task: BenchmarkTask, llm) -> TaskResult:
        t0 = time.monotonic()

        # Generate code
        input_tok = output_tok = cached_tok = reasoning_tok = 0
        if hasattr(llm, "generate_with_tracking"):
            response = llm.generate_with_tracking(SYSTEM_PROMPT, task.prompt)
            raw_text = response.text
            tokens = response.input_tokens + response.output_tokens
            input_tok = response.input_tokens
            output_tok = response.output_tokens
            cached_tok = response.cached_tokens
            reasoning_tok = response.reasoning_tokens
        else:
            raw_text = llm.generate(SYSTEM_PROMPT, task.prompt)
            tokens = 0

        # Extract the answer function
        code = extract_answer_function(raw_text)

        # Evaluate locally (run the code and check it doesn't crash)
        result = evaluate_locally(code, timeout=120)

        duration = time.monotonic() - t0

        # For CritPt, local evaluation only checks if code runs without error.
        # True scoring requires submission to the external CritPt evaluation server.
        passed = result.executed
        score = 1.0 if passed else 0.0

        return TaskResult(
            task_id=task.task_id,
            passed=passed,
            score=score,
            generated_code=code,
            actual_output=result.output[:2000],
            error=result.error[:2000] if result.error else None,
            tokens_used=tokens,
            duration_s=duration,
            metadata={
                "local_eval_only": True,
                "note": "Official scoring requires CritPt server submission",
            },
            raw_response=raw_text,
            input_tokens=input_tok,
            output_tokens=output_tok,
            cached_tokens=cached_tok,
            reasoning_tokens=reasoning_tok,
        )
