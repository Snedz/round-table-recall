import random

import pytest

from rtr import trust
from rtr.llm import ProviderUnavailable, Route, Seat, extract_json
from rtr.memory import JsonlMemory, MirroredMemory, WalrusMemory, decode, encode
from rtr.roundtable import RoundTable, domain
from rtr.sui import blob_id_from_u256


def test_encode_roundtrip():
    rec = {"kind": "seat_score", "seat": "a", "score": 7}
    assert decode(encode(rec)) == rec
    assert decode("not ours") is None


def test_extract_json_takes_last_object():
    text = 'format {"answer": "..."} thinking... final:\n```json\n{"answer": "Canberra {ok}", "sources": []}\n```'
    assert extract_json(text)["answer"] == "Canberra {ok}"
    with pytest.raises(ValueError):
        extract_json("no json here")


def test_trust_prior_and_weights():
    recs = [{"kind": "seat_score", "seat": "good", "score": 10}] * 4 + \
           [{"kind": "seat_score", "seat": "bad", "score": 0}] * 4
    w = trust.seat_weights(recs, ["good", "bad", "new"])
    assert w["new"] == 1.0
    assert w["good"] > 1.5 and w["bad"] < 0.5


def test_seat_failover_records_route():
    calls = []

    def chat(route, messages, max_tokens, timeout):
        calls.append(route.provider)
        if route.provider == "openrouter":
            raise ProviderUnavailable("429")
        return '{"answer": "ok answer here"}'

    seat = Seat("s", [Route("openrouter", "m1"), Route("nim", "m2")])
    reply = seat.ask([], chat=chat)
    assert reply.route.provider == "nim" and calls == ["openrouter", "nim"]


def test_validate_rejects_and_fails_over():
    def chat(route, messages, max_tokens, timeout):
        return "thinking only" if route.model == "m1" else '{"answer": "fine"}'

    seat = Seat("s", [Route("nim", "m1"), Route("nim", "m2")])
    assert seat.ask([], chat=chat, validate=extract_json).route.model == "m2"


def _fake_chat(route, messages, max_tokens, timeout):
    prompt = messages[-1]["content"]
    if "strict grader" in prompt:
        # Grade by content: the answer containing "Canberra" is right.
        blocks = prompt.split("Answer ")[1:]
        scores = {b[0]: (9 if "Canberra is" in b else 2) for b in blocks}
        return '{"scores": %s, "sources": {"wikipedia.org": 8}, "best": "A", "why": "x"}' % \
            str(scores).replace("'", '"')
    answer = "Canberra is the capital." if route.model == "good" else "Sydney is the capital."
    return '{"answer": "%s", "sources": ["https://en.wikipedia.org/wiki/Canberra"]}' % answer


def test_round_table_learns_across_runs(tmp_path):
    seats = [Seat("good", [Route("nim", "good")]), Seat("bad", [Route("nim", "bad")])]
    critic = Seat("critic", [Route("nim", "critic")])
    mem = JsonlMemory(tmp_path / "m.jsonl")
    table = RoundTable(seats, critic, mem, chat=_fake_chat, rng=random.Random(1))
    r1 = table.run("What is the capital of Australia?")
    assert r1.weights_before == {"good": 1.0, "bad": 1.0}
    assert r1.winner == "good"
    r2 = table.run("What is the capital of Australia?")
    assert r2.weights_before["good"] > 1.0 > r2.weights_before["bad"]  # memory changed the next run
    kinds = [r["kind"] for r in mem.recall()]
    assert kinds.count("seat_score") == 4 and "source_score" in kinds and "run" in kinds


def test_walrus_backend_with_sdk_mock(tmp_path):
    memwal = pytest.importorskip("memwal")
    client = memwal.MemWalMockSync.create(namespace="t")
    mem = MirroredMemory(WalrusMemory(client, "t", "testnet"), JsonlMemory(tmp_path / "mirror.jsonl"))
    receipts = mem.remember([{"kind": "seat_score", "seat": "a", "score": 6}])
    assert receipts and receipts[0].status == "done" and receipts[0].ref
    assert any(r.get("seat") == "a" for r in mem.recall())


def test_domain_and_blob_id():
    assert domain("https://www.britannica.com/x") == "britannica.com"
    assert len(blob_id_from_u256(12345)) == 43


def test_critic_rejects_flat_source_scores():
    from rtr.roundtable import _check_critic
    with pytest.raises(ValueError, match="too flat"):
        _check_critic({"scores": {"A": 8}, "sources": {"a.com": 10, "b.com": 10}}, ["A"])
    _check_critic({"scores": {"A": 8}, "sources": {"a.com": 9, "b.com": 6}}, ["A"])  # spread ok


def test_calibrate_source_scores_spreads_flat():
    from rtr.roundtable import calibrate_source_scores
    flat = {"nasa.gov": 10.0, "random-blog.xyz": 10.0, "britannica.com": 10.0}
    out = calibrate_source_scores(flat)
    assert max(out.values()) - min(out.values()) >= 2
    assert out["nasa.gov"] > out["random-blog.xyz"]
    already = {"nasa.gov": 9.0, "blog.xyz": 3.0}
    assert calibrate_source_scores(already) == already


def test_tatum_query_retries_on_429(monkeypatch):
    from rtr import sui

    class R:
        def __init__(self, code, data=None):
            self.status_code = code
            self.headers = {}
            self._data = data

        def json(self):
            return self._data

    calls = []

    class S:
        def post(self, *a, **k):
            calls.append(1)
            return R(429) if len(calls) < 3 else R(200, {"data": {"ok": 1}})

    monkeypatch.setattr(sui.time, "sleep", lambda s: None)
    t = sui.TatumSui(network="mainnet", session=S(), retries=4, backoff=0)
    t.key = "test"
    assert t.query("{ ok }") == {"ok": 1}
    assert len(calls) == 3
