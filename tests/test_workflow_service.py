"""Tests for WorkflowService.

Covers: register, get_all, get_by_id, update, archive, and _validate_dag.
Each method has at minimum: happy path, edge case, failure case.
"""

import pytest
from services.workflow_service import WorkflowService
from tests.conftest import make_workflow_payload


class TestWorkflowServiceRegister:

    def test_register_happy_path(self):
        """Successfully registers a valid workflow and returns it with steps."""
        payload = make_workflow_payload("order_flow")
        result = WorkflowService.register(payload)

        assert result["name"] == "order_flow"
        assert result["version"] == 1
        assert result["status"] == "active"
        assert len(result["steps"]) == 2

    def test_register_missing_name_raises(self):
        """Raises ValueError when 'name' is absent."""
        payload = make_workflow_payload()
        del payload["name"]

        with pytest.raises(ValueError, match="name"):
            WorkflowService.register(payload)

    def test_register_duplicate_name_raises(self):
        """Raises ValueError when a workflow with the same name already exists."""
        WorkflowService.register(make_workflow_payload("dup"))
        with pytest.raises(ValueError, match="already exists"):
            WorkflowService.register(make_workflow_payload("dup"))

    def test_register_missing_steps_raises(self):
        """Raises ValueError when steps list is absent or empty."""
        payload = make_workflow_payload()
        payload["steps"] = []

        with pytest.raises(ValueError, match="steps"):
            WorkflowService.register(payload)

    def test_register_stores_step_positions(self):
        """Steps are persisted in order with correct position values."""
        result = WorkflowService.register(make_workflow_payload())
        positions = [s["position"] for s in result["steps"]]
        assert positions == list(range(len(positions)))


class TestWorkflowServiceValidateDag:

    def test_duplicate_step_keys_raise(self):
        """Raises ValueError on duplicate step_key values."""
        payload = make_workflow_payload()
        payload["steps"][1]["step_key"] = "step_a"  # duplicate

        with pytest.raises(ValueError, match="Duplicate"):
            WorkflowService.register(payload)

    def test_unknown_dependency_raises(self):
        """Raises ValueError when depends_on references a non-existent step."""
        payload = make_workflow_payload()
        payload["steps"][1]["depends_on"] = ["ghost_step"]

        with pytest.raises(ValueError, match="unknown key"):
            WorkflowService.register(payload)

    def test_cyclic_dependency_raises(self):
        """Raises ValueError when steps form a cycle."""
        payload = {
            "name": "cyclic",
            "steps": [
                {"step_key": "a", "step_type": "http", "config": {}, "depends_on": ["b"]},
                {"step_key": "b", "step_type": "http", "config": {}, "depends_on": ["a"]},
            ],
        }
        with pytest.raises(ValueError, match="[Cc]ycle"):
            WorkflowService.register(payload)

    def test_linear_chain_is_valid(self):
        """A simple linear A→B→C DAG registers without error."""
        payload = {
            "name": "linear",
            "steps": [
                {"step_key": "a", "step_type": "http", "config": {}, "depends_on": []},
                {"step_key": "b", "step_type": "http", "config": {}, "depends_on": ["a"]},
                {"step_key": "c", "step_type": "http", "config": {}, "depends_on": ["b"]},
            ],
        }
        result = WorkflowService.register(payload)
        assert len(result["steps"]) == 3

    def test_fan_out_is_valid(self):
        """A→B and A→C (fan-out) registers without error."""
        payload = {
            "name": "fan_out",
            "steps": [
                {"step_key": "a", "step_type": "http", "config": {}, "depends_on": []},
                {"step_key": "b", "step_type": "http", "config": {}, "depends_on": ["a"]},
                {"step_key": "c", "step_type": "http", "config": {}, "depends_on": ["a"]},
            ],
        }
        result = WorkflowService.register(payload)
        assert len(result["steps"]) == 3


class TestWorkflowServiceGetAll:

    def test_get_all_returns_list(self):
        """Returns a list (empty when no workflows exist)."""
        assert WorkflowService.get_all() == []

    def test_get_all_returns_registered_workflows(self):
        """Returns all registered workflows."""
        WorkflowService.register(make_workflow_payload("w1"))
        WorkflowService.register(make_workflow_payload("w2"))
        results = WorkflowService.get_all()
        assert len(results) == 2

    def test_get_all_excludes_archived(self):
        """Archived workflows are not returned by get_all."""
        w = WorkflowService.register(make_workflow_payload("to_archive"))
        WorkflowService.archive(w["id"])
        assert WorkflowService.get_all() == []


class TestWorkflowServiceGetById:

    def test_get_by_id_returns_workflow_with_steps(self):
        """Returns workflow dict with nested steps list."""
        w = WorkflowService.register(make_workflow_payload())
        result = WorkflowService.get_by_id(w["id"])

        assert result["id"] == w["id"]
        assert "steps" in result
        assert len(result["steps"]) == 2

    def test_get_by_id_returns_none_for_missing(self):
        """Returns None for a non-existent workflow ID."""
        assert WorkflowService.get_by_id("does-not-exist") is None

    def test_get_by_id_step_keys_are_correct(self):
        """Steps returned have the correct step_key values."""
        w = WorkflowService.register(make_workflow_payload())
        result = WorkflowService.get_by_id(w["id"])
        keys = [s["step_key"] for s in result["steps"]]
        assert "step_a" in keys
        assert "step_b" in keys


class TestWorkflowServiceUpdate:

    def test_update_bumps_version(self):
        """Update increments the workflow version."""
        w = WorkflowService.register(make_workflow_payload())
        new_payload = make_workflow_payload()
        new_payload["steps"][0]["step_key"] = "new_step"
        new_payload["steps"][1]["depends_on"] = ["new_step"]

        updated = WorkflowService.update(w["id"], new_payload)
        assert updated["version"] == 2

    def test_update_replaces_steps(self):
        """Updated steps replace the old ones."""
        w = WorkflowService.register(make_workflow_payload())
        new_payload = {
            "steps": [
                {"step_key": "only_step", "step_type": "http", "config": {}, "depends_on": []},
            ]
        }
        updated = WorkflowService.update(w["id"], new_payload)
        assert len(updated["steps"]) == 1
        assert updated["steps"][0]["step_key"] == "only_step"

    def test_update_returns_none_for_missing_workflow(self):
        """Returns None when workflow ID does not exist."""
        assert WorkflowService.update("ghost", {"steps": []}) is None


class TestWorkflowServiceArchive:

    def test_archive_sets_status_to_archived(self):
        """Archive marks the workflow status as 'archived'."""
        w = WorkflowService.register(make_workflow_payload())
        result = WorkflowService.archive(w["id"])
        assert result["status"] == "archived"

    def test_archive_returns_none_for_missing(self):
        """Returns None when workflow ID does not exist."""
        assert WorkflowService.archive("ghost") is None

    def test_archived_workflow_not_in_get_all(self):
        """Archived workflow does not appear in get_all results."""
        w = WorkflowService.register(make_workflow_payload())
        WorkflowService.archive(w["id"])
        names = [wf["name"] for wf in WorkflowService.get_all()]
        assert w["name"] not in names
