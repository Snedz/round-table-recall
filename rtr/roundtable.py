"""One round: 3 seats answer, the critic scores, memory learns, weights move.

Flow for ``run(question)``:
1. Recall the track record from memory and compute seat weights.
2. Ask the 3 answer seats in parallel (each with cross-provider failover).
3. The critic sees the answers anonymized and shuffled (A/B/C), and scores
   each 0-10 plus each cited source domain 0-10.
4. Final pick = argmax(critic score x remembered seat weight).
5. Write one ``seat_score`` memory per seat, one ``source_score`` per source,
   and one ``run`` summary memory.
"""

from __future__ import annotations

import hashlib
import random
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from urllib.parse import urlparse

from . import trust
from .llm import ChatFn, ProviderUnavailable, Seat, extract_json, http_chat
from .memory import MemoryBackend, Receipt, now

ANSWER_PROMPT = """You are {persona}, one seat at a research round table.
Answer the public research question below in at most 120 words.
Then list up to 3 real sources you rely on, as full URLs.{memory_note}
Reply with one JSON object only, with two keys: "answer" (your answer as a
string) and "sources" (a list of URL strings).

Question: {question}"""

CRITIC_PROMPT = """You are a strict grader for a research round table.
Score each anonymous answer 0-10 for factual accuracy, directness and honesty
about uncertainty. Also score each cited source domain 0-10 for how reliable
it is for THIS question.

Rules for source scores (mandatory):
- Use the FULL 0-10 range. Do NOT give every source the same number.
- Primary scientific / government / encyclopedia domains (nasa.gov, noaa.gov,
  .edu research pages, britannica.com, nature.com, science.org, who.int,
  usgs.gov, metoffice.gov.uk) usually score 8-10.
- Good secondary explainers (scijinks.gov, spaceplace.nasa.gov, ucar.edu
  education pages, well-known museum sites) usually score 6-8.
- Generic blogs, SEO farms, unverified personal sites, or URLs that look
  fabricated usually score 0-4.
- If two sources are both strong, still separate them by at least 1 point
  when one is more primary for the question.
- When you list 2 or more sources, max(source scores) - min(source scores)
  MUST be at least 2.

Reply ONLY with JSON:
one object with keys "scores" (answer letter -> number), "sources"
(domain -> number), "best" (a letter) and "why" (one sentence).

Question: {question}

{answers}"""


PROBATION_BELOW = 0.8


@dataclass
class SeatResult:
    seat: str
    route: str = ""
    answer: str = ""
    sources: list[str] = field(default_factory=list)
    latency_s: float = 0.0
    error: str | None = None
    label: str = ""
    score: float | None = None


@dataclass
class RunResult:
    question: str
    question_id: str
    weights_before: dict[str, float]
    weights_after: dict[str, float]
    seats: list[SeatResult]
    critic_route: str
    critic_why: str
    source_scores: dict[str, float]
    winner: str | None
    receipts: list[Receipt]
    memory_backend: str
    effects: list[str] = field(default_factory=list)


def question_id(q: str) -> str:
    return hashlib.sha256(q.strip().lower().encode()).hexdigest()[:12]


def domain(url: str) -> str:
    host = urlparse(url if "://" in url else f"https://{url}").netloc.lower()
    return host.removeprefix("www.")


def _ask_seat(seat: Seat, question: str, chat: ChatFn, memory_note: str = "") -> SeatResult:
    res = SeatResult(seat=seat.id)
    try:
        reply = seat.ask([{"role": "user", "content": ANSWER_PROMPT.format(persona=seat.persona, question=question,
                                                                            memory_note=memory_note)}], chat=chat,
                         validate=_check_answer)
    except ProviderUnavailable as e:
        res.error = str(e)[:900]
        return res
    res.route, res.latency_s = str(reply.route), round(reply.latency_s, 1)
    try:
        j = extract_json(reply.text)
        res.answer = str(j.get("answer", "")).strip()
        res.sources = [str(s) for s in (j.get("sources") or []) if isinstance(s, str)][:3]
    except ValueError:
        res.answer = reply.text.strip()[:900]
        res.sources = re.findall(r"https?://[^\s)\]\"']+", reply.text)[:3]
    return res


