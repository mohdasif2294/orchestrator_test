"""Business logic for workflow definitions.

Responsibilities:
- Validate workflow DAG (unique keys, no dangling deps, no cycles)
- CRUD operations delegated to WorkflowModel
"""

import uuid
from datetime import datetime, timezone
from typing import Optional

from models.workflow_model import WorkflowModel
from utils.logger import get_logger

logger = get_logger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class WorkflowService:

    @staticmethod
    def register(payload: dict) -> dict:
        """Validate and persist a new workflow definition.

        Args:
            payload: Dict containing 'name', optional 'description', and 'steps' list.

        Returns:
            The created workflow dict including its steps.

        Raises:
            ValueError: If required fields are missing or the DAG is invalid.
        """
        name = payload.get("name", "").strip()
        if not name:
            raise ValueError("Field 'name' is required")

        steps = payload.get("steps")
        if not steps or not isinstance(steps, list):
            raise ValueError("Field 'steps' must be a non-empty list")

        WorkflowService._validate_dag(steps)

        existing = WorkflowModel.find_all()
        if any(w["name"] == name for w in existing):
            raise ValueError(f"Workflow with name '{name}' already exists")

        workflow_id = str(uuid.uuid4())
        now = _now()

        WorkflowModel.create(
            workflow_id=workflow_id,
            name=name,
            description=payload.get("description"),
            created_at=now,
        )

        step_rows = [
            {
                "id": str(uuid.uuid4()),
                "workflow_id": workflow_id,
                "step_key": s["step_key"],
                "step_type": s.get("step_type", "http"),
                "config": s.get("config", {}),
                "depends_on": s.get("depends_on", []),
                "branch_condition": s.get("branch_condition"),
                "retry_max": s.get("retry_max", 0),
                "retry_delay_seconds": s.get("retry_delay_seconds", 5),
                "timeout_seconds": s.get("timeout_seconds", 30),
                "compensation_config": s.get("compensation_config"),
                "position": idx,
            }
            for idx, s in enumerate(steps)
        ]
        WorkflowModel.create_steps(step_rows)

        logger.info("Workflow registered: id=%s name=%s", workflow_id, name)
        return WorkflowService.get_by_id(workflow_id)

    @staticmethod
    def get_all() -> list[dict]:
        """Return all active workflow summaries.

        Returns:
            List of workflow dicts (no steps).
        """
        return WorkflowModel.find_all()

    @staticmethod
    def get_by_id(workflow_id: str) -> Optional[dict]:
        """Return a workflow with its steps, or None if not found.

        Args:
            workflow_id: UUID string.

        Returns:
            Workflow dict with 'steps' key, or None.
        """
        workflow = WorkflowModel.find_by_id(workflow_id)
        if workflow is None:
            return None
        workflow["steps"] = WorkflowModel.find_steps(workflow_id)
        return workflow

    @staticmethod
    def update(workflow_id: str, payload: dict) -> Optional[dict]:
        """Replace a workflow's steps and bump its version.

        Args:
            workflow_id: UUID string.
            payload: Same shape as register payload.

        Returns:
            Updated workflow dict, or None if not found.

        Raises:
            ValueError: If the new DAG is invalid.
        """
        workflow = WorkflowModel.find_by_id(workflow_id)
        if workflow is None:
            return None

        steps = payload.get("steps")
        if not steps or not isinstance(steps, list):
            raise ValueError("Field 'steps' must be a non-empty list")

        WorkflowService._validate_dag(steps)

        now = _now()
        new_version = workflow["version"] + 1

        WorkflowModel.delete_steps(workflow_id)

        step_rows = [
            {
                "id": str(uuid.uuid4()),
                "workflow_id": workflow_id,
                "step_key": s["step_key"],
                "step_type": s.get("step_type", "http"),
                "config": s.get("config", {}),
                "depends_on": s.get("depends_on", []),
                "branch_condition": s.get("branch_condition"),
                "retry_max": s.get("retry_max", 0),
                "retry_delay_seconds": s.get("retry_delay_seconds", 5),
                "timeout_seconds": s.get("timeout_seconds", 30),
                "compensation_config": s.get("compensation_config"),
                "position": idx,
            }
            for idx, s in enumerate(steps)
        ]
        WorkflowModel.create_steps(step_rows)
        WorkflowModel.update_version(workflow_id, new_version, now)

        logger.info("Workflow updated: id=%s version=%d", workflow_id, new_version)
        return WorkflowService.get_by_id(workflow_id)

    @staticmethod
    def archive(workflow_id: str) -> Optional[dict]:
        """Soft-delete a workflow by setting its status to 'archived'.

        Args:
            workflow_id: UUID string.

        Returns:
            Updated workflow dict, or None if not found.
        """
        workflow = WorkflowModel.find_by_id(workflow_id)
        if workflow is None:
            return None

        WorkflowModel.set_status(workflow_id, "archived", _now())
        logger.info("Workflow archived: id=%s", workflow_id)
        return WorkflowModel.find_by_id(workflow_id)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_dag(steps: list[dict]) -> None:
        """Validate that the steps form a valid DAG.

        Checks:
        1. Each step has a non-empty 'step_key'.
        2. All step_key values are unique.
        3. Every key in 'depends_on' refers to an existing step_key.
        4. The graph is acyclic (DFS topological sort).

        Args:
            steps: List of step dicts from the workflow payload.

        Raises:
            ValueError: On the first validation failure found.
        """
        keys = []
        for s in steps:
            key = s.get("step_key", "").strip()
            if not key:
                raise ValueError("Every step must have a non-empty 'step_key'")
            keys.append(key)

        if len(keys) != len(set(keys)):
            raise ValueError("Duplicate step_key values found in workflow definition")

        key_set = set(keys)
        adjacency: dict[str, list[str]] = {k: [] for k in keys}

        for s in steps:
            for dep in s.get("depends_on", []):
                if dep not in key_set:
                    raise ValueError(
                        f"Step '{s['step_key']}' depends_on unknown key '{dep}'"
                    )
                adjacency[dep].append(s["step_key"])

        # DFS cycle detection
        visited: set[str] = set()
        in_progress: set[str] = set()

        def _dfs(node: str) -> None:
            in_progress.add(node)
            for neighbour in adjacency[node]:
                if neighbour in in_progress:
                    raise ValueError(
                        f"Cycle detected in workflow DAG involving step '{neighbour}'"
                    )
                if neighbour not in visited:
                    _dfs(neighbour)
            in_progress.discard(node)
            visited.add(node)

        for key in keys:
            if key not in visited:
                _dfs(key)
