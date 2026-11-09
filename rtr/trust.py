"""Trust ledger: turns remembered critic scores into seat and source weights.

Scores are 0-10. Each seat starts from a prior of ``PRIOR_MEAN`` worth
``PRIOR_N`` pseudo-runs, so one lucky answer does not dominate. The weight is
the posterior mean divided by the prior mean, so an unknown seat weighs 1.00,
a seat the critic keeps rating 8/10 trends toward 1.6, and a 2/10 seat toward 0.4.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

PRIOR_MEAN = 5.0
PRIOR_N = 2.0


@dataclass
class Track:
    key: str
    n: int
    mean: float
    weight: float


def _tracks(records: list[dict], kind: str, field: str) -> dict[str, Track]:
    sums: dict[str, float] = defaultdict(float)
    counts: dict[str, int] = defaultdict(int)
    for r in records:
        if r.get("kind") != kind or field not in r:
            continue
        try:
            s = float(r["score"])
        except (KeyError, TypeError, ValueError):
            continue
        s = max(0.0, min(10.0, s))
        sums[r[field]] += s
        counts[r[field]] += 1
    out = {}
    for k in counts:
        post = (PRIOR_MEAN * PRIOR_N + sums[k]) / (PRIOR_N + counts[k])
        out[k] = Track(k, counts[k], sums[k] / counts[k], round(post / PRIOR_MEAN, 3))
    return out


def seat_tracks(records: list[dict]) -> dict[str, Track]:
    return _tracks(records, "seat_score", "seat")


def model_tracks(records: list[dict]) -> dict[str, Track]:
    return _tracks(records, "seat_score", "route")


def source_tracks(records: list[dict]) -> dict[str, Track]:
    return _tracks(records, "source_score", "domain")


def seat_weights(records: list[dict], seat_ids: list[str]) -> dict[str, float]:
    t = seat_tracks(records)
    return {s: (t[s].weight if s in t else 1.0) for s in seat_ids}
