"""Tests for SchedulerService.

Covers: advance, _get_ready_steps, _evaluate_branch_condition,
        _build_context, _resolve_template, retry_step.
HTTP dispatch is mocked throughout.
"""

import pytest
from unittest.mock import patch, MagicMock
from services.workflow_service import WorkflowService
from services.execution_service import ExecutionService
from services.scheduler_service import SchedulerService
from models.step_state_model import StepStateModel
from models.execution_model import ExecutionModel
from tests.conftest import make_workflow_payload


def _mock_http_ok(output: dict = None):
    resp = MagicMock()
    resp.ok = True
    resp.json.return_value = output or {"result": "ok"}
    return resp


def _mock_http_fail(status_code: int = 500):
    resp = MagicMock()
    resp.ok = False
    resp.status_code = status_code
    resp.text = "Internal Server Error"
    return resp


def _register_and_trigger(name: str = "sched_wf", payload: dict = None) -> tuple[dict, dict]:
    wf = WorkflowService.register(payload or make_workflow_payload(name))
    with patch("services.scheduler_service.SchedulerService.advance"):
        ex = ExecutionService.trigger(wf["id"], {"order_id": "42"})
    return wf, ex


class TestSchedulerServiceAdvance:

    @patch("requests.request")
    def test_advance_completes_linear_workflow(self, mock_req):
        """A two-step linear workflow reaches 'completed' status."""
        mock_req.return_value = _mock_http_ok()
        wf = WorkflowService.register(make_workflow_payload("linear"))

        with patch("services.scheduler_service.SchedulerService.advance"):
            ex = ExecutionService.trigger(wf["id"], {})

        SchedulerService.advance(ex["id"])

        execution = ExecutionModel.find_by_id(ex["id"])
        assert execution["status"] == "completed"

    @patch("requests.request")
    def test_advance_marks_failed_step_triggers_compensation(self, mock_req):
        """When a step fails, advance triggers CompensationService."""
        mock_req.return_value = _mock_http_fail()
        wf = WorkflowService.register(make_workflow_payload("fail_wf"))

        with patch("services.compensation_service.CompensationService.compensate") as mock_comp:
            with patch("services.scheduler_service.SchedulerService.advance"):
                ex = ExecutionService.trigger(wf["id"], {})
            SchedulerService.advance(ex["id"])

        mock_comp.assert_called_once()

    @patch("requests.request")
    def test_advance_skips_step_on_false_branch_condition(self, mock_req):
        """A step with a branch_condition that evaluates false is marked skipped."""
        mock_req.return_value = _mock_http_ok({"approved": False})
        payload = make_workflow_payload("branch_wf")
        payload["steps"][1]["branch_condition"] = {
            "source": "steps.step_a.output.approved",
            "eq": True,
        }
        wf = WorkflowService.register(payload)

        with patch("services.scheduler_service.SchedulerService.advance"):
            ex = ExecutionService.trigger(wf["id"], {})

        SchedulerService.advance(ex["id"])

        step_b = StepStateModel.find_one(ex["id"], "step_b")
        assert step_b["status"] == "skipped"

    def test_advance_does_nothing_for_unknown_execution(self):
        """advance() returns silently for a non-existent execution ID."""
        SchedulerService.advance("ghost-id")  # should not raise


class TestGetReadySteps:

    def test_returns_steps_with_no_deps(self):
        """Steps with empty depends_on are always ready when pending."""
        step_defs = {
            "a": {"step_key": "a", "depends_on": []},
            "b": {"step_key": "b", "depends_on": ["a"]},
        }
        step_states = {
            "a": {"status": "pending"},
            "b": {"status": "pending"},
        }
        ready = SchedulerService._get_ready_steps(step_defs, step_states)
        assert ready == ["a"]

    def test_returns_step_after_dependency_completes(self):
        """A step becomes ready once all its dependencies are completed."""
        step_defs = {
            "a": {"step_key": "a", "depends_on": []},
            "b": {"step_key": "b", "depends_on": ["a"]},
        }
        step_states = {
            "a": {"status": "completed"},
            "b": {"status": "pending"},
        }
        ready = SchedulerService._get_ready_steps(step_defs, step_states)
        assert ready == ["b"]

    def test_returns_empty_when_dep_not_satisfied(self):
        """No steps are ready if a dependency is still running."""
        step_defs = {
            "a": {"step_key": "a", "depends_on": []},
            "b": {"step_key": "b", "depends_on": ["a"]},
        }
        step_states = {
            "a": {"status": "running"},
            "b": {"status": "pending"},
        }
        ready = SchedulerService._get_ready_steps(step_defs, step_states)
        assert ready == []

    def test_skipped_dep_satisfies_dependent(self):
        """A step whose dependency was skipped is still considered ready."""
        step_defs = {
            "a": {"step_key": "a", "depends_on": []},
            "b": {"step_key": "b", "depends_on": ["a"]},
        }
        step_states = {
            "a": {"status": "skipped"},
            "b": {"status": "pending"},
        }
        ready = SchedulerService._get_ready_steps(step_defs, step_states)
        assert ready == ["b"]


