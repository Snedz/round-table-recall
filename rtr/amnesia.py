"""Amnesia test: forget everything local, rebuild from Walrus alone, prove nothing was lost.

1. Rebuild the trust ledger from **Walrus-only recall** (no local mirror).
2. Rebuild it again from the **full local mirror** (every memory ever written).
3. Compare what memory makes the table do before anyone answers: seat, model and
   source tracks, seat weights, route order (demotions and probation) and the
   distrusted-domain list. They must be identical.
4. Check through **Tatum** that every memory Walrus returned is a Walrus ``Blob``
   object owned onchain by the account owner (works without a Tatum API key).

Read-only: it only calls ``recall`` and Tatum reads. Nothing is written.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import trust
from .llm import Seat

SECTIONS = (("seats", trust.seat_tracks), ("models", trust.model_tracks), ("sources", trust.source_tracks))


@dataclass
class Amnesia:
    recalled: int
    mirror: int
    counts: dict[str, tuple[int, int]] = field(default_factory=dict)
    diffs: list[str] = field(default_factory=list)
    weights: dict[str, float] = field(default_factory=dict)
    effects: list[str] = field(default_factory=list)
    routes: dict[str, list[str]] = field(default_factory=dict)
    snapshot_ts: float | None = None
    snapshot_runs: int | None = None
    onchain_checked: bool = False
    onchain_total: int = 0
    with_blob_id: int = 0
    found_onchain: int = 0
    missing: list[str] = field(default_factory=list)
    onchain_note: str = ""

    @property
    def same_ledger(self) -> bool:
        return not self.diffs

    @property
    def all_onchain(self) -> bool:
        return self.onchain_checked and self.with_blob_id > 0 and not self.missing

    @property
    def ok(self) -> bool:
        return self.same_ledger and self.all_onchain


def _plan(records: list[dict], seats: list[Seat]) -> tuple[dict[str, list[str]], list[str]]:
    from .roundtable import RoundTable

    planned, _, effects = RoundTable(seats, seats[0], memory=None).plan(records)  # type: ignore[arg-type]
    return {s.id: [str(r) for r in s.routes] for s in planned}, effects


def compare(recalled: list[dict], mirror: list[dict], seats: list[Seat],
            onchain_blob_ids: set[str] | None = None, onchain_note: str = "") -> Amnesia:
    a = Amnesia(recalled=len(recalled), mirror=len(mirror))
    for name, fn in SECTIONS:
        w = {k: (t.n, t.weight) for k, t in fn(recalled).items()}
        m = {k: (t.n, t.weight) for k, t in fn(mirror).items()}
        a.counts[name] = (len(w), len(m))
        for k in sorted(set(w) | set(m)):
            if w.get(k) != m.get(k):
                a.diffs.append(f"{name}: {k} walrus={w.get(k)} mirror={m.get(k)}")
    ids = [s.id for s in seats]
    a.weights = trust.seat_weights(recalled, ids)
    if a.weights != trust.seat_weights(mirror, ids):
        a.diffs.append(f"seat weights: walrus={a.weights} mirror={trust.seat_weights(mirror, ids)}")
    a.routes, a.effects = _plan(recalled, seats)
    m_routes, m_effects = _plan(mirror, seats)
    if a.routes != m_routes:
        a.diffs.append("route order (demotion/probation) differs")
    if a.effects != m_effects:
        a.diffs.append(f"memory effects differ: walrus={a.effects} mirror={m_effects}")
    snap = trust.latest_snapshot(recalled)
    if snap:
        a.snapshot_ts = float(snap.get("ts", 0))
        a.snapshot_runs = snap.get("runs")
    a.onchain_note = onchain_note
    if onchain_blob_ids is not None:
        a.onchain_checked = True
        a.onchain_total = len(onchain_blob_ids)
        rec_ids = sorted({r["_blob_id"] for r in recalled if r.get("_blob_id")})
        a.with_blob_id = len(rec_ids)
        a.missing = [b for b in rec_ids if b not in onchain_blob_ids]
        a.found_onchain = a.with_blob_id - len(a.missing)
    return a


def amnesia_text(a: Amnesia, network: str = "mainnet") -> str:
    import time as _t

    from .sui import walruscan

    lines = ["AMNESIA TEST: local memory ignored; the ledger is rebuilt from Walrus alone", "",
             f"  Walrus-only recall       : {a.recalled} memories",
             f"  local mirror (all writes): {a.mirror} memories"]
    if a.snapshot_ts:
        lines.append("  newest ledger snapshot   : "
                     + _t.strftime("%Y-%m-%d %H:%M %Z", _t.localtime(a.snapshot_ts))
                     + (f", covering {a.snapshot_runs} runs" if a.snapshot_runs else ""))
    lines.append("")
    lines.append("  rebuilt ledger             walrus  mirror")
    for name, (w, m) in a.counts.items():
        lines.append(f"    {name:<23}{w:>6}  {m:>6}")
    lines.append("  seat weights (walrus)    : " + ", ".join(f"{k}={v:.3f}" for k, v in a.weights.items()))
    lines.append("  what memory changes next run (rebuilt from Walrus):")
    lines += [f"    - {e}" for e in a.effects] or ["    - (no changes)"]
    lines.append("  differences vs mirror    : " + (str(len(a.diffs)) if a.diffs else "0, identical"))
    lines += [f"    ! {d}" for d in a.diffs]
    lines.append("")
    if a.onchain_checked:
        lines.append(f"  TATUM CHECK: {a.found_onchain}/{a.with_blob_id} recalled memories are Walrus Blob objects "
                     f"onchain ({a.onchain_total} owned by the account owner){' ' + a.onchain_note if a.onchain_note else ''}")
        for b in a.missing[:10]:
            lines.append(f"    ! not found onchain: {b}  {walruscan(b, network)}")
    else:
        lines.append(f"  TATUM CHECK: skipped {a.onchain_note}".rstrip())
    lines.append("")
    lines.append("RESULT: " + ("PASS. Forgetting the local copy loses nothing; every recalled memory is onchain."
                               if a.ok else "FAIL (see ! lines above)"))
    return "\n".join(lines)
