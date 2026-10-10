"""What the model knows about one supplier thread, built once at setup by code: the case and its
rates, the supplier's quote, our estimate of its economics, the lever table (every allowed term
row priced at the supplier's own valuation, with our total cost C), its texts and history, and
the claim bank. Every figure here comes from `economics` or the data; the model picks from it.
The text is stable over the thread, so the provider caches it as a prompt prefix."""

import json
import math

from . import economics as eco
from .personas import supplier_texts
from .writer import OWNERS, TRAITS

ROWS = 8  # lever rows shown besides our planned terms and the quote's own
TEXT_CHARS, TEXTS_CHARS = 700, 5000


def euro(x):
    return "n/a" if x is None or not math.isfinite(x) else f"{x:,.0f}"


def lever_rows(case, s, quote):
    """{key: non-price terms}, our planned terms first (L1), the quote's own next (L2, when allowed),
    then the rows with the lowest C at the value of our opening price."""
    anchor = eco.value(case, eco.at_price(s.terms, s.anchor), s.est)
    seen, rows = set(), []

    def add(terms):
        terms = eco.complete_offer(case, terms)
        key = repr(sorted((k, repr(v)) for k, v in terms.items() if k != "unit_price"))
        if key in seen or not eco.must_haves_ok(case, terms, s.std):
            return
        seen.add(key)
        price = eco.price_for_value(case, terms, s.est, anchor)
        rows.append((eco.cost(case, eco.at_price(terms, price), s.std, s.est), terms))

    add(s.terms)
    if eco.quoted_offer(case, quote, s.std):
        add(eco.quoted_offer(case, quote, s.std))
    first = len(rows)
    for combo in eco.options(case):
        add({**s.terms, **combo})
    rows = rows[:first] + sorted(rows[first:], key=lambda r: r[0])[:ROWS]
    return {f"L{i + 1}": terms for i, (_, terms) in enumerate(rows)}


def row_line(case, s, key, terms, quote):
    """A lever row at two levels of the supplier's value: its quote and our opening price."""
    cells = []
    for name, ref in (("its quote", quote), ("our opening", eco.at_price(s.terms, s.anchor))):
        price = round(eco.price_for_value(case, terms, s.est, eco.value(case, ref, s.est)), 2)
        c = eco.cost(case, eco.at_price(terms, price), s.std, s.est)
        cells.append(f"at the value of {name}: price {price}, C EUR {euro(c)}")
    return f"{key}: {terms_text(case, terms)} | " + " | ".join(cells)


def terms_text(case, terms):
    return ", ".join(f"{k}={json.dumps(v)}" for k, v in terms.items() if k in case["negotiable"] and k != "unit_price")


