"""Onchain proof that the memory exists, read through Tatum's Sui gateway.

Tatum serves Sui over GraphQL (``https://sui-<network>.gateway.tatum.io/graphql``,
``x-api-key`` header); Sui JSON-RPC on that gateway is retired. We read:

1. the latest checkpoint (the gateway is live),
2. the ``MemWalAccount`` object for our account id: type, version, owner,
   delegate-key count, active flag,
3. the Walrus ``Blob`` objects owned by the account owner (where each memory's
   encrypted bytes are registered onchain), if the relayer transferred any.
"""

from __future__ import annotations

import base64
import time
from dataclasses import dataclass, field

import requests

from . import config

TATUM_GQL = {"mainnet": "https://sui-mainnet.gateway.tatum.io/graphql",
             "testnet": "https://sui-testnet.gateway.tatum.io/graphql"}
SUIVISION = {"mainnet": "https://suivision.xyz/object/", "testnet": "https://testnet.suivision.xyz/object/"}
WALRUSCAN = {"mainnet": "https://walruscan.com/mainnet/blob/", "testnet": "https://walruscan.com/testnet/blob/"}

Q_CHECKPOINT = "{ checkpoint { sequenceNumber } }"
Q_OBJECT = """query($id: SuiAddress!) { object(address: $id) {
  version digest asMoveObject { contents { type { repr } json } } } }"""
Q_OWNED = """query($owner: SuiAddress!, $after: String) { address(address: $owner) {
  objects(first: 50, after: $after) { nodes { address contents { type { repr } json } }
  pageInfo { hasNextPage endCursor } } } }"""


class SuiRpcError(RuntimeError):
    pass


@dataclass
class Proof:
    network: str
    rpc: str
    account_id: str
    account_type: str = ""
    account_version: str = ""
    account_digest: str = ""
    owner: str = ""
    active: bool | None = None
    delegate_key_count: int = 0
    blobs: list[dict] = field(default_factory=list)
    checkpoint: str = ""
    errors: list[str] = field(default_factory=list)

    @property
    def blob_count(self) -> int:
        return len(self.blobs)

    def explorer(self, object_id: str) -> str:
        return SUIVISION.get(self.network, SUIVISION["mainnet"]) + object_id

    def walruscan(self, blob_id: str) -> str:
        return WALRUSCAN.get(self.network, WALRUSCAN["mainnet"]) + blob_id


class TatumSui:
    def __init__(self, network: str | None = None, session: requests.Session | None = None,
                 retries: int = 4, backoff: float = 1.0):
        self.retries = retries
        self.backoff = backoff
        self.network = network or config.network()
        self.key = config.get(f"TATUM_API_KEY_{self.network.upper()}")
        self.url = TATUM_GQL[self.network]
        self.http = session or requests.Session()

    def query(self, query: str, variables: dict | None = None) -> dict:
        if not self.key:
            raise SuiRpcError("Tatum API key not configured")
        # Free Tatum plans rate-limit (HTTP 429); back off and retry so paging
        # through owned objects doesn't stop early and undercount blobs.
        for attempt in range(self.retries + 1):
            r = self.http.post(self.url, json={"query": query, "variables": variables or {}},
                               headers={"x-api-key": self.key, "content-type": "application/json"}, timeout=30)
            if r.status_code != 429 or attempt == self.retries:
                break
            wait = r.headers.get("retry-after")
            try:
                delay = float(wait) if wait else self.backoff * (2 ** attempt)
            except ValueError:
                delay = self.backoff * (2 ** attempt)
            time.sleep(min(delay, 10.0))
        if r.status_code != 200:
            raise SuiRpcError(f"Tatum HTTP {r.status_code}")
        body = r.json()
        if body.get("errors"):
            raise SuiRpcError(f"Tatum GraphQL: {body['errors'][0].get('message')}")
        return body.get("data") or {}

    def proof(self, account_id: str, max_pages: int = 10) -> Proof:
        p = Proof(network=self.network, rpc=f"Tatum Sui gateway ({self.url})", account_id=account_id)
        try:
            p.checkpoint = str(self.query(Q_CHECKPOINT)["checkpoint"]["sequenceNumber"])
        except (SuiRpcError, KeyError, TypeError) as e:
            p.errors.append(str(e))
        try:
            obj = self.query(Q_OBJECT, {"id": account_id}).get("object")
            if not obj:
                p.errors.append("MemWalAccount object not found")
            else:
                c = obj["asMoveObject"]["contents"]
                j = c.get("json") or {}
                p.account_type = c["type"]["repr"]
                p.account_version = str(obj.get("version", ""))
                p.account_digest = obj.get("digest", "")
                p.owner = j.get("owner", "")
                p.active = j.get("active")
                keys = j.get("delegate_keys") or []
                p.delegate_key_count = len(keys) if isinstance(keys, list) else 0
        except (SuiRpcError, KeyError, TypeError) as e:
            p.errors.append(str(e))
        if p.owner:
            after = None
            for _ in range(max_pages):
                try:
                    objs = self.query(Q_OWNED, {"owner": p.owner, "after": after})["address"]["objects"]
                except (SuiRpcError, KeyError, TypeError) as e:
                    p.errors.append(str(e))
                    break
                for n in objs["nodes"]:
                    c = n.get("contents") or {}
                    t = (c.get("type") or {}).get("repr", "")
                    if "::blob::Blob" in t:
                        j = c.get("json") or {}
                        p.blobs.append({"object_id": n["address"], "blob_id": blob_id_from_u256(j.get("blob_id")),
                                        "size": j.get("size")})
                if not objs["pageInfo"]["hasNextPage"]:
                    break
                after = objs["pageInfo"]["endCursor"]
        return p


def blob_id_from_u256(raw) -> str:
    """Walrus stores blob_id as a u256 onchain; the familiar id is its little-endian URL-safe base64."""
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return str(raw or "")
    return base64.urlsafe_b64encode(n.to_bytes(32, "little")).decode().rstrip("=")