class TestEvaluateBranchCondition:

    def test_condition_true_when_value_matches(self):
        """Returns True when context value equals expected."""
        context = {"steps": {"validate": {"output": {"approved": True}}}}
        condition = {"source": "steps.validate.output.approved", "eq": True}
        assert SchedulerService._evaluate_branch_condition(condition, context) is True

    def test_condition_false_when_value_differs(self):
        """Returns False when context value does not match expected."""
        context = {"steps": {"validate": {"output": {"approved": False}}}}
        condition = {"source": "steps.validate.output.approved", "eq": True}
        assert SchedulerService._evaluate_branch_condition(condition, context) is False

    def test_condition_false_when_path_missing(self):
        """Returns False when the source path resolves to None."""
        context = {"steps": {}}
        condition = {"source": "steps.missing.output.field", "eq": "yes"}
        assert SchedulerService._evaluate_branch_condition(condition, context) is False


class TestResolveTemplate:

    def test_resolves_trigger_placeholder(self):
        """Replaces {{trigger.key}} with the value from trigger payload."""
        context = {"trigger": {"order_id": "99"}, "steps": {}}
        template = {"id": "{{trigger.order_id}}"}
        result = SchedulerService._resolve_template(template, context)
        assert result == {"id": "99"}

    def test_resolves_step_output_placeholder(self):
        """Replaces {{steps.step_a.output.total}} with the step's output value."""
        context = {
            "trigger": {},
            "steps": {"step_a": {"output": {"total": 42}}},
        }
        template = {"amount": "{{steps.step_a.output.total}}"}
        result = SchedulerService._resolve_template(template, context)
        assert result == {"amount": 42}

    def test_unresolved_placeholder_left_unchanged(self):
        """Leaves placeholder unchanged when the path does not exist."""
        context = {"trigger": {}, "steps": {}}
        template = {"x": "{{trigger.missing}}"}
        result = SchedulerService._resolve_template(template, context)
        assert result == {"x": "{{trigger.missing}}"}

    def test_nested_template_resolved(self):
        """Resolves placeholders in nested dict structures."""
        context = {"trigger": {"a": 1, "b": 2}, "steps": {}}
        template = {"outer": {"inner": "{{trigger.a}}"}}
        result = SchedulerService._resolve_template(template, context)
        assert result == {"outer": {"inner": 1}}


class TestRetryStep:

    @patch("requests.request")
    def test_retry_failed_step_reruns_it(self, mock_req):
        """retry_step resets a failed step to pending and advances the execution."""
        mock_req.side_effect = [_mock_http_fail(), _mock_http_ok(), _mock_http_ok()]
        wf = WorkflowService.register(make_workflow_payload("retry_wf"))

        with patch("services.scheduler_service.SchedulerService.advance"):
            ex = ExecutionService.trigger(wf["id"], {})

        # Manually mark step_a as failed to test retry path
        StepStateModel.update(ex["id"], "step_a", status="failed", error_message="oops")
        ExecutionModel.update_status(ex["id"], "running")

        mock_req.reset_mock()
        mock_req.return_value = _mock_http_ok()

        result = SchedulerService.retry_step(ex["id"], "step_a")
        assert result is not None

    def test_retry_non_failed_step_raises(self):
        """Raises ValueError when retrying a step that is not in failed state."""
        wf, ex = _register_and_trigger("retry_non_fail")

        with pytest.raises(ValueError, match="not in a failed state"):
            SchedulerService.retry_step(ex["id"], "step_a")

    def test_retry_returns_none_for_missing_step(self):
        """Returns None when the step_key does not exist in the execution."""
        wf, ex = _register_and_trigger("retry_missing")
        result = SchedulerService.retry_step(ex["id"], "no_such_step")
        assert result is None
