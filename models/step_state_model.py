"""Data access layer for the step_states table."""

import json
from typing import Optional
from models import get_conn


class StepStateModel:
    """Handles all SQL operations for the step_states table."""

    @staticmethod
    def create_all(execution_id: str, step_keys: list[str], state_id_fn) -> None:
        """Insert one pending step_state row per step key.

        Args:
            execution_id: FK to executions.id.
            step_keys: Ordered list of step_key strings from the workflow definition.
            state_id_fn: Callable that returns a new UUID string (injected to keep model pure).
        """
        conn = get_conn()
        try:
            conn.executemany(
                """
                INSERT INTO step_states (id, execution_id, step_key, status, attempt_number)
                VALUES (?, ?, ?, 'pending', 0)
                """,
                [(state_id_fn(), execution_id, key) for key in step_keys],
            )
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def find_by_execution(execution_id: str) -> list[dict]:
        """Fetch all step states for an execution.

        Args:
            execution_id: FK to executions.id.

        Returns:
            List of step_state dicts with JSON fields deserialized.
        """
        conn = get_conn()
        try:
            cursor = conn.execute(
                "SELECT * FROM step_states WHERE execution_id = ? ORDER BY rowid ASC",
                (execution_id,),
            )
            rows = cursor.fetchall()
            return [StepStateModel._deserialize(dict(row)) for row in rows]
        finally:
            conn.close()

    @staticmethod
    def find_one(execution_id: str, step_key: str) -> Optional[dict]:
        """Fetch a single step state by execution + step key.

        Args:
            execution_id: FK to executions.id.
            step_key: The step's unique key within the workflow.

        Returns:
            Step state dict or None if not found.
        """
        conn = get_conn()
        try:
            cursor = conn.execute(
                "SELECT * FROM step_states WHERE execution_id = ? AND step_key = ?",
                (execution_id, step_key),
            )
            row = cursor.fetchone()
            return StepStateModel._deserialize(dict(row)) if row else None
        finally:
            conn.close()

    @staticmethod
    def update(
        execution_id: str,
        step_key: str,
        status: str,
        attempt_number: Optional[int] = None,
        input_data: Optional[dict] = None,
        output: Optional[dict] = None,
        error_message: Optional[str] = None,
        started_at: Optional[str] = None,
        completed_at: Optional[str] = None,
    ) -> None:
        """Update a step state row.

        Args:
            execution_id: FK to executions.id.
            step_key: The step's unique key.
            status: New status string.
            attempt_number: Current attempt count (incremented on each retry).
            input_data: Input dict passed to the step.
            output: Output dict captured from the step.
            error_message: Error description on failure.
            started_at: ISO timestamp when the step started.
            completed_at: ISO timestamp when the step finished.
        """
        conn = get_conn()
        try:
            conn.execute(
                """
                UPDATE step_states
                SET status         = ?,
                    attempt_number = COALESCE(?, attempt_number),
                    input          = COALESCE(?, input),
                    output         = COALESCE(?, output),
                    error_message  = COALESCE(?, error_message),
                    started_at     = COALESCE(?, started_at),
                    completed_at   = COALESCE(?, completed_at)
                WHERE execution_id = ? AND step_key = ?
                """,
                (
                    status,
                    attempt_number,
                    json.dumps(input_data) if input_data is not None else None,
                    json.dumps(output) if output is not None else None,
                    error_message,
                    started_at,
                    completed_at,
                    execution_id,
                    step_key,
                ),
            )
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def reset_to_pending(execution_id: str, step_key: str) -> None:
        """Reset a step state back to pending for manual retry.

        Clears output, error, timestamps, and resets attempt_number to 0.

        Args:
            execution_id: FK to executions.id.
            step_key: The step's unique key.
        """
        conn = get_conn()
        try:
            conn.execute(
                """
                UPDATE step_states
                SET status = 'pending', attempt_number = 0,
                    output = NULL, error_message = NULL,
                    started_at = NULL, completed_at = NULL
                WHERE execution_id = ? AND step_key = ?
                """,
                (execution_id, step_key),
            )
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _deserialize(row: dict) -> dict:
        """Deserialize JSON fields in a step_state row.

        Args:
            row: Raw dict from sqlite3.Row.

        Returns:
            Dict with input/output fields parsed from JSON.
        """
        row["input"] = json.loads(row["input"]) if row.get("input") else None
        row["output"] = json.loads(row["output"]) if row.get("output") else None
        return row
