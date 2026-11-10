import json
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
        return json.dumps({"scores": scores, "sources": {"wikipedia.org": 8}, "best": "A", "why": "x"})
    answer = "Canberra is the capital." if route.model == "good" else "Sydney is the capital."
    return json.dumps({"answer": answer, "sources": ["https://en.wikipedia.org/wiki/Canberra"]})


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


def test_snapshot_keeps_history_past_recall_limit():
    old = [{"kind": "seat_score", "seat": "a", "route": "nim:x", "score": 9, "ts": float(i)} for i in range(150)]
    snap = trust.snapshot(old, ts=150.0, runs=150)
    newer = [{"kind": "seat_score", "seat": "a", "route": "nim:x", "score": 1, "ts": 151.0}]
    # recall only returns the snapshot plus the newest raw score; nothing older is needed
    t = trust.seat_tracks([snap] + newer + old[-5:])
    assert t["a"].n == 151
    assert abs(t["a"].mean - (9 * 150 + 1) / 151) < 1e-9
    assert trust.model_tracks([snap])["nim:x"].n == 150


def test_latest_snapshot_wins():
    s1 = trust.snapshot([{"kind": "seat_score", "seat": "a", "score": 2, "ts": 1.0}], ts=1.0)
    s2 = trust.snapshot([{"kind": "seat_score", "seat": "a", "score": 8, "ts": 1.0},
                         {"kind": "seat_score", "seat": "a", "score": 8, "ts": 2.0}], ts=2.0)
    assert trust.seat_tracks([s2, s1])["a"].n == 2


def test_memory_changes_routes_and_prompt(tmp_path):
    seen_prompts = []

    def chat(route, messages, max_tokens, timeout):
        seen_prompts.append((route.model, messages[0]["content"]))
        return _fake_chat(route, messages, max_tokens, timeout)

    mem = JsonlMemory(tmp_path / "m.jsonl")
    mem.remember([{"kind": "seat_score", "seat": "s", "route": "nim:bad", "score": 1, "ts": 1.0},
                  {"kind": "seat_score", "seat": "s", "route": "nim:bad", "score": 2, "ts": 2.0},
                  {"kind": "source_score", "domain": "seo-farm.xyz", "score": 1, "ts": 2.0}])
    seats = [Seat("s", [Route("nim", "bad"), Route("nim", "good")])]
    table = RoundTable(seats, Seat("critic", [Route("nim", "critic")]), mem, chat=chat, rng=random.Random(0))
    r = table.run("What is the capital of Australia?")
    assert r.seats[0].route == "nim:good"  # remembered-bad model was moved behind the good one
    answer_prompt = next(p for m, p in seen_prompts if m == "good")
    assert "seo-farm.xyz" in answer_prompt
    assert any("demoted model nim:bad" in e for e in r.effects)
    assert any("removed before grading: none" in e for e in r.effects)
    snaps = [x for x in mem.recall() if x["kind"] == "ledger"]
    assert snaps and snaps[-1]["tallies"]["seat"]["s"][1] == 3


def test_council_adapter_feeds_ledger():
    from rtr.adapters import council_records
    recs = council_records([("glm", 6), ("qwen", 3), ("gemma", 0)], n_rankers=2, question_id="q",
                           routes={"glm": "nim:z-ai/glm"}, ts=1.0)
    assert [r["score"] for r in recs] == [10.0, 5.0, 0.0]
    w = trust.seat_weights(recs, ["glm", "qwen", "gemma"])
    assert w["glm"] > w["qwen"] > w["gemma"]
    assert trust.model_tracks(recs)["nim:z-ai/glm"].n == 1


def test_history_is_the_learning_curve():
    recs = [{"kind": "run", "ts": 2.0, "winner": "a", "weights_before": {"a": 1.2}},
            {"kind": "run", "ts": 1.0, "winner": "b", "weights_before": {"a": 1.0}}]
    assert [w["a"] for _, _, w in trust.history(recs)] == [1.0, 1.2]


def test_grpc_cross_check():
    from rtr.sui_grpc import cross_check
    assert cross_check("7", "abc", {"version": "7", "digest": "abc"})[0]
    ok, msg = cross_check("7", "abc", {"version": "8", "digest": "abc"})
    assert not ok and "DO NOT match" in msg


def test_low_weight_seat_goes_on_probation(tmp_path):
    mem = JsonlMemory(tmp_path / "m.jsonl")
    mem.remember([{"kind": "seat_score", "seat": "s", "route": "nim:x", "score": 0, "ts": float(i)} for i in range(4)])
    seats = [Seat("s", [Route("nim", "bad"), Route("nim", "good")])]
    table = RoundTable(seats, Seat("critic", [Route("nim", "critic")]), mem, chat=_fake_chat, rng=random.Random(0))
    r = table.run("What is the capital of Australia?")
    assert r.seats[0].route == "nim:good"
    assert any("on probation" in e for e in r.effects)


def test_snapshot_carries_learning_curve():
    runs = [{"kind": "run", "ts": float(i), "winner": "a", "weights_before": {"a": 1 + i / 10}} for i in range(3)]
    snap = trust.snapshot(runs, ts=3.0)
    later = {"kind": "run", "ts": 4.0, "winner": "a", "weights_before": {"a": 1.4}}
    # old run memories no longer recalled: the curve still comes back from the snapshot
    assert [round(w["a"], 2) for _, _, w in trust.history([snap, later])] == [1.0, 1.1, 1.2, 1.4]


def test_low_trust_sources_are_removed_before_grading(tmp_path):
    def chat(route, messages, max_tokens, timeout):
        if route.model == "critic":
            return _fake_chat(route, messages, max_tokens, timeout)
        return '{"answer": "Canberra is the capital.", "sources": ["https://seo-farm.xyz/a", "https://www.britannica.com/x"]}'

    mem = JsonlMemory(tmp_path / "m.jsonl")
    mem.remember([{"kind": "source_score", "domain": "seo-farm.xyz", "score": 1, "ts": 1.0}])
    table = RoundTable([Seat("s", [Route("nim", "good")])], Seat("critic", [Route("nim", "critic")]), mem,
                       chat=chat, rng=random.Random(0))
    r = table.run("What is the capital of Australia?")
    assert r.seats[0].sources == ["https://www.britannica.com/x"]
    assert any("s: seo-farm.xyz" in e for e in r.effects)


def test_replay_of_recorded_mainnet_run():
    from rtr.replay import labeled_run, proof_snapshot

    text = labeled_run()
    assert "REPLAY OF A REAL MAINNET RUN" in text
    assert "MEMORY CHANGED THIS RUN" in text
    assert "147 -> 161" in text
    assert "Do we lose most of our body heat through our heads?" in text
    proof = proof_snapshot()
    assert "161" in proof
    assert "gRPC" in proof
    assert "DONE" not in proof


def test_replay_page_has_no_live_form():
    from rtr.web import replay_page

    page = replay_page()
    assert "Replay mode" in page
    assert "147 -&gt; 161" in page
    assert "<form" not in page
    assert "REPLAY OF A REAL MAINNET RUN" in page
