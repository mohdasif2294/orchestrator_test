"""Data access layer for workflows and workflow_steps tables."""

import json
from typing import Optional
from models import get_conn


class WorkflowModel:
    """Handles all SQL operations for the workflows and workflow_steps tables."""

    @staticmethod
    def create(
        workflow_id: str,
        name: str,
        description: Optional[str],
        created_at: str,
    ) -> dict:
        """Insert a new workflow row.

        Args:
            workflow_id: UUID string.
            name: Unique workflow name.
            description: Optional description.
            created_at: ISO timestamp string.

        Returns:
            The created workflow as a dict.
        """
        conn = get_conn()
        try:
            conn.execute(
                """
                INSERT INTO workflows (id, name, description, version, status, created_at, updated_at)
                VALUES (?, ?, ?, 1, 'active', ?, ?)
                """,
                (workflow_id, name, description, created_at, created_at),
            )
            conn.commit()
            return WorkflowModel.find_by_id(workflow_id)
        finally:
            conn.close()

    @staticmethod
    def create_steps(steps: list[dict]) -> None:
        """Insert multiple workflow step rows atomically.

        Args:
            steps: List of step dicts, each containing all workflow_steps columns.
        """
        conn = get_conn()
        try:
            conn.executemany(
                """
                INSERT INTO workflow_steps
                    (id, workflow_id, step_key, step_type, config, depends_on,
                     branch_condition, retry_max, retry_delay_seconds, timeout_seconds,
                     compensation_config, position)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        s["id"],
                        s["workflow_id"],
                        s["step_key"],
                        s["step_type"],
                        json.dumps(s["config"]),
                        json.dumps(s.get("depends_on", [])),
                        json.dumps(s["branch_condition"]) if s.get("branch_condition") else None,
                        s.get("retry_max", 0),
                        s.get("retry_delay_seconds", 5),
                        s.get("timeout_seconds", 30),
                        json.dumps(s["compensation_config"]) if s.get("compensation_config") else None,
                        s["position"],
                    )
                    for s in steps
                ],
            )
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def find_all() -> list[dict]:
        """Fetch all active workflow summaries (no steps).

        Returns:
            List of workflow dicts.
        """
        conn = get_conn()
        try:
            cursor = conn.execute(
                "SELECT * FROM workflows WHERE status = 'active' ORDER BY created_at DESC"
            )
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    @staticmethod
    def find_by_id(workflow_id: str) -> Optional[dict]:
        """Fetch a single workflow by ID (no steps).

        Args:
            workflow_id: UUID string.

        Returns:
            Workflow dict or None if not found.
        """
        conn = get_conn()
        try:
            cursor = conn.execute(
                "SELECT * FROM workflows WHERE id = ?", (workflow_id,)
            )
            row = cursor.fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    @staticmethod
    def find_steps(workflow_id: str) -> list[dict]:
        """Fetch all steps for a workflow, ordered by position.

        Args:
            workflow_id: UUID string.

        Returns:
            List of step dicts with JSON fields deserialized.
        """
        conn = get_conn()
        try:
            cursor = conn.execute(
                "SELECT * FROM workflow_steps WHERE workflow_id = ? ORDER BY position ASC",
                (workflow_id,),
            )
            rows = cursor.fetchall()
            steps = []
            for row in rows:
                step = dict(row)
                step["config"] = json.loads(step["config"])
                step["depends_on"] = json.loads(step["depends_on"])
                step["branch_condition"] = (
                    json.loads(step["branch_condition"]) if step["branch_condition"] else None
                )
                step["compensation_config"] = (
                    json.loads(step["compensation_config"]) if step["compensation_config"] else None
                )
                steps.append(step)
            return steps
        finally:
            conn.close()

    @staticmethod
    def update_version(workflow_id: str, new_version: int, updated_at: str) -> None:
        """Bump the version number and updated_at timestamp.

        Args:
            workflow_id: UUID string.
            new_version: New version integer.
            updated_at: ISO timestamp string.
        """
        conn = get_conn()
        try:
            conn.execute(
                "UPDATE workflows SET version = ?, updated_at = ? WHERE id = ?",
                (new_version, updated_at, workflow_id),
            )
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def delete_steps(workflow_id: str) -> None:
        """Delete all steps for a workflow (used before re-inserting on update).

        Args:
            workflow_id: UUID string.
        """
        conn = get_conn()
        try:
            conn.execute(
                "DELETE FROM workflow_steps WHERE workflow_id = ?", (workflow_id,)
            )
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def set_status(workflow_id: str, status: str, updated_at: str) -> None:
        """Set the workflow status (e.g. 'archived').

        Args:
            workflow_id: UUID string.
            status: New status string.
            updated_at: ISO timestamp string.
        """
        conn = get_conn()
        try:
            conn.execute(
                "UPDATE workflows SET status = ?, updated_at = ? WHERE id = ?",
                (status, updated_at, workflow_id),
            )
            conn.commit()
        finally:
            conn.close()
