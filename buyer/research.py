"""The research team, before the first e-mail: four specialist subagents each study one group of
the data about a supplier (the groups of `docs/design.md`, "What feeds the brief"), a lead
researcher consolidates their findings and past lessons into a negotiating strategy, and a
supplier and a buyer subagent rehearse the arguments against each other (`rehearsal.py`).

The strategy is about what to put on the table, not how fast to move: the terms this supplier is
likely to value more than they cost us, which arguments it will accept, the tone. Code collects
every figure a subagent sees and checks everything it returns: a proposed trade is priced with
the cost function and offered only at a price that costs us no more than our main proposal. No
brief (no model, a timeout): the plain engine."""

import json
import logging
import time

from . import llm, memory, rehearsal

log = logging.getLogger("buyer")
BUDGET_S = 40.0  # the whole team per case, before the session opens (no supplier clock runs yet)
STAGE_S = 13.0  # the specialists; then the lead and the demo supplier; then the demo buyer
TRADES = 2  # terms the lead may put next to our main proposal
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
studied one supplier before a negotiation. Consolidate their findings into a negotiating strategy.
Our price engine sets the prices and the pace; your job is what we put on the table and how we
argue.

"""
    + ARENA
    + """

Return JSON only:
{"trades": up to 2 objects {"field": a negotiable field of the case other than unit_price,
  "value": one of that field's allowed options exactly as the case lists it, "why": one short
  sentence}. A trade is a term this supplier is likely to value more than it costs us: faster
  payment for one short of cash, a later delivery or a longer contract for a full order book, an
  index clause for one exposed to a volatile material, more volume for idle machines. Code prices
  each trade and offers it next to our main proposal at a price that costs us no more, so the
  supplier's choice shows what it values. [] when the findings point to none.
 "claim_order": the kinds of argument this supplier will accept, strongest first, from: KINDS.
 "tone": "warm" or "businesslike".
 "notes": two or three sentences for the colleague who writes our e-mails: who this supplier is,
  what it cares about and what we can honestly offer it. No figures, no dates.
 "reason": one sentence on why this strategy.}"""
).replace("KINDS", ", ".join(CLAIM_KINDS))


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


def clamp(raw, case):
    """The lead's strategy with every value from the case or from its list; junk is dropped."""
    options = case.get("term_options") or {}
    trades = []
    for t in raw.get("trades") if isinstance(raw.get("trades"), list) else []:
        field = t.get("field") if isinstance(t, dict) else None
        if field in case.get("negotiable", []) and field != "unit_price" and t.get("value") in options.get(field, []):
            trades.append({"field": field, "value": t["value"], "why": " ".join(str(t.get("why") or "").split())[:160]})
    order = raw.get("claim_order")
    return {
        "trades": trades[:TRADES],
        "claim_order": [k for k in order if k in CLAIM_KINDS] if isinstance(order, list) else [],
        "tone": raw.get("tone") if raw.get("tone") in ("warm", "businesslike") else None,
        "notes": " ".join(str(raw.get("notes") or "").split())[:600],
        "reason": str(raw.get("reason") or "")[:300],
    }


def briefs(case, pkg, complete, budget_s=BUDGET_S):
    """{supplier_id: brief} for a case: the specialists' findings, the lead's checked strategy and
    the demo bidding's playbook. {} without a model; a supplier whose lead was late has no brief."""
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
        second[sid] = (findings, user, llm.submit(complete, LEAD, user), llm.submit(complete, rehearsal.SUPPLIER, user))
    stage = min(end, time.monotonic() + STAGE_S)
    third = {}
    for sid, (findings, user, lead, supplier) in second.items():
        strategy = llm.read_json(lead, stage - time.monotonic())
        view = rehearsal.supplier_view(llm.read_json(supplier, stage - time.monotonic()))
        buyer = None
        if view["arguments"]:  # the demo bidding's second half: our side answers its arguments
            buyer = llm.submit(complete, rehearsal.BUYER, f"{user}\n\n{rehearsal.exchange(view)}")
        third[sid] = (findings, strategy, view, buyer)
    stage = min(end, time.monotonic() + STAGE_S)
    out = {}
    for sid, (findings, strategy, view, buyer) in third.items():
        if strategy is None:
            continue
        out[sid] = {
            **clamp(strategy, case),
            "playbook": rehearsal.playbook(
                view, llm.read_json(buyer, stage - time.monotonic()), any(findings.values())
            ),
            "findings": {g: f.get("findings") for g, f in findings.items() if f.get("findings")},
        }
    log.info("%s research in %.1fs: %s", case["case_id"], time.monotonic() - t0, json.dumps(out, ensure_ascii=False))
    CACHE[case["case_id"]] = out
    return out
