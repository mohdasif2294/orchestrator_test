"""Execution routes.

Endpoints:
    POST   /executions                     — trigger a workflow execution
    GET    /executions/<id>                — get execution status + step states
    GET    /executions?workflow_id=<id>    — list executions for a workflow
    POST   /executions/<id>/cancel         — cancel a running execution
    DELETE /executions/<id>                — soft delete an execution
"""

from flask import Blueprint, request
from services.execution_service import ExecutionService
from utils.response import success_response, error_response
from utils.auth import require_api_key

execution_bp = Blueprint("executions", __name__, url_prefix="/executions")


@execution_bp.route("", methods=["POST"])
@require_api_key
def trigger_execution():
    """Trigger a new workflow execution.

    Expected body: {"workflow_id": "<id>", "payload": {...}}
    """
    body = request.get_json(silent=True)
    if not body:
        return error_response("Request body must be valid JSON")

    workflow_id = body.get("workflow_id")
    if not workflow_id:
        return error_response("Missing required field: workflow_id")

    trigger_payload = body.get("payload", {})

    try:
        execution = ExecutionService.trigger(workflow_id, trigger_payload)
        return success_response(data=execution, message="Execution triggered", status_code=201)
    except ValueError as exc:
        return error_response(str(exc), status_code=422)
    except Exception as exc:
        return error_response("Internal server error", errors=str(exc), status_code=500)


@execution_bp.route("", methods=["GET"])
@require_api_key
def list_executions():
    """List executions, optionally filtered by workflow_id query param."""
    workflow_id = request.args.get("workflow_id")

    try:
        executions = ExecutionService.list_by_workflow(workflow_id)
        return success_response(data=executions)
    except Exception as exc:
        return error_response("Internal server error", errors=str(exc), status_code=500)


@execution_bp.route("/<execution_id>", methods=["GET"])
@require_api_key
def get_execution(execution_id: str):
    """Get a single execution with all its step states."""
    try:
        execution = ExecutionService.get_status(execution_id)
        if execution is None:
            return error_response("Execution not found", status_code=404)
        return success_response(data=execution)
    except Exception as exc:
        return error_response("Internal server error", errors=str(exc), status_code=500)


@execution_bp.route("/<execution_id>", methods=["DELETE"])
@require_api_key
def delete_execution(execution_id: str):
    """Soft delete an execution (marks status as 'deleted')."""
    try:
        result = ExecutionService.delete(execution_id)
        if result is None:
            return error_response("Execution not found", status_code=404)
        return success_response(data=result, message="Execution deleted")
    except ValueError as exc:
        return error_response(str(exc), status_code=422)
    except Exception as exc:
        return error_response("Internal server error", errors=str(exc), status_code=500)


@execution_bp.route("/<execution_id>/cancel", methods=["POST"])
@require_api_key
def cancel_execution(execution_id: str):
    """Cancel a running execution."""
    try:
        result = ExecutionService.cancel(execution_id)
        if result is None:
            return error_response("Execution not found", status_code=404)
        return success_response(data=result, message="Execution cancelled")
    except ValueError as exc:
        return error_response(str(exc), status_code=422)
    except Exception as exc:
        return error_response("Internal server error", errors=str(exc), status_code=500)
