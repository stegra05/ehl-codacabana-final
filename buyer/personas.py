"""Supplier personas: built at runtime from the data package (rules over the structured data), or a
cautious default for a supplier the data does not know, then refined from its first reply.

A persona names the archetype with its evidence, the levers the supplier answers, what to avoid,
the tone, and the relationship guard: how hard we may push a supplier we depend on. Nothing here is
keyed on a supplier ID; the rules read signals that any supplier can show."""

import re

ARCHETYPES = {
    "cash_short": {
        "levers": ["payment_days", "tooling_eur"],
        "avoid": ["asking for longer payment terms"],
        "tone": "firm",
        "about": "needs cash and work: pays for faster money with price",
    },
    "group_ladder": {
        "levers": ["effective_date", "payment_days", "contract_months"],
        "avoid": ["big jumps the rep cannot sign without the boss"],
        "tone": "neutral",
        "about": "a rep with an approval ladder: small steps, data it can forward",
    },
    "family_memory": {
        "levers": ["contract_months", "volume_per_year", "effective_date"],
        "avoid": ["threats", "an aggressive tone", "ignoring the history"],
        "tone": "warm",
        "about": "a family firm that remembers how it was treated: fairness and security move it",
    },
    "near_monopolist": {
        "levers": ["effective_date", "payment_days", "lead_time_days", "index_clause"],
        "avoid": ["bluffing an alternative", "pressure on the list price"],
        "tone": "neutral",
        "about": "single source with its own tooling: barely moves on price, moves on other terms",
    },
    "capacity_full": {
        "levers": ["volume_per_year", "contract_months", "lead_time_days"],
        "avoid": ["squeezing price on a bottleneck"],
        "tone": "warm",
        "about": "order book full: commitment and schedule flexibility are worth more than price",
    },
    "quality_troubled": {
        "levers": ["ppm_commitment", "chargeback_eur_per_complaint", "unit_price"],
        "avoid": ["ignoring quality in a price case"],
        "tone": "firm",
        "about": "red or amber scorecard: trades price for a ppm commitment and chargebacks",
    },
    "neutral": {
        "levers": ["payment_days", "contract_months"],
        "avoid": [],
        "tone": "neutral",
        "about": "no clear signal yet: probe with two packages and classify from the first reply",
    },
}
# Category strategies (company.md): categories where the relationship itself is scored.
CATEGORY_GOAL = {"castings": "stabilise", "seals": "secure_supply", "electrical": "stabilise"}
TIERS = {
    "strategic": {"protect": True, "max_price_pushes": 2, "walk_allowed": False},
    "important": {"protect": True, "max_price_pushes": 3, "walk_allowed": True},
    "standard": {"protect": False, "max_price_pushes": 6, "walk_allowed": True},
}
CASH_NEWS = {"credit_watch", "credit_downgrade", "short_time_work", "restructuring"}
FULL_NEWS = {"full_order_book", "big_order", "allocation", "chip_shortage"}
FREE_NEWS = {"free_capacity", "short_time_work"}
WORDS = {
    "cash": re.compile(r"liquidit|cash|pay(ment)? within|advance|prepay|short-time|bank", re.I),
    "approval": re.compile(r"approv|head[- ]office|management board|headquarters|group|directive", re.I),
    "memory": re.compile(r"partnership|remember|remind|loyal|years|decades|trust", re.I),
    "capacity": re.compile(r"full|capacity|backlog|allocation|lead time|book", re.I),
}
# First-reply classification: what a supplier's own words add to the data signals.
REPLY_WORDS = {
    "family_memory": re.compile(
        r"family[- ]run|family[- ]owned|generations|long relationship|trustful|partnership", re.I
    ),
    "group_ladder": re.compile(r"approv|head office|headquarters|management|my boss|the board|group", re.I),
    "capacity_full": re.compile(r"order book|fully booked|capacity is|allocation|backlog", re.I),
    "cash_short": re.compile(r"liquidity|cash flow|faster payment|prepay|advance payment", re.I),
}


def num(supplier_id):
    return supplier_id.split(":", 1)[-1]


def _doc_text(pkg, doc_id):
    try:
        return pkg.document(doc_id)
    except (FileNotFoundError, ValueError, KeyError):
        return ""


