"""Demo: Order Placement + Inventory Removal Workflow.

Registers a two-step DAG workflow via the HTTP API and runs it end-to-end:

  Step 1 (place_order)      — validates and records the order; returns order_id and total
  Step 2 (remove_inventory) — removes the ordered quantity from inventory (depends on Step 1)

Step 2 receives item and quantity from Step 1's output via payload templates:
  {{steps.place_order.output.item}}
  {{steps.place_order.output.quantity}}

Prints a formatted summary of all steps, their outputs, and the relevant log lines.

Usage:
    source .venv/bin/activate
    python demo_order.py
"""

import json
import os
import socket
import subprocess
import sys
import tempfile
import time

import requests

# ── Helpers ─────────────────────────────────────────────────────────────────────

def _free_port() -> int:
    """Return a free TCP port by binding to port 0 and releasing it."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_for_server(base_url: str, api_key: str, retries: int = 40, delay: float = 0.25) -> None:
    """Block until the Flask server responds to GET /workflows or raise after timeout."""
    headers = {"X-API-Key": api_key}
    for _ in range(retries):
        try:
            r = requests.get(f"{base_url}/workflows", headers=headers, timeout=1)
            if r.status_code in (200, 401, 405):  # server is up and responding
                return
        except requests.exceptions.ConnectionError:
            pass
        time.sleep(delay)
    raise RuntimeError("Flask server did not start in time.")


def _post(base_url: str, headers: dict, path: str, body: dict) -> dict:
    resp = requests.post(f"{base_url}{path}", json=body, headers=headers, timeout=10)
    resp.raise_for_status()
    return resp.json()


def _get(base_url: str, headers: dict, path: str) -> dict:
    resp = requests.get(f"{base_url}{path}", headers=headers, timeout=10)
    resp.raise_for_status()
    return resp.json()


def _poll_execution(base_url: str, headers: dict, execution_id: str, max_wait: int = 20) -> dict:
    """Poll GET /executions/<id> until execution reaches a terminal status."""
    terminal = {"completed", "failed", "compensated", "compensating"}
    deadline = time.time() + max_wait
    while time.time() < deadline:
        data = _get(base_url, headers, f"/executions/{execution_id}")
        status = data["data"]["status"]
        if status in terminal:
            return data["data"]
        time.sleep(0.2)
    raise RuntimeError(f"Execution did not finish within {max_wait}s")


def _filter_logs(lines: list[str], execution_id: str) -> list[str]:
    """Return log lines relevant to this execution."""
    keywords = {execution_id[:8], "place_order", "remove_inventory",
                "Dispatching step", "Step completed", "Step failed",
                "local step", "Execution completed"}
    return [line for line in lines if any(k in line for k in keywords)]


# ── Display ──────────────────────────────────────────────────────────────────────

def _sep(char: str = "─", width: int = 72) -> None:
    print(char * width)


def _section(title: str) -> None:
    _sep()
    print(f"  {title}")
    _sep()


def _display_summary(
    workflow: dict, execution: dict, trigger: dict, server_log_lines: list[str]
) -> None:
    print()
    _sep("═")
    print("  ORDER PLACEMENT + INVENTORY REMOVAL — Execution Summary")
    _sep("═")
    print(f"\n  Workflow   : {workflow['name']}  (v{workflow['version']})")
    print(f"  Workflow ID: {workflow['id']}")
    print(f"\n  Execution  : {execution['id']}")
    print(f"  Status     : {execution['status'].upper()}")

    _section("Trigger Payload (order request)")
    for k, v in trigger.items():
        print(f"    {k:<12}: {v}")

    _section("Step Results")
    step_positions = {s["step_key"]: s["position"] for s in workflow["steps"]}
    sorted_steps = sorted(
        execution["steps"],
        key=lambda s: step_positions.get(s["step_key"], 999),
    )
    for i, step in enumerate(sorted_steps, start=1):
        icon = "✓" if step["status"] == "completed" else "✗"
        print(f"\n  [{i}] {icon}  {step['step_key']}")
        print(f"       Status  : {step['status']}")
        print(f"       Attempts: {step.get('attempt_number', 0)}")
        if step.get("input"):
            print(f"       Input   : {json.dumps(step['input'])}")
        if step.get("output"):
            print(f"       Output  : {json.dumps(step['output'])}")
        if step.get("error_message"):
            print(f"       Error   : {step['error_message']}")

    _section("Execution Logs (filtered to this run)")
    relevant = _filter_logs(server_log_lines, execution["id"])
    if relevant:
        for line in relevant:
            print(f"  {line}")
    else:
        print("  (no matching log lines — check app.log for full output)")
    _sep("═")
    print()


# ── Workflow definition ───────────────────────────────────────────────────────────

WORKFLOW_NAME = "order_inventory_demo"

WORKFLOW_PAYLOAD = {
    "name": WORKFLOW_NAME,
    "description": "Place an order then remove the purchased items from inventory",
    "steps": [
        {
            "step_key": "place_order",
            "step_type": "local",
            "config": {
                "action": "place_order",
                # pulls item, quantity, unit_price from the execution trigger payload
                "payload_template": {
                    "item": "{{trigger.item}}",
                    "quantity": "{{trigger.quantity}}",
                    "unit_price": "{{trigger.unit_price}}",
                },
            },
            "depends_on": [],
            "retry_max": 0,
            "timeout_seconds": 10,
            "compensation_config": None,
        },
        {
            "step_key": "remove_inventory",
            "step_type": "local",
            "config": {
                "action": "remove_inventory",
                # pulls item and quantity from Step 1's output
                "payload_template": {
                    "item": "{{steps.place_order.output.item}}",
                    "quantity": "{{steps.place_order.output.quantity}}",
                },
            },
            "depends_on": ["place_order"],
            "retry_max": 0,
            "timeout_seconds": 10,
            "compensation_config": None,
        },
    ],
}

TRIGGER_PAYLOAD = {
    "item": "laptop",
    "quantity": 3,
    "unit_price": 999.99,
}


# ── Main ──────────────────────────────────────────────────────────────────────────

def run_demo() -> None:
    """Run the order + inventory demo end-to-end via real HTTP API calls."""
    api_key = "dev-secret-key"
    port = _free_port()
    base_url = f"http://127.0.0.1:{port}"
    headers = {"X-API-Key": api_key, "Content-Type": "application/json"}

    # Use a temp DB so the demo never touches production state
    db_fd, db_path = tempfile.mkstemp(suffix=".db", prefix="demo_order_")
    os.close(db_fd)

    # Build environment for the subprocess
    env = {
        **os.environ,
        "DATABASE_PATH": db_path,
        "FLASK_PORT": str(port),
        "FLASK_DEBUG": "false",
        "API_KEY": api_key,
    }

    project_root = os.path.dirname(os.path.abspath(__file__))
    server_proc = None

    try:
        # ── Start Flask server in a subprocess ─────────────────────────────────
        print(f"\n  Starting Flask server on port {port} (temp DB)...")
        server_proc = subprocess.Popen(
            [sys.executable, "app.py"],
            cwd=project_root,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        _wait_for_server(base_url, api_key)
        print("  Server ready.\n")

        # ── Step 1: Register workflow ──────────────────────────────────────────
        _section(f"API CALL 1 — POST /workflows  (register workflow)")
        print(f"  Payload: name={WORKFLOW_NAME!r}, steps={len(WORKFLOW_PAYLOAD['steps'])}")

        resp = _post(base_url, headers, "/workflows", WORKFLOW_PAYLOAD)
        workflow_id = resp["data"]["id"]
        print(f"\n  Response : {resp['message']}")
        print(f"  Workflow : id={workflow_id}")

        workflow_resp = _get(base_url, headers, f"/workflows/{workflow_id}")
        workflow = workflow_resp["data"]

        # ── Step 2: Trigger execution ──────────────────────────────────────────
        _section(f"API CALL 2 — POST /executions  (trigger execution)")
        print(f"  Payload: workflow_id={workflow_id}")
        print(f"           trigger   ={json.dumps(TRIGGER_PAYLOAD)}")

        exec_resp = _post(
            base_url, headers, "/executions",
            {"workflow_id": workflow_id, "payload": TRIGGER_PAYLOAD},
        )
        execution_id = exec_resp["data"]["id"]
        print(f"\n  Response  : {exec_resp['message']}")
        print(f"  Execution : id={execution_id}")

        # ── Poll until done ────────────────────────────────────────────────────
        print("\n  Waiting for execution to complete...")
        execution = _poll_execution(base_url, headers, execution_id)

        # Fetch step states
        steps_resp = _get(base_url, headers, f"/executions/{execution_id}/steps")
        execution["steps"] = steps_resp["data"]

        # Give logs a moment to flush before stopping the server
        time.sleep(0.3)

        # Collect all server stdout (logger writes to stdout via console_handler)
        server_proc.terminate()
        raw_output, _ = server_proc.communicate(timeout=3)
        server_lines = raw_output.decode(errors="replace").splitlines() if raw_output else []

        # ── Display formatted summary ──────────────────────────────────────────
        _display_summary(workflow, execution, TRIGGER_PAYLOAD, server_lines)

    finally:
        if server_proc and server_proc.poll() is None:
            server_proc.terminate()
            server_proc.wait(timeout=3)
        # Clean up temp DB
        try:
            os.unlink(db_path)
        except OSError:
            pass


if __name__ == "__main__":
    run_demo()
