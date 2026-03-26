"""Workflow definition routes.

Endpoints:
    POST   /workflows              — register a new workflow
    GET    /workflows              — list all active workflows
    GET    /workflows/<id>         — get one workflow with its steps
    PUT    /workflows/<id>         — update a workflow (bumps version)
    DELETE /workflows/<id>         — archive a workflow (soft delete)
"""

from flask import Blueprint, request
from services.workflow_service import WorkflowService
from utils.response import success_response, error_response
from utils.auth import require_api_key

workflow_bp = Blueprint("workflows", __name__, url_prefix="/workflows")


@workflow_bp.route("", methods=["POST"])
@require_api_key
def register_workflow():
    """Register a new workflow definition."""
    payload = request.get_json(silent=True)
    if not payload:
        return error_response("Request body must be valid JSON")

    try:
        workflow = WorkflowService.register(payload)
        return success_response(data=workflow, message="Workflow registered", status_code=201)
    except ValueError as exc:
        return error_response(str(exc), status_code=422)
    except Exception as exc:
        return error_response("Internal server error", errors=str(exc), status_code=500)


@workflow_bp.route("", methods=["GET"])
@require_api_key
def list_workflows():
    """List all active workflow definitions."""
    try:
        workflows = WorkflowService.get_all()
        return success_response(data=workflows)
    except Exception as exc:
        return error_response("Internal server error", errors=str(exc), status_code=500)


@workflow_bp.route("/<workflow_id>", methods=["GET"])
@require_api_key
def get_workflow(workflow_id: str):
    """Get a single workflow definition including its steps."""
    try:
        workflow = WorkflowService.get_by_id(workflow_id)
        if workflow is None:
            return error_response("Workflow not found", status_code=404)
        return success_response(data=workflow)
    except Exception as exc:
        return error_response("Internal server error", errors=str(exc), status_code=500)


@workflow_bp.route("/<workflow_id>", methods=["PUT"])
@require_api_key
def update_workflow(workflow_id: str):
    """Update an existing workflow definition (bumps the version)."""
    payload = request.get_json(silent=True)
    if not payload:
        return error_response("Request body must be valid JSON")

    try:
        workflow = WorkflowService.update(workflow_id, payload)
        if workflow is None:
            return error_response("Workflow not found", status_code=404)
        return success_response(data=workflow, message="Workflow updated")
    except ValueError as exc:
        return error_response(str(exc), status_code=422)
    except Exception as exc:
        return error_response("Internal server error", errors=str(exc), status_code=500)


@workflow_bp.route("/<workflow_id>", methods=["DELETE"])
@require_api_key
def archive_workflow(workflow_id: str):
    """Archive a workflow definition (soft delete)."""
    try:
        result = WorkflowService.archive(workflow_id)
        if result is None:
            return error_response("Workflow not found", status_code=404)
        return success_response(data=result, message="Workflow archived")
    except Exception as exc:
        return error_response("Internal server error", errors=str(exc), status_code=500)
