"""The live analyst: reads each supplier e-mail as it arrives (the opening quote included) and
tells the bidder who is writing and where the talks stand, so the strategy follows the supplier we
actually meet and not only the one in our files. It returns asks and a mood from fixed lists plus
notes for the e-mail writer; the policy decides what each of them changes. Traits that move
anchors or rates stay with the patterns in `personas.py`: a model's guess there costs too much."""

from . import llm

TIMEOUT_S = 6.0
MOODS = ("open", "firm", "closing")
ASKS = ("volume", "proof", "payment", "target")  # the kinds `policy.asks` reads

SYSTEM = (
    """You are the analyst next to our buyer at Hollerau Pumpenwerke during a price negotiation.
Read the supplier's latest e-mail and say who is writing and where the talks stand.
Return JSON only:
{"asks": what it asks of us, from this list only: ASKS.
 "mood": "open" if it signals room to move or keeps offering more, "closing" if it says or hints
  that its room or patience is nearly used up, else "firm".
 "notes": one or two sentences for the colleague who writes our reply: what this person cares
  about and how to answer them. No figures, no dates.}"""
).replace("ASKS", ", ".join(ASKS))


def read(complete, case, body, ours, theirs, timeout=TIMEOUT_S):
    """{asks, mood, notes} for a supplier e-mail, every value from its list; None when the
    model is off, late or wrong. `ours`, `theirs`: the price paths so far, for context."""
    user = (
        f"CASE: {case.get('title')} ({case.get('type')}, goal {case['buyer'].get('category_goal')})\n"
        f"OUR PRICES SO FAR: {ours}\nITS PRICES SO FAR: {theirs}\nITS E-MAIL:\n{(body or '')[:2500]}"
    )
    raw = llm.ask_json(complete, SYSTEM, user, min(timeout, TIMEOUT_S))
    if raw is None:
        return None

    def listed(key, allowed):
        value = raw.get(key)
        return [v for v in value if v in allowed] if isinstance(value, list) else []

    return {
        "asks": listed("asks", ASKS),
        "mood": raw.get("mood") if raw.get("mood") in MOODS else "firm",
        "notes": " ".join(str(raw.get("notes") or "").split())[:400],
    }
