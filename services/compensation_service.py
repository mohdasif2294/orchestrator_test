"""Saga compensation (rollback) logic.

When a step fails after all retries, CompensationService runs the
compensation_config of each previously completed step in reverse
completion order (most-recently-completed first).

Compensation is best-effort: if a compensation HTTP call fails, the
error is logged and the next step is still compensated.
"""

import requests
from datetime import datetime, timezone
from typing import Optional

from models.execution_model import ExecutionModel
from models.step_state_model import StepStateModel
from models.workflow_model import WorkflowModel
from utils.logger import get_logger

logger = get_logger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class CompensationService:

    @staticmethod
    def compensate(execution_id: str, failed_step_key: str) -> None:
        """Run compensation actions for all completed steps in reverse order.

        Marks the execution as 'compensating', iterates completed steps
        newest-first, calls each step's compensation_config URL, then
        marks the execution as 'compensated'.

        Args:
            execution_id: UUID string.
            failed_step_key: The step_key that triggered compensation (not compensated itself).
        """
        execution = ExecutionModel.find_by_id(execution_id)
        if execution is None:
            logger.error("Compensation called for unknown execution: %s", execution_id)
            return

        ExecutionModel.update_status(execution_id, "compensating")
        logger.info(
            "Compensation started: execution=%s triggered_by=%s",
            execution_id, failed_step_key,
        )

        workflow_id = execution["workflow_id"]
        step_defs = {s["step_key"]: s for s in WorkflowModel.find_steps(workflow_id)}
        completed_states = CompensationService._get_completed_steps_in_reverse_order(execution_id)

        context = CompensationService._build_context(
            execution["trigger_payload"],
            StepStateModel.find_by_execution(execution_id),
        )

        for step_state in completed_states:
            step_key = step_state["step_key"]
            step_def = step_defs.get(step_key)

            if step_def is None:
                logger.warning("Step definition not found during compensation: %s", step_key)
                continue

            compensation_config = step_def.get("compensation_config")
            if not compensation_config:
                logger.info("No compensation defined for step '%s', skipping", step_key)
                continue

            CompensationService._run_compensation_step(
                execution_id, step_key, compensation_config, context
            )

        ExecutionModel.update_status(execution_id, "compensated", completed_at=_now())
        logger.info("Compensation completed: execution=%s", execution_id)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _get_completed_steps_in_reverse_order(execution_id: str) -> list[dict]:
        """Return completed step states sorted by completed_at descending.

        Args:
            execution_id: UUID string.

        Returns:
            List of step_state dicts, most recently completed first.
        """
        all_states = StepStateModel.find_by_execution(execution_id)
        completed = [s for s in all_states if s["status"] == "completed"]
        return sorted(
            completed,
            key=lambda s: s.get("completed_at") or "",
            reverse=True,
        )

    @staticmethod
    def _build_context(trigger_payload: dict, step_states: list[dict]) -> dict:
        """Build context dict for template resolution during compensation.

        Args:
            trigger_payload: Original trigger input dict.
            step_states: All step state dicts for the execution.

        Returns:
            Context dict with 'trigger' and 'steps' keys.
        """
        steps_context = {
            s["step_key"]: {"output": s.get("output") or {}}
            for s in step_states
        }
        return {"trigger": trigger_payload, "steps": steps_context}

    @staticmethod
    def _resolve_template(template: object, context: dict) -> object:
        """Recursively replace {{path}} placeholders in a compensation payload template.

        Args:
            template: Dict, list, or string with optional placeholders.
            context: Execution context dict.

        Returns:
            Template with placeholders substituted.
        """
        if isinstance(template, dict):
            return {
                k: CompensationService._resolve_template(v, context)
                for k, v in template.items()
            }
        if isinstance(template, list):
            return [CompensationService._resolve_template(item, context) for item in template]
        if isinstance(template, str) and template.startswith("{{") and template.endswith("}}"):
            path = template[2:-2].strip()
            return CompensationService._resolve_path(path, context)
        return template

    @staticmethod
    def _resolve_path(path: str, context: dict) -> Optional[object]:
        """Walk a dot-separated key path into the context dict.

        Args:
            path: Dot-separated path string e.g. 'steps.charge_payment.output.payment_id'.
            context: The execution context dict.

        Returns:
            The value at the path, or None if any key is missing.
        """
        node: object = context
        for part in path.split("."):
            if not isinstance(node, dict) or part not in node:
                return None
            node = node[part]
        return node

    @staticmethod
    def _run_compensation_step(
        execution_id: str,
        step_key: str,
        compensation_config: dict,
        context: dict,
    ) -> None:
        """Execute one compensation HTTP call (best-effort, no retry).

        Args:
            execution_id: UUID string.
            step_key: The step being compensated.
            compensation_config: The compensation config dict from the step definition.
            context: Execution context for template resolution.
        """
        StepStateModel.update(
            execution_id=execution_id,
            step_key=step_key,
            status="compensating",
        )

        url = compensation_config.get("url", "")
        method = compensation_config.get("method", "POST").upper()
        headers = compensation_config.get("headers", {"Content-Type": "application/json"})
        payload_template = compensation_config.get("payload_template", {})
        payload = CompensationService._resolve_template(payload_template, context)

        logger.info(
            "Running compensation: execution=%s step=%s url=%s",
            execution_id, step_key, url,
        )

        try:
            response = requests.request(
                method=method,
                url=url,
                json=payload,
                headers=headers,
                timeout=30,
            )
            if response.ok:
                StepStateModel.update(
                    execution_id=execution_id,
                    step_key=step_key,
                    status="compensated",
                    completed_at=_now(),
                )
                logger.info("Compensation succeeded: execution=%s step=%s", execution_id, step_key)
            else:
                StepStateModel.update(
                    execution_id=execution_id,
                    step_key=step_key,
                    status="failed",
                    error_message=f"Compensation HTTP {response.status_code}: {response.text[:200]}",
                    completed_at=_now(),
                )
                logger.error(
                    "Compensation HTTP error: execution=%s step=%s status=%d",
                    execution_id, step_key, response.status_code,
                )
        except Exception as exc:
            StepStateModel.update(
                execution_id=execution_id,
                step_key=step_key,
                status="failed",
                error_message=f"Compensation exception: {exc}",
                completed_at=_now(),
            )
            logger.error(
                "Compensation exception: execution=%s step=%s error=%s",
                execution_id, step_key, exc,
            )
