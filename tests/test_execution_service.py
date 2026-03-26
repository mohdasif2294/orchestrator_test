"""Tests for ExecutionService.

Covers: trigger, get_status, list_by_workflow, cancel, delete.
HTTP calls made by SchedulerService are mocked so tests are self-contained.
"""

import pytest
from unittest.mock import patch, MagicMock
from services.workflow_service import WorkflowService
from services.execution_service import ExecutionService
from tests.conftest import make_workflow_payload


def _mock_http_ok(output: dict = None):
    """Return a mock requests.Response with a 200 status and JSON body."""
    resp = MagicMock()
    resp.ok = True
    resp.json.return_value = output or {"result": "ok"}
    return resp


def _register_workflow(name: str = "exec_test_wf") -> dict:
    return WorkflowService.register(make_workflow_payload(name))


class TestExecutionServiceTrigger:

    @patch("requests.request")
    def test_trigger_happy_path(self, mock_req):
        """Triggering a valid workflow creates an execution and runs it."""
        mock_req.return_value = _mock_http_ok()
        wf = _register_workflow()

        result = ExecutionService.trigger(wf["id"], {"order_id": "123"})

        assert result["workflow_id"] == wf["id"]
        assert result["status"] == "completed"

    def test_trigger_unknown_workflow_raises(self):
        """Raises ValueError when the workflow ID does not exist."""
        with pytest.raises(ValueError, match="not found"):
            ExecutionService.trigger("ghost-id", {})

    def test_trigger_archived_workflow_raises(self):
        """Raises ValueError when the workflow is archived."""
        wf = _register_workflow("archived_wf")
        WorkflowService.archive(wf["id"])

        with pytest.raises(ValueError, match="not active"):
            ExecutionService.trigger(wf["id"], {})

    @patch("requests.request")
    def test_trigger_creates_step_states(self, mock_req):
        """Triggering an execution creates one step_state row per step."""
        mock_req.return_value = _mock_http_ok()
        wf = _register_workflow()

        result = ExecutionService.trigger(wf["id"], {})
        assert len(result["steps"]) == 2

    @patch("requests.request")
    def test_trigger_payload_is_stored(self, mock_req):
        """The trigger payload is persisted on the execution row."""
        mock_req.return_value = _mock_http_ok()
        wf = _register_workflow()

        result = ExecutionService.trigger(wf["id"], {"order_id": "abc"})
        assert result["trigger_payload"]["order_id"] == "abc"


class TestExecutionServiceGetStatus:

    @patch("requests.request")
    def test_get_status_returns_execution_with_steps(self, mock_req):
        """get_status returns execution dict including step states."""
        mock_req.return_value = _mock_http_ok()
        wf = _register_workflow()
        ex = ExecutionService.trigger(wf["id"], {})

        result = ExecutionService.get_status(ex["id"])
        assert result["id"] == ex["id"]
        assert "steps" in result

    def test_get_status_returns_none_for_missing(self):
        """Returns None for a non-existent execution ID."""
        assert ExecutionService.get_status("ghost") is None

    @patch("requests.request")
    def test_get_status_step_keys_present(self, mock_req):
        """Each step state contains the expected step_key."""
        mock_req.return_value = _mock_http_ok()
        wf = _register_workflow()
        ex = ExecutionService.trigger(wf["id"], {})

        result = ExecutionService.get_status(ex["id"])
        keys = {s["step_key"] for s in result["steps"]}
        assert "step_a" in keys
        assert "step_b" in keys


class TestExecutionServiceListByWorkflow:

    @patch("requests.request")
    def test_list_by_workflow_returns_executions(self, mock_req):
        """Returns executions filtered by workflow_id."""
        mock_req.return_value = _mock_http_ok()
        wf = _register_workflow()
        ExecutionService.trigger(wf["id"], {})
        ExecutionService.trigger(wf["id"], {})

        results = ExecutionService.list_by_workflow(wf["id"])
        assert len(results) == 2

    def test_list_by_workflow_empty_when_none(self):
        """Returns empty list when workflow has no executions."""
        wf = _register_workflow()
        assert ExecutionService.list_by_workflow(wf["id"]) == []

    @patch("requests.request")
    def test_list_without_filter_returns_all(self, mock_req):
        """Passing None as workflow_id returns all executions."""
        mock_req.return_value = _mock_http_ok()
        wf1 = _register_workflow("wf_list_1")
        wf2 = _register_workflow("wf_list_2")
        ExecutionService.trigger(wf1["id"], {})
        ExecutionService.trigger(wf2["id"], {})

        results = ExecutionService.list_by_workflow(None)
        assert len(results) == 2


class TestExecutionServiceCancel:

    @patch("requests.request")
    def test_cancel_running_execution(self, mock_req):
        """Cancelling a completed execution raises ValueError."""
        mock_req.return_value = _mock_http_ok()
        wf = _register_workflow()
        ex = ExecutionService.trigger(wf["id"], {})

        # execution is already completed after trigger; test cancel on a fresh pending one
        # by mocking advance to do nothing
        with patch("services.scheduler_service.SchedulerService.advance"):
            wf2 = _register_workflow("cancel_wf")
            ex2 = ExecutionService.trigger(wf2["id"], {})

        result = ExecutionService.cancel(ex2["id"])
        assert result["status"] == "failed"

    def test_cancel_returns_none_for_missing(self):
        """Returns None when execution ID does not exist."""
        assert ExecutionService.cancel("ghost") is None

    @patch("requests.request")
    def test_cancel_terminal_execution_raises(self, mock_req):
        """Raises ValueError when trying to cancel an already-completed execution."""
        mock_req.return_value = _mock_http_ok()
        wf = _register_workflow()
        ex = ExecutionService.trigger(wf["id"], {})  # completes synchronously

        with pytest.raises(ValueError, match="terminal"):
            ExecutionService.cancel(ex["id"])


class TestExecutionServiceDelete:

    @patch("requests.request")
    def test_delete_sets_status_to_deleted(self, mock_req):
        """Soft delete marks execution status as 'deleted'."""
        mock_req.return_value = _mock_http_ok()
        wf = _register_workflow()
        ex = ExecutionService.trigger(wf["id"], {})

        result = ExecutionService.delete(ex["id"])
        assert result["status"] == "deleted"

    def test_delete_returns_none_for_missing(self):
        """Returns None when execution ID does not exist."""
        assert ExecutionService.delete("ghost") is None

    @patch("services.scheduler_service.SchedulerService.advance")
    def test_delete_running_execution_raises(self, mock_advance):
        """Raises ValueError when trying to delete a running execution."""
        wf = _register_workflow()
        ex = ExecutionService.trigger(wf["id"], {})  # advance mocked → stays 'running'

        with pytest.raises(ValueError, match="running"):
            ExecutionService.delete(ex["id"])