class RoundTable:
    def __init__(self, seats: list[Seat], critic: Seat, memory: MemoryBackend,
                 chat: ChatFn = http_chat, rng: random.Random | None = None):
        self.seats, self.critic, self.memory, self.chat = seats, critic, memory, chat
        self.rng = rng or random.Random()

    def weights(self) -> tuple[dict[str, float], list[dict]]:
        records = self.memory.recall(limit=100)
        return trust.seat_weights(records, [s.id for s in self.seats]), records

    def plan(self, records: list[dict]) -> tuple[list[Seat], str, list[str]]:
        """Let memory change what the table does this run, not just who wins.

        1. Model routes with a below-prior record (n >= 2) move to the back of each seat's failover chain.
        2. A seat whose own weight fell below ``PROBATION_BELOW`` is put on probation: its usual first
           model is swapped for the next one in its chain for this run.
        3. Source domains with a below-prior record are named in every answer prompt.
        Returns (seats for this run, prompt note, human-readable effects).
        """
        effects: list[str] = []
        demoted = trust.demoted_routes(records)
        weights = trust.seat_weights(records, [s.id for s in self.seats])
        seats = []
        for s in self.seats:
            if weights[s.id] < PROBATION_BELOW and len(s.routes) > 1:
                effects.append(f"seat {s.id} on probation (weight {weights[s.id]:.2f}): "
                               f"swapped first model {s.routes[0]} for {s.routes[1]}")
                s = Seat(s.id, s.routes[1:] + s.routes[:1], s.persona)
            keep = [r for r in s.routes if str(r) not in demoted]
            moved = [r for r in s.routes if str(r) in demoted]
            if moved and keep:
                for r in moved:
                    t = demoted[str(r)]
                    effects.append(f"seat {s.id}: demoted model {r} to last (remembered mean {t.mean:.1f}, n={t.n})")
                s = Seat(s.id, keep + moved, s.persona)
            seats.append(s)
        bad = trust.distrusted_sources(records)
        note = ""
        if bad:
            listed = ", ".join(f"{t.key} (mean {t.mean:.1f}, n={t.n})" for t in bad)
            note = ("\nThe table's memory rates these domains below an unknown source. Do NOT cite them; "
                    f"use stronger primary sources instead: {listed}.")
            effects.append(f"told every seat to avoid {len(bad)} low-trust domains: " + ", ".join(t.key for t in bad))
        return seats, note, effects

    def run(self, question: str) -> RunResult:
        qid = question_id(question)
        before, records = self.weights()
        seats, note, effects = self.plan(records)
        with ThreadPoolExecutor(max_workers=len(seats)) as pool:
            results = list(pool.map(lambda s: _ask_seat(s, question, self.chat, note), seats))
        avoided = {t.key for t in trust.distrusted_sources(records)}
        if avoided:
            stripped = []
            for r in results:
                bad = [u for u in r.sources if domain(u) in avoided]
                if bad:
                    r.sources = [u for u in r.sources if domain(u) not in avoided]
                    stripped.append(f"{r.seat}: {', '.join(sorted({domain(u) for u in bad}))}")
            effects.append("low-trust sources cited anyway, removed before grading: "
                           + ("; ".join(stripped) if stripped else "none"))

        answered = [r for r in results if r.answer]
        order = answered[:]
        self.rng.shuffle(order)
        for i, r in enumerate(order):
            r.label = "ABCDEFG"[i]
        block = "\n\n".join(f"Answer {r.label}:\n{r.answer}\nSources: {', '.join(r.sources) or 'none'}"
                            for r in order)
        critic_route, why, src_scores = "", "", {}
        if order:
            reply = self.critic.ask([{"role": "user", "content": CRITIC_PROMPT.format(
                question=question, answers=block)}], chat=self.chat, max_tokens=2500,
                validate=lambda t: _check_critic(extract_json(t), [r.label for r in order]))
            critic_route = str(reply.route)
            j = extract_json(reply.text)
            scores = j.get("scores") or {}
            for r in order:
                if r.label in scores:
                    r.score = _clamp(scores[r.label])
            src_scores = calibrate_source_scores({domain(k): _clamp(v) for k, v in (j.get("sources") or {}).items() if k})
            why = str(j.get("why", ""))[:300]

        scored = [r for r in results if r.score is not None]
        winner = max(scored, key=lambda r: r.score * before[r.seat]).seat if scored else None

        ts = now()
        recs: list[dict] = []
        for r in scored:
            recs.append({"kind": "seat_score", "seat": r.seat, "route": r.route, "score": r.score,
                         "weight_used": before[r.seat], "question_id": qid, "critic": critic_route, "ts": ts})
        cited = {domain(s) for r in scored for s in r.sources}
        for d, s in src_scores.items():
            match = d if d in cited else next((c for c in cited if c.endswith("." + d)), None)
            if match:  # only score sources a seat actually cited
                recs.append({"kind": "source_score", "domain": match, "score": s, "question_id": qid, "ts": ts})
        if scored:
            prev = trust.latest_snapshot(records)
            runs = (int(prev.get("runs", 0)) if prev else sum(1 for r in records if r.get("kind") == "run")) + 1
            recs.append({"kind": "run", "question": question, "question_id": qid, "winner": winner,
                         "weights_before": before, "effects": effects, "ts": ts})
            recs.append(trust.snapshot(records + recs, ts, runs))
        receipts = self.memory.remember(recs) if recs else []

        after = trust.seat_weights(records + recs, [s.id for s in self.seats])
        return RunResult(question, qid, before, after, results, critic_route, why, src_scores,
                         winner, receipts, self.memory.name, effects)


