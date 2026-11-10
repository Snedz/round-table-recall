"""Memory backends behind one small interface.

``MemoryBackend`` is deliberately tiny (``remember`` many records, ``recall``
all records of this app) so other loops can reuse it: 67's Round Table and
the Vultr lane loop only need to emit records and read a trust ledger back.

Records are plain dicts. On Walrus they are stored as text lines of the form
``RTR1 <json>`` so they stay human-readable in the Walrus Memory dashboard and
can be recalled and parsed back.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Protocol

PREFIX = "RTR1 "
LEDGER_QUERY = "RTR1 kind ledger snapshot tallies running sums counts"


def encode(record: dict) -> str:
    return PREFIX + json.dumps(record, sort_keys=True, separators=(",", ":"))


def decode(text: str) -> dict | None:
    text = text.strip()
    if not text.startswith(PREFIX):
        return None
    try:
        rec = json.loads(text[len(PREFIX):])
    except json.JSONDecodeError:
        return None
    return rec if isinstance(rec, dict) else None


@dataclass
class Receipt:
    backend: str
    ref: str  # blob id for Walrus, line number for JSONL
    status: str = "done"
    job_id: str | None = None


class MemoryBackend(Protocol):
    name: str

    def remember(self, records: list[dict]) -> list[Receipt]: ...

    def recall(self, query: str = "round table track record", limit: int = 100) -> list[dict]: ...


class JsonlMemory:
    """Append-only local file. The default for tests and offline runs."""

    name = "jsonl"

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def remember(self, records: list[dict]) -> list[Receipt]:
        receipts = []
        n = sum(1 for _ in self._lines())
        with self.path.open("a") as f:
            for rec in records:
                f.write(encode(rec) + "\n")
                n += 1
                receipts.append(Receipt(self.name, f"{self.path.name}:{n}"))
        return receipts

    def _lines(self) -> Iterable[str]:
        if self.path.exists():
            yield from self.path.read_text().splitlines()

    def recall(self, query: str = "", limit: int = 100) -> list[dict]:
        recs = [r for r in (decode(l) for l in self._lines()) if r]
        return recs[-limit:]


class WalrusMemory:
    """Walrus Memory through the official ``memwal`` Python SDK (managed relayer).

    ``client`` is a ``MemWalSync`` (real) or ``MemWalMockSync`` (tests). Writes go
    through ``remember_bulk_and_wait`` so each record becomes its own memory
    with its own Walrus blob id.
    """

    name = "walrus"

    def __init__(self, client, namespace: str, network: str, wait: bool = True,
                 timeout_ms: int = 120_000):
        self.client = client
        self.namespace = namespace
        self.network = network
        self.wait = wait
        self.timeout_ms = timeout_ms

    @classmethod
    def from_config(cls, namespace: str = "round-table-recall") -> "WalrusMemory":
        from memwal import MemWalSync

        from . import config

        key = config.get("MEMWAL_PRIVATE_KEY")
        account = config.get("MEMWAL_ACCOUNT_ID")
        if not key or not account:
            raise RuntimeError("Walrus Memory credentials missing (MEMWAL_PRIVATE_KEY / MEMWAL_ACCOUNT_ID)")
        net = config.network()
        env = "prod" if net == "mainnet" else "staging"
        client = MemWalSync.create(key=key, account_id=account, env=env, namespace=namespace)
        return cls(client, namespace, net)

    def remember(self, records: list[dict]) -> list[Receipt]:
        from memwal import RememberBulkItem

        receipts: list[Receipt] = []
        for i in range(0, len(records), 20):  # relayer bulk limit is 20
            chunk = records[i:i + 20]
            items = [RememberBulkItem(text=encode(r), namespace=self.namespace) for r in chunk]
            if self.wait:
                res = self.client.remember_bulk_and_wait(items)
                for item in _bulk_items(res):
                    receipts.append(Receipt(self.name, getattr(item, "blob_id", "") or "",
                                            getattr(item, "status", "done") or "done",
                                            getattr(item, "job_id", None) or getattr(item, "id", None)))
            else:
                res = self.client.remember_bulk(items)
                for jid in getattr(res, "job_ids", []):
                    receipts.append(Receipt(self.name, "", "accepted", jid))
        return receipts

    def recall(self, query: str = "RTR1 round table seat score source score track record",
               limit: int = 100) -> list[dict]:
        from memwal import RecallParams

        out: list[dict] = []
        seen: set[str] = set()
        # Second, small query so the latest ledger snapshot is always in the set
        # even when the main query's top-``limit`` is full of raw scores.
        for q, n in ((query, limit), (LEDGER_QUERY, 5)):
            res = self.client.recall(RecallParams(query=q, limit=n, namespace=self.namespace))
            for m in res.results:
                rec = decode(m.text)
                key = getattr(m, "blob_id", None) or m.text
                if rec and key not in seen:
                    seen.add(key)
                    rec.setdefault("_blob_id", getattr(m, "blob_id", None))
                    out.append(rec)
        return out

    def stats(self) -> dict:
        inner = getattr(self.client, "_inner", None)
        if inner is None or not hasattr(inner, "_signed_request"):
            return {}
        import asyncio

        async def go():
            from memwal.client import _with_fresh_http_client  # type: ignore
            return await _with_fresh_http_client(
                inner, inner._signed_request("POST", "/api/stats", {"namespace": self.namespace},
                                             include_seal_session=False))
        try:
            return asyncio.run(go())
        except Exception as e:  # stats are informational only
            return {"error": str(e)[:200]}


def _bulk_items(res) -> list:
    for attr in ("results", "items"):
        v = getattr(res, attr, None)
        if v is not None:
            return list(v)
    return list(res) if isinstance(res, (list, tuple)) else []


class MirroredMemory:
    """Write to a primary (Walrus) and a local mirror; read from the primary, falling back to the mirror."""

    def __init__(self, primary: MemoryBackend, mirror: JsonlMemory):
        self.primary = primary
        self.mirror = mirror
        self.name = f"{primary.name}+{mirror.name}"
        self.last_error: str | None = None

    def remember(self, records: list[dict]) -> list[Receipt]:
        receipts = self.primary.remember(records)
        stamped = [dict(r, _blob_id=rc.ref) for r, rc in zip(records, receipts)]
        self.mirror.remember(stamped)
        return receipts

    def recall(self, query: str = "", limit: int = 100) -> list[dict]:
        try:
            recs = self.primary.recall(limit=limit)
            if recs:
                return recs
        except Exception as e:
            self.last_error = str(e)[:200]
        return self.mirror.recall(limit=limit)


def now() -> float:
    return round(time.time(), 3)
