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
from .render import proof_text, run_text, tracks_text
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


def cmd_ask(args) -> int:
    table = build_table(args.memory)
    log = Path(args.log) if args.log else None
    qs = args.question or PUBLIC_QUESTIONS[: args.n]
    for q in qs:
        _log(f"\n=== {time.strftime('%Y-%m-%d %H:%M:%S %Z')} | network={config.network()} "
             f"| memory={table.memory.name} ===", log)
        _log(run_text(table.run(q)), log)
    return 0


def cmd_trust(args) -> int:
    recs = build_memory(args.memory).recall(limit=100)
    print(f"{len(recs)} memories recalled")
    print(tracks_text("SEATS", trust.seat_tracks(recs)))
    print(tracks_text("MODELS (route that actually answered)", trust.model_tracks(recs)))
    print(tracks_text("SOURCES", trust.source_tracks(recs)))
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
