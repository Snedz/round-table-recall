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
Then list up to 3 real sources you rely on, as full URLs.
Reply with one JSON object only, with two keys: "answer" (your answer as a
string) and "sources" (a list of URL strings).

Question: {question}"""

CRITIC_PROMPT = """You are a strict grader for a research round table.
Score each anonymous answer 0-10 for factual accuracy, directness and honesty
about uncertainty. Also score each cited source domain 0-10 for how reliable
it is for this question. Be decisive: use the full range.
Reply ONLY with JSON:
one object with keys "scores" (answer letter -> number), "sources"
(domain -> number), "best" (a letter) and "why" (one sentence).

Question: {question}

{answers}"""


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


def question_id(q: str) -> str:
    return hashlib.sha256(q.strip().lower().encode()).hexdigest()[:12]


def domain(url: str) -> str:
    host = urlparse(url if "://" in url else f"https://{url}").netloc.lower()
    return host[4:] if host.startswith("www.") else host


def _ask_seat(seat: Seat, question: str, chat: ChatFn) -> SeatResult:
    res = SeatResult(seat=seat.id)
    try:
        reply = seat.ask([{"role": "user", "content": ANSWER_PROMPT.format(persona=seat.persona,
                                                                            question=question)}], chat=chat,
                         validate=_check_answer)
    except ProviderUnavailable as e:
        res.error = str(e)[:300]
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

    def run(self, question: str) -> RunResult:
        qid = question_id(question)
        before, records = self.weights()
        with ThreadPoolExecutor(max_workers=len(self.seats)) as pool:
            results = list(pool.map(lambda s: _ask_seat(s, question, self.chat), self.seats))

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
            src_scores = {domain(k): _clamp(v) for k, v in (j.get("sources") or {}).items() if k}
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
            recs.append({"kind": "run", "question": question, "question_id": qid, "winner": winner,
                         "weights_before": before, "ts": ts})
        receipts = self.memory.remember(recs) if recs else []

        after = trust.seat_weights(records + recs, [s.id for s in self.seats])
        return RunResult(question, qid, before, after, results, critic_route, why, src_scores,
                         winner, receipts, self.memory.name)


def _check_answer(text: str) -> None:
    j = extract_json(text)
    answer = str(j.get("answer", "")).strip()
    if len(answer.strip(". ")) < 8:
        raise ValueError("answer reply has no real answer (empty or placeholder)")


def _check_critic(j: dict, labels: list[str]) -> None:
    scores = j.get("scores")
    if not isinstance(scores, dict) or not any(l in scores for l in labels):
        raise ValueError("critic reply has no scores for the answers")


def _clamp(v) -> float:
    try:
        return max(0.0, min(10.0, float(v)))
    except (TypeError, ValueError):
        return 0.0
