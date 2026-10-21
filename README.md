# Autonomous Driving Evaluation & Simulation Pipeline

```
                     ┌─────────────────────────┐
                     │   React Dashboard        │
                     │   (pass/fail reporting)  │
                     └────────────┬─────────────┘
                                  │ REST (JSON)
                                  ▼
                     ┌─────────────────────────┐
                     │   Go Service (:8080)     │
                     │   - bulk ingest (CopyFrom)│
                     │   - summary/runs queries │
                     │   - pgx connection pool  │
                     └────────────┬─────────────┘
                                  │ SQL
                                  ▼
                     ┌─────────────────────────┐
                     │   PostgreSQL             │
                     │   (operational store)    │
                     │   indexed for <150ms P95 │
                     └─────────────────────────┘
                                  ▲
                                  │ parallel chunked ingest (HTTP)
                     ┌────────────┴─────────────┐
                     │  Python Orchestrator      │
                     │  (:8000, FastAPI)         │
                     │  - simulate scenario runs │
                     │  - evaluate pass/fail     │
                     │  - fan out ingest chunks  │
                     └────────────┬─────────────┘
                                  │
                    ┌─────────────┴─────────────┐
                    ▼                            ▼
           ┌────────────────┐          ┌───────────────────┐
           │  BigQuery       │          │  Redshift          │
           │  (analytics)    │          │  (analytics)       │
           └────────────────┘          └───────────────────┘
```

**Why this split:** Postgres stays small and heavily indexed so the
dashboard's live pass/fail queries stay fast even under continuous
ingest. BigQuery and Redshift hold the full historical corpus for
longer-retention, ad-hoc SQL analytics (trend tracking across model
versions, regression detection, dimensional slicing by scenario
category) without competing with the operational store for resources.

## Components

| Path | Responsibility |
|---|---|
| `go-service/` | Go HTTP API: bulk ingestion (`CopyFrom`), pass/fail summary queries, recent-runs queries. Backed by a `pgxpool` connection pool. |
| `python-service/` | FastAPI orchestrator: simulates scenario-variant telemetry, applies pass/fail evaluation rules, fans ingestion out in parallel chunks to the Go service, and exports evaluated batches to BigQuery/Redshift. |
| `db/init.sql` | PostgreSQL schema (`scenarios`, `scenario_runs`, `evaluation_batches`) with the indexes the query latency target depends on. |
| `dashboard/` | React (Vite) dashboard: summary cards, pass-rate-by-scenario chart, filterable recent-runs table, and a button to trigger a new evaluation batch. |
| `scripts/` | `run_large_batch.sh` to trigger a 10,000+ variant batch; `measure_p95_latency.py` to measure real P50/P95/P99 latency against the Go service. |

## Prerequisites

- Docker and Docker Compose (this is the fastest path to running everything)
- For local (non-Docker) development: Go 1.22+, Python 3.11+, Node.js 20+, PostgreSQL 16

## Quick start (Docker Compose)

```bash
git clone <this-repo>
cd av-eval-pipeline
cp .env.example .env   # optional: fill in BigQuery/Redshift creds; otherwise
                        # the pipeline falls back to local CSV exports

docker compose up --build
```

This starts:
- `postgres` on `localhost:5432`
- `go-service` on `localhost:8080`
- `python-service` on `localhost:8000`
- `dashboard` on `localhost:5173`

Open **http://localhost:5173** — you'll see the console with the seeded
scenario categories and zero runs. Click **"Run evaluation batch"** (or
set the variant count field first) to simulate scenario-variant
executions, evaluate them, ingest them, and export them to your
warehouses (or local CSV fallback).

To trigger a large parallel batch from the command line instead:

```bash
./scripts/run_large_batch.sh 10000
```

To measure real query latency against the operational store:

```bash
pip install --no-cache-dir requests  # not required; script uses stdlib only
python3 scripts/measure_p95_latency.py --requests 300 --concurrency 20
```

