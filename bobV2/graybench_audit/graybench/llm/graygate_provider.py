"""GrayGate provider – connects to a GrayGate server for code generation."""

import json
import time
import logging
from typing import Optional

import httpx

from .base import LLMProvider, LLMResponse

log = logging.getLogger(__name__)


class GrayGateProvider:
    """Sends prompts through a GrayGate server.

    GrayGate is a separate product by GrayArea Labs. To use this provider,
    you need a running GrayGate instance. See https://github.com/GrayArea-Labs
    for more information.
    """

    provider_name = "graygate"

    def __init__(self, base_url: str = "http://localhost:5000",
                 mode: str = "bench", timeout: int = 300):
        self.base_url = base_url.rstrip("/")
        self.mode = mode
        self.timeout = timeout

    def _submit_and_wait(self, prompt: str, canonical_solution: str = None) -> dict:
        """Submit a run and poll until completion."""
        with httpx.Client(timeout=self.timeout) as client:
            payload = {"mode": self.mode, "prompt": prompt}
            if canonical_solution:
                payload["canonical_solution"] = canonical_solution

            resp = client.post(f"{self.base_url}/v1/runs", json=payload)
            resp.raise_for_status()
            run_id = resp.json()["run_id"]

            while True:
                time.sleep(2)
                resp = client.get(f"{self.base_url}/v1/runs/{run_id}")
                resp.raise_for_status()
                info = resp.json()
                status = info.get("status", "")
                if status in ("completed", "failed", "canceled"):
                    break

            # Always try to retrieve artifacts, even for failed runs.
            # GrayGate may save final.py even when repair loop can't fully fix
            # the code — the code is still worth evaluating in the benchmark venv.
            try:
                resp = client.get(f"{self.base_url}/v1/runs/{run_id}/artifacts")
                resp.raise_for_status()
                artifacts = resp.json()
            except Exception:
                artifacts = {}

            if status != "completed" and not artifacts:
                error = info.get("error", "Run did not complete successfully")
                raise RuntimeError(f"GrayGate run {run_id} {status}: {error}")

            return {"run_id": run_id, "artifacts": artifacts, "info": info}

    def generate(self, system: str, user: str,
                 max_tokens: Optional[int] = None,
                 temperature: Optional[float] = None,
                 canonical_solution: str = None) -> str:
        result = self._submit_and_wait(user, canonical_solution=canonical_solution)
        artifacts = result.get("artifacts", {})

        for name in ("final.py", "candidate.py"):
            if name in artifacts:
                art = artifacts[name]
                if isinstance(art, dict):
                    return art.get("content", art.get("code", str(art)))
                return str(art)

        return json.dumps(artifacts, indent=2)

    def generate_json(self, system: str, user: str,
                      max_tokens: Optional[int] = None) -> dict:
        text = self.generate(system, user, max_tokens)
        return {"code": text}

    def generate_with_tracking(self, system: str, user: str,
                                max_tokens: Optional[int] = None,
                                temperature: Optional[float] = None,
                                canonical_solution: str = None) -> LLMResponse:
        t0 = time.monotonic()
        text = self.generate(system, user, max_tokens, temperature, canonical_solution=canonical_solution)
        duration = time.monotonic() - t0

        return LLMResponse(
            text=text,
            model="graygate",
            provider="graygate",
            duration_s=duration,
        )
