"""The demo bidding before the real one: a supplier subagent and a buyer subagent argue the case
against each other. The supplier, in character and knowing what our analysts found, says which
arguments it will bring, which weak points it hopes we miss and what it would give price for. The
buyer answers each argument and picks the weak points to press. What comes out is a playbook for
the real bidding: the live analyst matches a supplier e-mail to one of the expected arguments and
the writer gets our prepared answer. Words only: every price and term stays with code, and a line
with a figure in it is dropped (the writer may not use one)."""

import re

SUPPLIER = """You play the sales lead of a supplier in a rehearsal of a negotiation with your customer
Hollerau Pumpenwerke. Below is the case and what the customer's analysts found out about your
company. Stay in character and be honest with yourself: this rehearsal is private.
Return JSON only:
{"arguments": the up to 4 arguments you will bring to defend your price or refuse a request, one
  sentence each, strongest first,
 "weak_points": the up to 3 points in your position you hope the customer does not raise, one
  sentence each,
 "wants": the up to 3 things other than price you would give a better price for, one short phrase each}
Write no figures, dates or names."""

BUYER = """You are the senior buyer of Hollerau Pumpenwerke in a rehearsal of a negotiation. Below is
the case, what our analysts found, and what the supplier's sales lead said in the rehearsal: the
arguments it will bring and the weak points it hopes we miss.
Find our best answer to each of its arguments: reasoning that is fair, factual and hard to
dismiss. An answer may acknowledge its point, put it in proportion and point to what we already
bring (our full volume, a long term, reliable payment). An answer never promises or offers
anything new, sets no condition, and is never a threat, a deadline, a bluff or a request for its
cost breakdown (all tested, none works).
Return JSON only:
{"rebuttals": one object per supplier argument, {"to": the argument's number, "answer": our answer
  in one or two sentences},
 "press": the up to 2 weak points worth raising, each as one polite, respectful sentence we could
  write, taken only from what the analysts found, never about its finances; [] when the analysts
  found nothing}
Write no figures, dates or names: code adds the data."""

DIGIT = re.compile(r"\d")


def lines(value, limit, chars=260):
    """A subagent's list as clean sentences: strings only, no figures, capped in number and length."""
    out = []
    for item in value if isinstance(value, list) else []:
        text = " ".join(str(item).split())[:chars] if isinstance(item, str) else ""
        if text and not DIGIT.search(text):
            out.append(text)
    return out[:limit]


def supplier_view(raw):
    """What the supplier subagent said, clamped."""
    raw = raw or {}
    return {
        "arguments": lines(raw.get("arguments"), 4),
        "weak_points": lines(raw.get("weak_points"), 3),
        "wants": lines(raw.get("wants"), 3, 80),
    }


def exchange(view):
    """The supplier's side of the rehearsal as the buyer subagent reads it."""
    numbered = "\n".join(f"{i}. {a}" for i, a in enumerate(view["arguments"], 1))
    weak = "\n".join(f"- {w}" for w in view["weak_points"])
    return f"THE SUPPLIER'S ARGUMENTS:\n{numbered}\nWEAK POINTS IT HOPES WE MISS:\n{weak or '- none named'}"


def playbook(view, raw, informed=True):
    """The rehearsal's result: each expected argument with our answer ("" when the buyer found
    none), the weak points to press and what the supplier wants besides price. `informed`: our
    analysts had data on this supplier; without it a "weak point" is a guess, and we never write
    a supplier something our records do not show."""
    raw = raw or {}
    answers = {}
    for r in raw.get("rebuttals") if isinstance(raw.get("rebuttals"), list) else []:
        if isinstance(r, dict) and isinstance(r.get("to"), int) and lines([r.get("answer")], 1, 400):
            answers[r["to"]] = lines([r["answer"]], 1, 400)[0]
    return {
        "arguments": view["arguments"],
        "rebuttals": [answers.get(i, "") for i in range(1, len(view["arguments"]) + 1)],
        "press": lines(raw.get("press"), 2) if informed else [],
        "wants": view["wants"],
    }
