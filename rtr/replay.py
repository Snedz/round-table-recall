"""Offline replay of a recorded Mainnet run. No model or Tatum call."""

from __future__ import annotations

import re
from pathlib import Path

from .sui import walruscan

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUN = ROOT / "preview" / "replay-run.txt"
DEFAULT_PROOF = ROOT / "preview" / "proof6.log"
DEFAULT_TRACKS = ROOT / "preview" / "trust6.log"

BANNER = (
    "REPLAY OF A REAL MAINNET RUN — recorded 2026-11-09 23:56 America/Toronto.\n"
    "No live model call was made. The memory writes and the Tatum receipt below already happened."
)

NOTE = (
    "Replay of a real Mainnet run recorded 2026-11-09 23:56 America/Toronto. "
    "No live model call. Memory writes and the Tatum receipt already happened."
)


def _clean(text: str) -> str:
    lines = []
    for line in text.splitlines():
        if line.startswith("ask_exit") or line.strip() == "DONE":
            continue
        lines.append(line)
    return "\n".join(lines).strip() + "\n"


_BLOB = re.compile(r"blob=([A-Za-z0-9_-]{43})(?![A-Za-z0-9_-])")


def link_blobs(text: str) -> str:
    """Append the Walruscan page to every line that shows a Walrus blob id."""
    out = []
    for line in text.splitlines():
        m = _BLOB.search(line)
        out.append(f"{line}  {walruscan(m.group(1))}" if m and "https://" not in line else line)
    return "\n".join(out) + ("\n" if text.endswith("\n") else "")


def run_transcript(path: Path | None = None) -> str:
    return link_blobs(_clean((path or DEFAULT_RUN).read_text()))


def labeled_run(path: Path | None = None) -> str:
    return BANNER + "\n\n" + run_transcript(path)


def proof_snapshot(path: Path | None = None) -> str:
    return link_blobs(_clean((path or DEFAULT_PROOF).read_text()))


def tracks_snapshot(path: Path | None = None) -> str:
    return _clean((path or DEFAULT_TRACKS).read_text())
