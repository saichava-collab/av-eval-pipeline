package models

import "time"

// ScenarioRun represents a single simulated scenario-variant execution
// result as produced by the Python evaluation workers.
type ScenarioRun struct {
	ScenarioID          string    `json:"scenario_id"`
	VariantID           string    `json:"variant_id"`
	ModelVersion        string    `json:"model_version"`
	Status              string    `json:"status"` // PASS | FAIL | ERROR
	MinTTCSeconds       *float64  `json:"min_ttc_seconds,omitempty"`
	LaneDeviationMeters *float64  `json:"lane_deviation_meters,omitempty"`
	CollisionDetected   bool      `json:"collision_detected"`
	ComfortScore        *float64  `json:"comfort_score,omitempty"`
	LatencyMs           *float64  `json:"latency_ms,omitempty"`
	FailureReason       *string   `json:"failure_reason,omitempty"`
	ExecutedAt          time.Time `json:"executed_at,omitempty"`
}

// IngestRequest is the batch payload posted by evaluation workers. Batching
// (rather than one row per HTTP call) is what lets 10,000+ variants be
// ingested per run without overwhelming the connection pool.
type IngestRequest struct {
	BatchID string        `json:"batch_id"`
	Runs    []ScenarioRun `json:"runs"`
}

// ScenarioSummary is the aggregate pass/fail view the dashboard renders.
type ScenarioSummary struct {
	ScenarioID   string  `json:"scenario_id"`
	ScenarioName string  `json:"scenario_name"`
	Category     string  `json:"category"`
	Total        int     `json:"total"`
	PassCount    int     `json:"pass_count"`
	FailCount    int     `json:"fail_count"`
	ErrorCount   int     `json:"error_count"`
	PassRate     float64 `json:"pass_rate"`
}

// BatchStatus reports on an in-flight or completed evaluation batch.
type BatchStatus struct {
	BatchID            string     `json:"batch_id"`
	TotalVariants       int        `json:"total_variants"`
	PassCount           int        `json:"pass_count"`
	FailCount           int        `json:"fail_count"`
	ErrorCount          int        `json:"error_count"`
	StartedAt           time.Time  `json:"started_at"`
	CompletedAt         *time.Time `json:"completed_at,omitempty"`
	P95QueryLatencyMs   *float64   `json:"p95_query_latency_ms,omitempty"`
}
