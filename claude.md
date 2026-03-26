# CLAUDE.md — Project Guidelines for Flask + SQLite3 Application

You are a staff software engineer with expertise in building platform systems in python.


## Project Overview

This repository implements a Python 3 workflow orchestrator using **Flask** and **SQLite3**.
It accepts workflow triggers via **HTTP APIs**, executes configured workflows (DAGs with branching, retries, and timeouts), persists durable execution state, and supports compensatory actions on failures.

## README (Project Summary)

The platform’s purpose is to provide a durable, debuggable workflow execution system:

1. **Workflow Definition Engine**: workflows are defined as configuration (a DAG of steps), forming the contract between service teams and the platform.
2. **Scheduler & Dispatcher**: turns an execution request into ordered step dispatching (respecting branching).
3. **Durable State Tracking**: stores step completion/failure and intermediate outputs so execution can be audited and debugged.
4. **Compensation for Failures**: supports compensatory actions when a step fails.
5. **Observability**: uses centralized logging to enable faster debugging.

### Key Architectural Contract

The codebase uses a strict layered architecture:

```
Routes (API layer)
  ↓
Services (Business logic layer)
  ↓
Models (Data access layer)
  ↓
SQLite3 Database
```

<!-- For the full architecture and design decisions narrative, see `docs/README.md`. -->

Follow every instruction in this file strictly. Do not deviate or assume anything not explicitly stated here.

---

## Architecture: Layered Structure

The project follows a strict layered architecture. Each layer only communicates with the layer directly below it.

```
Routes (API layer)
  ↓
Services (Business logic layer)
  ↓
Models (Data access layer)
  ↓
SQLite3 Database
```

### Layer Rules

- **Routes** call **Services**. Routes never call Models or the database directly.
- **Services** call **Models**. Services never import from Routes.
- **Models** interact with the database. Models never import from Services or Routes.
- No layer may import from a layer above it. This prevents circular dependencies.
- If a new dependency direction is needed, stop and ask the user how to proceed.

### Folder Structure

```
project_root/
├── CLAUDE.md
├── TASKS.md              # Task planning and status tracking
├── app.py                # Flask app factory and initialization
├── config.py             # App configuration
├── routes/
│   ├── __init__.py
│   └── <resource>_routes.py
├── services/
│   ├── __init__.py
│   └── <resource>_service.py
├── models/
│   ├── __init__.py
│   └── <resource>_model.py
├── utils/
│   ├── __init__.py
│   ├── response.py       # Structured API response helper
│   ├── logger.py         # Centralized logging setup
│   └── auth.py           # Authentication and authorization helpers
├── tests/
│   ├── __init__.py
│   └── test_<resource>_service.py
├── database/
│   └── schema.sql        # SQL schema definitions
└── requirements.txt
```

---

## Task Planning and Tracking

Before starting any task:

1. Open (or create) `TASKS.md` in the project root.
2. Write a brief plan with numbered steps for what you will do.
3. Mark each step with a status as you work:
   - `[ ]` — not started
   - `[~]` — in progress
   - `[x]` — done
   - `[!]` — blocked (add reason)
4. Update the status in `TASKS.md` after completing each step.

Example:

```markdown
## Task: Add user registration endpoint

1. [x] Define User model in models/user_model.py
2. [x] Write UserService.register() in services/user_service.py
3. [~] Add POST /register route in routes/user_routes.py
4. [ ] Write 3+ tests for UserService.register()
5. [ ] Update TASKS.md with final status
```

---

## Coding Standards

### General

- Write simple, readable code. Prefer the straightforward approach first.
- Follow PEP 8 style guidelines.
- Use type hints for all function signatures.
- Write docstrings for every public function and class.
- Keep functions short and single-purpose.
- Use snake_case for variables and functions, PascalCase for classes.
- Never use wildcard imports (`from x import *`).

### Flask Routes

- Each route file registers a Blueprint.
- Routes handle HTTP concerns only: parse request, call a service, return a response.
- Always use the `utils/response.py` helper for consistent JSON output.
- Keep route functions thin — no business logic in routes.

