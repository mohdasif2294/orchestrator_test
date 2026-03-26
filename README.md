# Workflow Orchestrator

A durable workflow execution platform built with **Python 3**, **Flask**, and **SQLite3**.

Service teams define workflows as DAG configs (steps with branching, retries, timeouts, and compensations). The platform accepts execution triggers via HTTP API, dispatches steps in dependency order, persists all state durably, and automatically rolls back completed steps on failure (saga pattern).

---

## Features

| Feature | Description |
|---------|-------------|
| **Workflow Definition Engine** | DAGs defined as JSON config — versioned, validated, stored |
| **Scheduler & Dispatcher** | Topological step dispatch, branch conditions, fan-in/fan-out |
| **Durable State Tracking** | Every step's status, input, output, and error persisted in SQLite |
| **HTTP API Triggers** | REST endpoints to register workflows, trigger and inspect executions |
| **Compensation (Saga)** | Automatic rollback of completed steps in reverse order on failure |
| **Centralized Logging** | Structured logs to console and `app.log` for fast debugging |
| **Local Step Type** | In-process step execution for demos and testing without HTTP targets |

---

## Architecture

```
Routes (API layer)
  ↓
Services (Business logic layer)
  ↓
Models (Data access layer)
  ↓
SQLite3 Database
```

Each layer communicates only with the layer directly below it. No circular imports.

---

## Project Structure

```
pocket_interview/
├── app.py                      # Flask factory, blueprint registration, DB init
├── config.py                   # Configuration (DATABASE, API_KEY, host/port)
├── requirements.txt
├── demo.py                     # Demo: Service A — print message + random number
├── demo_order.py               # Demo: Order placement + inventory removal via HTTP API
│
├── database/
│   └── schema.sql              # SQLite table definitions
│
├── routes/
│   ├── workflow_routes.py      # POST/GET/PUT/DELETE /workflows
│   ├── execution_routes.py     # POST/GET /executions, cancel, delete
│   └── step_routes.py          # GET /executions/<id>/steps, manual retry
│
├── services/
│   ├── workflow_service.py     # DAG validation + workflow CRUD
│   ├── execution_service.py    # Trigger, status, cancel, delete
│   ├── scheduler_service.py    # DAG traversal, step dispatch (core brain)
│   └── compensation_service.py # Saga rollback
│
├── models/
│   ├── __init__.py             # Shared get_conn() helper
│   ├── workflow_model.py       # workflows + workflow_steps tables
│   ├── execution_model.py      # executions table
│   └── step_state_model.py     # step_states table
│
├── utils/
│   ├── response.py             # success_response / error_response helpers
│   ├── logger.py               # get_logger(name) → console + app.log
│   └── auth.py                 # @require_api_key decorator
│
└── tests/
    ├── conftest.py             # In-memory DB fixtures, shared helpers
    ├── test_workflow_service.py
    ├── test_execution_service.py
    ├── test_scheduler_service.py
    └── test_compensation_service.py
```

---

## Setup

**Requirements:** Python 3.11+

```bash
# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Run the server
python app.py
```

The server starts at `http://localhost:5000`. The SQLite database (`app.db`) and log file (`app.log`) are created automatically on first run.

---

## Configuration

All settings are environment-variable driven with development defaults:

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_PATH` | `app.db` | Path to the SQLite database file |
| `API_KEY` | `dev-secret-key` | Value expected in `X-API-Key` header |
| `FLASK_DEBUG` | `true` | Enable Flask debug mode |
| `FLASK_HOST` | `0.0.0.0` | Host to bind |
| `FLASK_PORT` | `5000` | Port to listen on |

---

## Authentication

All endpoints require an `X-API-Key` header:

```bash
curl -H "X-API-Key: dev-secret-key" http://localhost:5000/workflows
```

---

## API Reference

### Workflows

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/workflows` | Register a new workflow |
| `GET` | `/workflows` | List all active workflows |
| `GET` | `/workflows/<id>` | Get workflow + steps |
| `PUT` | `/workflows/<id>` | Update workflow (bumps version) |
| `DELETE` | `/workflows/<id>` | Archive workflow (soft delete) |

### Executions

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/executions` | Trigger an execution |
| `GET` | `/executions` | List executions (`?workflow_id=<id>` to filter) |
| `GET` | `/executions/<id>` | Get execution + all step states |
| `POST` | `/executions/<id>/cancel` | Cancel a running execution |
| `DELETE` | `/executions/<id>` | Soft delete an execution |

### Steps

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/executions/<id>/steps` | List all step states |
| `POST` | `/executions/<id>/steps/<key>/retry` | Manually retry a failed step |

### Response Envelope

All responses follow this structure:

