"""Minimal demo page (stdlib only): ask a public question, watch weights move, see the onchain proof."""

from __future__ import annotations

import html
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs

from . import config, trust
from .render import proof_text, run_text, tracks_text
from .roundtable import RoundTable

PAGE = """<!doctype html><meta charset=utf-8><title>Round Table Recall</title>
<style>body{{background:#101218;color:#e6e6e6;font:14px ui-monospace,monospace;max-width:1100px;margin:24px auto}}
pre{{background:#181b23;padding:14px;border-radius:8px;white-space:pre-wrap}}h1,h2{{color:#78c8ff}}
input{{width:75%;padding:8px;background:#181b23;color:#eee;border:1px solid #333}}button{{padding:8px 14px}}</style>
<h1>Round Table Recall</h1><p>3 free-model seats answer, a critic scores, Walrus Memory ({net}) remembers who to trust.</p>
<form method=post action=/ask><input name=q placeholder="A public research question" required> <button>Ask the table</button></form>
<p>{status}</p><h2>Last run</h2><pre>{last}</pre><h2>Track record (recalled from memory)</h2><pre>{tracks}</pre>
<h2>Proof the memory exists (Tatum Sui gateway)</h2><pre>{proof}</pre>"""


def serve(table: RoundTable, port: int = 8787) -> None:
    state = {"last": "No run yet.", "busy": False}
    lock = threading.Lock()

    class H(BaseHTTPRequestHandler):
        def _page(self) -> None:
            recs = table.memory.recall(limit=100)
            tracks = "\n".join([tracks_text("SEATS", trust.seat_tracks(recs)),
                                tracks_text("SOURCES", trust.source_tracks(recs))])
            try:
                from .sui import TatumSui
                proof = proof_text(TatumSui().proof(config.get("MEMWAL_ACCOUNT_ID") or ""))
            except Exception as e:  # the page should render even if the RPC is down
                proof = f"proof unavailable: {e}"
            body = PAGE.format(net=config.network(), status="running..." if state["busy"] else "",
                               last=html.escape(state["last"]), tracks=html.escape(tracks),
                               proof=html.escape(proof)).encode()
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
                except Exception as e:
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
