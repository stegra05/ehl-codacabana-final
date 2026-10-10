"""What the supplier's reply tells us, as a fixed schema: what it asks of us, which terms it says
would improve its price (its levers), which it refuses, which of our claim kinds it counted or
dismissed, and whether this is its last word. A model reads first (unseen suppliers word things
their own way); the regex reading is the fallback when the model is absent, late or invalid. The
arena's templated lines ("We checked the price history data you cited; it holds, but it does not
change our calculation.") are the same for every supplier, so the fallback is exact on those.

Nothing here decides anything: the policy owns prices and terms, this module only reads."""

import json
import logging
import re
import time

from . import llm

log = logging.getLogger("buyer")

ASKS = ("volume", "proof", "payment", "target")
FIELDS = (
    "payment_days",
    "volume_per_year",
    "contract_months",
    "lead_time_days",
    "index_clause",
    "ppm_commitment",
    "chargeback_eur_per_complaint",
    "effective_date",
    "tooling_eur",
    "incoterm",
)
# our claim kinds (buyer/claims.py) and how the arena names them in the supplier's verdict line
KINDS = {
    "index": r"index change",
    "order_history": r"price history",
    "forecast": r"volume change|forecast",
    "scorecard": r"quality record|delivery record|delivery data",
    "should_cost": r"should.cost|cost estimate",
    "rival": r"quote|rival|offer",
    "notice": r"notice",
}
EMPTY = {"asks": [], "levers": [], "refused": [], "counted": [], "dismissed": [], "final": False, "cash": False}

# -- the regex fallback --------------------------------------------------------------------------
ASK_PATTERNS = {
    "volume": r"volume (can )?you (can )?commit|binding (higher )?volume|higher (order )?volume|volume figures"
    r"|confirm .{0,40}volume|anticipated (order )?volume",
    "proof": r"proof of|send us the data|figures is that based|provide the (volume|forecast|binding)"
    r"|forecast data|volume data",
    "payment": r"faster payment|pay(ment)? (terms )?(earlier|faster|sooner|within)|need .{0,12}days payment"
    r"|shorter payment|quicker payment|cash flow|pay (exactly )?on (the )?due date|late payments",
    "target": r"what price|which price|your target|price you have in mind",
}
LEVER_PATTERNS = {
    "payment_days": r"faster payment[^.]{0,60}(reflect|price|help)|pay(ment)? (earlier|faster|sooner)[^.]{0,40}price"
    r"|zahlungsziel[^.]{0,40}(reflect|price)",
    "volume_per_year": r"(higher|larger|binding) volume[^.]{0,60}(improve|better|price|help)",
    "contract_months": r"(longer|long-term|multi-year) (contract|commitment|term)[^.]{0,60}(improve|price|help)",
    "lead_time_days": r"(longer|later|relaxed) (lead time|delivery)[^.]{0,60}(price|overtime|help)",
    "ppm_commitment": r"ppm[^.]{0,60}(price|checks|sorting)",
}
REFUSE_PATTERNS = {
    "index_clause": r"cannot (fix|offer a fixed|maintain a fixed) price|must (apply|maintain|include) (an? |the )?"
    r"[\w -]{0,20}index clause|index-linked pricing (structure )?is essential",
    "contract_months": r"cannot (fix|maintain)[^.]{0,30}(over|for) (a |the )?\d+-month",
    "payment_days": r"(payment|zahlungsziel)[^.]{0,30}(cannot|not) (be )?(change|shorten|extend)",
    "ppm_commitment": r"ppm[^.]{0,40}(cannot|not possible)",
}
VERDICT = re.compile(
    r"we checked the (?P<kind>[\w .-]{3,40}?) data you (cited|provided); it holds"
    r"(?P<verdict>, but it does not change our calculation| and we (took|have taken) it into account)",
    re.I,
)
DISMISS_WORDS = re.compile(
    r"does not change our calculation|not our reality|does not bear on|already taken[^.]{0,30}into account"
    r"|cannot give up margin",
    re.I,
)
FINAL = re.compile(r"final offer|letztes angebot|last price|take it or leave it|absolute limit", re.I)
CASH = re.compile(
    r"cash (is )?tight|cash flow|faster payment|pay(ment)? (earlier|faster|sooner)|liquidity|banks?\b", re.I
)


