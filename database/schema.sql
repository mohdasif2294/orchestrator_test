-- Workflow definitions: immutable versioned contracts
CREATE TABLE IF NOT EXISTS workflows (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    description TEXT,
    version     INTEGER NOT NULL DEFAULT 1,
    status      TEXT NOT NULL DEFAULT 'active',   -- active | archived
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

-- Individual step definitions within a workflow (DAG nodes + edges)
CREATE TABLE IF NOT EXISTS workflow_steps (
    id                  TEXT PRIMARY KEY,
    workflow_id         TEXT NOT NULL REFERENCES workflows(id),
    step_key            TEXT NOT NULL,              -- unique name within a workflow
    step_type           TEXT NOT NULL,              -- http | noop
    config              TEXT NOT NULL,              -- JSON: url, method, headers, payload_template
    depends_on          TEXT NOT NULL DEFAULT '[]', -- JSON array of step_key strings (DAG edges)
    branch_condition    TEXT,                       -- JSON condition object or NULL (always run)
    retry_max           INTEGER NOT NULL DEFAULT 0,
    retry_delay_seconds INTEGER NOT NULL DEFAULT 5,
    timeout_seconds     INTEGER NOT NULL DEFAULT 30,
    compensation_config TEXT,                       -- JSON: undo action config or NULL
    position            INTEGER NOT NULL,           -- display order hint
    UNIQUE(workflow_id, step_key)
);

-- A single run of a workflow
CREATE TABLE IF NOT EXISTS executions (
    id               TEXT PRIMARY KEY,
    workflow_id      TEXT NOT NULL REFERENCES workflows(id),
    workflow_version INTEGER NOT NULL,
    status           TEXT NOT NULL DEFAULT 'pending',
    -- pending | running | completed | failed | compensating | compensated | deleted
    trigger_payload  TEXT NOT NULL DEFAULT '{}',    -- JSON input at trigger time
    output           TEXT,                          -- JSON final output
    error_message    TEXT,
    started_at       TEXT,
    completed_at     TEXT,
    created_at       TEXT NOT NULL
);

-- Durable state of each step within an execution
CREATE TABLE IF NOT EXISTS step_states (
    id             TEXT PRIMARY KEY,
    execution_id   TEXT NOT NULL REFERENCES executions(id),
    step_key       TEXT NOT NULL,
    status         TEXT NOT NULL DEFAULT 'pending',
    -- pending | running | completed | failed | skipped | compensating | compensated
    attempt_number INTEGER NOT NULL DEFAULT 0,
    input          TEXT,    -- JSON input passed to this step
    output         TEXT,    -- JSON output captured from step
    error_message  TEXT,
    started_at     TEXT,
    completed_at   TEXT,
    UNIQUE(execution_id, step_key)
);
