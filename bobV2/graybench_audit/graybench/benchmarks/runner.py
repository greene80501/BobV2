"""Benchmark runner – orchestrates execution with progress tracking."""

import sys
import time
import logging
import platform
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional, Callable

from .base import Benchmark, BenchmarkTask, TaskResult
from .failure_classifier import classify_failure
from ..db import runs_db
from ..llm.base import LLMProvider, LLMResponse
from ..llm.cost_tracker import calculate_cost

log = logging.getLogger(__name__)


class BenchmarkRunner:
    """Orchestrates benchmark execution with DB tracking and progress callbacks."""

    def __init__(self, benchmark: Benchmark, llm: LLMProvider,
                 parallel: int = 1,
                 on_task_complete: Optional[Callable] = None,
                 on_progress: Optional[Callable] = None):
        self.benchmark = benchmark
        self.llm = llm
        self.parallel = max(1, parallel)
        self.on_task_complete = on_task_complete
        self.on_progress = on_progress
        self._canceled = threading.Event()

    def cancel(self):
        """Signal the runner to stop after current task completes."""
        self._canceled.set()

    def _ensure_environment(self) -> None:
        """Ensure the benchmark's execution environment is ready.
        
        If the benchmark defines an execution environment, create it if needed.
        """
        env = self.benchmark.get_execution_environment()
        if env:
            log.info("Using execution environment: %s", env.display_name)
            env.ensure_exists()
            if not env.validate():
                raise RuntimeError(
                    f"Execution environment '{env.name}' failed validation. "
                    "Try running: graybench env setup"
                )
        else:
            log.debug("No execution environment required, using system Python")

    def run(self, task_limit: Optional[int] = None,
            route: str = "direct",
            model_provider: str = "",
            model_id: str = "",
            task_ids: Optional[list[str]] = None) -> str:
        """Execute the benchmark. Returns run_id.

        Creates DB records, runs all tasks, records results.
        """
        # Enrich config with model settings
        config = {"task_limit": task_limit, "parallel": self.parallel}
        for attr in ("temperature", "max_tokens"):
            val = getattr(self.llm, attr, None)
            if val is not None:
                config[attr] = val

        # Ensure execution environment is ready
        try:
            self._ensure_environment()
        except Exception as e:
            log.error("Failed to setup execution environment: %s", e)
            raise

        # Capture environment info
        environment = _capture_environment(self.benchmark)

        # Create run in DB
        run_id = runs_db.create_run(
            benchmark=self.benchmark.name(),
            model_provider=model_provider or getattr(self.llm, "provider_name", "unknown"),
            model_id=model_id or getattr(self.llm, "model", "unknown"),
            route=route,
            config=config,
            environment=environment,
        )
        runs_db.start_run(run_id)
        log.info("Started benchmark run %s (%s)", run_id, self.benchmark.name())

        if self.on_progress:
            self.on_progress({"type": "run_started", "run_id": run_id})

        try:
            # Load tasks
            if task_ids:
                # Load all tasks then filter to requested IDs
                all_tasks = self.benchmark.load_tasks(limit=None)
                id_set = set(task_ids)
                tasks = [t for t in all_tasks if t.task_id in id_set]
                if not tasks:
                    available = [t.task_id for t in all_tasks[:10]]
                    raise ValueError(f"No tasks matched IDs {task_ids}. Examples: {available}")
            else:
                tasks = self.benchmark.load_tasks(limit=task_limit)
            log.info("Loaded %d tasks for %s", len(tasks), self.benchmark.name())

            # Execute tasks
            results = self._execute_tasks(run_id, tasks)

            # Aggregate
            agg = self.benchmark.aggregate_results(results)
            runs_db.complete_run(
                run_id=run_id,
                total_tasks=agg["total"],
                passed_tasks=agg["passed"],
                failed_tasks=agg["failed"],
                score=agg["score"],
                total_cost_usd=agg["total_cost_usd"],
                total_tokens=agg["total_tokens"],
                total_duration_s=agg["total_duration_s"],
            )
            log.info("Run %s completed: %d/%d passed (%.1f%%)",
                     run_id, agg["passed"], agg["total"],
                     agg["score"] * 100)

            if self.on_progress:
                self.on_progress({"type": "run_completed", "run_id": run_id, **agg})

        except Exception as e:
            log.error("Run %s failed: %s", run_id, e, exc_info=True)
            runs_db.fail_run(run_id, str(e))
            if self.on_progress:
                self.on_progress({"type": "run_failed", "run_id": run_id, "error": str(e)})

        return run_id

    def _execute_tasks(self, run_id: str,
                       tasks: list[BenchmarkTask]) -> list[TaskResult]:
        """Execute all tasks, either sequentially or in parallel."""
        results = []

        if self.parallel <= 1:
            for i, task in enumerate(tasks):
                if self._canceled.is_set():
                    log.info("Run canceled after %d tasks", i)
                    break
                result = self._run_single_task(run_id, task, i, len(tasks))
                results.append(result)
        else:
            with ThreadPoolExecutor(max_workers=self.parallel) as executor:
                futures = {}
                for i, task in enumerate(tasks):
                    fut = executor.submit(
                        self._run_single_task, run_id, task, i, len(tasks)
                    )
                    futures[fut] = task

                for fut in as_completed(futures):
                    if self._canceled.is_set():
                        break
                    results.append(fut.result())

        return results

    def _run_single_task(self, run_id: str, task: BenchmarkTask,
                         index: int, total: int) -> TaskResult:
        """Run a single benchmark task and record the result."""
        log.info("[%d/%d] Evaluating task %s", index + 1, total, task.task_id)

        if self.on_progress:
            self.on_progress({
                "type": "task_started",
                "run_id": run_id,
                "task_id": task.task_id,
                "index": index,
                "total": total,
            })

        t0 = time.monotonic()
        try:
            result = self.benchmark.evaluate_task(task, self.llm)
        except Exception as e:
            log.error("Task %s failed: %s", task.task_id, e, exc_info=True)
            result = TaskResult(
                task_id=task.task_id,
                passed=False,
                score=0.0,
                error=str(e),
                duration_s=time.monotonic() - t0,
            )

        # Calculate cost from token breakdown if not already set
        if result.cost_usd == 0.0 and result.tokens_used > 0:
            cost_response = LLMResponse(
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                cached_tokens=result.cached_tokens,
                provider=getattr(self.llm, "provider_name", ""),
                model=getattr(self.llm, "model", ""),
            )
            result.cost_usd = calculate_cost(cost_response)

        # Auto-classify failure
        if not result.passed and result.failure_category is None:
            result.failure_category = classify_failure(result.error, result.generated_code)

        # Record to DB
        runs_db.record_task(
            run_id=run_id,
            task_id=result.task_id,
            task_name=task.task_name,
            passed=result.passed,
            score=result.score,
            generated_code=result.generated_code,
            expected_output=task.expected,
            actual_output=result.actual_output,
            error=result.error,
            tokens_used=result.tokens_used,
            cost_usd=result.cost_usd,
            duration_s=result.duration_s,
            attempts=result.attempts,
            metadata=result.metadata,
            raw_llm_response=result.raw_response,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            cached_tokens=result.cached_tokens,
            reasoning_tokens=result.reasoning_tokens,
            failure_category=result.failure_category,
        )

        if self.on_task_complete:
            self.on_task_complete(result)

        if self.on_progress:
            self.on_progress({
                "type": "task_completed",
                "run_id": run_id,
                "task_id": result.task_id,
                "passed": result.passed,
                "score": result.score,
                "index": index,
                "total": total,
            })

        status = "PASS" if result.passed else "FAIL"
        log.info("[%d/%d] %s %s (%.1fs)", index + 1, total, status,
                 task.task_id, result.duration_s)
        return result


def _capture_environment(benchmark: Optional[Benchmark] = None) -> dict:
    """Capture environment info for reproducibility.
    
    If the benchmark has an execution environment, capture info from that.
    Otherwise capture system Python info.
    """
    env = {
        "python_version": sys.version,
        "platform": platform.platform(),
    }
    
    # Get info from benchmark's execution environment if available
    if benchmark:
        bench_env = benchmark.get_execution_environment()
        if bench_env:
            try:
                env_info = bench_env.get_info()
                env["execution_environment"] = {
                    "name": env_info.get("name"),
                    "display_name": env_info.get("display_name"),
                    "venv_path": str(env_info.get("venv_path", "")),
                }
                # Add qiskit version if available
                if "qiskit_version" in env_info:
                    env["qiskit_version"] = env_info["qiskit_version"]
            except Exception as e:
                env["execution_environment_error"] = str(e)
        else:
            # No custom environment, try to get qiskit from system
            try:
                import qiskit
                env["qiskit_version"] = qiskit.__version__
                env["execution_environment"] = "system_python"
            except ImportError:
                env["qiskit_version"] = "not_installed"
    
    try:
        import numpy
        env["numpy_version"] = numpy.__version__
    except ImportError:
        pass
        
    return env
