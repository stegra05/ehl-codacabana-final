"""The research team, before the first e-mail: four specialist subagents each study one group of
the data about a supplier (the groups of `docs/design.md`, "What feeds the brief"), a lead
researcher consolidates their findings and past lessons into a bidding strategy, and a supplier
subagent writes the playbook the demo bidding (`rehearsal.py`) plays that strategy against.

Code collects every figure a subagent sees and clamps everything it returns: a brief changes how
the price engine opens and paces, which arguments come first and what the e-mail writer knows.
It never sets a price, a term or an accept. No brief (no model, a timeout): the plain engine."""

import json
import logging
import time

from . import llm, memory
from .rehearsal import blend, clamp_model

log = logging.getLogger("buyer")
BUDGET_S = 40.0  # the whole team per case, before the session opens (no supplier clock runs yet)
PLAYBOOKS = 3  # answers of the supplier subagent per supplier, blended (one answer alone varies too much)
STAGE_S = 15.0  # the specialists together; then the lead and the supplier subagent together
NOISE = ("holiday", "iso ", "certificate", "contact person", "packaging", "trade fair")
CLAIM_KINDS = ("should_cost", "order_history", "index", "notice", "rival", "forecast", "scorecard", "hedged")
CACHE = {}  # case_id -> briefs: a case resumed after a crash must not wait for the team again

# group -> (the data it studies, what it should find out)
GROUPS = {
    "economics": (
        "the case file, our should-cost estimate, the supplier's price history and the indices of its cost drivers",
        "how far its price sits above its cost, whether its cost drivers justify its price, "
        "and how much room there is on price",
    ),
    "persona": (
        "its company profile, its letters, our call and meeting notes, news about it and how we pay it",
        "who decides there and what moves them: cash, capacity, the relationship, approvals, frozen prices",
    ),
    "history": (
        "our past negotiations with it, our contract and its clauses, and how the part is sourced",
        "how far it usually moves from what it asks, what the contract obliges it to, and how dependent "
        "each side is on the other",
    ),
    "leverage": (
        "its delivery and quality record, our forecast, our order prices and rival quotes for the part",
        "which verified facts argue for a lower price or better terms, and which would argue its case",
    ),
}
SPECIALIST = """You are the {name} analyst in the purchasing team of Hollerau Pumpenwerke, a German pump
maker. Before we negotiate with a supplier you study one group of our data: {scope}.
From the data below report {goal}.
Use only the data given. When it says nothing useful, return no findings.
Return JSON only: {{"findings": [up to 4 short sentences, the most important first],
"leverage": "ours" | "balanced" | "theirs"}}"""

ARENA = """What we know about how these suppliers negotiate:
- Their first counter is a cap plus the verified arguments they accept, not a reaction to how low we
  open. Opening far below the quote buys nothing and costs patience.
- After that they concede a shrinking step per round, only after a move from us, and stop after a
  few counters with a final offer. They agree the moment our price reaches the counter they would make.
- Typical: a foundry or family firm with rising wages drops about 3 % first and then small steps
  over up to 5 counters; a raw-material distributor drops 8 to 10 % first and then almost nothing;
  a small job shop with free machines drops 10 to 18 % and keeps moving; a supplier with frozen
  list prices barely moves on price; a fully booked one or one selling near its cost ends after 1
  or 2 counters.
- Patience ends at a cumulative gap of about 0.4 between our prices and theirs, 0.15 to 0.2 for a
  touchy supplier."""

LEAD = (
    """You are the lead researcher of the purchasing team of Hollerau Pumpenwerke. Your analysts
studied one supplier before a negotiation. Consolidate their findings into a bidding strategy for
our price engine, which opens below the quote and then moves a share of the gap to the supplier's
counter each round.

"""
    + ARENA
    + """

Return JSON only:
{"shift": number from -0.05 to 0, how much lower than usual we open, as a share of the quote.
  Lower only with evidence of a deep floor (a large margin over should-cost, free capacity,
  cheaper rivals). 0 when the evidence is thin or the supplier is touchy, near its cost, fully
  booked or frozen on price.
 "fraction": number from 0.2 to 0.3, the share of the gap we move per round. Low to hold out
  against a supplier that keeps conceding. Usual: 0.3.
 "claim_order": the kinds of argument this supplier will accept, strongest first, from: KINDS.
 "tone": "warm" or "businesslike".
 "notes": two or three sentences for the colleague who writes our e-mails: who this supplier is,
  what it cares about and what we can honestly offer it. No figures, no dates.
 "reason": one sentence on why this strategy.}"""
).replace("KINDS", ", ".join(CLAIM_KINDS))

