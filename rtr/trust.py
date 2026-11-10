"""Trust ledger: turns remembered critic scores into seat, model and source weights.

Scores are 0-10. Each key starts from a prior of ``PRIOR_MEAN`` worth
``PRIOR_N`` pseudo-runs, so one lucky answer does not dominate. The weight is
the posterior mean divided by the prior mean, so an unknown seat weighs 1.00,
a seat the critic keeps rating 8/10 trends toward 1.6, and a 2/10 seat toward 0.4.

Snapshots: recall returns at most ~100 memories, so a ledger built only from
raw scores would silently forget its oldest runs. Every run therefore also
stores one ``ledger`` memory holding the running sums and counts. The ledger
is rebuilt as *latest snapshot + every raw score newer than it*, so the track
record stays complete however many memories exist.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

PRIOR_MEAN = 5.0
PRIOR_N = 2.0

# ledger section -> (record kind, record field)
SECTIONS = {"seat": ("seat_score", "seat"), "route": ("seat_score", "route"), "domain": ("source_score", "domain")}


@dataclass
class Track:
    key: str
    n: int
    mean: float
    weight: float


def latest_snapshot(records: list[dict]) -> dict | None:
    snaps = [r for r in records if r.get("kind") == "ledger" and isinstance(r.get("tallies"), dict)]
    return max(snaps, key=lambda r: float(r.get("ts", 0))) if snaps else None


def tallies(records: list[dict]) -> dict[str, dict[str, list[float]]]:
    """``{section: {key: [sum, count]}}`` from the latest snapshot plus newer raw scores."""
    snap = latest_snapshot(records)
    out: dict[str, dict[str, list[float]]] = {s: defaultdict(lambda: [0.0, 0]) for s in SECTIONS}
    cutoff = float("-inf")
    if snap:
        cutoff = float(snap.get("ts", 0))
        for sec, rows in snap["tallies"].items():
            if sec in out and isinstance(rows, dict):
                for k, v in rows.items():
                    try:
                        out[sec][k] = [float(v[0]), int(v[1])]
                    except (TypeError, ValueError, IndexError):
                        continue
    for r in records:
        try:
            ts = float(r.get("ts", 0))
        except (TypeError, ValueError):
            ts = 0.0
        if snap and ts <= cutoff:
            continue
        for sec, (kind, field) in SECTIONS.items():
            if r.get("kind") != kind or not r.get(field):
                continue
            try:
                s = max(0.0, min(10.0, float(r["score"])))
            except (KeyError, TypeError, ValueError):
                continue
            t = out[sec][r[field]]
            t[0] += s
            t[1] += 1
    return {s: dict(v) for s, v in out.items()}


CURVE_POINTS = 100


def snapshot(records: list[dict], ts: float, runs: int | None = None) -> dict:
    """A ``ledger`` memory summarizing everything in ``records`` up to ``ts``.

    It also carries the last ``CURVE_POINTS`` points of the learning curve, so the
    history survives even when old ``run`` memories fall out of recall.
    """
    t = tallies(records)
    rows = {sec: {k: [round(v[0], 3), int(v[1])] for k, v in d.items() if v[1]} for sec, d in t.items()}
    curve = [[round(ts_, 3), w, {k: round(float(x), 3) for k, x in wb.items()}]
             for ts_, w, wb in history(records)][-CURVE_POINTS:]
    snap = {"kind": "ledger", "tallies": rows, "curve": curve, "ts": ts}
    if runs is not None:
        snap["runs"] = runs
    return snap


def _tracks(records: list[dict], section: str) -> dict[str, Track]:
    out = {}
    for k, (total, n) in tallies(records)[section].items():
        if not n:
            continue
        post = (PRIOR_MEAN * PRIOR_N + total) / (PRIOR_N + n)
        out[k] = Track(k, int(n), total / n, round(post / PRIOR_MEAN, 3))
    return out


def seat_tracks(records: list[dict]) -> dict[str, Track]:
    return _tracks(records, "seat")


def model_tracks(records: list[dict]) -> dict[str, Track]:
    return _tracks(records, "route")


def source_tracks(records: list[dict]) -> dict[str, Track]:
    return _tracks(records, "domain")


def seat_weights(records: list[dict], seat_ids: list[str]) -> dict[str, float]:
    t = seat_tracks(records)
    return {s: (t[s].weight if s in t else 1.0) for s in seat_ids}


def distrusted_sources(records: list[dict], below: float = 1.0, limit: int = 8) -> list[Track]:
    """Source domains whose remembered record is worse than an unknown source."""
    rows = [t for t in source_tracks(records).values() if t.weight < below]
    return sorted(rows, key=lambda t: t.weight)[:limit]


def demoted_routes(records: list[dict], below: float = 1.0, min_n: int = 2) -> dict[str, Track]:
    """Model routes with at least ``min_n`` scores whose record is worse than an unknown model."""
    return {k: t for k, t in model_tracks(records).items() if t.n >= min_n and t.weight < below}


def history(records: list[dict]) -> list[tuple[float, str, dict[str, float]]]:
    """``(ts, winner, seat weights going into that run)`` for every remembered run, oldest first."""
    points: dict[float, tuple[float, str, dict[str, float]]] = {}
    snap = latest_snapshot(records)
    for item in (snap or {}).get("curve") or []:
        try:
            points[round(float(item[0]), 3)] = (float(item[0]), str(item[1]), dict(item[2]))
        except (TypeError, ValueError, IndexError):
            continue
    for r in records:
        if r.get("kind") == "run" and isinstance(r.get("weights_before"), dict):
            ts = float(r.get("ts", 0))
            points[round(ts, 3)] = (ts, str(r.get("winner")), r["weights_before"])
    return [points[k] for k in sorted(points)]