def _check_answer(text: str) -> None:
    j = extract_json(text)
    answer = str(j.get("answer", "")).strip()
    if len(answer.strip(". ")) < 8:
        raise ValueError("answer reply has no real answer (empty or placeholder)")


def _check_critic(j: dict, labels: list[str]) -> None:
    scores = j.get("scores")
    if not isinstance(scores, dict) or not any(l in scores for l in labels):
        raise ValueError("critic reply has no scores for the answers")
    src = j.get("sources") or {}
    if isinstance(src, dict) and len(src) >= 2:
        vals = []
        for v in src.values():
            try:
                vals.append(float(v))
            except (TypeError, ValueError):
                continue
        if len(vals) >= 2 and max(vals) - min(vals) < 2:
            raise ValueError(
                "critic source scores are too flat "
                f"(spread {max(vals) - min(vals):.1f} < 2); differentiate them"
            )


def _clamp(v) -> float:
    try:
        return max(0.0, min(10.0, float(v)))
    except (TypeError, ValueError):
        return 0.0


# Soft authority tiers used only when a critic reply still lands flat after
# validation failover. Keeps source weights from collapsing to all-identical.
_SOURCE_TIER = {
    "nasa.gov": 9.5, "science.nasa.gov": 9.5, "noaa.gov": 9.5, "usgs.gov": 9.5,
    "who.int": 9.5, "nature.com": 9.5, "science.org": 9.5, "britannica.com": 9.0,
    "metoffice.gov.uk": 9.0, "edu": 8.5, "scijinks.gov": 7.5,
    "spaceplace.nasa.gov": 7.5, "scied.ucar.edu": 7.5, "wikipedia.org": 7.0,
    "en.wikipedia.org": 7.0,
}


def calibrate_source_scores(scores: dict[str, float]) -> dict[str, float]:
    """If every source got the same score, spread them by known authority tiers."""
    if len(scores) < 2:
        return scores
    vals = list(scores.values())
    if max(vals) - min(vals) >= 2:
        return scores
    out: dict[str, float] = {}
    for d, s in scores.items():
        tier = None
        if d in _SOURCE_TIER:
            tier = _SOURCE_TIER[d]
        else:
            for suf, t in _SOURCE_TIER.items():
                if d == suf or d.endswith("." + suf) or (suf == "edu" and d.endswith(".edu")):
                    tier = t
                    break
        out[d] = round(tier if tier is not None else max(1.0, min(5.0, s * 0.5)), 1)
    # Guarantee a spread of at least 2 even for unknown domains.
    if max(out.values()) - min(out.values()) < 2:
        ranked = sorted(out.keys())
        for i, d in enumerate(ranked):
            out[d] = round(3.0 + (6.0 * i / max(1, len(ranked) - 1)), 1)
    return out
