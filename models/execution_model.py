"""Data access layer for the executions table."""

import json
from typing import Optional
from models import get_conn


class ExecutionModel:
    """Handles all SQL operations for the executions table."""

    @staticmethod
    def create(
        execution_id: str,
        workflow_id: str,
        workflow_version: int,
        trigger_payload: dict,
        created_at: str,
    ) -> dict:
        """Insert a new execution row with status 'pending'.

        Args:
            execution_id: UUID string.
            workflow_id: FK to workflows.id.
            workflow_version: Snapshot of the workflow version at trigger time.
            trigger_payload: Input data dict passed by the caller.
            created_at: ISO timestamp string.

        Returns:
            The created execution as a dict.
        """
        conn = get_conn()
        try:
            conn.execute(
                """
                INSERT INTO executions
                    (id, workflow_id, workflow_version, status, trigger_payload, created_at)
                VALUES (?, ?, ?, 'pending', ?, ?)
                """,
                (
                    execution_id,
                    workflow_id,
                    workflow_version,
                    json.dumps(trigger_payload),
                    created_at,
                ),
            )
            conn.commit()
            return ExecutionModel.find_by_id(execution_id)
        finally:
            conn.close()

    @staticmethod
    def find_by_id(execution_id: str) -> Optional[dict]:
        """Fetch a single execution by ID.

        Args:
            execution_id: UUID string.

        Returns:
            Execution dict with trigger_payload deserialized, or None.
        """
        conn = get_conn()
        try:
            cursor = conn.execute(
                "SELECT * FROM executions WHERE id = ?", (execution_id,)
            )
            row = cursor.fetchone()
            if not row:
                return None
            execution = dict(row)
            execution["trigger_payload"] = json.loads(execution["trigger_payload"])
            execution["output"] = (
                json.loads(execution["output"]) if execution["output"] else None
            )
            return execution
        finally:
            conn.close()

    @staticmethod
    def find_by_workflow(workflow_id: str) -> list[dict]:
        """Fetch all executions for a given workflow, newest first.

        Args:
            workflow_id: FK to workflows.id.

        Returns:
            List of execution dicts.
        """
        conn = get_conn()
        try:
            cursor = conn.execute(
                "SELECT * FROM executions WHERE workflow_id = ? AND status != 'deleted' ORDER BY created_at DESC",
                (workflow_id,),
            )
            rows = cursor.fetchall()
            result = []
            for row in rows:
                execution = dict(row)
                execution["trigger_payload"] = json.loads(execution["trigger_payload"])
                execution["output"] = (
                    json.loads(execution["output"]) if execution["output"] else None
                )
                result.append(execution)
            return result
        finally:
            conn.close()

    @staticmethod
    def find_all() -> list[dict]:
        """Fetch all executions ordered by created_at descending.

        Returns:
            List of execution dicts.
        """
        conn = get_conn()
        try:
            cursor = conn.execute(
                "SELECT * FROM executions WHERE status != 'deleted' ORDER BY created_at DESC"
            )
            rows = cursor.fetchall()
            result = []
            for row in rows:
                execution = dict(row)
                execution["trigger_payload"] = json.loads(execution["trigger_payload"])
                execution["output"] = (
                    json.loads(execution["output"]) if execution["output"] else None
                )
                result.append(execution)
            return result
        finally:
            conn.close()

    @staticmethod
    def soft_delete(execution_id: str) -> None:
        """Mark an execution as deleted without removing it from the database.

        Args:
            execution_id: UUID string.
        """
        conn = get_conn()
        try:
            conn.execute(
                "UPDATE executions SET status = 'deleted' WHERE id = ?",
                (execution_id,),
            )
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def update_status(
        execution_id: str,
        status: str,
        error_message: Optional[str] = None,
        output: Optional[dict] = None,
        started_at: Optional[str] = None,
        completed_at: Optional[str] = None,
    ) -> None:
        """Update execution status and optional fields.

        Args:
            execution_id: UUID string.
            status: New status string.
            error_message: Optional error description.
            output: Optional final output dict.
            started_at: Optional ISO timestamp when execution started.
            completed_at: Optional ISO timestamp when execution finished.
        """
        conn = get_conn()
        try:
            conn.execute(
                """
                UPDATE executions
                SET status = ?,
                    error_message = COALESCE(?, error_message),
                    output = COALESCE(?, output),
                    started_at = COALESCE(?, started_at),
                    completed_at = COALESCE(?, completed_at)
                WHERE id = ?
                """,
                (
                    status,
                    error_message,
                    json.dumps(output) if output is not None else None,
                    started_at,
                    completed_at,
                    execution_id,
                ),
            )
            conn.commit()
        finally:
            conn.close()