def _finish(persona, scores, signals, tier, why):
    ranked = sorted(scores.items(), key=lambda kv: -kv[1])
    archetype = ranked[0][0] if ranked[0][1] >= 0.4 else "neutral"
    secondary = ranked[1][0] if ranked[1][1] >= 0.4 and archetype != "neutral" else None
    arch = ARCHETYPES[archetype]
    levers = list(arch["levers"]) + (list(ARCHETYPES[secondary]["levers"]) if secondary else [])
    tone = "warm" if tier == "strategic" and arch["tone"] != "firm" else arch["tone"]
    if archetype == "quality_troubled" and tier == "strategic":
        tone = "neutral"
    persona.update(
        {
            "importance": {**persona.get("importance", {}), "tier": tier, "reason": why},
            "signals": signals,
            "archetype": archetype,
            "secondary": secondary,
            "archetype_scores": {k: round(v, 2) for k, v in scores.items()},
            "levers": list(dict.fromkeys(levers)),
            "avoid": list(arch["avoid"]),
            "tone": tone,
            "relationship": {**TIERS[tier], "cite_rivals": tier != "strategic"},
        }
    )
    persona.setdefault("estimate", {"interest_rate": 0.08, "country_factor": 1.0})
    persona["estimate"]["interest_rate"] = 0.15 if scores.get("cash_short", 0) >= 0.4 else 0.08
    return persona


def stranger(supplier_id, case=None, name=None):
    """A supplier the data does not know (hidden cases): a cautious persona, classified from its reply."""
    goal = (case or {}).get("buyer", {}).get("category_goal")
    tier = "strategic" if goal in ("stabilise", "secure_supply") else "standard"
    persona = {
        "supplier_id": supplier_id,
        "name": name or supplier_id,
        "country": None,
        "category": None,
        "profile": {},
        "estimate": {"interest_rate": 0.08, "country_factor": 1.0},
    }
    scores = {k: 0.0 for k in ARCHETYPES}
    return _finish(
        persona, scores, ["not in the data package"], tier, f"unknown supplier in a {goal or 'unknown'} case"
    )


