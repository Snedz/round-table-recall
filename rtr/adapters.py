"""Feed other multi-model loops into the same trust ledger.

The ledger only needs ``seat_score`` records, so any loop that ranks its
members can get a cross-run, Walrus-backed track record. This module turns a
Borda-style council ranking (independent answers -> anonymized peer ranking ->
chairman, the shape used by llm-council style round tables) into records.
"""

from __future__ import annotations

from .memory import now


def council_records(aggregate: list[tuple[str, float]], n_rankers: int, question_id: str,
                    routes: dict[str, str] | None = None, ts: float | None = None) -> list[dict]:
    """``aggregate`` is ``[(seat_id, borda_points), ...]``; each ranker gives n-rank points to its rank-th pick.

    Points are scaled to 0-10 against the maximum a seat could earn
    (every ranker puts it first), so records mix cleanly with critic scores.
    """
    n = len(aggregate)
    if n == 0 or n_rankers <= 0:
        return []
    best = n * n_rankers
    ts = now() if ts is None else ts
    out = []
    for seat, pts in aggregate:
        rec = {"kind": "seat_score", "seat": seat, "score": round(10.0 * float(pts) / best, 2),
               "question_id": question_id, "critic": "peer-ranking", "ts": ts}
        if routes and seat in routes:
            rec["route"] = routes[seat]
        out.append(rec)
    return out
