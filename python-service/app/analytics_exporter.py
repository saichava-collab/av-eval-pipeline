"""
Exports evaluated scenario-run batches to BigQuery and Redshift for
large-scale historical analytics (trend tracking, regression detection
across model versions, dimensional slicing by scenario category/difficulty).

PostgreSQL (see db.py in go-service) stays the low-latency operational
store the dashboard queries live. BigQuery/Redshift hold the full
historical corpus for ad-hoc SQL analytics and BI tooling.

Both exporters are optional and credential-gated: if the relevant
environment variables aren't set, the exporter falls back to writing a
local CSV/JSON so the pipeline still runs end to end on a laptop with no
cloud accounts configured. Wire up real credentials to switch it on.
"""
import csv
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from app.evaluator import EvaluationResult

LOCAL_EXPORT_DIR = Path(os.getenv("LOCAL_EXPORT_DIR", "/tmp/av-eval-exports"))
LOCAL_EXPORT_DIR.mkdir(parents=True, exist_ok=True)


def _rows_as_dicts(results: Iterable[EvaluationResult]) -> list[dict]:
    now = datetime.now(timezone.utc).isoformat()
    return [
        {
            "scenario_id": r.scenario_id,
            "variant_id": r.variant_id,
            "model_version": r.model_version,
            "status": r.status,
            "min_ttc_seconds": r.min_ttc_seconds,
            "lane_deviation_meters": r.lane_deviation_meters,
            "collision_detected": r.collision_detected,
            "comfort_score": r.comfort_score,
            "latency_ms": r.latency_ms,
            "failure_reason": r.failure_reason,
            "exported_at": now,
        }
        for r in results
    ]


def _local_fallback(results: list[dict], destination: str) -> str:
    fname = LOCAL_EXPORT_DIR / f"{destination}_{datetime.now().strftime('%Y%m%dT%H%M%S')}.csv"
    with open(fname, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(results[0].keys()))
        writer.writeheader()
        writer.writerows(results)
    return str(fname)


def export_to_bigquery(results: list[EvaluationResult]) -> str:
    """Streams evaluated rows into a BigQuery table for large-scale
    scenario analytics. Requires GOOGLE_APPLICATION_CREDENTIALS and
    BIGQUERY_DATASET/BIGQUERY_TABLE env vars; falls back to a local CSV
    otherwise so the demo still runs without a GCP project."""
    rows = _rows_as_dicts(results)

    creds = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    dataset = os.getenv("BIGQUERY_DATASET")
    table = os.getenv("BIGQUERY_TABLE", "scenario_runs")
    project = os.getenv("BIGQUERY_PROJECT")

    if not (creds and dataset and project):
        path = _local_fallback(rows, "bigquery")
        return f"[local-fallback] wrote {len(rows)} rows to {path} (set GOOGLE_APPLICATION_CREDENTIALS, BIGQUERY_PROJECT, BIGQUERY_DATASET to export for real)"

    from google.cloud import bigquery  # imported lazily so the dependency is optional at runtime

    client = bigquery.Client(project=project)
    table_ref = f"{project}.{dataset}.{table}"
    errors = client.insert_rows_json(table_ref, rows)
    if errors:
        raise RuntimeError(f"BigQuery insert errors: {errors}")
    return f"inserted {len(rows)} rows into {table_ref}"


def export_to_redshift(results: list[EvaluationResult]) -> str:
    """Bulk-loads evaluated rows into Redshift for warehouse-side
    analytics (joins against fleet/telemetry data, longer retention).
    Requires REDSHIFT_HOST/PORT/DATABASE/USER/PASSWORD; falls back to a
    local CSV otherwise."""
    rows = _rows_as_dicts(results)

    host = os.getenv("REDSHIFT_HOST")
    database = os.getenv("REDSHIFT_DATABASE")
    user = os.getenv("REDSHIFT_USER")
    password = os.getenv("REDSHIFT_PASSWORD")
    port = int(os.getenv("REDSHIFT_PORT", "5439"))
    table = os.getenv("REDSHIFT_TABLE", "scenario_runs")

    if not (host and database and user and password):
        path = _local_fallback(rows, "redshift")
        return f"[local-fallback] wrote {len(rows)} rows to {path} (set REDSHIFT_HOST/DATABASE/USER/PASSWORD to export for real)"

    import redshift_connector  # imported lazily so the dependency is optional at runtime

    conn = redshift_connector.connect(host=host, database=database, user=user, password=password, port=port)
    try:
        cursor = conn.cursor()
        cursor.execute(f"""
            CREATE TABLE IF NOT EXISTS {table} (
                scenario_id VARCHAR(64),
                variant_id VARCHAR(64),
                model_version VARCHAR(64),
                status VARCHAR(16),
                min_ttc_seconds FLOAT8,
                lane_deviation_meters FLOAT8,
                collision_detected BOOLEAN,
                comfort_score FLOAT8,
                latency_ms FLOAT8,
                failure_reason VARCHAR(256),
                exported_at TIMESTAMP
            );
        """)
        insert_sql = f"""
            INSERT INTO {table}
            (scenario_id, variant_id, model_version, status, min_ttc_seconds,
             lane_deviation_meters, collision_detected, comfort_score,
             latency_ms, failure_reason, exported_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        values = [
            (r["scenario_id"], r["variant_id"], r["model_version"], r["status"],
             r["min_ttc_seconds"], r["lane_deviation_meters"], r["collision_detected"],
             r["comfort_score"], r["latency_ms"], r["failure_reason"], r["exported_at"])
            for r in rows
        ]
        cursor.executemany(insert_sql, values)
        conn.commit()
        return f"inserted {len(rows)} rows into Redshift table {table}"
    finally:
        conn.close()