def build(neg, s, quote, events):
    """The dossier text for supplier `s`; sets `s.rows` (lever key -> terms) for the guard."""
    case, b = neg.case, neg.case["buyer"]
    s.rows = lever_rows(case, s, quote)
    c_quote = eco.cost(case, quote, s.std, s.est)
    c_alt = eco.c_alt(case)
    out = [
        "# CASE",
        f"{case.get('title')} ({case.get('type')}). Category goal: {b.get('category_goal')}.",
        (case.get("briefing") or "").strip(),
        f"Need {b['need_per_year']} units a year over {b['horizon_years']} year(s); today's price "
        f"{b.get('current_unit_price')}; uncovered need costs {b.get('fallback_unit_price')} per unit plus "
        f"{b.get('fallback_risk_pct')} % risk. Late delivery beyond {b.get('need_lead_time_days')} days costs "
        f"EUR {b.get('late_cost_per_day')} a day. Our money costs {b.get('interest_rate')} a year "
        f"(reference payment {b.get('reference_payment_days')} days). Cost per defect EUR {b.get('cost_per_defect')}.",
        f"Negotiable: {', '.join(case['negotiable'])}. Allowed values: {json.dumps(case.get('term_options') or {})}.",
        f"Fixed: {json.dumps(case.get('fixed_terms') or {})}. Must-haves: {json.dumps(b.get('must_haves') or [])}.",
        f"Index paths over the horizon (our cost of a clause): {json.dumps(b.get('index_paths') or {})}.",
        f"Our alternative: {(b.get('alternative') or {}).get('kind')}, total cost C_alt EUR {euro(c_alt)}. "
        "No deal scores the alternative; a deal must cost less than it.",
        f"Messages per thread: {case.get('round_limit', 10)}.",
        "",
        "# ITS QUOTE",
        f"Terms: {json.dumps(quote)}. Its standard terms: {json.dumps(s.std)}.",
        f"Total cost of its quote as it stands, C_open: EUR {euro(c_quote)}. Our score is "
        "(C_open - C_deal) / (C_open - C_best): every euro of C counts, the price is only part of it.",
        "",
        "# OUR ESTIMATE OF THE SUPPLIER (code)",
        f"Full cost per unit: {s.est.get('full_cost') or 'unknown'}. Its cost of money: {s.prof.get('rate')} a year. "
        f"Overtime per day faster than quoted: {s.est.get('overtime')} of the price.",
        f"Code's opening price at L1: {s.anchor}. Its quote at L1 terms: {s.quote}."
        + (
            f" Relationship goal: below {s.target} per unit at L1 a lower price raises our C "
            "(the supplier's margin charge grows faster than the saving); never go below it."
            if s.target
            else ""
        ),
        "",
        "# LEVER TABLE",
        "Each row: allowed non-price terms; the unit price at which the row is worth exactly as much to the "
        "supplier (its cost of money, overtime, clause value) as its quote and as our opening, and our C at "
        "that price. Between rows of equal value to the supplier, the lower C is a free gain for us. Which "
        "row is best can change with the price level (coverage pays off only at a low price).",
    ]
    out += [row_line(case, s, key, terms, quote) for key, terms in s.rows.items()]
    l1 = eco.at_price(s.terms, s.anchor)
    step = eco.cost(case, l1, s.std, s.est) - eco.cost(case, eco.at_price(l1, s.anchor * 0.99), s.std, s.est)
    out.append(f"At L1 one percent off the price lowers C by EUR {euro(step)}.")
    out += ["", "# THE SUPPLIER"]
    prof = s.prof
    who = OWNERS.get(prof.get("owner_type"), "unknown ownership")
    out.append(f"{s.sid}: {who}; country {prof.get('country')}; category {prof.get('category')}.")
    traits = [f"{k}: {TRAITS.get(k, k)}" for k in prof.get("signals", [])]
    out.append("Traits from our notes: " + ("; ".join(traits) if traits else "none found."))
    out += background(neg, s.sid)
    out += ["", "# CLAIM BANK (verified sentences with figure and data ID; cite by key, each once per case)"]
    s.claim_keys = {}
    for i, c in enumerate(s.claims):
        key = f"C{i + 1}"
        s.claim_keys[key] = c
        out.append(f"{key} [{c['kind']}, strength {round(c['strength'], 1)}]: {c['text']}")
    if not s.claims:
        out.append("none")
    first = next((m for m in events if m.get("from") != "buyer"), {})
    out += ["", "# ITS OPENING E-MAIL", (first.get("body") or "")[:2500]]
    for att in first.get("attachments") or []:
        if att.get("text"):
            out += [f"[attachment {att.get('name')}]", att["text"][:2500]]
    return "\n".join(out)


def background(neg, sid):
    """Its record in our data: profile, past renewals, how we paid it, its texts."""
    pkg, out = neg.pkg, []
    if pkg is None or not pkg.lookup(sid):
        return ["Not in our data package: read it from its e-mails."]

    def rows(sql):
        try:
            return pkg.query(sql, (sid,))
        except Exception:  # noqa: BLE001 - a package without SQLite
            return []

    for r in rows(
        "SELECT staff, turnover_band, equity_ratio_pct, credit_index, credit_index_12m_ago FROM supplier_intel "
        "WHERE supplier_id = ?"
    ):
        out.append(
            f"Staff {r['staff']}, turnover {r['turnover_band']}, equity {r['equity_ratio_pct']} %, credit index "
            f"{r['credit_index']} (12 months ago {r['credit_index_12m_ago']}; lower is better)."
        )
    for r in rows("SELECT payment_days, skonto_days, skonto_pct FROM suppliers WHERE id = ?"):
        if r.get("skonto_pct"):
            out.append(f"It offers {r['skonto_pct']} % cash discount for payment within {r['skonto_days']} days.")
    late = rows(
        "SELECT AVG(julianday(paid_date) - julianday(due_date)) AS late FROM invoices "
        "WHERE supplier_id = ? AND paid_date IS NOT NULL"
    )
    if late and late[0].get("late") is not None:
        out.append(f"We paid its invoices {late[0]['late']:.0f} days after the due date on average.")
    history = rows("SELECT date, type, asked_pct, settled_pct, note FROM negotiation_history WHERE supplier_id = ?")
    if history:
        out.append("Past negotiations (asked % -> settled %):")
        out += [f"- {r['date']} {r['type']}: {r['asked_pct']} -> {r['settled_pct']} {r['note'] or ''}" for r in history]
    texts, total = [], 0
    for t in supplier_texts(pkg, sid):
        t = " ".join(t.split())[:TEXT_CHARS]
        if t and total + len(t) <= TEXTS_CHARS:
            texts.append(f"- {t}")
            total += len(t)
    if texts:
        out += ["Its letters, call notes, news and quote remarks:", *texts]
    return out
