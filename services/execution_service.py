"""Business logic for workflow executions.

Responsibilities:
- Trigger new executions
- Query execution status
- Cancel / soft-delete executions
- Delegates step dispatch to SchedulerService
"""

import uuid
from datetime import datetime, timezone
from typing import Optional

from models.execution_model import ExecutionModel
from models.step_state_model import StepStateModel
from models.workflow_model import WorkflowModel
from utils.logger import get_logger

logger = get_logger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ExecutionService:

    @staticmethod
    def trigger(workflow_id: str, trigger_payload: dict) -> dict:
        """Create and immediately start a workflow execution.

        Creates the execution row, one step_state row per step, then
        hands off to SchedulerService to begin dispatching steps.

        Args:
            workflow_id: ID of the workflow to run.
            trigger_payload: Arbitrary input data passed by the caller.

        Returns:
            The execution dict after the first round of dispatch.

        Raises:
            ValueError: If the workflow does not exist or is archived.
        """
        workflow = WorkflowModel.find_by_id(workflow_id)
        if workflow is None:
            raise ValueError(f"Workflow '{workflow_id}' not found")
        if workflow["status"] != "active":
            raise ValueError(f"Workflow '{workflow_id}' is not active")

        steps = WorkflowModel.find_steps(workflow_id)
        if not steps:
            raise ValueError(f"Workflow '{workflow_id}' has no steps defined")

        execution_id = str(uuid.uuid4())
        now = _now()

        ExecutionModel.create(
            execution_id=execution_id,
            workflow_id=workflow_id,
            workflow_version=workflow["version"],
            trigger_payload=trigger_payload,
            created_at=now,
        )

        StepStateModel.create_all(
            execution_id=execution_id,
            step_keys=[s["step_key"] for s in steps],
            state_id_fn=lambda: str(uuid.uuid4()),
        )

        ExecutionModel.update_status(execution_id, "running", started_at=now)
        logger.info("Execution started: id=%s workflow=%s", execution_id, workflow_id)

        # Import here to avoid circular import at module level
        from services.scheduler_service import SchedulerService
        SchedulerService.advance(execution_id)

        return ExecutionService.get_status(execution_id)

    @staticmethod
    def get_status(execution_id: str) -> Optional[dict]:
        """Return an execution with all its step states.

        Args:
            execution_id: UUID string.

        Returns:
            Execution dict with 'steps' key, or None if not found.
        """
        execution = ExecutionModel.find_by_id(execution_id)
        if execution is None:
            return None
        execution["steps"] = StepStateModel.find_by_execution(execution_id)
        return execution

    @staticmethod
    def list_by_workflow(workflow_id: Optional[str]) -> list[dict]:
        """Return executions, optionally filtered by workflow.

        Args:
            workflow_id: If provided, return only executions for this workflow.

        Returns:
            List of execution dicts (no step detail).
        """
        if workflow_id:
            return ExecutionModel.find_by_workflow(workflow_id)
        return ExecutionModel.find_all()

    @staticmethod
    def cancel(execution_id: str) -> Optional[dict]:
        """Cancel a running execution.

        Marks the execution as failed and any pending/running steps as failed.

        Args:
            execution_id: UUID string.

        Returns:
            Updated execution dict, or None if not found.

        Raises:
            ValueError: If the execution is already in a terminal state.
        """
        execution = ExecutionModel.find_by_id(execution_id)
        if execution is None:
            return None

        terminal = {"completed", "failed", "compensated", "deleted"}
        if execution["status"] in terminal:
            raise ValueError(
                f"Cannot cancel execution in terminal state '{execution['status']}'"
            )

        now = _now()
        step_states = StepStateModel.find_by_execution(execution_id)
        for step in step_states:
            if step["status"] in ("pending", "running"):
                StepStateModel.update(
                    execution_id=execution_id,
                    step_key=step["step_key"],
                    status="failed",
                    error_message="Execution cancelled",
                    completed_at=now,
                )

        ExecutionModel.update_status(
            execution_id,
            "failed",
            error_message="Cancelled by user",
            completed_at=now,
        )
        logger.info("Execution cancelled: id=%s", execution_id)
        return ExecutionService.get_status(execution_id)

    @staticmethod
    def delete(execution_id: str) -> Optional[dict]:
        """Soft-delete an execution (sets status to 'deleted').

        Args:
            execution_id: UUID string.

        Returns:
            Updated execution dict, or None if not found.

        Raises:
            ValueError: If the execution is currently running.
        """
        execution = ExecutionModel.find_by_id(execution_id)
        if execution is None:
            return None

        if execution["status"] == "running":
            raise ValueError("Cannot delete a running execution. Cancel it first.")

        ExecutionModel.soft_delete(execution_id)
        logger.info("Execution soft-deleted: id=%s", execution_id)
        return ExecutionModel.find_by_id(execution_id)
