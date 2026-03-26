"""Shared pytest fixtures for all service tests.

Uses an in-memory SQLite database so tests never touch app.db.
Patches config.DATABASE before any model import uses it.
"""

import os
import sqlite3
import pytest
import config


@pytest.fixture(autouse=True)
def use_in_memory_db(tmp_path, monkeypatch):
    """Point config.DATABASE at a fresh temp file for every test.

    Using a file-based temp DB (not :memory:) so that multiple
    sqlite3.connect() calls within a single test share the same data.
    """
    db_path = str(tmp_path / "test.db")
    monkeypatch.setattr(config, "DATABASE", db_path)

    schema_path = os.path.join(
        os.path.dirname(__file__), "..", "database", "schema.sql"
    )
    with open(schema_path) as f:
        schema = f.read()

    conn = sqlite3.connect(db_path)
    conn.executescript(schema)
    conn.commit()
    conn.close()

    yield db_path


# ---------------------------------------------------------------------------
# Reusable workflow payload builders
# ---------------------------------------------------------------------------

def make_workflow_payload(name: str = "test_workflow", extra_steps: list = None) -> dict:
    """Return a minimal valid workflow registration payload."""
    steps = [
        {
            "step_key": "step_a",
            "step_type": "http",
            "config": {
                "url": "http://example.com/step_a",
                "method": "POST",
                "payload_template": {"order_id": "{{trigger.order_id}}"},
            },
            "depends_on": [],
            "retry_max": 0,
            "timeout_seconds": 5,
            "compensation_config": None,
        },
        {
            "step_key": "step_b",
            "step_type": "http",
            "config": {
                "url": "http://example.com/step_b",
                "method": "POST",
                "payload_template": {},
            },
            "depends_on": ["step_a"],
            "retry_max": 1,
            "timeout_seconds": 5,
            "compensation_config": {
                "url": "http://example.com/step_b/undo",
                "method": "POST",
                "payload_template": {},
            },
        },
    ]
    if extra_steps:
        steps.extend(extra_steps)
    return {"name": name, "description": "Test workflow", "steps": steps}
