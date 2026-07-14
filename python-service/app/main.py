"""
Evaluation orchestrator service.

Exposes an endpoint that:
  1. Generates N synthetic scenario-variant executions (or accepts a fixed
     scenario_id to focus a run).
  2. Applies pass/fail evaluation rules.
  3. Ingests the evaluated batch into the Go service's Postgres-backed
     operational store, in parallel chunks, to exercise the
     "parallel evaluation across 10,000+ scenario variants" path.
  4. Exports the same batch to BigQuery and Redshift for large-scale
     historical analytics.
"""
import asyncio
import os
import time
import uuid
from typing import Optional

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware

from app import analytics_exporter
from app.evaluator import evaluate_batch
from app.scenario_generator import generate_batch

GO_SERVICE_URL = os.getenv("GO_SERVICE_URL", "http://localhost:8080")
INGEST_CHUNK_SIZE = int(os.getenv("INGEST_CHUNK_SIZE", "500"))
PARALLEL_CHUNKS = int(os.getenv("PARALLEL_INGEST_WORKERS", "8"))

app = FastAPI(title="AV Evaluation Orchestrator", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class RunRequest(BaseModel):
    n_variants: int = 1000
    scenario_id: Optional[str] = None
    export_to_warehouse: bool = True


class RunResponse(BaseModel):
    batch_id: str
    total_variants: int
    pass_count: int
    fail_count: int
    ingest_seconds: float
    bigquery_export: Optional[str] = None
    redshift_export: Optional[str] = None


def _chunk(items, size):
    for i in range(0, len(items), size):
        yield items[i : i + size]


async def _ingest_chunk(client: httpx.AsyncClient, batch_id: str, chunk: list) -> None:
    payload = {
        "batch_id": batch_id,
        "runs": [
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
            }
            for r in chunk
        ],
    }
    resp = await client.post(f"{GO_SERVICE_URL}/api/v1/runs/ingest", json=payload, timeout=30.0)
    resp.raise_for_status()


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/api/v1/evaluate", response_model=RunResponse)
async def run_evaluation(req: RunRequest):
    if req.n_variants <= 0 or req.n_variants > 200_000:
        raise HTTPException(status_code=400, detail="n_variants must be between 1 and 200000")

    batch_id = str(uuid.uuid4())

    # 1. Simulate
    metrics = generate_batch(req.n_variants, scenario_id=req.scenario_id)

    # 2. Evaluate against pass/fail rules
    results = evaluate_batch(metrics)
    pass_count = sum(1 for r in results if r.status == "PASS")
    fail_count = sum(1 for r in results if r.status != "PASS")

    # 3. Ingest into the operational store in parallel chunks
    start = time.time()
    chunks = list(_chunk(results, INGEST_CHUNK_SIZE))
    semaphore = asyncio.Semaphore(PARALLEL_CHUNKS)

    async with httpx.AsyncClient() as client:
        async def bounded_ingest(c):
            async with semaphore:
                await _ingest_chunk(client, batch_id, c)

        try:
            await asyncio.gather(*(bounded_ingest(c) for c in chunks))
        except httpx.HTTPError as e:
            raise HTTPException(status_code=502, detail=f"failed to ingest into go-service: {e}")

    ingest_seconds = time.time() - start

    # 4. Export to warehouses for historical analytics
    bq_result = None
    rs_result = None
    if req.export_to_warehouse:
        bq_result = analytics_exporter.export_to_bigquery(results)
        rs_result = analytics_exporter.export_to_redshift(results)

    return RunResponse(
        batch_id=batch_id,
        total_variants=len(results),
        pass_count=pass_count,
        fail_count=fail_count,
        ingest_seconds=round(ingest_seconds, 3),
        bigquery_export=bq_result,
        redshift_export=rs_result,
    )
