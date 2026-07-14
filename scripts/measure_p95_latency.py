#!/usr/bin/env python3
"""
Fires repeated requests at the Go service's /api/v1/summary and
/api/v1/runs endpoints and reports P50/P95/P99 latency, so the
"sub-150ms P95 query latency" claim can be measured against a real
database rather than asserted.

Usage:
    python3 scripts/measure_p95_latency.py --requests 300 --concurrency 20

Run this AFTER seeding enough data with seed_data.py (or after a few
evaluation batches) so the measurement reflects a realistically sized
table rather than an empty one.
"""
import argparse
import statistics
import time
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed


def timed_request(url: str) -> float:
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            resp.read()
    except urllib.error.URLError as e:
        print(f"request failed: {e}")
        return -1
    return (time.perf_counter() - start) * 1000.0


def percentile(data, pct):
    data = sorted(data)
    k = (len(data) - 1) * (pct / 100)
    f = int(k)
    c = min(f + 1, len(data) - 1)
    if f == c:
        return data[f]
    return data[f] + (data[c] - data[f]) * (k - f)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8080")
    parser.add_argument("--requests", type=int, default=300)
    parser.add_argument("--concurrency", type=int, default=20)
    parser.add_argument("--endpoint", default="/api/v1/summary", choices=["/api/v1/summary", "/api/v1/runs"])
    args = parser.parse_args()

    url = args.base_url.rstrip("/") + args.endpoint
    latencies = []

    print(f"Firing {args.requests} requests at {url} with concurrency={args.concurrency}...")
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = [pool.submit(timed_request, url) for _ in range(args.requests)]
        for f in as_completed(futures):
            ms = f.result()
            if ms >= 0:
                latencies.append(ms)

    if not latencies:
        print("No successful requests -- is the go-service running?")
        return

    print("\n--- Query Latency Report ---")
    print(f"  successful requests : {len(latencies)}/{args.requests}")
    print(f"  min                 : {min(latencies):.2f} ms")
    print(f"  p50                 : {percentile(latencies, 50):.2f} ms")
    print(f"  p95                 : {percentile(latencies, 95):.2f} ms")
    print(f"  p99                 : {percentile(latencies, 99):.2f} ms")
    print(f"  max                 : {max(latencies):.2f} ms")
    print(f"  mean                : {statistics.mean(latencies):.2f} ms")


if __name__ == "__main__":
    main()