```json
{
  "success": true,
  "data": { ... },
  "message": "optional message",
  "errors": null
}
```

---

## Workflow Definition Format

```json
{
  "name": "order_fulfillment",
  "description": "End-to-end order processing",
  "steps": [
    {
      "step_key": "validate_order",
      "step_type": "http",
      "config": {
        "url": "https://internal.svc/orders/validate",
        "method": "POST",
        "payload_template": { "order_id": "{{trigger.order_id}}" }
      },
      "depends_on": [],
      "retry_max": 3,
      "retry_delay_seconds": 2,
      "timeout_seconds": 10,
      "compensation_config": null
    },
    {
      "step_key": "charge_payment",
      "step_type": "http",
      "config": {
        "url": "https://internal.svc/payments/charge",
        "method": "POST",
        "payload_template": {
          "order_id": "{{trigger.order_id}}",
          "amount": "{{steps.validate_order.output.total}}"
        }
      },
      "depends_on": ["validate_order"],
      "branch_condition": { "source": "steps.validate_order.output.approved", "eq": true },
      "retry_max": 1,
      "timeout_seconds": 20,
      "compensation_config": {
        "url": "https://internal.svc/payments/refund",
        "method": "POST",
        "payload_template": { "payment_id": "{{steps.charge_payment.output.payment_id}}" }
      }
    }
  ]
}
```

**Key fields:**

| Field | Description |
|-------|-------------|
| `step_key` | Unique name within the workflow (used in `depends_on` and template refs) |
| `step_type` | `http` — makes an HTTP call; `local` — runs in-process |
| `depends_on` | List of `step_key` values that must complete before this step runs |
| `branch_condition` | `{"source": "path.to.value", "eq": <expected>}` — skips step if false |
| `payload_template` | `{{trigger.*}}` and `{{steps.<key>.output.*}}` placeholders |
| `retry_max` | Number of retry attempts after the first failure (0 = no retry) |
| `timeout_seconds` | Per-attempt timeout for HTTP steps |
| `compensation_config` | Undo action run if a later step fails (same shape as `config`) |

---

## Execution Flow

```
POST /executions  {"workflow_id": "<id>", "payload": {...}}
  → Create execution row (status: pending → running)
  → Create one step_state row per step (status: pending)
  → SchedulerService.advance()
       → Find ready steps (all depends_on satisfied)
       → Evaluate branch conditions (skip if false)
       → Resolve payload templates from trigger + prior step outputs
       → Dispatch step (HTTP call or local action)
       → On success: mark completed → advance() again
       → On failure after retries: mark failed → trigger compensation
       → All steps done: mark execution completed
```

### Compensation (Saga)

When a step fails after all retries, the platform automatically:
1. Marks execution as `compensating`
2. Iterates all previously `completed` steps in **reverse completion order**
3. Calls each step's `compensation_config` URL (best-effort, no retry)
4. Marks execution as `compensated`

---

## Demos

### Service A — Print & Random Number

```bash
source .venv/bin/activate
python demo.py
```

Registers a two-step local workflow:
- Step 1: prints `"step 1 executed"`
- Step 2: generates a random number (1–1000)

### Order + Inventory Demo (via HTTP API)

```bash
source .venv/bin/activate
python demo_order.py
```

Starts the Flask server on port 5001, registers a workflow via the REST API, and triggers it with `{"item": "widget", "quantity": 3, "unit_price": 9.99}`:
- Step 1 (`place_order`): records order, returns `order_id` and `total`
- Step 2 (`remove_inventory`): deducts quantity from stock using Step 1's output

---

## Running Tests

```bash
source .venv/bin/activate
pytest tests/ -v
```

**70 tests** across 4 service test files. Every test runs against a fresh in-memory SQLite database — `app.db` is never touched.

```
tests/test_workflow_service.py     — 18 tests (register, DAG validation, CRUD)
tests/test_execution_service.py    — 15 tests (trigger, status, cancel, delete)
tests/test_scheduler_service.py    — 14 tests (advance, branch, templates, retry)
tests/test_compensation_service.py — 13 tests (compensate, reverse order, rollback)
```

---

## Database Schema

Four tables:

| Table | Purpose |
|-------|---------|
| `workflows` | Workflow definitions (versioned, soft-deletable) |
| `workflow_steps` | Step definitions per workflow (DAG edges stored as JSON) |
| `executions` | One row per workflow run with status and trigger payload |
| `step_states` | Durable per-step state: status, attempt count, input, output, error |

Step statuses: `pending` → `running` → `completed` / `failed` / `skipped` / `compensating` / `compensated`

Execution statuses: `pending` → `running` → `completed` / `failed` / `compensating` / `compensated` / `deleted`
