"""What the supplier's e-mail asks of us. The bots write their asks in a few fixed sentences
("Which volume can you commit to?", "Please send us the data.", "Faster payment would help us
more than anything"), so plain patterns read them; no model, no latency."""

import re

ASKS = {
    # a binding volume figure; stated in words with the figure, it was "taken into account" (D01, D02)
    "volume": r"volume (can )?you (can )?commit|binding (higher )?volume|higher (order )?volume|volume figures"
    r"|confirm .{0,40}volume|anticipated (order )?volume",
    # proof of the forecast or of figures we mentioned without an ID
    "proof": r"proof of|send us the data|figures is that based|provide the (volume|forecast|binding)"
    r"|forecast data|volume data",
    # it wants to be paid sooner
    "payment": r"faster payment|pay(ment)? (terms )?(earlier|faster|sooner|within)|need .{0,12}days payment"
    r"|shorter payment|quicker payment|cash flow",
    # it asks for our current price level or our target
    "target": r"what price|which price|your target|price you have in mind",
}


def asks(body):
    """The kinds of ask in a supplier e-mail, in a fixed order."""
    text = body or ""
    return [k for k, pat in ASKS.items() if re.search(pat, text, re.I)]
