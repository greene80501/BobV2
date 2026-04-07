"""Task management database for Bob V2."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional, List
from datetime import datetime
from enum import Enum


class TaskStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class TaskPriority(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class TaskDB:
    """SQLite-based task management database."""
    
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._init_db()
    
    def _init_db(self):
        """Create tables if they don't exist."""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS tasks (
                    task_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    description TEXT,
                    status TEXT NOT NULL,
                    priority TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL,
                    completed_at INTEGER
                )
            """)
            
            conn.execute("""
                CREATE TABLE IF NOT EXISTS task_outputs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL,
                    timestamp INTEGER NOT NULL,
                    output_text TEXT NOT NULL,
                    FOREIGN KEY (task_id) REFERENCES tasks(task_id)
                )
            """)
            
            conn.commit()
        finally:
            conn.close()
    
    def create_task(
        self,
        task_id: str,
        title: str,
        description: str = "",
        status: TaskStatus = TaskStatus.PENDING,
        priority: TaskPriority = TaskPriority.MEDIUM,
    ) -> dict:
        """Create a new task and return it as a dict."""
        now = int(datetime.now().timestamp())
        
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        
        try:
            conn.execute(
                """
                INSERT INTO tasks (task_id, title, description, status, priority, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (task_id, title, description, status.value, priority.value, now, now),
            )
            conn.commit()
            
            return self.get_task(task_id)
        finally:
            conn.close()
    
    def update_task(self, task_id: str, **kwargs) -> Optional[dict]:
        """Update task fields and return the updated task."""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        
        try:
            # Build update query dynamically
            updates = []
            values = []
            
            for key, value in kwargs.items():
                if key in ("title", "description", "status", "priority"):
                    updates.append(f"{key} = ?")
                    if isinstance(value, Enum):
                        values.append(value.value)
                    else:
                        values.append(value)
            
            if not updates:
                return self.get_task(task_id)
            
            # Always update updated_at
            now = int(datetime.now().timestamp())
            updates.append("updated_at = ?")
            values.append(now)
            
            # If status is completed, set completed_at
            if "status" in kwargs and kwargs["status"] in (TaskStatus.COMPLETED, "completed"):
                updates.append("completed_at = ?")
                values.append(now)
            
            values.append(task_id)
            
            query = f"UPDATE tasks SET {', '.join(updates)} WHERE task_id = ?"
            conn.execute(query, values)
            conn.commit()
            
            return self.get_task(task_id)
        finally:
            conn.close()
    
    def get_task(self, task_id: str) -> Optional[dict]:
        """Get a single task by ID."""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        
        try:
            cursor = conn.execute(
                "SELECT * FROM tasks WHERE task_id = ?",
                (task_id,),
            )
            row = cursor.fetchone()
            return dict(row) if row else None
        finally:
            conn.close()
    
    def list_tasks(self, status: Optional[TaskStatus] = None) -> List[dict]:
        """List all tasks, optionally filtered by status."""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        
        try:
            if status:
                cursor = conn.execute(
                    "SELECT * FROM tasks WHERE status = ? ORDER BY created_at DESC",
                    (status.value,),
                )
            else:
                cursor = conn.execute(
                    "SELECT * FROM tasks ORDER BY created_at DESC"
                )
            
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()
    
    def append_output(self, task_id: str, output_text: str) -> bool:
        """Append output log to a task."""
        now = int(datetime.now().timestamp())
        
        conn = sqlite3.connect(str(self.db_path))
        
        try:
            conn.execute(
                """
                INSERT INTO task_outputs (task_id, timestamp, output_text)
                VALUES (?, ?, ?)
                """,
                (task_id, now, output_text),
            )
            conn.commit()
            return True
        except Exception:
            return False
        finally:
            conn.close()
    
    def get_outputs(self, task_id: str) -> List[dict]:
        """Get all output logs for a task."""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        
        try:
            cursor = conn.execute(
                """
                SELECT * FROM task_outputs
                WHERE task_id = ?
                ORDER BY timestamp ASC
                """,
                (task_id,),
            )
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()
    
    def cancel_task(self, task_id: str) -> Optional[dict]:
        """Cancel a task (set status to CANCELLED)."""
        return self.update_task(task_id, status=TaskStatus.CANCELLED)
