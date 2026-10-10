"""The team's model over an OpenAI-compatible chat completions endpoint. It negotiates (`brain.py`):
one JSON answer per move under a strict schema, with a hard timeout. A late call is abandoned, not
interrupted: it finishes in the background (httpx timeout) while the move goes out from the code
policy. Prose the model writes is checked here: no figure, data ID or leak reaches an e-mail."""

import json
import logging
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor

import httpx

log = logging.getLogger("buyer")
TIMEOUT_S = 20.0
MIN_S = 3.0  # less time than this left on the clocks: no model call, the code policy moves
POOL = ThreadPoolExecutor(max_workers=32, thread_name_prefix="model")
FORBIDDEN = re.compile(
    r"\d|\b(?:idx|quote|offer|sc|qn|po|cost|fc|news|doc|ctr|sup|part):|urgent|urgency|deadline|budget|"
    r"no alternative|walk away|other options|last chance|desperate|must close|time pressure|target price",
    re.I,
)
YEAR = re.compile(r"\b(?:19|20)\d\d\b")  # "since 2022" is not a figure the arena checks


def complete_from_env():
    """(system, user, schema) -> text with `LLM_MODEL` at `LLM_BASE_URL` (`LLM_API_KEY`,
    `LLM_EFFORT`, default low), or None when not configured. With a schema the answer is JSON."""
    model, key = os.environ.get("LLM_MODEL"), os.environ.get("LLM_API_KEY")
    if not model or not key:
        return None
    base = os.environ.get("LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    client = httpx.Client(timeout=TIMEOUT_S + 10, headers={"Authorization": f"Bearer {key}"})
    effort = os.environ.get("LLM_EFFORT", "low")

    def complete(system, user, schema=None):
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        body = {"model": model, "messages": messages, "reasoning_effort": effort}
        if schema:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "answer", "strict": True, "schema": schema},
            }
        r = client.post(f"{base}/chat/completions", json=body)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]

    return complete


def call_json(complete, system, user, schema, timeout=TIMEOUT_S):
    """The model's JSON answer within `timeout` seconds of wall clock, or None (no model, no time,
    late, broken)."""
    if complete is None:
        return None
    if timeout < MIN_S:
        log.warning("model skipped: %.1fs left on the clocks", timeout)
        return None
    t0 = time.monotonic()
    try:
        text = POOL.submit(complete, system, user, schema).result(timeout=min(timeout, TIMEOUT_S))
        out = json.loads(text)
    except Exception as e:  # noqa: BLE001 - a slow or broken model must not cost the move
        log.warning("model failed after %.1fs: %s", time.monotonic() - t0, e)
        return None
    log.info("model answered in %.1fs", time.monotonic() - t0)
    return out if isinstance(out, dict) else None


GREETING = re.compile(r"^(?:dear|hello|hi|guten tag)\b[^,\n]{0,60},\s*", re.I)
SIGNOFF = re.compile(r"\s*(?:kind|best|warm)? ?regards\b.*$", re.I)


def prose(text, limit=1200):
    """The model's words for an e-mail without its own greeting or sign-off (code writes both), or
    None when they carry a figure, a data ID or a leak."""
    text = SIGNOFF.sub("", GREETING.sub("", " ".join((text or "").split())))
    if not text or len(text) > limit or FORBIDDEN.search(YEAR.sub("", text)):
        return None
    return text


PING = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"], "additionalProperties": False}


def preflight(complete):
    """One small call before any case opens: the model is configured, reachable and answers JSON."""
    if complete is None:
        raise SystemExit("no model: set LLM_MODEL and LLM_API_KEY in .env (or pass --no-llm)")
    t0 = time.monotonic()
    if not (call_json(complete, "Answer with JSON.", 'Reply {"ok": true}.', PING) or {}).get("ok"):
        raise SystemExit("the model did not answer the pre-flight call")
    log.warning("model ready in %.1fs", time.monotonic() - t0)
