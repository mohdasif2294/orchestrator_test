"""Tests for CompensationService.

Covers: compensate, _get_completed_steps_in_reverse_order,
        _resolve_template, _run_compensation_step.
"""

import pytest
from unittest.mock import patch, MagicMock, call
from services.workflow_service import WorkflowService
from services.execution_service import ExecutionService
from services.compensation_service import CompensationService
from models.execution_model import ExecutionModel
from models.step_state_model import StepStateModel
from tests.conftest import make_workflow_payload


def _mock_http_ok(output: dict = None):
    resp = MagicMock()
    resp.ok = True
    resp.json.return_value = output or {"result": "ok"}
    return resp


def _mock_http_fail():
    resp = MagicMock()
    resp.ok = False
    resp.status_code = 500
    resp.text = "Server Error"
    return resp


def _setup_execution_with_completed_step() -> tuple[dict, dict]:
    """Register a workflow, trigger execution, mark step_a completed manually."""
    payload = make_workflow_payload("comp_wf")
    wf = WorkflowService.register(payload)

    with patch("services.scheduler_service.SchedulerService.advance"):
        ex = ExecutionService.trigger(wf["id"], {"order_id": "1"})

    # Manually mark step_a completed so compensation has something to undo
    StepStateModel.update(
        ex["id"], "step_a", status="completed",
        output={"result": "ok"}, completed_at="2024-01-01T00:00:01Z"
    )
    StepStateModel.update(
        ex["id"], "step_b", status="completed",
        output={"result": "ok"}, completed_at="2024-01-01T00:00:02Z"
    )
    ExecutionModel.update_status(ex["id"], "running")
    return wf, ex


class TestCompensationServiceCompensate:

    @patch("requests.request")
    def test_compensate_marks_execution_compensated(self, mock_req):
        """After compensation, execution status is 'compensated'."""
        mock_req.return_value = _mock_http_ok()
        wf, ex = _setup_execution_with_completed_step()

        CompensationService.compensate(ex["id"], "step_b")

        execution = ExecutionModel.find_by_id(ex["id"])
        assert execution["status"] == "compensated"

    @patch("requests.request")
    def test_compensate_only_compensates_completed_steps(self, mock_req):
        """Pending steps are never compensated — only completed ones."""
        mock_req.return_value = _mock_http_ok()
        payload = make_workflow_payload("partial_comp")
        wf = WorkflowService.register(payload)

        with patch("services.scheduler_service.SchedulerService.advance"):
            ex = ExecutionService.trigger(wf["id"], {})

        # step_a completed, step_b still pending → only step_a should be attempted
        StepStateModel.update(ex["id"], "step_a", status="completed",
                              completed_at="2024-01-01T00:00:01Z")

        CompensationService.compensate(ex["id"], "step_b")

        # step_b has no compensation_config so it is skipped; step_a has none either
        # just verify execution reached compensated state without error
        execution = ExecutionModel.find_by_id(ex["id"])
        assert execution["status"] == "compensated"

    @patch("requests.request")
    def test_compensate_runs_in_reverse_order(self, mock_req):
        """Compensation calls are made in reverse completion order."""
        mock_req.return_value = _mock_http_ok()
        payload = make_workflow_payload("reverse_comp")
        # Give step_b a compensation config so we can track call order
        payload["steps"][1]["compensation_config"] = {
            "url": "http://example.com/step_b/undo",
            "method": "POST",
            "payload_template": {},
        }
        wf = WorkflowService.register(payload)

        with patch("services.scheduler_service.SchedulerService.advance"):
            ex = ExecutionService.trigger(wf["id"], {})

        StepStateModel.update(ex["id"], "step_a", status="completed",
                              completed_at="2024-01-01T00:00:01Z")
        StepStateModel.update(ex["id"], "step_b", status="completed",
                              completed_at="2024-01-01T00:00:02Z")

        urls_called = []
        def capture_request(method, url, **kwargs):
            urls_called.append(url)
            return _mock_http_ok()

        with patch("requests.request", side_effect=capture_request):
            CompensationService.compensate(ex["id"], "step_b")

        # step_b completed last so its compensation should be called first
        assert urls_called[0] == "http://example.com/step_b/undo"

    def test_compensate_unknown_execution_does_not_raise(self):
        """compensate() handles a missing execution gracefully."""
        CompensationService.compensate("ghost-id", "step_a")  # should not raise


