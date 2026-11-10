"""Plain-text rendering shared by the CLI, the preview log and the web page."""

from __future__ import annotations

from .roundtable import RunResult
from .sui import Proof
from .trust import Track


def short(x: str, n: int = 10) -> str:
    return x if not x or len(x) <= 2 * n else f"{x[:n]}…{x[-6:]}"


def run_text(r: RunResult) -> str:
    out = [f"QUESTION [{r.question_id}]: {r.question}", "",
           "Seat weights from memory (before this run): "
           + ", ".join(f"{k}={v:.2f}" for k, v in r.weights_before.items())]
    if r.effects:
        out.append("MEMORY CHANGED THIS RUN:")
        out += [f"  - {e}" for e in r.effects]
    out.append("")
    for s in r.seats:
        if s.error:
            out.append(f"  [{s.seat}] FAILED on every route:")
            for part in s.error.split(": ", 1)[-1].split(" | "):
                out.append(f"     - {part[:150]}")
            continue
        score = "n/a" if s.score is None else f"{s.score:.1f}/10"
        out.append(f"  [{s.seat}] answer {s.label or '-'} via {s.route} ({s.latency_s}s)  critic score: {score}")
        out.append("     " + s.answer.replace("\n", " ")[:420])
        if s.sources:
            out.append("     sources: " + ", ".join(s.sources))
    out += ["", f"CRITIC via {r.critic_route}: {r.critic_why}"]
    if r.source_scores:
        out.append("Source scores: " + ", ".join(f"{d}={v:.0f}" for d, v in r.source_scores.items()))
    out.append(f"WINNER (critic score x remembered weight): {r.winner}")
    out.append("Seat weights after this run: " + ", ".join(f"{k}={v:.2f}" for k, v in r.weights_after.items()))
    out.append("")
    ok = [x for x in r.receipts if x.status == "done"]
    out.append(f"MEMORY WRITES -> {r.memory_backend}: {len(ok)}/{len(r.receipts)} done")
    for x in r.receipts:
        out.append(f"  {x.status:<8} blob={x.ref or '-'} job={short(x.job_id or '-', 6)}")
    return "\n".join(out)


def tracks_text(title: str, tracks: dict[str, Track]) -> str:
    rows = sorted(tracks.values(), key=lambda t: -t.weight)
    lines = [title] + [f"  {t.key:<48} n={t.n:<3} mean={t.mean:4.1f} weight={t.weight:.2f}" for t in rows]
    return "\n".join(lines if rows else [title, "  (no memories yet)"])


def proof_text(p: Proof) -> str:
    lines = [f"PROOF THE MEMORY EXISTS ({p.network}) via {p.rpc}",
             f"  latest checkpoint : {p.checkpoint or '-'}",
             f"  MemWalAccount     : {short(p.account_id)}",
             f"  type              : {p.account_type or '-'}",
             f"  version / digest  : {p.account_version or '-'} / {p.account_digest or '-'}",
             f"  owner             : {short(p.owner)}   active={p.active}",
             f"  delegate keys     : {p.delegate_key_count}",
             f"  Walrus Blob objects owned by owner: {p.blob_count}"]
    for b in p.blobs[:12]:
        lines.append(f"    {short(b['object_id'])} blob={b['blob_id']} size={b['size']}  {p.walruscan(b['blob_id'])}")
    for e in p.errors:
        lines.append(f"  ! {e}")
    return "\n".join(lines)


def history_text(rows) -> str:
    """Seat weights going into each remembered run: the learning curve."""
    import time as _t
    if not rows:
        return "LEARNING CURVE\n  (no runs yet)"
    seats = sorted({k for _, _, w in rows for k in w})
    lines = ["LEARNING CURVE (seat weights going into each run, recalled from memory)",
             "  " + "time (local)".ljust(18) + "".join(s.ljust(8) for s in seats) + "winner"]
    for ts, winner, w in rows:
        lines.append("  " + _t.strftime("%m-%d %H:%M %Z", _t.localtime(ts)).ljust(18)
                     + "".join(f"{w.get(s, 1.0):<8.2f}" for s in seats) + winner)
    return "\n".join(lines)
