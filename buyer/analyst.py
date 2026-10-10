"""The live analyst: reads each supplier e-mail as it arrives (the opening quote included) and
tells the bidder the mood of the person writing and the tactic for our next move, so the bidding
follows the supplier we actually meet and not only the one in our files. It picks out what the
supplier says would help it and the points that deserve a direct answer, and matches the e-mail
to the arguments the demo bidding expected, so the writer gets our prepared answer.
Everything it returns comes from a fixed list; the policy decides what each value changes. Traits
that move anchors or rates stay with the patterns in `personas.py`: a model's guess there costs too
much."""

import re

from . import llm

TIMEOUT_S = 6.0
MOODS = ("warm", "neutral", "irritated", "pressured")
TACTICS = ("steady", "hold", "argue")
ASKS = ("volume", "proof", "payment", "target")  # the kinds `policy.asks` reads
DIGIT = re.compile(r"\d")  # the writer may not use a figure, so a point with one is dropped

SYSTEM = """You are the analyst next to our buyer at Hollerau Pumpenwerke during a negotiation. Read
the supplier's latest e-mail and say who we are dealing with right now and what to do next.
Return JSON only:
{"mood": the mood of the person writing: "warm", "neutral", "irritated" or "pressured",
 "tactic": our best next move, one of:
   "hold" - it still concedes or signals room to move: we move less than usual,
   "argue" - it brings an argument we can answer or doubts our data: we answer it with evidence,
   "steady" - none of these,
 "argument": the number of the EXPECTED ARGUMENT its e-mail makes, or 0 if none,
 "asks": what it asks of us, from this list only: volume, proof, payment, target,
 "would_help": the TERMS OF THE CASE it explicitly says would help it, or would let it improve its
  price, if we changed them (for example "faster payment would help us", "with a longer contract
  we could do more"), as the field names listed. A term it merely lists in its offer does not
  count. [] if none,
 "points": the up to 2 things it says in this e-mail that most deserve a direct answer from us,
  each as one short sentence in its own words, without figures or dates,
 "notes": one or two sentences for the colleague who writes our reply: what this person cares
  about right now and how to answer them. No figures, no dates.}"""


def read(complete, case, body, ours, theirs, arguments=(), fields=(), timeout=TIMEOUT_S):
    """{mood, tactic, argument, asks, would_help, points, notes} for a supplier e-mail, every value from
    its list; None when the model is off, late or wrong. `ours`, `theirs`: the price paths so far;
    `arguments`: what the demo bidding expected this supplier to say (`argument` indexes them from
    1); `fields`: the case's terms it may name in `would_help`."""
    expected = "\n".join(f"{i}. {a}" for i, a in enumerate(arguments, 1)) or "none prepared"
    user = (
        f"CASE: {case.get('title')} ({case.get('type')}, goal {case['buyer'].get('category_goal')})\n"
        f"TERMS OF THE CASE: {', '.join(fields) or 'none'}\n"
        f"OUR PRICES SO FAR: {ours}\nITS PRICES SO FAR: {theirs}\nEXPECTED ARGUMENTS:\n{expected}\n"
        f"ITS E-MAIL:\n{(body or '')[:2500]}"
    )
    raw = llm.ask_json(complete, SYSTEM, user, min(timeout, TIMEOUT_S))
    if raw is None:
        return None
    asks, wants, points = raw.get("asks"), raw.get("would_help"), raw.get("points")
    points = [" ".join(p.split())[:200] for p in points if isinstance(p, str)] if isinstance(points, list) else []
    argument = raw.get("argument")
    return {
        "mood": raw.get("mood") if raw.get("mood") in MOODS else "neutral",
        "tactic": raw.get("tactic") if raw.get("tactic") in TACTICS else "steady",
        "argument": argument if isinstance(argument, int) and 0 < argument <= len(arguments) else 0,
        "asks": [a for a in asks if a in ASKS] if isinstance(asks, list) else [],
        "would_help": [w for w in wants if w in fields] if isinstance(wants, list) else [],
        "points": [p for p in points if p and not DIGIT.search(p)][:2],
        "notes": " ".join(str(raw.get("notes") or "").split())[:400],
    }
