"""What the data says about a supplier before the first move: owner type, the persona traits in
its notes, letters, quote remarks and news, and from those its cost of money. Unknown suppliers
(not in the package, e.g. the sandbox) get the neutral profile."""

import re
from pathlib import Path

SIGNALS = {
    "cash_need": r"pay earlier|bank is watching|cash and the banks|within 10 days|under pressure"
    r"|restructures|short-time work|lowers rating|cash is tight|we like fast payers",
    "spare_capacity": r"second shift has been on hold|take additional parts|looks for new customers|free capacity",
    "capacity_full": r"order intake is very strong|binding 12-month commitment"
    r"|cannot confirm your full forecast|fully booked|allocates volumes|factory is super busy",
    "open_book": r"walk us through their calculation",
    "stale_costing": r"not followed his material|own spreadsheet",
    "partnership_2022": r"kept supplying at the old price",
    "reference_customer": r"important reference customer",
    "approval_2pct": r"above 2 % need the approval",
    "deprioritising_us": r"reviewing small accounts|not strategic|reorganising our range"
    r"|supply from stock only|sharpens its focus",
    "price_frozen": r"no room on price|not discounted|price list applies to all|discounts not possible"
    r"|frozen all price reductions",
    "hedged": r"bought their \w+ forward|covered at fixed prices|material covered until|secures power prices",
    "complains_late_pay": r"invoices are overdue",
}
# Cost of money per year by owner type (seen in practice: groups 4 to 7 %, family firms 7 to 8.5 %,
# founder-run job shops 12 to 17 %); a cash need adds to it.
RATE = {"group": 0.05, "private": 0.07, "family": 0.075, "founder": 0.12}
DEFAULT_RATE = 0.07


def signals_in(text):
    return sorted(k for k, pat in SIGNALS.items() if re.search(pat, text or "", re.I))


def profile(pkg, sid):
    """{owner_type, country, category, signals, rate, warm}; neutral when the package does not know it."""
    out = {"owner_type": None, "country": None, "category": None, "signals": [], "rate": DEFAULT_RATE, "warm": True}
    if pkg is None or not pkg.lookup(sid):
        return out
    try:
        sup = pkg.query("SELECT country, category, skonto_days, skonto_pct FROM suppliers WHERE id = ?", (sid,))
        intel = pkg.query("SELECT owner_type, staff FROM supplier_intel WHERE supplier_id = ?", (sid,))
        docs = pkg.query("SELECT file FROM documents WHERE supplier_id = ?", (sid,))
        remarks = pkg.query("SELECT remarks FROM quotes WHERE supplier_id = ?", (sid,))
        news = pkg.query("SELECT headline, body FROM news WHERE supplier_id = ?", (sid,))
    except Exception:  # noqa: BLE001 - no SQLite: neutral
        return out
    texts = [r.get("remarks") or "" for r in remarks] + [f"{n['headline']}. {n['body']}" for n in news]
    for d in docs:
        path = Path(pkg.root) / (d.get("file") or "")
        if d.get("file") and path.is_file():
            texts.append(path.read_text(encoding="utf-8", errors="replace"))
    sig = signals_in("\n".join(texts))
    owner = intel[0]["owner_type"] if intel else None
    rate = RATE.get(owner, DEFAULT_RATE)
    if "cash_need" in sig:
        rate += 0.05
    if sup and sup[0].get("skonto_pct") and sup[0].get("skonto_days"):
        # a cash discount of s % for paying d days early is worth s / d * 360 % a year to it
        days_early = max(1, 30 - int(sup[0]["skonto_days"]))
        rate = max(rate, min(0.2, sup[0]["skonto_pct"] / 100 * 360 / max(days_early, 10) / 2))
    out.update(
        owner_type=owner,
        country=sup[0]["country"] if sup else None,
        category=sup[0]["category"] if sup else None,
        signals=sig,
        rate=round(rate, 3),
        warm=owner in (None, "family", "founder", "private"),
    )
    return out
