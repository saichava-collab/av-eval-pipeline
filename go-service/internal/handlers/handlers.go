package handlers

import (
	"context"
	"encoding/json"
	"log"
	"net/http"
	"strconv"
	"time"

	"av-eval-pipeline/go-service/internal/db"
	"av-eval-pipeline/go-service/internal/models"
)

type API struct {
	Store *db.Store
}

func NewAPI(store *db.Store) *API {
	return &API{Store: store}
}

func writeJSON(w http.ResponseWriter, status int, v interface{}) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(v)
}

func writeErr(w http.ResponseWriter, status int, msg string) {
	writeJSON(w, status, map[string]string{"error": msg})
}

// Health is a simple liveness probe used by Docker/ECS health checks.
func (a *API) Health(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, http.StatusOK, map[string]string{"status": "ok"})
}

// IngestRuns accepts a batch of scenario run results from the Python
// evaluation workers and bulk-inserts them via CopyFrom.
func (a *API) IngestRuns(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		writeErr(w, http.StatusMethodNotAllowed, "POST only")
		return
	}

	var req models.IngestRequest

	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeErr(w, http.StatusBadRequest, "invalid JSON body: "+err.Error())
		return
	}
	if len(req.Runs) == 0 {
		writeErr(w, http.StatusBadRequest, "runs array is empty")
		return
	}

	ctx, cancel := context.WithTimeout(r.Context(), 30*time.Second)
	defer cancel()

	n, err := a.Store.InsertRuns(ctx, req.Runs)
	if err != nil {
		log.Printf("insert error: %v", err)
		writeErr(w, http.StatusInternalServerError, "failed to ingest runs")
		return
	}

	writeJSON(w, http.StatusCreated, map[string]interface{}{
		"batch_id":     req.BatchID,
		"rows_ingested": n,
	})
}

// Summary returns per-scenario pass/fail aggregates for the dashboard.
func (a *API) Summary(w http.ResponseWriter, r *http.Request) {
	ctx, cancel := context.WithTimeout(r.Context(), 5*time.Second)
	defer cancel()

	start := time.Now()
	summaries, err := a.Store.ScenarioSummaries(ctx)
	elapsed := time.Since(start)

	if err != nil {
		log.Printf("summary query error: %v", err)
		writeErr(w, http.StatusInternalServerError, "failed to query summaries")
		return
	}

	w.Header().Set("X-Query-Latency-Ms", strconv.FormatFloat(float64(elapsed.Microseconds())/1000.0, 'f', 2, 64))
	writeJSON(w, http.StatusOK, summaries)
}

// Runs returns recent run rows, filterable by scenario_id and status.
func (a *API) Runs(w http.ResponseWriter, r *http.Request) {
	scenarioID := r.URL.Query().Get("scenario_id")
	status := r.URL.Query().Get("status")
	limit := 100
	if l := r.URL.Query().Get("limit"); l != "" {
		if parsed, err := strconv.Atoi(l); err == nil && parsed > 0 && parsed <= 5000 {
			limit = parsed
		}
	}

	ctx, cancel := context.WithTimeout(r.Context(), 5*time.Second)
	defer cancel()

	start := time.Now()
	runs, err := a.Store.RecentRuns(ctx, scenarioID, status, limit)
	elapsed := time.Since(start)

	if err != nil {
		log.Printf("runs query error: %v", err)
		writeErr(w, http.StatusInternalServerError, "failed to query runs")
		return
	}

	w.Header().Set("X-Query-Latency-Ms", strconv.FormatFloat(float64(elapsed.Microseconds())/1000.0, 'f', 2, 64))
	writeJSON(w, http.StatusOK, runs)
}
