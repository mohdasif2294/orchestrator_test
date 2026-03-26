"""Demo: Service A workflow.

Registers a two-step workflow and runs it end-to-end:
  Step 1 (print_message)   — prints "step 1 executed"
  Step 2 (generate_random) — generates a random number

Prints a formatted summary of all steps and their outputs.

Usage:
    source .venv/bin/activate
    python demo.py
"""

import json
import sys
import os

# Ensure project root is on the path when run directly
sys.path.insert(0, os.path.dirname(__file__))

from app import init_db, create_app
from services.workflow_service import WorkflowService
from services.execution_service import ExecutionService

WORKFLOW_PAYLOAD = {
    "name": "service_a_demo",
    "description": "Service A demo: print message + generate random number",
    "steps": [
        {
            "step_key": "print_message",
            "step_type": "local",
            "config": {
                "action": "print_message",
                "message": "step 1 executed",
            },
            "depends_on": [],
            "retry_max": 0,
            "timeout_seconds": 5,
            "compensation_config": None,
        },
        {
            "step_key": "generate_random",
            "step_type": "local",
            "config": {
                "action": "generate_random",
            },
            "depends_on": ["print_message"],
            "retry_max": 0,
            "timeout_seconds": 5,
            "compensation_config": None,
        },
    ],
}


def run_demo() -> None:
    """Seed, execute, and display the Service A demo workflow."""
    # Bootstrap — create Flask app context to init the DB
    app = create_app()

    with app.app_context():
        print("\n=== Service A Demo Workflow ===\n")

        # Register workflow (skip if already exists from a prior run)
        existing = [w for w in WorkflowService.get_all() if w["name"] == "service_a_demo"]
        if existing:
            workflow = WorkflowService.get_by_id(existing[0]["id"])
            print(f"Workflow already registered (id={workflow['id'][:8]}...), reusing.")
        else:
            print("Registering workflow...")
            workflow = WorkflowService.register(WORKFLOW_PAYLOAD)
            print(f"Workflow registered  — id: {workflow['id'][:8]}...")

        # Trigger execution
        print("Triggering execution...\n")
        execution = ExecutionService.trigger(workflow["id"], {})

        # Print summary
        print("\n--- Execution Result ---")
        print(f"Execution id : {execution['id'][:8]}...")
        print(f"Status       : {execution['status']}")
        print(f"Steps        :")

        # Sort steps by position from workflow definition
        step_positions = {s["step_key"]: s["position"] for s in workflow["steps"]}
        sorted_steps = sorted(
            execution["steps"],
            key=lambda s: step_positions.get(s["step_key"], 999),
        )

        for i, step in enumerate(sorted_steps, start=1):
            output_str = json.dumps(step["output"]) if step["output"] else "—"
            error_str = f" | error: {step['error_message']}" if step.get("error_message") else ""
            print(
                f"  [{i}] {step['step_key']:<20} → {step['status']:<12}"
                f"| output: {output_str}{error_str}"
            )

        print()


if __name__ == "__main__":
    run_demo()
