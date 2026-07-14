-- Operational store schema for the AV Evaluation & Simulation Pipeline
-- This is the low-latency read/write store the Go service queries directly.
-- BigQuery / Redshift hold the larger historical analytics copy (see python-service/app/analytics_exporter.py).

CREATE TABLE IF NOT EXISTS scenarios (
    scenario_id     VARCHAR(64) PRIMARY KEY,
    scenario_name   TEXT NOT NULL,
    category        VARCHAR(32) NOT NULL,          -- e.g. intersection, highway_merge, pedestrian_crossing
    difficulty      VARCHAR(16) NOT NULL DEFAULT 'medium',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS scenario_runs (
    run_id          BIGSERIAL PRIMARY KEY,
    scenario_id     VARCHAR(64) NOT NULL REFERENCES scenarios(scenario_id),
    variant_id      VARCHAR(64) NOT NULL,           -- one of 10,000+ simulated variants of a scenario
    model_version   VARCHAR(64) NOT NULL,
    status          VARCHAR(16) NOT NULL,           -- PASS | FAIL | ERROR
    min_ttc_seconds         DOUBLE PRECISION,        -- time-to-collision metric
    lane_deviation_meters   DOUBLE PRECISION,
    collision_detected      BOOLEAN NOT NULL DEFAULT FALSE,
    comfort_score           DOUBLE PRECISION,
    latency_ms              DOUBLE PRECISION,        -- planner/perception latency recorded during sim
    failure_reason          TEXT,
    executed_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Indexes chosen specifically to support the query patterns behind the
-- sub-150ms P95 dashboard queries: filter by scenario, by status, and
-- time-windowed aggregation.
CREATE INDEX IF NOT EXISTS idx_runs_scenario_id   ON scenario_runs (scenario_id);
CREATE INDEX IF NOT EXISTS idx_runs_status         ON scenario_runs (status);
CREATE INDEX IF NOT EXISTS idx_runs_executed_at    ON scenario_runs (executed_at DESC);
CREATE INDEX IF NOT EXISTS idx_runs_scenario_status ON scenario_runs (scenario_id, status);

CREATE TABLE IF NOT EXISTS evaluation_batches (
    batch_id        UUID PRIMARY KEY,
    triggered_by     VARCHAR(64),
    total_variants   INT NOT NULL,
    pass_count       INT NOT NULL DEFAULT 0,
    fail_count       INT NOT NULL DEFAULT 0,
    error_count      INT NOT NULL DEFAULT 0,
    started_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at     TIMESTAMPTZ,
    p95_query_latency_ms DOUBLE PRECISION
);

-- Seed a handful of scenario categories so the pipeline has something to
-- reference immediately after `docker compose up`.
INSERT INTO scenarios (scenario_id, scenario_name, category, difficulty) VALUES
    ('SC-001', 'Unprotected Left Turn at Intersection', 'intersection', 'hard'),
    ('SC-002', 'Highway Merge Under Heavy Traffic', 'highway_merge', 'medium'),
    ('SC-003', 'Pedestrian Crossing Mid-Block', 'pedestrian_crossing', 'hard'),
    ('SC-004', 'Roundabout Multi-Lane Entry', 'roundabout', 'medium'),
    ('SC-005', 'Sudden Lead Vehicle Braking', 'car_following', 'easy'),
    ('SC-006', 'Cyclist Lane Merge', 'vulnerable_road_user', 'medium'),
    ('SC-007', 'Construction Zone Lane Shift', 'construction', 'hard'),
    ('SC-008', 'Nighttime Low-Visibility Turn', 'low_visibility', 'hard')
ON CONFLICT (scenario_id) DO NOTHING;