def kind_of(words):
    for kind, pat in KINDS.items():
        if re.search(pat, words, re.I):
            return kind
    return None


def read_regex(body):
    text = body or ""
    out = {k: list(v) if isinstance(v, list) else v for k, v in EMPTY.items()}
    out["asks"] = [k for k, pat in ASK_PATTERNS.items() if re.search(pat, text, re.I)]
    out["levers"] = [f for f, pat in LEVER_PATTERNS.items() if re.search(pat, text, re.I)]
    out["refused"] = [f for f, pat in REFUSE_PATTERNS.items() if re.search(pat, text, re.I)]
    for m in VERDICT.finditer(text):
        kind = kind_of(m.group("kind"))
        if kind is None:
            continue
        key = "dismissed" if "does not change" in m.group("verdict").lower() else "counted"
        if kind not in out[key]:
            out[key].append(kind)
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        if DISMISS_WORDS.search(sentence):
            kind = kind_of(sentence)
            if kind and kind not in out["dismissed"]:
                out["dismissed"].append(kind)
    out["counted"] = [k for k in out["counted"] if k not in out["dismissed"]]
    out["final"] = bool(FINAL.search(text))
    out["cash"] = bool(CASH.search(text))
    return out


# -- the model reader -----------------------------------------------------------------------------
SYSTEM = f"""You read a supplier's e-mail in a B2B price negotiation and return ONLY a JSON object:
{{"asks": [...], "levers": [...], "refused": [...], "counted": [...], "dismissed": [...], "final": bool, "cash": bool}}

- asks: what it asks of us, from {list(ASKS)}: "volume" = a binding volume figure, "proof" = data or
  proof for figures we gave, "payment" = being paid sooner or on time, "target" = our target price.
- levers: term fields it says would improve its price if we moved them, from {list(FIELDS)}.
- refused: term fields it says it cannot change or will not offer (e.g. no fixed price for a long
  term means "index_clause" is required: list "index_clause"), from the same field names.
- counted: kinds of our cited data it says it took into account, from {list(KINDS)} ("index" = index
  change, "order_history" = price history / our order prices, "forecast" = volume change or
  forecast, "scorecard" = quality or delivery record, "should_cost", "rival" = another quote or
  offer, "notice" = notice period).
- dismissed: kinds it says do not change its calculation, are not its reality, or do not bear on
  the part.
- final: true if it calls this its final offer or last price.
- cash: true if it says cash is tight, asks for faster payment or mentions its banks.

Use only the e-mail. Empty lists when unsure. No prose."""


def valid(data):
    if not isinstance(data, dict):
        return None
    out = {}
    schema = (("asks", ASKS), ("levers", FIELDS), ("refused", FIELDS), ("counted", KINDS), ("dismissed", KINDS))
    for key, allowed in schema:
        vals = data.get(key) or []
        if not isinstance(vals, list):
            return None
        out[key] = [v for v in vals if isinstance(v, str) and v in allowed]
    out["final"] = bool(data.get("final", False))
    out["cash"] = bool(data.get("cash", False))
    return out


def parse(text):
    text = (text or "").strip()
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        return valid(json.loads(m.group(0)))
    except ValueError:
        return None


def read(complete, body, timeout=llm.TIMEOUT_S):
    """The reading of `body`: the model's within `timeout` seconds, else the regex fallback. Both
    are computed; where they differ the fallback is kept under `fallback` for the log."""
    fallback = read_regex(body)
    if complete is None or timeout < llm.MIN_S or not body:
        return {**fallback, "source": "regex"}
    t0 = time.monotonic()
    try:
        job = llm.POOL.submit(llm.fast(complete), SYSTEM, (body or "")[:6000])
        text = job.result(timeout=min(timeout, llm.TIMEOUT_S))
        data = parse(text)
    except Exception as e:  # noqa: BLE001 - a slow or broken model must not cost the move
        log.warning("reader model failed after %.1fs: %s", time.monotonic() - t0, e)
        data = None
    if data is None:
        log.warning("reader: regex fallback")
        return {**fallback, "source": "regex"}
    log.info("reader in %.1fs", time.monotonic() - t0)
    data["source"] = "model"
    diff = {k: fallback[k] for k in EMPTY if fallback[k] != data[k]}
    if diff:
        data["fallback"] = diff
    return data