```python
# Example route pattern
from flask import Blueprint, request
from services.user_service import UserService
from utils.response import success_response, error_response

user_bp = Blueprint("users", __name__, url_prefix="/users")

@user_bp.route("/", methods=["GET"])
def get_users():
    users = UserService.get_all()
    return success_response(data=users)
```

### Services

- Each service is a class with static or class methods.
- All business logic lives here.
- Services validate inputs and raise exceptions on failure.
- Services return plain data (dicts, lists, primitives) — not Flask Response objects.

```python
# Example service pattern
from models.user_model import UserModel

class UserService:
    @staticmethod
    def get_all() -> list[dict]:
        """Retrieve all users."""
        return UserModel.find_all()
```

### Models

- Each model handles all SQL queries for its resource.
- Use parameterized queries to prevent SQL injection. Never use f-strings or string concatenation for SQL.
- Return plain Python data structures (dicts, lists), not raw cursor objects.
- Close connections and cursors properly using context managers or try/finally.

```python
# Example model pattern
import sqlite3
from typing import Optional

DATABASE = "app.db"

class UserModel:
    @staticmethod
    def find_all() -> list[dict]:
        """Fetch all users from the database."""
        conn = sqlite3.connect(DATABASE)
        conn.row_factory = sqlite3.Row
        try:
            cursor = conn.execute("SELECT * FROM users")
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()
```

---

## Required Utilities (utils/)

### utils/response.py — Structured Responses

All API responses must follow this structure:

```json
{
  "success": true,
  "data": { ... },
  "message": "optional message",
  "errors": null
}
```

Provide at minimum these helpers:

- `success_response(data, message, status_code)` — returns a Flask JSON response with success=True.
- `error_response(message, errors, status_code)` — returns a Flask JSON response with success=False.

### utils/logger.py — Logging

- Set up a centralized logger using Python's `logging` module.
- Provide a `get_logger(name)` function that returns a configured logger.
- Log to both console and a file (`app.log`).
- Use appropriate log levels: DEBUG, INFO, WARNING, ERROR.

### utils/auth.py — Authentication

- Provide a decorator or helper for protecting routes.
- The exact auth mechanism (token-based, session-based, etc.) must be decided with the user before implementation. Do not assume one.

---

## Testing Requirements

- Every service method that contains business logic must have **at least 3 test cases**.
- Use `pytest` as the test runner.
- Tests go in the `tests/` folder, one test file per service.
- Test files are named `test_<resource>_service.py`.
- Tests must cover: a happy path, an edge case, and a failure/error case at minimum.
- Use a separate test database or in-memory SQLite (`:memory:`) for tests. Never test against the production database.

```python
# Example test pattern
import pytest
from services.user_service import UserService

class TestUserService:
    def test_get_all_returns_list(self, setup_db):
        result = UserService.get_all()
        assert isinstance(result, list)

    def test_get_all_empty_database(self, empty_db):
        result = UserService.get_all()
        assert result == []

    def test_get_all_returns_correct_fields(self, setup_db):
        result = UserService.get_all()
        assert "id" in result[0]
        assert "name" in result[0]
```

---

## Decision-Making Rules

1. **Do not assume anything.** If a requirement is unclear — what auth method to use, what a field should be named, what the expected behavior is — ask the user before writing code.
2. **Simple first.** Always implement the simplest working solution. Do not add abstractions, patterns, or dependencies unless the user asks for them.
3. **Multiple approaches? Ask.** If there are two or more reasonable ways to implement something, briefly list the options with one-line tradeoffs and ask the user which to pick. Do not choose on their behalf.
4. **No extra dependencies.** Only add packages to `requirements.txt` when they are clearly needed. Prefer the standard library when it covers the use case.

---

## Workflow Checklist (follow for every task)

1. Read and understand the request fully.
2. Create or update `TASKS.md` with a step-by-step plan.
3. Implement changes one step at a time, updating task status after each.
4. Ensure no circular imports — routes → services → models only.
5. Write or update tests (minimum 3 per service method with logic).
6. Verify the structured response format is used on all endpoints.
7. Mark the task complete in `TASKS.md`.