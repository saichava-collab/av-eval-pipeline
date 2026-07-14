package db

import (
	"context"
	"fmt"
	"os"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"

	"av-eval-pipeline/go-service/internal/models"
)

type Store struct {
	Pool *pgxpool.Pool
}

// New opens a pooled connection to Postgres. Pool sizing is what allows the
// service to sustain parallel evaluation runs across many scenario variants
// without connection contention.
func New(ctx context.Context) (*Store, error) {
	dsn := os.Getenv("DATABASE_URL")
	if dsn == "" {
		dsn = "postgres://av_user:av_pass@localhost:5432/av_eval?sslmode=disable"
	}

	cfg, err := pgxpool.ParseConfig(dsn)
	if err != nil {
		return nil, fmt.Errorf("parsing dsn: %w", err)
	}
	cfg.MaxConns = 20
	cfg.MinConns = 2
	cfg.MaxConnLifetime = time.Hour
	cfg.MaxConnIdleTime = 15 * time.Minute

	pool, err := pgxpool.NewWithConfig(ctx, cfg)
	if err != nil {
		return nil, fmt.Errorf("connecting to postgres: %w", err)
	}
	if err := pool.Ping(ctx); err != nil {
		return nil, fmt.Errorf("pinging postgres: %w", err)
	}
	return &Store{Pool: pool}, nil
}

func (s *Store) Close() {
	s.Pool.Close()
}

// InsertRuns bulk-inserts scenario run results using pgx's CopyFrom, which
// is materially faster than row-by-row INSERTs when ingesting thousands of
// simulated variant results per batch.
func (s *Store) InsertRuns(ctx context.Context, runs []models.ScenarioRun) (int64, error) {
	rows := make([][]interface{}, 0, len(runs))
	for _, r := range runs {
		rows = append(rows, []interface{}{
			r.ScenarioID,
			r.VariantID,
			r.ModelVersion,
			r.Status,
			r.MinTTCSeconds,
			r.LaneDeviationMeters,
			r.CollisionDetected,
			r.ComfortScore,
			r.LatencyMs,
			r.FailureReason,
		})
	}

	copyCount, err := s.Pool.CopyFrom(
		ctx,
		[]string{"scenario_runs"},
		[]string{
			"scenario_id", "variant_id", "model_version", "status",
			"min_ttc_seconds", "lane_deviation_meters", "collision_detected",
			"comfort_score", "latency_ms", "failure_reason",
		},
		CopyFromRows(rows),
	)
	return copyCount, err
}

// CopyFromRows adapts a [][]interface{} into pgx's CopyFromSource interface.
type copyFromRows struct {
	rows [][]interface{}
	idx  int
}

func CopyFromRows(rows [][]interface{}) *copyFromRows {
	return &copyFromRows{rows: rows, idx: -1}
}

func (c *copyFromRows) Next() bool {
	c.idx++
	return c.idx < len(c.rows)
}

func (c *copyFromRows) Values() ([]interface{}, error) {
	return c.rows[c.idx], nil
}

func (c *copyFromRows) Err() error {
	return nil
}

// ScenarioSummaries returns pass/fail aggregates per scenario. Backed by the
// (scenario_id, status) composite index, this is the query that must stay
// under the 150ms P95 target even with millions of accumulated rows.
func (s *Store) ScenarioSummaries(ctx context.Context) ([]models.ScenarioSummary, error) {
	query := `
		SELECT
			sc.scenario_id,
			sc.scenario_name,
			sc.category,
			COUNT(sr.run_id) AS total,
			COUNT(*) FILTER (WHERE sr.status = 'PASS') AS pass_count,
			COUNT(*) FILTER (WHERE sr.status = 'FAIL') AS fail_count,
			COUNT(*) FILTER (WHERE sr.status = 'ERROR') AS error_count
		FROM scenarios sc
		LEFT JOIN scenario_runs sr ON sr.scenario_id = sc.scenario_id
		GROUP BY sc.scenario_id, sc.scenario_name, sc.category
		ORDER BY sc.scenario_id;
	`
	rows, err := s.Pool.Query(ctx, query)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var out []models.ScenarioSummary
	for rows.Next() {
		var sm models.ScenarioSummary
		if err := rows.Scan(&sm.ScenarioID, &sm.ScenarioName, &sm.Category, &sm.Total, &sm.PassCount, &sm.FailCount, &sm.ErrorCount); err != nil {
			return nil, err
		}
		if sm.Total > 0 {
			sm.PassRate = float64(sm.PassCount) / float64(sm.Total) * 100
		}
		out = append(out, sm)
	}
	return out, rows.Err()
}

// RecentRuns returns the most recent N runs, optionally filtered by scenario
// or status, for the dashboard's detail table.
func (s *Store) RecentRuns(ctx context.Context, scenarioID, status string, limit int) ([]models.ScenarioRun, error) {
	query := `
		SELECT scenario_id, variant_id, model_version, status,
		       min_ttc_seconds, lane_deviation_meters, collision_detected,
		       comfort_score, latency_ms, failure_reason, executed_at
		FROM scenario_runs
		WHERE ($1 = '' OR scenario_id = $1)
		  AND ($2 = '' OR status = $2)
		ORDER BY executed_at DESC
		LIMIT $3;
	`
	rows, err := s.Pool.Query(ctx, query, scenarioID, status, limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var out []models.ScenarioRun
	for rows.Next() {
		var r models.ScenarioRun
		if err := rows.Scan(&r.ScenarioID, &r.VariantID, &r.ModelVersion, &r.Status,
			&r.MinTTCSeconds, &r.LaneDeviationMeters, &r.CollisionDetected,
			&r.ComfortScore, &r.LatencyMs, &r.FailureReason, &r.ExecutedAt); err != nil {
			return nil, err
		}
		out = append(out, r)
	}
	return out, rows.Err()
}
