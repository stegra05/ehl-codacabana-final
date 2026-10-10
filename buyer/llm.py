"""The model writes one paragraph of each e-mail: it answers the supplier's last e-mail like a
person would (its questions, its points, its situation). Code writes everything that binds or is
checked: figures, data IDs, the proposal. A paragraph with any digit, data ID or leak is dropped
and the template stands in. Hard timeout: the move goes out without the model if it is late."""

import logging
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor

import httpx

log = logging.getLogger("buyer")
TIMEOUT_S = 15.0
MIN_S = 2.0  # less time than this left on the clocks: the template, no model call
# A late call is abandoned, not interrupted: it finishes in the background (httpx timeout) while
# the move goes out with the template.
POOL = ThreadPoolExecutor(max_workers=32, thread_name_prefix="writer")
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


def paragraph(complete, brief, timeout=TIMEOUT_S):
    """The model's paragraph for this brief within `timeout` seconds of wall clock, or None (no
    model, no time, late, broken or unsafe)."""
    if complete is None:
        return None
    if timeout < MIN_S:
        log.warning("writer skipped: %.1fs left on the clocks", timeout)
        return None
    t0 = time.monotonic()
    try:
        text = (POOL.submit(complete, SYSTEM, brief).result(timeout=min(timeout, TIMEOUT_S)) or "").strip()
    except Exception as e:  # noqa: BLE001 - a slow or broken model must not cost the move
        log.warning("writer model failed after %.1fs: %s", time.monotonic() - t0, e)
        return None
    text = " ".join(text.split())
    if not text or len(text) > 900 or FORBIDDEN.search(text):
        log.warning("writer paragraph dropped: %r", text[:200])
        return None
    log.info("writer paragraph in %.1fs", time.monotonic() - t0)
    return text
