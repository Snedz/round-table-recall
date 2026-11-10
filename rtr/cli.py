"""Command line: ``python -m rtr {ask,demo,trust,proof,serve}``."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from . import config, trust
from .llm import default_seats
from .memory import JsonlMemory, MirroredMemory, WalrusMemory
from .questions import PUBLIC_QUESTIONS
from .render import history_text, proof_text, run_text, tracks_text
from .roundtable import RoundTable


def build_memory(backend: str):
    mirror = JsonlMemory(config.state_dir() / f"memory-{config.network()}.jsonl")
    if backend == "jsonl":
        return mirror
    return MirroredMemory(WalrusMemory.from_config(), mirror)


def build_table(backend: str) -> RoundTable:
    seats, critic = default_seats()
    return RoundTable(seats, critic, build_memory(backend))


def _log(text: str, log: Path | None) -> None:
    print(text, flush=True)
    if log:
        with log.open("a") as f:
            f.write(text + "\n")


def _blob_count() -> int | None:
    """Walrus Blob objects owned by the MemWal account owner, read via Tatum (None if unavailable)."""
    try:
        from .sui import TatumSui

        p = TatumSui().proof(config.get("MEMWAL_ACCOUNT_ID") or "")
        return None if p.errors else p.blob_count
    except Exception:
        return None


def cmd_ask(args) -> int:
    table = build_table(args.memory)
    log = Path(args.log) if args.log else None
    qs = args.question or PUBLIC_QUESTIONS[: args.n]
    for q in qs:
        _log(f"\n=== {time.strftime('%Y-%m-%d %H:%M:%S %Z')} | network={config.network()} "
             f"| memory={table.memory.name} ===", log)
        before = _blob_count() if args.memory == "walrus" else None
        r = table.run(q)
        _log(run_text(r), log)
        if before is not None:
            writes = sum(1 for x in r.receipts if x.status == "done")
            after = _blob_count()
            if after is None:
                _log("TATUM RECEIPT: Blob count unavailable after the run", log)
            else:
                verdict = "matches" if after - before == writes else "DOES NOT match (relayer may still be settling)"
                _log(f"TATUM RECEIPT (Sui Mainnet via Tatum): Walrus Blob objects {before} -> {after} "
                     f"(+{after - before}); {writes} memory writes this run; {verdict}", log)
    return 0


def cmd_trust(args) -> int:
    recs = build_memory(args.memory).recall(limit=100)
    snap = trust.latest_snapshot(recs)
    print(f"{len(recs)} memories recalled"
          + (f"; ledger snapshot from {time.strftime('%Y-%m-%d %H:%M %Z', time.localtime(float(snap['ts'])))}"
             f" covering {snap.get('runs', '?')} runs" if snap else "; no ledger snapshot yet"))
    print(tracks_text("SEATS", trust.seat_tracks(recs)))
    print(tracks_text("MODELS (route that actually answered)", trust.model_tracks(recs)))
    print(tracks_text("SOURCES", trust.source_tracks(recs)))
    print(history_text(trust.history(recs)))
    return 0


def cmd_proof(args) -> int:
    from .sui import TatumSui

    account = config.get("MEMWAL_ACCOUNT_ID")
    if not account:
        print("MEMWAL_ACCOUNT_ID missing", file=sys.stderr)
        return 1
    print(proof_text(TatumSui().proof(account)))
    return 0


def cmd_serve(args) -> int:
    from .web import serve

    serve(build_table(args.memory), port=args.port)
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="rtr", description="Round Table Recall")
    p.add_argument("--memory", choices=["walrus", "jsonl"], default="walrus")
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("ask", help="run the round table on public questions")
    a.add_argument("question", nargs="*")
    a.add_argument("-n", type=int, default=1, help="number of built-in public questions when none given")
    a.add_argument("--log", help="append the transcript to this file")
    a.set_defaults(fn=cmd_ask)
    sub.add_parser("trust", help="show remembered track records").set_defaults(fn=cmd_trust)
    sub.add_parser("proof", help="read the MemWal account and blobs via Tatum").set_defaults(fn=cmd_proof)
    s = sub.add_parser("serve", help="minimal demo web page")
    s.add_argument("--port", type=int, default=8787)
    s.set_defaults(fn=cmd_serve)
    args = p.parse_args(argv)
    return args.fn(args)
