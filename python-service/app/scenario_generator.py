"""
Generates synthetic simulated-driving-scenario variant data.

In a real AV stack this module would be replaced by the actual simulator
(CARLA, LGSVL, or an internal replay/synthetic engine) that produces
per-variant sensor and planner telemetry. Here we generate statistically
reasonable synthetic metrics so the rest of the pipeline (evaluation,
ingestion, analytics export, dashboard) can be exercised end to end
without a real simulator dependency.
"""
import random
import string
import uuid
from dataclasses import dataclass, field
from typing import Optional

SCENARIO_IDS = [f"SC-{i:03d}" for i in range(1, 9)]
MODEL_VERSIONS = ["planner-v2.3.1", "planner-v2.4.0-rc1", "perception-v1.9.2"]


@dataclass
class VariantMetrics:
    scenario_id: str
    variant_id: str
    model_version: str
    min_ttc_seconds: float
    lane_deviation_meters: float
    collision_detected: bool
    comfort_score: float
    latency_ms: float


def _random_variant_id() -> str:
    return "VAR-" + "".join(random.choices(string.hexdigits.lower(), k=10))


def generate_variant(scenario_id: Optional[str] = None, model_version: Optional[str] = None) -> VariantMetrics:
    """Simulate one scenario-variant execution and return raw telemetry.

    Difficulty is baked into the distribution shape so that harder scenario
    categories (e.g. unprotected left turns, pedestrian crossings) produce
    a realistically higher failure rate than easy ones like car-following.
    """
    scenario_id = scenario_id or random.choice(SCENARIO_IDS)
    model_version = model_version or random.choice(MODEL_VERSIONS)

    hard_scenarios = {"SC-001", "SC-003", "SC-007", "SC-008"}
    is_hard = scenario_id in hard_scenarios

    min_ttc = max(0.0, random.gauss(2.2 if is_hard else 3.4, 1.1))
    lane_deviation = abs(random.gauss(0.35 if is_hard else 0.15, 0.25))
    comfort_score = max(0.0, min(100.0, random.gauss(72 if is_hard else 88, 12)))
    latency_ms = max(1.0, random.gauss(45 if is_hard else 30, 15))

    collision = min_ttc < 0.4 or random.random() < (0.015 if is_hard else 0.002)

    return VariantMetrics(
        scenario_id=scenario_id,
        variant_id=_random_variant_id(),
        model_version=model_version,
        min_ttc_seconds=round(min_ttc, 3),
        lane_deviation_meters=round(lane_deviation, 3),
        collision_detected=collision,
        comfort_score=round(comfort_score, 2),
        latency_ms=round(latency_ms, 2),
    )


def generate_batch(n_variants: int, scenario_id: Optional[str] = None) -> list[VariantMetrics]:
    """Generate n_variants synthetic scenario runs, spread across scenario
    categories if scenario_id is not pinned. Supports the 10,000+ variant
    parallel-evaluation claim by being cheap enough to call at that scale."""
    return [generate_variant(scenario_id=scenario_id) for _ in range(n_variants)]