SUPPLIER = (
    """You play the sales lead of a supplier in a rehearsal of a price negotiation with your
customer Hollerau Pumpenwerke. Below is what the customer's analysts found out about your company.
Stay in character: decide how you would really bid, given your costs, your order book, your cash
and how much you need this customer.

"""
    + ARENA
    + """

State your playbook. Return JSON only:
{"floor": the lowest price you would finally take, as a share of your quote (0.7 to 0.995),
 "first_drop": your first concession as a share of your quote (0 to 0.2),
 "step": the most you concede in the round after, as a share of your quote (0.001 to 0.04),
 "counters": how many counters you make before your final offer (1 to 6),
 "patience": the cumulative gap you bear before you end the talks (0.1 to 0.6),
 "eager": true if you keep lowering your price even when the customer barely moves, else false}"""
)


def rows(pkg, sql, params=(), limit=8):
    try:
        return pkg.query(sql, params, limit)
    except Exception:  # noqa: BLE001 - a package without this table: the analyst sees less
        return []


def block(title, data):
    data = [d for d in data if d]
    if not data:
        return ""
    return f"{title}:\n" + "\n".join(d if isinstance(d, str) else json.dumps(d, ensure_ascii=False) for d in data)


def case_brief(case):
    """The case as every subagent sees it."""
    b = case["buyer"]
    keep = ("category_goal", "need_per_year", "horizon_years", "current_unit_price", "must_haves")
    return block(
        "CASE",
        [
            f"{case.get('title')} ({case.get('type')})",
            case.get("briefing"),
            {k: b.get(k) for k in keep},
            {"negotiable": case.get("negotiable"), "term_options": case.get("term_options")},
        ],
    )