def build(pkg, supplier_id, case=None):
    """The persona of one supplier from the data package, or a stranger if it is not in it."""
    q = pkg.query
    rows = q("SELECT * FROM suppliers WHERE id = ?", (supplier_id,))
    if not rows:
        return stranger(supplier_id, case)
    sup = rows[0]
    intel = (q("SELECT * FROM supplier_intel WHERE supplier_id = ?", (supplier_id,)) or [{}])[0]
    spend = {
        r["fiscal_year"]: r["spend_eur"] for r in q("SELECT * FROM spend_cube WHERE supplier_id = ?", (supplier_id,))
    }
    spend26 = spend.get("FY2026", 0.0)
    rank = q(
        "SELECT COUNT(*) + 1 AS r FROM spend_cube c JOIN suppliers s ON s.id = c.supplier_id "
        "WHERE c.fiscal_year = 'FY2026' AND s.detail = 'full' AND c.spend_eur > ?",
        (spend26,),
    )[0]["r"]
    sourcing = q("SELECT * FROM sourcing WHERE supplier_id = ?", (supplier_id,))
    single = []
    for r in sourcing:
        others = q(
            "SELECT COUNT(*) AS n FROM sourcing WHERE part_id = ? AND supplier_id <> ? AND status = 'active'",
            (r["part_id"], supplier_id),
        )[0]["n"]
        if r["status"] == "active" and others == 0:
            single.append(r["part_id"])
    tooling = [r["part_id"] for r in sourcing if r["tooling_owner"] == "supplier"]
    sc = (q("SELECT * FROM scorecards WHERE supplier_id = ? ORDER BY quarter DESC LIMIT 1", (supplier_id,)) or [None])[
        0
    ]
    late = q(
        "SELECT AVG(julianday(paid_date) - julianday(due_date)) AS d FROM invoices "
        "WHERE supplier_id = ? AND paid_date IS NOT NULL",
        (supplier_id,),
    )[0]
    hist = q(
        "SELECT asked_pct, settled_pct, note FROM negotiation_history "
        "WHERE supplier_id = ? AND type = 'annual renewal' AND settled_pct IS NOT NULL",
        (supplier_id,),
    )
    ctr = (q("SELECT * FROM contracts WHERE supplier_id = ? ORDER BY valid_to DESC LIMIT 1", (supplier_id,)) or [None])[
        0
    ]
    docs = q(
        "SELECT id, date, kind, subject FROM documents WHERE supplier_id = ? ORDER BY date DESC LIMIT 8", (supplier_id,)
    )
    notes = "\n\n".join(_doc_text(pkg, d["id"]) for d in docs[:6])
    news = q(
        "SELECT id, date, topic, headline FROM news WHERE supplier_id = ? AND topic <> 'noise' ORDER BY date DESC",
        (supplier_id,),
    )
    remark_text = " ".join(
        r["remarks"]
        for r in q(
            "SELECT remarks FROM quotes WHERE supplier_id = ? AND remarks <> '' ORDER BY quote_date DESC LIMIT 5",
            (supplier_id,),
        )
    )

    # Archetype scores: every point of evidence is a signal the persona can explain.
    scores, signals = {k: 0.0 for k in ARCHETYPES}, []

    def add(arch, points, text):
        scores[arch] += points
        signals.append(text)

    eq, ci, ci12 = intel.get("equity_ratio_pct"), intel.get("credit_index"), intel.get("credit_index_12m_ago")
    if eq is not None and eq < 28:
        add("cash_short", 0.3, f"equity ratio {eq}% (thin)")
    if ci and ci12 and ci - ci12 >= 30:
        add("cash_short", 0.3, f"credit index worsened from {ci12} to {ci}")
    for n in (n for n in news if n["topic"] in CASH_NEWS):
        add("cash_short", 0.3, f"news: {n['headline']} ({n['id']})")
    if WORDS["cash"].search(remark_text):
        add("cash_short", 0.2, "quote remarks ask for fast payment")
    if WORDS["cash"].search(notes):
        add("cash_short", 0.2, "notes mention cash or liquidity")
    if late.get("d") and late["d"] >= 8:
        add("cash_short", 0.1, f"we pay it {late['d']:.0f} days late on average")
    if intel.get("owner_type") == "group":
        add("group_ladder", 0.5, "group-owned")
    if intel.get("group_parent"):
        add("group_ladder", 0.2, f"parent: {intel['group_parent']}")
    if WORDS["approval"].search(remark_text):
        add("group_ladder", 0.3, "quote remarks cite head office or approvals")
    if WORDS["approval"].search(notes):
        add("group_ladder", 0.2, "notes mention approvals or head office")
    if intel.get("owner_type") in ("family", "founder"):
        add("family_memory", 0.4 if intel["owner_type"] == "family" else 0.25, f"{intel['owner_type']}-owned")
    if intel.get("founded") and intel["founded"] < 1990:
        add("family_memory", 0.1, f"founded {intel['founded']}")
    if WORDS["memory"].search(notes):
        add("family_memory", 0.3, "notes speak of partnership, loyalty or the past")
    if single:
        add(
            "near_monopolist",
            0.4 + (0.2 if len(single) == len(sourcing) else 0),
            f"single source for {', '.join(single)}",
        )
    if tooling:
        add("near_monopolist", 0.2, f"owns the tooling for {', '.join(tooling)}")
    settled = [h["settled_pct"] for h in hist]
    asked = [h["asked_pct"] for h in hist if h["asked_pct"] is not None]
    if settled and asked and sum(settled) / len(settled) >= sum(asked) / len(asked) - 0.2:
        add("near_monopolist", 0.2, "past renewals settled at what it asked")
    if any(n["topic"] in FULL_NEWS for n in news):
        add("capacity_full", 0.5, "news: order book full or allocation")
    if WORDS["capacity"].search(notes):
        add("capacity_full", 0.2, "notes mention capacity or lead times")
    capacity_free = any(n["topic"] in FREE_NEWS for n in news)
    if capacity_free:
        signals.append("news: free capacity (volume is a lever)")
    if sc:
        if sc["colour"] == "red":
            add("quality_troubled", 0.6, f"red scorecard {sc['quarter']}: OTD {sc['otd_pct']}%, {sc['ppm']} ppm")
        elif sc["colour"] == "amber":
            add("quality_troubled", 0.3, f"amber scorecard {sc['quarter']}: OTD {sc['otd_pct']}%, {sc['ppm']} ppm")
        if sc["open_8d_overdue"]:
            add("quality_troubled", 0.2, f"{sc['open_8d_overdue']} overdue 8D report(s)")
        if sc["ppm"] and sc["ppm"] > 1500:
            add("quality_troubled", 0.2, f"{sc['ppm']} ppm")
    for h in hist:
        if h.get("note"):
            signals.append(f"history: {h['note']}")

    goal = CATEGORY_GOAL.get(sup["category"])
    if goal and (sup["abc_class"] == "A" or rank <= 15 or single):
        tier, why = "strategic", f"{sup['category']} is a {goal} category"
    elif sup["abc_class"] == "A" or spend26 >= 500_000 or single:
        tier, why = "important", "A supplier, high spend or single source"
    else:
        tier, why = "standard", "no dependency signal"
    persona = {
        "supplier_id": supplier_id,
        "name": sup["name"],
        "country": sup["country"],
        "category": sup["category"],
        "importance": {
            "spend_eur_fy2026": round(spend26),
            "spend_rank": rank,
            "single_source_parts": single,
            "tooling_owned_by_supplier": tooling,
        },
        "profile": {
            "owner_type": intel.get("owner_type"),
            "equity_ratio_pct": eq,
            "credit_index": ci,
            "scorecard": sc and {k: sc[k] for k in ("id", "quarter", "colour", "otd_pct", "ppm", "open_8d_overdue")},
            "we_pay_late_days": round(late["d"], 1) if late.get("d") is not None else None,
            "contract": ctr and {"id": ctr["id"], "valid_to": ctr["valid_to"], "notice_days": ctr["notice_days"]},
            "settle": {
                "renewals": len(hist),
                "avg_asked_pct": round(sum(asked) / len(asked), 2) if asked else None,
                "avg_settled_pct": round(sum(settled) / len(settled), 2) if settled else None,
            },
        },
        "estimate": {
            "country_factor": {
                "DE": 1.0,
                "AT": 1.05,
                "CH": 1.1,
                "CZ": 0.82,
                "PL": 0.82,
                "HU": 0.82,
                "TR": 0.75,
                "CN": 0.7,
            }.get(sup["country"], 1.0)
        },
    }
    persona = _finish(persona, scores, signals, tier, why)
    if capacity_free and "volume_per_year" not in persona["levers"]:
        persona["levers"].insert(0, "volume_per_year")
    return persona