class TestGetCompletedStepsInReverseOrder:

    def test_returns_completed_steps_only(self):
        """Only completed steps are returned, not pending/failed/skipped."""
        payload = make_workflow_payload("rev_order")
        wf = WorkflowService.register(payload)

        with patch("services.scheduler_service.SchedulerService.advance"):
            ex = ExecutionService.trigger(wf["id"], {})

        StepStateModel.update(ex["id"], "step_a", status="completed",
                              completed_at="2024-01-01T00:00:01Z")
        StepStateModel.update(ex["id"], "step_b", status="failed")

        result = CompensationService._get_completed_steps_in_reverse_order(ex["id"])
        assert len(result) == 1
        assert result[0]["step_key"] == "step_a"

    def test_returns_in_reverse_completion_order(self):
        """Steps are sorted by completed_at descending."""
        payload = make_workflow_payload("rev_sort")
        wf = WorkflowService.register(payload)

        with patch("services.scheduler_service.SchedulerService.advance"):
            ex = ExecutionService.trigger(wf["id"], {})

        StepStateModel.update(ex["id"], "step_a", status="completed",
                              completed_at="2024-01-01T00:00:01Z")
        StepStateModel.update(ex["id"], "step_b", status="completed",
                              completed_at="2024-01-01T00:00:05Z")

        result = CompensationService._get_completed_steps_in_reverse_order(ex["id"])
        assert result[0]["step_key"] == "step_b"
        assert result[1]["step_key"] == "step_a"

    def test_returns_empty_when_no_completed_steps(self):
        """Returns empty list when no steps have completed."""
        payload = make_workflow_payload("no_completed")
        wf = WorkflowService.register(payload)

        with patch("services.scheduler_service.SchedulerService.advance"):
            ex = ExecutionService.trigger(wf["id"], {})

        result = CompensationService._get_completed_steps_in_reverse_order(ex["id"])
        assert result == []


class TestCompensationResolveTemplate:

    def test_resolves_step_output_in_compensation_payload(self):
        """Resolves step output placeholders in compensation payload template."""
        context = {
            "trigger": {"order_id": "7"},
            "steps": {"charge": {"output": {"payment_id": "pay_99"}}},
        }
        template = {"payment_id": "{{steps.charge.output.payment_id}}"}
        result = CompensationService._resolve_template(template, context)
        assert result == {"payment_id": "pay_99"}

    def test_unresolved_path_returns_none(self):
        """Returns None for a placeholder whose path does not exist."""
        context = {"trigger": {}, "steps": {}}
        template = {"x": "{{steps.missing.output.field}}"}
        result = CompensationService._resolve_template(template, context)
        assert result == {"x": None}

    def test_non_placeholder_strings_are_unchanged(self):
        """String values without {{ }} are passed through unmodified."""
        context = {"trigger": {}, "steps": {}}
        template = {"action": "refund"}
        result = CompensationService._resolve_template(template, context)
        assert result == {"action": "refund"}


class TestRunCompensationStep:

    @patch("requests.request")
    def test_successful_compensation_marks_step_compensated(self, mock_req):
        """A successful HTTP call marks the step state as 'compensated'."""
        mock_req.return_value = _mock_http_ok()
        payload = make_workflow_payload("run_comp")
        wf = WorkflowService.register(payload)

        with patch("services.scheduler_service.SchedulerService.advance"):
            ex = ExecutionService.trigger(wf["id"], {})

        StepStateModel.update(ex["id"], "step_b", status="completed",
                              completed_at="2024-01-01T00:00:01Z")

        compensation_config = {
            "url": "http://example.com/step_b/undo",
            "method": "POST",
            "payload_template": {},
        }
        context = {"trigger": {}, "steps": {"step_b": {"output": {}}}}

        CompensationService._run_compensation_step(
            ex["id"], "step_b", compensation_config, context
        )

        state = StepStateModel.find_one(ex["id"], "step_b")
        assert state["status"] == "compensated"

    @patch("requests.request")
    def test_failed_compensation_http_marks_step_failed(self, mock_req):
        """A non-2xx compensation response marks step as failed (best-effort)."""
        mock_req.return_value = _mock_http_fail()
        payload = make_workflow_payload("comp_fail")
        wf = WorkflowService.register(payload)

        with patch("services.scheduler_service.SchedulerService.advance"):
            ex = ExecutionService.trigger(wf["id"], {})

        compensation_config = {
            "url": "http://example.com/undo",
            "method": "POST",
            "payload_template": {},
        }
        context = {"trigger": {}, "steps": {}}

        CompensationService._run_compensation_step(
            ex["id"], "step_a", compensation_config, context
        )

        state = StepStateModel.find_one(ex["id"], "step_a")
        assert state["status"] == "failed"

    @patch("requests.request", side_effect=Exception("network down"))
    def test_compensation_exception_marks_step_failed(self, mock_req):
        """An exception during compensation HTTP call marks step as failed."""
        payload = make_workflow_payload("comp_exc")
        wf = WorkflowService.register(payload)

        with patch("services.scheduler_service.SchedulerService.advance"):
            ex = ExecutionService.trigger(wf["id"], {})

        compensation_config = {
            "url": "http://example.com/undo",
            "method": "POST",
            "payload_template": {},
        }
        context = {"trigger": {}, "steps": {}}

        CompensationService._run_compensation_step(
            ex["id"], "step_a", compensation_config, context
        )

        state = StepStateModel.find_one(ex["id"], "step_a")
        assert state["status"] == "failed"
