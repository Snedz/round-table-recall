"""Minimal demo page (stdlib only): ask a public question, watch weights move, see the onchain proof."""

from __future__ import annotations

import html
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs

from . import config, trust
from .render import history_text, proof_text, run_text, tracks_text
from .roundtable import RoundTable

PAGE = """<!doctype html><meta charset=utf-8><title>Round Table Recall</title>
<style>body{{background:#101218;color:#e6e6e6;font:14px ui-monospace,monospace;max-width:1100px;margin:24px auto}}
pre{{background:#181b23;padding:14px;border-radius:8px;white-space:pre-wrap}}h1,h2{{color:#78c8ff}}
input{{width:75%;padding:8px;background:#181b23;color:#eee;border:1px solid #333}}button{{padding:8px 14px}}</style>
<h1>Round Table Recall</h1><p>3 free-model seats answer, a critic scores, Walrus Memory ({net}) remembers who to trust.</p>
<form method=post action=/ask><input name=q placeholder="A public research question" required> <button>Ask the table</button></form>
<p>{status}</p><h2>Last run</h2><pre>{last}</pre><h2>Track record (recalled from memory)</h2><pre>{tracks}</pre>
<h2>Proof the memory exists (Tatum Sui gateway)</h2><pre>{proof}</pre>"""


_URL = re.compile(r"\s+https://walruscan\.com/\S+")
_BLOB_ID = re.compile(r"blob=([A-Za-z0-9_-]{43})(?![A-Za-z0-9_-])")
_OBJ = re.compile(r"(?<![0-9a-fA-Fx])(0x[0-9a-f]{64})(?![0-9a-f])")


def linkify(escaped: str, network: str = "mainnet") -> str:
    """Make blob ids open on Walruscan and full Sui object ids open on Suiscan (input is already HTML-escaped)."""
    from .sui import suiscan, walruscan

    text = _URL.sub("", escaped)
    text = _BLOB_ID.sub(lambda m: f'blob=<a href="{walruscan(m.group(1), network)}">{m.group(1)}</a>', text)
    return _OBJ.sub(lambda m: f'<a href="{suiscan(m.group(1), network)}">{m.group(1)}</a>', text)


def render_static(records: list[dict], last_run: str, proof: str, network: str, note: str,
                  amnesia: str = "") -> str:
    """A read-only snapshot of the demo page (no form, no keys) for static hosting."""
    tracks = "\n".join([tracks_text("SEATS", trust.seat_tracks(records)),
                        tracks_text("MODELS", trust.model_tracks(records)),
                        tracks_text("SOURCES", trust.source_tracks(records)),
                        history_text(trust.history(records))])
    body = PAGE.format(net=network, status=html.escape(note), last=linkify(html.escape(last_run), network),
                       tracks=html.escape(tracks), proof=linkify(html.escape(proof), network))
    if amnesia:
        body += ("<h2>Amnesia test (local copy ignored, ledger rebuilt from Walrus, blobs checked via Tatum)</h2>"
                 f"<pre>{html.escape(amnesia)}</pre>")
    start, end = body.index("<form"), body.index("</form>") + len("</form>")
    return body[:start] + "<p><b>Static snapshot</b> of a real Mainnet run. Run it yourself: see the README.</p>" + body[end:]


def serve(table: RoundTable, port: int = 8787) -> None:
    state = {"last": "No run yet.", "busy": False}
    lock = threading.Lock()

    class H(BaseHTTPRequestHandler):
        def _page(self) -> None:
            recs = table.memory.recall(limit=100)
            tracks = "\n".join([tracks_text("SEATS", trust.seat_tracks(recs)),
                                tracks_text("SOURCES", trust.source_tracks(recs)),
                                history_text(trust.history(recs))])
            try:
                from .sui import TatumSui
                proof = proof_text(TatumSui().proof(config.get("MEMWAL_ACCOUNT_ID") or ""))
            except Exception as e:  # the page should render even if the RPC is down  # noqa: BLE001
                proof = f"proof unavailable: {e}"
            body = PAGE.format(net=config.network(), status="running..." if state["busy"] else "",
                               last=linkify(html.escape(state["last"]), config.network()),
                               tracks=html.escape(tracks),
                               proof=linkify(html.escape(proof), config.network())).encode()
            self.send_response(200)
            self.send_header("content-type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            self._page()

        def do_POST(self) -> None:
            n = int(self.headers.get("content-length", 0))
            q = (parse_qs(self.rfile.read(n).decode()).get("q") or [""])[0].strip()[:300]
            if q and lock.acquire(blocking=False):
                try:
                    state["busy"] = True
                    state["last"] = run_text(table.run(q))
                except Exception as e:  # noqa: BLE001
                    state["last"] = f"run failed: {e}"
                finally:
                    state["busy"] = False
                    lock.release()
            self.send_response(303)
            self.send_header("location", "/")
            self.end_headers()

        def log_message(self, *a) -> None:
            pass

    print(f"Round Table Recall on http://127.0.0.1:{port}")
    ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()


def replay_page() -> str:
    """Read-only demo page built from the recorded Mainnet run. No keys, no network."""
    from . import replay

    last = replay.labeled_run()
    tracks = replay.tracks_snapshot()
    proof = replay.proof_snapshot()
    body = PAGE.format(
        net="mainnet (replay)",
        status=html.escape(replay.NOTE),
        last=linkify(html.escape(last)),
        tracks=html.escape(tracks),
        proof=linkify(html.escape(proof)),
    )
    start, end = body.index("<form"), body.index("</form>") + len("</form>")
    return (
        body[:start]
        + "<p><b>Replay mode.</b> This page is a recording of a real Mainnet run. "
        "Live ask is off so a rate limit cannot break the demo. "
        "Use <code>python -m rtr serve</code> with keys for a live run.</p>"
        + body[end:]
    )


def serve_replay(port: int = 8787) -> None:
    body = replay_page().encode()

    class H(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(200)
            self.send_header("content-type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a) -> None:
            pass

    print(f"Round Table Recall replay on http://127.0.0.1:{port}")
    ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()