# group -> [(title, SQL, what the SQL is keyed on, rows)]: the tables each specialist studies
TABLES = {
    "economics": [
        (
            "OUR SHOULD-COST (EUR per unit, without margin)",
            "SELECT cost_base, supplier_id, unit_cost, material_eur, conversion_eur, overhead_eur, confidence_pct "
            "FROM should_cost WHERE part_id = ?",
            "part",
            8,
        ),
        (
            "ITS PRICES FOR THE PART",
            "SELECT valid_from, price, price_unit, basis FROM price_conditions "
            "WHERE part_id = ? AND supplier_id = ? ORDER BY valid_from DESC",
            "part_sid",
            5,
        ),
        (
            "ITS LETTER",
            "SELECT date, subject, asked_pct, asked_price, effective_date, notice_days FROM documents WHERE id = ?",
            "doc",
            1,
        ),
    ],
    "persona": [
        (
            "VENDOR MASTER",
            "SELECT name, country, payment_days, skonto_days, skonto_pct, category, abc_class "
            "FROM suppliers WHERE id = ?",
            "sid",
            1,
        ),
        (
            "COMPANY PROFILE (a lower credit index is better)",
            "SELECT legal_form, founded, owner_type, group_parent, staff, turnover_eur, equity_ratio_pct, "
            "credit_index, credit_index_12m_ago FROM supplier_intel WHERE supplier_id = ?",
            "sid",
            1,
        ),
        ("NEWS", "SELECT date, headline, body FROM news WHERE supplier_id = ? ORDER BY date DESC", "sid", 5),
        (
            "HOW WE PAY ITS INVOICES",
            "SELECT round(avg(julianday(paid_date) - julianday(due_date)), 1) AS days_late, count(*) AS invoices "
            "FROM invoices WHERE supplier_id = ? AND paid_date IS NOT NULL HAVING count(*) > 0",
            "sid",
            1,
        ),
        ("REMARKS ON ITS QUOTES", "SELECT remarks FROM quotes WHERE supplier_id = ? AND remarks != ''", "sid", 4),
    ],
    "history": [
        (
            "PAST NEGOTIATIONS (asked and settled price change in %)",
            "SELECT date, type, asked_pct, settled_pct, note FROM negotiation_history "
            "WHERE supplier_id = ? ORDER BY date DESC",
            "sid",
            10,
        ),
        (
            "CONTRACT",
            "SELECT type, valid_from, valid_to, payment_days, incoterm, notice_days, price_basis "
            "FROM contracts WHERE supplier_id = ?",
            "sid",
            2,
        ),
        (
            "CLAUSES",
            "SELECT cl.type, cl.series, cl.material_share, cl.deadband_pct, cl.days, substr(cl.text, 1, 160) AS text "
            "FROM contract_clauses cl JOIN contracts c ON c.id = cl.contract_id WHERE c.supplier_id = ?",
            "sid",
            8,
        ),
        (
            "WHO SUPPLIES THE PART",
            "SELECT supplier_id, status, quota_pct, tooling_owner FROM sourcing WHERE part_id = ?",
            "part",
            6,
        ),
    ],
    "leverage": [
        (
            "ITS SCORECARDS (on-time delivery, defects in ppm)",
            "SELECT quarter, otd_pct, ppm, qn_count, class FROM scorecards WHERE supplier_id = ? ORDER BY quarter DESC",
            "sid",
            4,
        ),
        (
            "OUR FORECAST FOR THE PART",
            "SELECT snapshot_month, qty_next_12m FROM forecasts WHERE part_id = ? ORDER BY snapshot_month DESC",
            "part",
            3,
        ),
        (
            "OUR LAST ORDERS OF THE PART FROM IT",
            "SELECT order_date, qty, price, price_unit FROM po_lines "
            "WHERE part_id = ? AND supplier_id = ? ORDER BY order_date DESC",
            "part_sid",
            4,
        ),
        (
            "QUOTES FOR THE PART (all suppliers)",
            "SELECT supplier_id, quote_date, unit_price, price_unit, lead_time_days, payment_days, awarded, remarks "
            "FROM quotes WHERE part_id = ? ORDER BY quote_date DESC",
            "part",
            8,
        ),
        (
            "WHAT WE SPEND WITH IT",
            "SELECT fiscal_year, round(sum(spend_eur)) AS our_spend_eur FROM spend_cube "
            "WHERE supplier_id = ? GROUP BY fiscal_year ORDER BY fiscal_year DESC",
            "sid",
            2,
        ),
    ],
}


def index_moves(pkg, part):
    """The part's cost drivers with each index's change over the last 12 months."""
    out = []
    for d in rows(pkg, "SELECT series_id, weight FROM cost_drivers WHERE part_id = ?", (part,)):
        sql = "SELECT value FROM index_values WHERE series_id = ? ORDER BY month DESC"
        v = rows(pkg, sql, (d["series_id"],), 13)
        if len(v) == 13 and v[12]["value"]:
            d["change_12m_pct"] = round((v[0]["value"] / v[12]["value"] - 1) * 100, 1)
        out.append(d)
    return out


def letters(pkg, sid):
    """Its latest letters and our notes on it, without the routine mail."""
    out = []
    sql = "SELECT id, date, kind, subject FROM documents WHERE supplier_id = ? ORDER BY date DESC"
    for d in rows(pkg, sql, (sid,), 30):
        if any(n in (d.get("subject") or "").lower() for n in NOISE) or len(out) >= 6:
            continue
        try:
            out.append(f"{d['date']} {d['kind']}: {pkg.document(d['id'])[:700]}")
        except Exception:  # noqa: BLE001 - a row without a readable file
            out.append(f"{d['date']} {d['kind']}: {d.get('subject')}")
    return out


