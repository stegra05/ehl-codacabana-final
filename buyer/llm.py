"""The model writes one paragraph of each e-mail: it answers the supplier's last e-mail like a
person would (its questions, its points, its situation). Code writes everything that binds or is
checked: figures, data IDs, the proposal. A paragraph with any digit, data ID or leak is dropped
and the template stands in. Hard timeout: the move goes out without the model if it is late."""

import json
import logging
import os
import re
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

import httpx

log = logging.getLogger("buyer")
_METRICS = Counter()
_METRICS_LOCK = threading.Lock()
TIMEOUT_S = 15.0
MIN_S = 2.0  # less time than this left on the clocks: the template, no model call
# A late call is abandoned, not interrupted: it finishes in the background (httpx timeout) while
# the move goes out with the template.
POOL = ThreadPoolExecutor(max_workers=96, thread_name_prefix="model")  # 10 cases x their subagents
FORBIDDEN = re.compile(
    r"\d|\b(?:idx|quote|offer|sc|qn|po|cost|fc|news|doc|ctr):|urgent|urgency|deadline|budget|no alternative|"
    r"walk away|other options|last chance|desperate|must close|time pressure|target price",
    re.I,
)

SYSTEM = """You are a senior buyer at Hollerau Pumpenwerke, a German pump maker, writing to a supplier.
Write ONLY the middle paragraph of our reply e-mail: 2 to 4 sentences, plain text, no greeting, no
sign-off, no lists.

In it:
- answer the supplier's last e-mail like a thoughtful person: respond to what it asked and to the
  reasons it gave, using only the facts listed under WHAT WE CAN SAY;
- acknowledge its situation where the notes give one (for example cash needs, full capacity, rising
  costs, a long relationship), sincerely and briefly;
- if it asks for something we cannot give, say so kindly and point to what we do offer;
- ask one short question only if QUESTION ALLOWED is yes.

Never write any number, price, percentage, date, quantity or data ID (code adds the figures). Never
mention urgency, deadlines, a budget, our alternatives or the lack of them, a target price, or that
we will walk away. Never invent facts, promises or commitments. Be polite, factual and warm unless the
tone says firm."""


def _metric(name):
    with _METRICS_LOCK:
        _METRICS[name] += 1


def metrics_snapshot():
    """Thread-safe process counters for model reliability reports at the end of a case batch."""
    with _METRICS_LOCK:
        return dict(_METRICS)


def metrics_since(before):
    """Counter deltas and failure rates since a batch snapshot."""
    after = metrics_snapshot()
    delta = {key: after.get(key, 0) - before.get(key, 0) for key in after.keys() | before.keys()}
    for role, failures in (
        ("writer", ("timeout", "error", "rejected")),
        ("subagent", ("timeout", "error", "invalid")),
    ):
        attempts = delta.get(f"{role}.attempted", 0)
        delta[f"{role}.failure_rate"] = (
            round(sum(delta.get(f"{role}.{failure}", 0) for failure in failures) / attempts, 3) if attempts else None
        )
    return delta


def complete_from_env():
    """(system, user) -> text with the team's model over an OpenAI-compatible chat completions
    endpoint (`LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY`, `LLM_EFFORT`), or None when not configured."""
    model, key = os.environ.get("LLM_MODEL"), os.environ.get("LLM_API_KEY")
    if not model or not key:
        return None
    base = os.environ.get("LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    client = httpx.Client(timeout=TIMEOUT_S, headers={"Authorization": f"Bearer {key}"})

    effort = os.environ.get("LLM_EFFORT", "low")

    def complete(system, user):
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        body = {"model": model, "messages": messages, "reasoning_effort": effort}
        r = client.post(f"{base}/chat/completions", json=body)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]

    return complete


def submit(complete, system, user):
    """A subagent's call in the background (several run at once): a future for `read_json`."""
    return POOL.submit(complete, system, user) if complete else None


def read_json(future, timeout=TIMEOUT_S):
    """A subagent's answer as a dict within `timeout` seconds, or None (no model, late, broken, not
    JSON). The caller clamps every value: nothing a model returns binds us unchecked."""
    if future is None or timeout <= 0:
        _metric("subagent.unavailable")
        return None
    _metric("subagent.attempted")
    try:
        text = future.result(timeout=timeout) or ""
    except TimeoutError as e:
        _metric("subagent.timeout")
        log.warning("subagent timed out: %s", e)
        return None
    except Exception as e:  # noqa: BLE001 - a slow or broken model must not cost the move
        _metric("subagent.error")
        log.warning("subagent failed: %r", e)
        return None
    try:
        out = json.loads(text[text.index("{") : text.rindex("}") + 1])
    except (ValueError, TypeError, AttributeError):
        _metric("subagent.invalid")
        log.warning("subagent returned invalid JSON")
        return None
    if not isinstance(out, dict):
        _metric("subagent.invalid")
        return None
    _metric("subagent.success")
    return out


def ask_json(complete, system, user, timeout=TIMEOUT_S):
    if timeout < MIN_S:
        _metric("subagent.skipped_deadline")
        return None
    if complete is None:
        _metric("subagent.disabled")
        return None
    return read_json(submit(complete, system, user), timeout)


def paragraph(complete, brief, timeout=TIMEOUT_S):
    """The model's paragraph for this brief within `timeout` seconds of wall clock, or None (no
    model, no time, late, broken or unsafe)."""
    if complete is None:
        _metric("writer.disabled")
        return None
    if timeout < MIN_S:
        _metric("writer.skipped_deadline")
        log.warning("writer skipped: %.1fs left on the clocks", timeout)
        return None
    t0 = time.monotonic()
    _metric("writer.attempted")
    try:
        text = (POOL.submit(complete, SYSTEM, brief).result(timeout=min(timeout, TIMEOUT_S)) or "").strip()
    except TimeoutError as e:
        _metric("writer.timeout")
        log.warning("writer model timed out after %.1fs: %s", time.monotonic() - t0, e)
        return None
    except Exception as e:  # noqa: BLE001 - a slow or broken model must not cost the move
        _metric("writer.error")
        log.warning("writer model failed after %.1fs: %s", time.monotonic() - t0, e)
        return None
    text = " ".join(text.split())
    if not text or len(text) > 900 or FORBIDDEN.search(text):
        _metric("writer.rejected")
        log.warning("writer paragraph dropped: %r", text[:200])
        return None
    _metric("writer.success")
    log.info("writer paragraph in %.1fs", time.monotonic() - t0)
    return text
