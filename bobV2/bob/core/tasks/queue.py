from __future__ import annotations

from typing import Optional

from bob.core.tasks.models import TaskRecord, TaskStore


class TaskQueue:
    def __init__(self, store: TaskStore, worker_id: str) -> None:
        self._store = store
        self._worker_id = worker_id

    def claim_next(self) -> Optional[TaskRecord]:
        return self._store.claim_next(self._worker_id)