## Running components individually (no Docker)

### 1. PostgreSQL

```bash
createdb av_eval
psql av_eval < db/init.sql
```

### 2. Go service

```bash
cd go-service
go mod tidy
export DATABASE_URL="postgres://<user>:<pass>@localhost:5432/av_eval?sslmode=disable"
go run ./cmd/server
# listens on :8080
```

### 3. Python orchestrator

```bash
cd python-service
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export GO_SERVICE_URL="http://localhost:8080"
uvicorn app.main:app --reload --port 8000
```

### 4. React dashboard

```bash
cd dashboard
npm install
npm run dev
# open http://localhost:5173
```

## API reference

### Go service (`:8080`)

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Liveness probe |
| POST | `/api/v1/runs/ingest` | Bulk-insert evaluated scenario runs (`{batch_id, runs: [...]}`) |
| GET | `/api/v1/summary` | Per-scenario pass/fail/error aggregates. Returns `X-Query-Latency-Ms` header. |
| GET | `/api/v1/runs?scenario_id=&status=&limit=` | Recent run rows, filterable. Returns `X-Query-Latency-Ms` header. |

### Python orchestrator (`:8000`)

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Liveness probe |
| POST | `/api/v1/evaluate` | Simulate + evaluate + ingest + export a batch. Body: `{n_variants, scenario_id?, export_to_warehouse}` |

Example:

```bash
curl -X POST http://localhost:8000/api/v1/evaluate \
  -H "Content-Type: application/json" \
  -d '{"n_variants": 5000, "export_to_warehouse": true}'
```

## Connecting real BigQuery / Redshift / AWS

The analytics exporters (`python-service/app/analytics_exporter.py`) are
credential-gated: without credentials set, evaluated batches are written
to local CSVs under `/tmp/av-eval-exports` so the whole pipeline still
runs end to end with zero cloud setup. To export for real:

**BigQuery**
1. Create a GCP service account with `BigQuery Data Editor` on your dataset.
2. Set `GOOGLE_APPLICATION_CREDENTIALS`, `BIGQUERY_PROJECT`,
   `BIGQUERY_DATASET`, `BIGQUERY_TABLE` (see `.env.example`).

**Redshift**
1. Provision a Redshift cluster (or Redshift Serverless workgroup).
2. Set `REDSHIFT_HOST`, `REDSHIFT_DATABASE`, `REDSHIFT_USER`,
   `REDSHIFT_PASSWORD`, `REDSHIFT_PORT` (see `.env.example`). The table is
   created automatically on first export if it doesn't exist.

**AWS deployment shape** (for reference; not automated by this repo):
- `go-service` and `python-service` as containers on ECS Fargate (or EKS),
  each behind an internal ALB target group.
- `postgres` as RDS for PostgreSQL (Multi-AZ for production).
- Container images pushed to ECR; `docker-compose.yml` maps 1:1 to task
  definitions if you want to convert it to ECS task defs or a Helm chart.
- `dashboard` served from S3 + CloudFront, or as a small ECS service
  behind the same ALB.

## Repository layout

```
av-eval-pipeline/
├── docker-compose.yml
├── .env.example
├── db/
│   └── init.sql
├── go-service/
│   ├── cmd/server/main.go
│   ├── internal/db/db.go
│   ├── internal/handlers/handlers.go
│   ├── internal/models/models.go
│   ├── go.mod
│   └── Dockerfile
├── python-service/
│   ├── app/
│   │   ├── main.py
│   │   ├── scenario_generator.py
│   │   ├── evaluator.py
│   │   └── analytics_exporter.py
│   ├── requirements.txt
│   └── Dockerfile
├── dashboard/
│   ├── src/{App.jsx, main.jsx, index.css}
│   ├── package.json
│   └── Dockerfile
└── scripts/
    ├── run_large_batch.sh
    └── measure_p95_latency.py
```
