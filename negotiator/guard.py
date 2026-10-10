"""The last check before anything leaves: no leaks, no unknown IDs, no figure the plan did not
set, every planned claim present. What fails is dropped sentence by sentence; what cannot be
repaired falls back to the template e-mail."""

import re

LEAK = re.compile(
    r"\b(urgent|urgently|deadline|budget|no alternative|only supplier|sole supplier|single[- ]source|"
    r"must close|cannot wait|as soon as possible|asap|under pressure|target price|reservation|"
    r"walk away|no other|our limit|last resort|desperate|running out)\b",
    re.I,
)
ID_RE = re.compile(r"\b(?:idx|quote|offer|sc|qn|po|cost|fc|news|doc|ctr|sup|part):[\w.:@#/-]*\w")
DECIMAL = re.compile(r"\d[\d,]*\.\d+")
SENTENCE = re.compile(r"[^.!?\n]+[.!?]?\s*")
MAX_BODY = 8000


def sentences(text):
    return [s for s in SENTENCE.findall(text) if s.strip()]


def allowed_numbers(sheets, claims):
    """Every decimal figure the plan set: sheet values and claim figures, in the forms the text may use."""
    nums = set()

    def add(v):
        if isinstance(v, bool) or not isinstance(v, int | float):
            return
        for s in (f"{v:.2f}", f"{v:.1f}", f"{v:,.2f}", f"{abs(v):.1f}", f"{abs(v):.2f}", str(v)):
            nums.add(s)

    for sheet in sheets:
        for v in sheet.values():
            add(v)
            if isinstance(v, dict):
                for x in v.values():
                    add(x)
    for c in claims:
        add(c.get("figure"))
        for m in DECIMAL.findall(c.get("sentence", "")):
            nums.add(m)
    return nums


def check(body, allowed_ids, sheets, claims):
    """A clean body, or None if nothing usable is left. Drops any sentence that leaks, cites an
    ID outside the plan or states a decimal figure the plan did not set; appends missing claims."""
    if not body or not body.strip():
        return None
    nums = allowed_numbers(sheets, claims)
    kept = []
    for s in sentences(body):
        if LEAK.search(s):
            continue
        if any(i not in allowed_ids for i in ID_RE.findall(s)):
            continue
        if any(n not in nums for n in DECIMAL.findall(s)):
            continue
        kept.append(s)
    text = "".join(kept).strip()
    for c in claims:
        if not all(i in text for i in c["ids"]):
            text = f"{text}\n{c['sentence']}" if text else c["sentence"]
    text = re.sub(r"[ \t]+\n", "\n", text)
    if len(text) < 40:
        return None
    return text[:MAX_BODY]


def template(name, sheets_text, claims, question, ack=None, opening=False, tone="neutral"):
    """A deterministic e-mail: what goes out when the model is slow, down or unusable."""
    hello = f"Dear {name} team," if tone != "firm" else "Dear Sir or Madam,"
    thanks = "thank you for your quote." if opening else "thank you for your reply."
    lines = [hello, "", thanks]
    if ack:
        lines.append(ack)
    lines += [c["sentence"] for c in claims]
    if sheets_text:
        lines.append("")
        lines.append("We can go ahead on one of these packages:")
        lines += [f"- {t}" for t in sheets_text]
    if question:
        lines += ["", question]
    close = (
        "We value the cooperation and look forward to your reply."
        if tone == "warm"
        else "We look forward to your reply."
    )
    lines += ["", close, "", "Kind regards", "Hollerau Pumpenwerke, Purchasing"]
    return "\n".join(lines)
