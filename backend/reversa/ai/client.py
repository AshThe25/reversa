"""Language-model access.

Three rules govern everything that goes through here.

**The model never returns prose we act on.** Every call demands JSON against a
schema the caller supplies. Output that does not parse or does not validate is
discarded, not salvaged - a partially-understood instruction about money is
worse than none.

**Untrusted text goes in a nonce-delimited data block, never the instruction
channel.** See `security/sanitize.py`. Customer names and order notes are things
other people wrote.

**Nothing here authorises anything.** The model's output is a proposal that
deterministic code then evaluates, and every downstream consumer is built to
work when the model is absent, wrong, or hostile. That is what makes the first
two rules survivable if they fail.

Without an API key the client returns `None` and callers fall back to their own
deterministic path. The fallbacks are real implementations, not stubs - the
product must be demonstrable on a laptop with no credentials, and a judge should
be able to see exactly which parts needed a model and which did not.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from reversa.config import Settings, get_settings

log = logging.getLogger(__name__)

MAX_OUTPUT_TOKENS = 1600
MAX_ATTEMPTS = 2

# Published per-million-token rates for the model we call. Used only to report
# what a run cost - no billing decisions hang off it.
PRICE_PER_MTOK = {"input": 3.0, "output": 15.0}


@dataclass(slots=True)
class LLMResult:
    parsed: dict
    raw: str
    model: str
    prompt_hash: str
    latency_ms: float
    input_tokens: int
    output_tokens: int
    cost_micro_usd: int
    attempts: int
    validation_errors: list[str] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return not self.validation_errors

    def as_dict(self) -> dict:
        return {
            "model": self.model,
            "prompt_hash": self.prompt_hash,
            "latency_ms": round(self.latency_ms, 1),
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cost_micro_usd": self.cost_micro_usd,
            "attempts": self.attempts,
            "valid": self.valid,
            "validation_errors": self.validation_errors,
        }


class LLMClient:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self._client = None
        self.calls: list[dict] = []

    @property
    def available(self) -> bool:
        return self.settings.has_llm

    def _anthropic(self):
        if self._client is None:
            from anthropic import Anthropic

            self._client = Anthropic(api_key=self.settings.anthropic_api_key)
        return self._client

    def complete_json(
        self,
        *,
        system: str,
        user: str,
        validator: Callable[[Any], list[str]],
        max_tokens: int | None = None,
    ) -> LLMResult | None:
        """One structured call. Returns None when no model is configured.

        Retries once on invalid JSON or a failed schema check, feeding the errors
        back. Beyond that it gives up rather than negotiating - a model that
        cannot produce the schema twice is not going to on the third try, and the
        caller has a deterministic path anyway.
        """
        if not self.available:
            return None

        prompt_hash = hashlib.sha256(f"{system}\n{user}".encode()).hexdigest()[:16]
        messages = [{"role": "user", "content": user}]
        errors: list[str] = []
        started = time.perf_counter()

        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                response = self._anthropic().messages.create(
                    model=self.settings.llm_model,
                    max_tokens=max_tokens or MAX_OUTPUT_TOKENS,
                    system=system,
                    messages=messages,
                )
            except Exception as exc:  # network, auth, rate limit
                log.warning("llm call failed (%s); falling back to deterministic path", exc)
                return None

            raw = "".join(
                block.text for block in response.content if getattr(block, "type", "") == "text"
            )
            parsed, errors = _parse_and_validate(raw, validator)

            if parsed is not None and not errors:
                latency = (time.perf_counter() - started) * 1000
                usage = getattr(response, "usage", None)
                in_tok = getattr(usage, "input_tokens", 0) or 0
                out_tok = getattr(usage, "output_tokens", 0) or 0
                result = LLMResult(
                    parsed=parsed, raw=raw, model=self.settings.llm_model,
                    prompt_hash=prompt_hash, latency_ms=latency,
                    input_tokens=in_tok, output_tokens=out_tok,
                    cost_micro_usd=_cost_micro_usd(in_tok, out_tok),
                    attempts=attempt,
                )
                self.calls.append(result.as_dict())
                return result

            if attempt < MAX_ATTEMPTS:
                messages = messages + [
                    {"role": "assistant", "content": raw},
                    {
                        "role": "user",
                        "content": (
                            "That did not validate:\n- "
                            + "\n- ".join(errors)
                            + "\n\nReturn only the corrected JSON object."
                        ),
                    },
                ]

        log.warning("llm output failed validation after %d attempts: %s", MAX_ATTEMPTS, errors)
        return None

    def stats(self) -> dict:
        return {
            "available": self.available,
            "model": self.settings.llm_model if self.available else None,
            "calls": len(self.calls),
            "total_cost_micro_usd": sum(c["cost_micro_usd"] for c in self.calls),
            "total_latency_ms": round(sum(c["latency_ms"] for c in self.calls), 1),
        }


def _cost_micro_usd(input_tokens: int, output_tokens: int) -> int:
    dollars = (
        input_tokens / 1e6 * PRICE_PER_MTOK["input"]
        + output_tokens / 1e6 * PRICE_PER_MTOK["output"]
    )
    return int(round(dollars * 1e6))


_JSON_BLOCK = re.compile(r"\{.*\}", re.S)


def _parse_and_validate(
    raw: str, validator: Callable[[Any], list[str]]
) -> tuple[dict | None, list[str]]:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.S)

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        # Models occasionally wrap the object in commentary. Take the outermost
        # braces and try once - but only once, and only structurally. We are not
        # writing a recovery parser for arbitrary prose.
        match = _JSON_BLOCK.search(text)
        if not match:
            return None, ["output was not JSON"]
        try:
            parsed = json.loads(match.group(0))
        except json.JSONDecodeError as exc:
            return None, [f"output was not JSON: {exc}"]

    if not isinstance(parsed, dict):
        return None, ["output was not a JSON object"]
    return parsed, validator(parsed)


_client: LLMClient | None = None


def get_client() -> LLMClient:
    global _client
    if _client is None:
        _client = LLMClient()
    return _client