def digest(pkg, case, sid, group):
    """The data one specialist studies, as text; empty when the package knows nothing here."""
    parts = case.get("parts") or []
    part = parts[0] if parts else None
    keys = {"part": (part,), "sid": (sid,), "part_sid": (part, sid), "doc": (case.get("trigger_doc"),)}
    out = [block(title, rows(pkg, sql, keys[key], limit)) for title, sql, key, limit in TABLES[group]]
    if group == "economics":
        out.append(block("COST DRIVERS OF THE PART (weight, index change over 12 months in %)", index_moves(pkg, part)))
    if group == "persona":
        out.append(block("LETTERS AND NOTES", letters(pkg, sid)))
    return "\n".join(filter(None, out))


def clamp(raw):
    """The lead's strategy with every value in range or from its list; junk falls back to usual."""

    def number(key, lo, hi, default):
        try:
            return min(hi, max(lo, float(raw.get(key, default))))
        except (TypeError, ValueError):
            return default

    def listed(key, allowed):
        value = raw.get(key)
        return [v for v in value if v in allowed] if isinstance(value, list) else []

    return {
        "shift": round(number("shift", -0.05, 0.0, 0.0), 3),
        "fraction": round(number("fraction", 0.2, 0.3, 0.3), 2),
        "claim_order": listed("claim_order", CLAIM_KINDS),
        "tone": raw.get("tone") if raw.get("tone") in ("warm", "businesslike") else None,
        "notes": " ".join(str(raw.get("notes") or "").split())[:600],
        "reason": str(raw.get("reason") or "")[:300],
    }


def briefs(case, pkg, complete, budget_s=BUDGET_S):
    """{supplier_id: brief} for a case: the specialists' findings, the lead's clamped strategy and
    the demo supplier's playbook. {} without a model; a supplier whose lead was late has no brief."""
    if complete is None:
        return {}
    if case["case_id"] in CACHE:
        return CACHE[case["case_id"]]
    t0 = time.monotonic()
    end = t0 + budget_s
    head = case_brief(case)
    suppliers = case.get("suppliers") or []
    known = pkg is not None and any(pkg.lookup(r) for r in case.get("refs") or [])
    jobs = {}
    for sid in suppliers:
        for group, (scope, goal) in GROUPS.items():
            data = digest(pkg, case, sid, group) if known else ""
            if data:
                system = SPECIALIST.format(name=group, scope=scope, goal=goal)
                jobs[sid, group] = llm.submit(complete, system, f"{head}\n\nSUPPLIER {sid}\n{data}")
    stage = min(end, time.monotonic() + STAGE_S)
    found = {key: llm.read_json(f, stage - time.monotonic()) for key, f in jobs.items()}
    lessons = memory.recall(case)
    second = {}
    for sid in suppliers:
        findings = {g: (found.get((sid, g)) or {}) for g in GROUPS}
        report = "\n".join(
            f"{g.upper()} (leverage: {f.get('leverage', 'unknown')}): "
            + " ".join(str(x) for x in f.get("findings") or [])
            for g, f in findings.items()
            if f.get("findings")
        )
        user = "\n\n".join(
            filter(
                None,
                [
                    head,
                    f"SUPPLIER {sid}, one of {len(suppliers)} in this case",
                    block("ANALYSTS", [report or "No data on this supplier: judge from the case alone."]),
                    block("LESSONS FROM EARLIER NEGOTIATIONS OF THIS KIND", lessons),
                ],
            )
        )
        playbooks = [llm.submit(complete, SUPPLIER, user) for _ in range(PLAYBOOKS)]
        second[sid] = (findings, llm.submit(complete, LEAD, user), playbooks)
    stage = min(end, time.monotonic() + STAGE_S)
    out = {}
    for sid, (findings, lead, playbooks) in second.items():
        strategy = llm.read_json(lead, stage - time.monotonic())
        answers = [llm.read_json(f, stage - time.monotonic()) for f in playbooks]
        if strategy is None:
            continue
        out[sid] = {
            **clamp(strategy),
            "model": blend([clamp_model(a) for a in answers if a]),
            "findings": {g: f.get("findings") for g, f in findings.items() if f.get("findings")},
        }
    log.info("%s research in %.1fs: %s", case["case_id"], time.monotonic() - t0, json.dumps(out, ensure_ascii=False))
    CACHE[case["case_id"]] = out
    return out
