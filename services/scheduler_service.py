"""DAG traversal and step dispatch engine.

Responsibilities:
- Determine which steps are ready to run given current state
- Evaluate branch conditions
- Resolve payload templates
- Dispatch HTTP steps and capture output
- Drive the execution forward via recursive advance() calls
- Trigger compensation on step failure
"""

import time
import requests
from datetime import datetime, timezone
from typing import Any, Optional

from models.execution_model import ExecutionModel
from models.step_state_model import StepStateModel
from models.workflow_model import WorkflowModel
from utils.logger import get_logger

logger = get_logger(__name__)

TERMINAL_STATUSES = {"completed", "failed", "skipped", "compensated"}
SATISFIED_STATUSES = {"completed", "skipped"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SchedulerService:

    @staticmethod
    def advance(execution_id: str) -> None:
        """Drive the execution forward by dispatching all currently ready steps.

        Called after every state change. Reads current DB state, finds steps
        whose dependencies are satisfied, and dispatches them. Calls itself
        recursively after each step completes.

        Args:
            execution_id: UUID string of the execution to advance.
        """
        execution = ExecutionModel.find_by_id(execution_id)
        if execution is None or execution["status"] not in ("running", "pending"):
            return

        workflow_id = execution["workflow_id"]
        step_defs = {s["step_key"]: s for s in WorkflowModel.find_steps(workflow_id)}
        step_states = {s["step_key"]: s for s in StepStateModel.find_by_execution(execution_id)}

        # Check for any failed step — trigger compensation
        failed = [s for s in step_states.values() if s["status"] == "failed"]
        if failed:
            from services.compensation_service import CompensationService
            CompensationService.compensate(execution_id, failed[0]["step_key"])
            return

        ready_steps = SchedulerService._get_ready_steps(step_defs, step_states)

        if not ready_steps:
            # All steps are in terminal status → execution is complete
            all_terminal = all(s["status"] in TERMINAL_STATUSES for s in step_states.values())
            if all_terminal:
                ExecutionModel.update_status(
                    execution_id, "completed", completed_at=_now()
                )
                logger.info("Execution completed: id=%s", execution_id)
            return

        context = SchedulerService._build_context(execution["trigger_payload"], step_states)

        for step_key in ready_steps:
            step_def = step_defs[step_key]

            # Evaluate branch condition — skip step if condition is false
            condition = step_def.get("branch_condition")
            if condition and not SchedulerService._evaluate_branch_condition(condition, context):
                StepStateModel.update(
                    execution_id=execution_id,
                    step_key=step_key,
                    status="skipped",
                    completed_at=_now(),
                )
                logger.info("Step skipped (branch condition false): %s", step_key)
                SchedulerService.advance(execution_id)
                return

            resolved_input = SchedulerService._resolve_template(
                step_def.get("config", {}).get("payload_template", {}), context
            )
            SchedulerService._dispatch_step(execution_id, step_def, resolved_input)
            return  # advance() is called again inside _dispatch_step

    @staticmethod
    def retry_step(execution_id: str, step_key: str) -> Optional[dict]:
        """Manually reset a failed step to pending and re-advance the execution.

        Args:
            execution_id: UUID string.
            step_key: The step to retry.

        Returns:
            The updated step state dict, or None if not found.

        Raises:
            ValueError: If the step is not in a failed state.
        """
        step_state = StepStateModel.find_one(execution_id, step_key)
        if step_state is None:
            return None

        if step_state["status"] != "failed":
            raise ValueError(
                f"Step '{step_key}' is not in a failed state (current: {step_state['status']})"
            )

        execution = ExecutionModel.find_by_id(execution_id)
        if execution is None:
            return None

        StepStateModel.reset_to_pending(execution_id, step_key)
        ExecutionModel.update_status(execution_id, "running")

        logger.info("Manual retry triggered: execution=%s step=%s", execution_id, step_key)
        SchedulerService.advance(execution_id)

        return StepStateModel.find_one(execution_id, step_key)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _get_ready_steps(
        step_defs: dict[str, dict],
        step_states: dict[str, dict],
    ) -> list[str]:
        """Return step keys that are pending and have all dependencies satisfied.

        Args:
            step_defs: Map of step_key → step definition dict.
            step_states: Map of step_key → current step state dict.

        Returns:
            List of step keys ready to dispatch, in definition order.
        """
        ready = []
        for key, step_def in step_defs.items():
            state = step_states.get(key, {})
            if state.get("status") != "pending":
                continue
            deps = step_def.get("depends_on", [])
            if all(step_states.get(dep, {}).get("status") in SATISFIED_STATUSES for dep in deps):
                ready.append(key)
        return ready

    @staticmethod
    def _evaluate_branch_condition(condition: dict, context: dict) -> bool:
        """Evaluate a branch condition against the current execution context.

        Condition shape: {"source": "steps.validate.output.approved", "eq": true}

        Args:
            condition: The branch_condition dict from the step definition.
            context: The merged trigger + step output context dict.

        Returns:
            True if the condition is satisfied, False otherwise.
        """
        source_path = condition.get("source", "")
        expected = condition.get("eq")
        actual = SchedulerService._resolve_path(source_path, context)
        return actual == expected

    @staticmethod
    def _build_context(trigger_payload: dict, step_states: dict[str, dict]) -> dict:
        """Merge trigger payload and completed step outputs into one context dict.

        Args:
            trigger_payload: The input dict from the execution trigger.
            step_states: Map of step_key → current step state dict.

        Returns:
            Context dict with keys 'trigger' and 'steps'.
        """
        steps_context: dict[str, Any] = {}
        for key, state in step_states.items():
            steps_context[key] = {"output": state.get("output") or {}}
        return {"trigger": trigger_payload, "steps": steps_context}

    @staticmethod
    def _resolve_template(template: Any, context: dict) -> Any:
        """Recursively replace {{path}} placeholders in a template structure.

        Args:
            template: A dict, list, or string possibly containing placeholders.
            context: The execution context built by _build_context.

        Returns:
            The template with all placeholders replaced by their resolved values.
        """
        if isinstance(template, dict):
            return {k: SchedulerService._resolve_template(v, context) for k, v in template.items()}
        if isinstance(template, list):
            return [SchedulerService._resolve_template(item, context) for item in template]
        if isinstance(template, str) and template.startswith("{{") and template.endswith("}}"):
            path = template[2:-2].strip()
            resolved = SchedulerService._resolve_path(path, context)
            return resolved if resolved is not None else template
        return template

    @staticmethod
    def _resolve_path(path: str, context: dict) -> Any:
        """Walk a dot-separated path into the context dict.

        Args:
            path: Dot-separated key path e.g. 'steps.validate_order.output.total'.
            context: The execution context dict.

        Returns:
            The value at the path, or None if any key is missing.
        """
        parts = path.split(".")
        node: Any = context
        for part in parts:
            if not isinstance(node, dict) or part not in node:
                return None
            node = node[part]
        return node

    @staticmethod
    def _dispatch_step(execution_id: str, step_def: dict, resolved_input: dict) -> None:
        """Execute a single step, handle retries, and update step state.

        On success: updates step state to 'completed' and calls advance().
        On failure after all retries: updates step state to 'failed' and calls advance()
        (which will then trigger compensation).

        Args:
            execution_id: UUID string.
            step_def: The step definition dict (from workflow_steps).
            resolved_input: The resolved payload to send to the step target.
        """
        step_key = step_def["step_key"]
        retry_max = step_def.get("retry_max", 0)
        retry_delay = step_def.get("retry_delay_seconds", 5)
        timeout = step_def.get("timeout_seconds", 30)

        last_error = ""

        for attempt in range(retry_max + 1):
            StepStateModel.update(
                execution_id=execution_id,
                step_key=step_key,
                status="running",
                attempt_number=attempt + 1,
                input_data=resolved_input,
                started_at=_now(),
            )
            logger.info(
                "Dispatching step: execution=%s step=%s attempt=%d",
                execution_id, step_key, attempt + 1,
            )

            try:
                step_type = step_def.get("step_type", "http")
                if step_type == "local":
                    output = SchedulerService._execute_local_step(step_def, resolved_input)
                else:
                    output = SchedulerService._execute_http_step(step_def, resolved_input, timeout)
                StepStateModel.update(
                    execution_id=execution_id,
                    step_key=step_key,
                    status="completed",
                    output=output,
                    completed_at=_now(),
                )
                logger.info("Step completed: execution=%s step=%s", execution_id, step_key)
                SchedulerService.advance(execution_id)
                return

            except Exception as exc:
                last_error = str(exc)
                logger.warning(
                    "Step attempt failed: execution=%s step=%s attempt=%d error=%s",
                    execution_id, step_key, attempt + 1, last_error,
                )
                if attempt < retry_max:
                    time.sleep(retry_delay)

        # All attempts exhausted
        StepStateModel.update(
            execution_id=execution_id,
            step_key=step_key,
            status="failed",
            error_message=last_error,
            completed_at=_now(),
        )
        logger.error(
            "Step failed after %d attempt(s): execution=%s step=%s error=%s",
            retry_max + 1, execution_id, step_key, last_error,
        )
        SchedulerService.advance(execution_id)

    @staticmethod
    def _execute_local_step(step_def: dict, payload: dict) -> dict:
        """Execute an in-process local step (no HTTP call).

        Supported actions (set via config.action):
            print_message   — prints config.message, returns {"message": ...}
            generate_random — generates a random int 1–1000, returns {"number": ...}

        Args:
            step_def: The step definition dict.
            payload: Resolved input payload (unused for local steps).

        Returns:
            Output dict for the step.

        Raises:
            RuntimeError: If the action is unknown.
        """
        import random as _random
        import uuid as _uuid
        action = step_def.get("config", {}).get("action", "")
        if action == "print_message":
            msg = step_def["config"].get("message", "step executed")
            print(f"[local step] {msg}")
            return {"message": msg}
        elif action == "generate_random":
            number = _random.randint(1, 1000)
            print(f"[local step] generated random number: {number}")
            return {"number": number}
        elif action == "place_order":
            item = payload.get("item", "unknown-item")
            quantity = int(payload.get("quantity", 1))
            unit_price = float(payload.get("unit_price", 0.0))
            order_id = str(_uuid.uuid4())[:8]
            total = round(quantity * unit_price, 2)
            print(f"[local step] order placed: order_id={order_id} item={item} qty={quantity} total=${total}")
            logger.info("place_order: order_id=%s item=%s qty=%d total=%.2f", order_id, item, quantity, total)
            return {"order_id": order_id, "item": item, "quantity": quantity, "unit_price": unit_price, "total": total}
        elif action == "remove_inventory":
            item = payload.get("item", "unknown-item")
            quantity = int(payload.get("quantity", 1))
            # Simulate a fixed starting stock of 100 units
            starting_stock = 100
            remaining = starting_stock - quantity
            print(f"[local step] inventory updated: item={item} removed={quantity} remaining={remaining}")
            logger.info("remove_inventory: item=%s removed=%d remaining=%d", item, quantity, remaining)
            return {"item": item, "quantity_removed": quantity, "remaining_stock": remaining}
        else:
            raise RuntimeError(f"Unknown local action: '{action}'")

    @staticmethod
    def _execute_http_step(step_def: dict, payload: dict, timeout: int) -> dict:
        """Make the HTTP call for an http-type step.

        Args:
            step_def: The step definition dict.
            payload: Resolved request payload.
            timeout: Request timeout in seconds.

        Returns:
            Parsed JSON response body as a dict.

        Raises:
            RuntimeError: On non-2xx response or network/timeout error.
        """
        config = step_def.get("config", {})
        url = config.get("url", "")
        method = config.get("method", "POST").upper()
        headers = config.get("headers", {"Content-Type": "application/json"})

        try:
            response = requests.request(
                method=method,
                url=url,
                json=payload,
                headers=headers,
                timeout=timeout,
            )
        except requests.exceptions.Timeout:
            raise RuntimeError(f"Step timed out after {timeout}s")
        except requests.exceptions.RequestException as exc:
            raise RuntimeError(f"HTTP request failed: {exc}")

        if not response.ok:
            raise RuntimeError(
                f"Non-2xx response: {response.status_code} {response.text[:200]}"
            )

        try:
            return response.json()
        except ValueError:
            return {"raw": response.text}
