"""Free-model seats over OpenAI-compatible chat APIs, with cross-provider failover."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Callable, Protocol

import requests

from . import config


@dataclass(frozen=True)
class Provider:
    name: str
    base_url: str
    key_var: str | None  # env var holding the key; None means no key needed

    def headers(self) -> dict[str, str]:
        h = {"content-type": "application/json"}
        if self.key_var:
            key = config.get(self.key_var)
            if not key:
                raise ProviderUnavailable(f"{self.name}: {self.key_var} not set")
            h["authorization"] = f"Bearer {key}"
        return h


PROVIDERS = {
    "nim": Provider("nim", "https://integrate.api.nvidia.com/v1", "NVIDIA_API_KEY"),
    "openrouter": Provider("openrouter", "https://openrouter.ai/api/v1", "OPENROUTER_API_KEY"),
    # opencode Zen free models; anonymous use is allowed until the free quota runs out.
    "zen": Provider("zen", "https://opencode.ai/zen/v1", None),
}


class ProviderUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class Route:
    provider: str
    model: str

    def __str__(self) -> str:
        return f"{self.provider}:{self.model}"


@dataclass
class Reply:
    text: str
    route: Route
    latency_s: float
    tried: list[str] = field(default_factory=list)


class ChatFn(Protocol):
    def __call__(self, route: Route, messages: list[dict], max_tokens: int, timeout: float) -> str: ...


def http_chat(route: Route, messages: list[dict], max_tokens: int, timeout: float) -> str:
    prov = PROVIDERS[route.provider]
    system = {"role": "system", "content": "Output only the final JSON the user asks for. detailed thinking off"}
    body = {"model": route.model, "messages": [system, *messages], "max_tokens": max_tokens, "temperature": 0.3}
    r = requests.post(f"{prov.base_url}/chat/completions", headers=prov.headers(), json=body, timeout=timeout)
    if r.status_code != 200:
        raise ProviderUnavailable(f"HTTP {r.status_code} {r.text[:90]}")
    try:
        msg = r.json()["choices"][0]["message"]
    except (ValueError, KeyError, IndexError) as e:
        raise ProviderUnavailable(f"{route}: bad response ({e})") from e
    text = msg.get("content") or msg.get("reasoning_content") or msg.get("reasoning") or ""
    if not text.strip():
        raise ProviderUnavailable(f"{route}: empty reply")
    return text


@dataclass
class Seat:
    """A named seat at the table. Its identity (``id``) is what the trust ledger scores."""

    id: str
    routes: list[Route]
    persona: str = "a careful research analyst"

    def ask(self, messages: list[dict], *, chat: ChatFn = http_chat, max_tokens: int = 2500,
            timeout: float = 90.0, validate: Callable[[str], object] | None = None) -> Reply:
        """Try each route in order. ``validate`` may raise ValueError to reject a reply and fail over."""
        tried: list[str] = []
        start = time.monotonic()
        for route in self.routes:
            try:
                text = chat(route, messages, max_tokens, timeout)
                if validate is not None:
                    try:
                        validate(text)
                    except ValueError as e:
                        tried.append(f"{route} -> rejected: {e}")
                        continue
                return Reply(text=text, route=route, latency_s=time.monotonic() - start, tried=tried)
            except (ProviderUnavailable, requests.RequestException) as e:
                msg = "timeout" if isinstance(e, requests.Timeout) else str(e)[:100]
                tried.append(f"{route} -> {msg}")
        raise ProviderUnavailable(f"seat {self.id}: all routes failed: " + " | ".join(tried))


def default_seats() -> tuple[list[Seat], Seat]:
    """Three answer seats, each led by a different provider, plus a critic seat.

    Every seat fails over across providers, so one exhausted free tier does
    not take a seat off the table. The route that actually answered is
    recorded with each memory. OpenRouter :free model IDs are the ones that
    answered live on 2026-11-09 evening (gemma-4 :free was 429).
    """
    R = Route
    seats = [
        Seat("atlas", [R("openrouter", "dots-studio/dots-3-note-preview:free"),
                       R("nim", "mistralai/mistral-large-4-1t-a52b"),
                       R("zen", "glm-5.3-flash-free"),
                       R("nim", "stepfun-ai/step-5-preview")],
             persona="a methodical encyclopedist who prefers primary sources"),
        Seat("vega", [R("openrouter", "nvidia/nemotron-3.5-lightning:free"),
                      R("zen", "nemotron-3.5-lightning-free"),
                      R("nim", "nvidia/nemotron-3.5-lightning-30b-a3b"),
                      R("nim", "stepfun-ai/step-5-preview")],
             persona="a fast fact-checker who answers briefly"),
        Seat("orion", [R("openrouter", "recursive/flint-v1.0:free"),
                       R("openrouter", "cohere/north-mini-code:free"),
                       R("zen", "mimo-v2.6-flash-free"),
                       R("nim", "minimaxai/minimax-m3.1-flash")],
             persona="a contrarian who looks for the common misconception"),
    ]
    critic = Seat("critic", [R("openrouter", "nvidia/nemotron-3-ultra-550b-a55b:free"),
                             R("openrouter", "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free"),
                             R("nim", "nvidia/nemotron-3-ultra-550b-a55b"),
                             R("nim", "stepfun-ai/step-5-preview"),
                             R("zen", "big-pickle")],
                  persona="a strict grader")
    return seats, critic


def extract_json(text: str) -> dict:
    """Return the LAST complete JSON object in a model reply.

    Reasoning models often echo the requested format before the real answer,
    so the last object is the one that counts. Code fences and prose are ignored.
    """
    t = text.replace("```json", "```").replace("```", "\n")
    found: dict | None = None
    i = t.find("{")
    while i != -1:
        depth, in_str, esc = 0, False, False
        end = -1
        for j in range(i, len(t)):
            ch = t[j]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
            elif ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end = j
                    break
        if end != -1:
            try:
                obj = json.loads(t[i:end + 1])
                if isinstance(obj, dict):
                    found = obj
                    i = t.find("{", end + 1)
                    continue
            except json.JSONDecodeError:
                pass
        i = t.find("{", i + 1)
    if found is None:
        raise ValueError("no JSON object in reply")
    return found
