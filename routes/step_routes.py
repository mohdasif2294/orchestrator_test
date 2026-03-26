"""Step state routes.

Endpoints:
    GET   /executions/<execution_id>/steps                     — list all step states
    POST  /executions/<execution_id>/steps/<step_key>/retry    — manually retry a failed step
"""

from flask import Blueprint
from services.execution_service import ExecutionService
from services.scheduler_service import SchedulerService
from utils.response import success_response, error_response
from utils.auth import require_api_key

step_bp = Blueprint("steps", __name__, url_prefix="/executions")


@step_bp.route("/<execution_id>/steps", methods=["GET"])
@require_api_key
def list_step_states(execution_id: str):
    """List all step states for an execution."""
    try:
        execution = ExecutionService.get_status(execution_id)
        if execution is None:
            return error_response("Execution not found", status_code=404)
        return success_response(data=execution.get("steps", []))
    except Exception as exc:
        return error_response("Internal server error", errors=str(exc), status_code=500)


@step_bp.route("/<execution_id>/steps/<step_key>/retry", methods=["POST"])
@require_api_key
def retry_step(execution_id: str, step_key: str):
    """Manually retry a failed step in an execution."""
    try:
        result = SchedulerService.retry_step(execution_id, step_key)
        if result is None:
            return error_response("Execution or step not found", status_code=404)
        return success_response(data=result, message=f"Step '{step_key}' queued for retry")
    except ValueError as exc:
        return error_response(str(exc), status_code=422)
    except Exception as exc:
        return error_response("Internal server error", errors=str(exc), status_code=500)
