# Workflow Orchestrator — Task Tracker

## Task: Initial Project Build

1. [x] Create folder structure and empty files
2. [x] Generate config.py, app.py, utils/, database/schema.sql, requirements.txt
3. [x] Generate routes (workflow_routes, execution_routes, step_routes)
4. [x] Generate models (workflow_model, execution_model, step_state_model)
5. [x] Generate services (workflow_service, execution_service, scheduler_service, compensation_service)
6. [x] Generate tests (conftest + 4 service test files)

---

## Task: Order Placement + Inventory Removal Demo (demo_order.py)

1. [~] Add `place_order` and `remove_inventory` local step handlers to SchedulerService
2. [ ] Create demo_order.py — starts Flask, registers workflow via API, triggers execution via API
3. [ ] Show formatted step summary and execution logs
