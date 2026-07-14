"""
Pass/fail evaluation rules applied to raw simulated scenario telemetry.

Keeping the rule thresholds in one place makes the evaluation criteria
auditable, and separates "what happened in the simulation" (scenario_generator)
from "did that constitute a pass" (this module) -- mirroring how a real AV
eval pipeline separates simulation output from safety-case scoring.
"""
from dataclasses import dataclass
from typing import Optional

from app.scenario_generator import VariantMetrics

MIN_ACCEPTABLE_TTC_SECONDS = 1.0
MAX_ACCEPTABLE_LANE_DEVIATION_METERS = 0.6
MIN_ACCEPTABLE_COMFORT_SCORE = 55.0


@dataclass
class EvaluationResult:
    scenario_id: str
    variant_id: str
    model_version: str
    status: str  # PASS | FAIL | ERROR
    min_ttc_seconds: float
    lane_deviation_meters: float
    collision_detected: bool
    comfort_score: float
    latency_ms: float
    failure_reason: Optional[str] = None


def evaluate(metrics: VariantMetrics) -> EvaluationResult:
    failure_reasons = []

    if metrics.collision_detected:
        failure_reasons.append("collision_detected")
    if metrics.min_ttc_seconds < MIN_ACCEPTABLE_TTC_SECONDS:
        failure_reasons.append(f"min_ttc_below_threshold({metrics.min_ttc_seconds}s)")
    if metrics.lane_deviation_meters > MAX_ACCEPTABLE_LANE_DEVIATION_METERS:
        failure_reasons.append(f"lane_deviation_exceeded({metrics.lane_deviation_meters}m)")
    if metrics.comfort_score < MIN_ACCEPTABLE_COMFORT_SCORE:
        failure_reasons.append(f"comfort_score_low({metrics.comfort_score})")

    status = "FAIL" if failure_reasons else "PASS"

    return EvaluationResult(
        scenario_id=metrics.scenario_id,
        variant_id=metrics.variant_id,
        model_version=metrics.model_version,
        status=status,
        min_ttc_seconds=metrics.min_ttc_seconds,
        lane_deviation_meters=metrics.lane_deviation_meters,
        collision_detected=metrics.collision_detected,
        comfort_score=metrics.comfort_score,
        latency_ms=metrics.latency_ms,
        failure_reason="; ".join(failure_reasons) if failure_reasons else None,
    )


def evaluate_batch(metrics_list: list[VariantMetrics]) -> list[EvaluationResult]:
    return [evaluate(m) for m in metrics_list]