def refine(persona, text, reading=None):
    """Re-classify from the supplier's own words and the reader's signals: approval hints, cash
    interest, a family voice, a full order book. The tier and the guard stay as the data set them."""
    scores = dict(persona.get("archetype_scores") or {k: 0.0 for k in ARCHETYPES})
    signals = list(persona.get("signals") or [])
    for arch, rx in REPLY_WORDS.items():
        if rx.search(text or ""):
            scores[arch] = scores.get(arch, 0) + 0.4
            signals.append(f"reply: {arch.replace('_', ' ')} wording")
    reading = reading or {}
    if reading.get("needs_approval"):
        scores["group_ladder"] = scores.get("group_ladder", 0) + 0.4
        signals.append("reply: needs an approval")
    if "payment_days" in (reading.get("interested_in") or []):
        scores["cash_short"] = scores.get("cash_short", 0) + 0.3
        signals.append("reply: interested in faster payment")
    before = persona["archetype"]
    tier = persona["importance"]["tier"]
    _finish(persona, scores, signals, tier, persona["importance"].get("reason", ""))
    return persona["archetype"] != before


def lever_answered(our_sheets, their_terms):
    """Which of our sheets the supplier answered: the one whose non-price terms it matched most."""
    best, best_n = None, 0
    for sheet in our_sheets:
        n = sum(1 for k, v in sheet.items() if k != "unit_price" and their_terms.get(k) == v)
        if n > best_n:
            best, best_n = sheet, n
    return best
