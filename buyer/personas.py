"""What the data says about a supplier before the first move: owner type, the persona traits in
its notes, letters, quote remarks and news (the package and the Sunday release alike), and from
those its cost of money. Unknown suppliers (not in the package, e.g. the sandbox) get the neutral
profile; their own e-mails are scanned for the same traits as they arrive (`signals_in`)."""

import re

# One or two fixed phrases per trait in the generated texts, widened to the word forms seen across
# the whole package (restructuring programme, lowered its rating, "nickel and alloys forward").
SIGNALS = {
    "cash_need": r"pay earlier|bank is watching|cash and the banks|within 10 days|under pressure"
    r"|restructur\w*|short-time work|lower\w* (its |their )?rating|cash is tight|we like fast payers"
    r"|negotiat\w+ with (its|their) banks|lowers our margin|loss-making|liquidity|waiting for cash",
    "spare_capacity": r"second shift has been on hold|take additional parts|looks for new customers"
    r"|free (machine )?capacity|keep (the|our) machines (busy|running)",
    "capacity_full": r"order intake is very strong|binding 12-month commitment"
    r"|cannot confirm your full forecast|fully booked|allocat\w+ (volumes|in line)|factory is super busy"
    r"|high capacity utili[sz]ation|prioriti[sz]e customers with firm",
    "open_book": r"walk (us|you) through (their|our) calculation",
    "stale_costing": r"not followed (his|its|their) material|own spreadsheet",
    "partnership_2022": r"kept supplying at the old price",
    "reference_customer": r"important reference customer",
    "approval_2pct": r"above 2 ?% need the approval|pricing committee",
    "deprioritising_us": r"reviewing small accounts|not strategic|reorganising our range"
    r"|supply from stock only|sharpens its focus|focus on customers with volume",
    "price_frozen": r"no room on price|not discounted|price list applies to all|discounts not possible"
    r"|frozen all price reductions",
    "hedged": r"bought (their|our) [\w ,]{1,40} forward|covered at fixed prices|material covered until"
    r"|secures power prices|hedged",
    "complains_late_pay": r"invoices are overdue",
}
# Cost of money per year by owner type (seen in practice: groups 4 to 7 %, family firms 7 to 8.5 %,
# founder-run job shops 12 to 17 %); a cash need adds to it.
RATE = {"group": 0.05, "private": 0.07, "family": 0.075, "founder": 0.12}
DEFAULT_RATE = 0.07


def signals_in(text):
    return sorted(k for k, pat in SIGNALS.items() if re.search(pat, text or "", re.I))


def supplier_texts(pkg, sid):
    """Every text about this supplier: its letters, call and meeting notes and news, from the
    package and the Sunday release (both reach `ids` and `document`), plus its quote remarks."""
    texts = []
    for ref in pkg.ids("doc:") + pkg.ids("news:"):
        row = pkg.lookup(ref) or {}
        if row.get("supplier") != sid and row.get("supplier_id") != sid:
            continue
        try:
            texts.append(pkg.document(ref))
        except Exception:  # noqa: BLE001 - a row without a readable file: its headline still counts
            texts.append(" ".join(str(v) for k, v in row.items() if k in ("title", "headline", "body", "subject")))
    try:
        texts += [r.get("remarks") or "" for r in pkg.query("SELECT remarks FROM quotes WHERE supplier_id = ?", (sid,))]
    except Exception:  # noqa: BLE001 - no SQLite
        pass
    return texts


def profile(pkg, sid):
    """{owner_type, country, category, signals, rate, warm}; neutral when the package does not know it."""
    out = {"owner_type": None, "country": None, "category": None, "signals": [], "rate": DEFAULT_RATE, "warm": True}
    if pkg is None or not pkg.lookup(sid):
        return out
    try:
        sup = pkg.query("SELECT country, category, skonto_days, skonto_pct FROM suppliers WHERE id = ?", (sid,))
        intel = pkg.query("SELECT owner_type, staff FROM supplier_intel WHERE supplier_id = ?", (sid,))
    except Exception:  # noqa: BLE001 - no SQLite: neutral
        return out
    sig = signals_in("\n".join(supplier_texts(pkg, sid)))
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
