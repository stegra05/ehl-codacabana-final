"""Supplier persona knowledge base: one JSON file per supplier under knowledge/personas/.

A persona is built offline from the data package (rules over the structured data, plus an
optional model digest of the notes and letters), loaded when a case opens, and updated after every
negotiation with what the supplier actually did. It names the archetype, the levers the supplier
answers, what to avoid, the tone, and the relationship guard: how hard we may push a supplier we
depend on. Hidden-case strangers get a persona built on the spot and are learned from the same way.
"""

import json
import re
from datetime import UTC, datetime
from pathlib import Path

KB_DIR = Path("knowledge/personas")
NEGOTIATIONS = Path("knowledge/negotiations.jsonl")

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
    "strategic": {"protect": True, "min_margin_pct": 8.0, "max_price_pushes": 2, "walk_allowed": False},
    "important": {"protect": True, "min_margin_pct": 5.0, "max_price_pushes": 3, "walk_allowed": True},
    "standard": {"protect": False, "min_margin_pct": 2.0, "max_price_pushes": 6, "walk_allowed": True},
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


def now():
    return datetime.now(UTC).isoformat(timespec="seconds")


def num(supplier_id):
    return supplier_id.split(":", 1)[-1]


def path(supplier_id):
    return KB_DIR / f"{num(supplier_id)}.json"


def load(supplier_id):
    p = path(supplier_id)
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None


def save(persona):
    KB_DIR.mkdir(parents=True, exist_ok=True)
    persona["updated"] = now()
    path(persona["supplier_id"]).write_text(json.dumps(persona, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return persona


def load_all():
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(KB_DIR.glob("*.json"))]


def _doc_text(pkg, doc_id):
    try:
        return pkg.document(doc_id)
    except (FileNotFoundError, ValueError, KeyError):
        return ""


def _fresh_learned():
    return {
        "cases": 0,
        "deals": 0,
        "walked_away": 0,
        "final_offers": 0,
        "avg_score": None,
        "claims": {"verified": 0, "contradicted": 0, "irrelevant": 0, "duplicate": 0},
        "lever_answered": {},
        "needs_approval_seen": 0,
        "moods": {},
        "notes": [],
    }


def stranger(supplier_id, case=None, name=None):
    """A supplier the data does not know (hidden cases): a cautious persona to learn from."""
    goal = (case or {}).get("buyer", {}).get("category_goal")
    tier = "strategic" if goal in ("stabilise", "secure_supply") else "standard"
    arch = ARCHETYPES["neutral"]
    return {
        "supplier_id": supplier_id,
        "name": name or supplier_id,
        "country": None,
        "category": None,
        "abc_class": None,
        "importance": {"tier": tier, "reason": f"unknown supplier in a {goal or 'unknown'} case"},
        "profile": {},
        "signals": ["not in the data package"],
        "archetype": "neutral",
        "secondary": None,
        "archetype_scores": {k: 0.0 for k in ARCHETYPES},
        "levers": list(arch["levers"]),
        "avoid": list(arch["avoid"]),
        "tone": "warm" if tier == "strategic" else arch["tone"],
        "relationship": {**TIERS[tier], "cite_rivals": tier != "strategic"},
        "estimate": {"interest_rate": 0.08, "country_factor": 1.0},
        "recent": {"documents": [], "news": []},
        "digest": None,
        "learned": _fresh_learned(),
        "negotiations": [],
        "built": now(),
        "updated": now(),
    }


def build(pkg, supplier_id, llm=None, case=None):
    """The persona of one supplier from the data package; `llm` adds a digest of its notes."""
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
        "SELECT AVG(julianday(paid_date) - julianday(due_date)) AS d, COUNT(*) AS n FROM invoices "
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
    clause = None
    if ctr:
        clause = (q("SELECT * FROM contract_clauses WHERE contract_id = ? AND type = 'index'", (ctr["id"],)) or [None])[
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
    remarks = [
        r["remarks"]
        for r in q(
            "SELECT remarks FROM quotes WHERE supplier_id = ? AND remarks <> '' ORDER BY quote_date DESC LIMIT 5",
            (supplier_id,),
        )
    ]
    remark_text = " ".join(remarks)

    # Archetype scores: every point of evidence is a signal the persona can explain.
    scores = {k: 0.0 for k in ARCHETYPES}
    signals = []

    def add(arch, points, text):
        scores[arch] += points
        signals.append(text)

    eq, ci, ci12 = intel.get("equity_ratio_pct"), intel.get("credit_index"), intel.get("credit_index_12m_ago")
    if eq is not None and eq < 28:
        add("cash_short", 0.3, f"equity ratio {eq}% (thin)")
    if ci and ci12 and ci - ci12 >= 30:
        add("cash_short", 0.3, f"credit index worsened from {ci12} to {ci}")
    cash_news = [n for n in news if n["topic"] in CASH_NEWS]
    for n in cash_news:
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

    ranked = sorted(scores.items(), key=lambda kv: -kv[1])
    archetype = ranked[0][0] if ranked[0][1] >= 0.4 else "neutral"
    secondary = ranked[1][0] if ranked[1][1] >= 0.4 and archetype != "neutral" else None
    arch = ARCHETYPES[archetype]

    goal = CATEGORY_GOAL.get(sup["category"])
    if goal and (sup["abc_class"] == "A" or rank <= 15 or single):
        tier, why = "strategic", f"{sup['category']} is a {goal} category"
    elif sup["abc_class"] == "A" or spend26 >= 500_000 or single:
        tier, why = "important", "A supplier, high spend or single source"
    else:
        tier, why = "standard", "no dependency signal"
    levers = list(arch["levers"]) + (list(ARCHETYPES[secondary]["levers"]) if secondary else [])
    levers = list(dict.fromkeys(levers))
    if capacity_free and "volume_per_year" not in levers:
        levers.insert(0, "volume_per_year")
    tone = "warm" if tier == "strategic" and arch["tone"] != "firm" else arch["tone"]
    if archetype == "quality_troubled" and tier == "strategic":
        tone = "neutral"

    persona = {
        "supplier_id": supplier_id,
        "name": sup["name"],
        "country": sup["country"],
        "category": sup["category"],
        "abc_class": sup["abc_class"],
        "importance": {
            "tier": tier,
            "reason": why,
            "spend_eur_fy2026": round(spend26),
            "spend_rank": rank,
            "parts": [r["part_id"] for r in sourcing],
            "single_source_parts": single,
            "tooling_owned_by_supplier": tooling,
            "category_goal": goal,
        },
        "profile": {
            "owner_type": intel.get("owner_type"),
            "group_parent": intel.get("group_parent"),
            "founded": intel.get("founded"),
            "staff": intel.get("staff"),
            "turnover_band": intel.get("turnover_band"),
            "equity_ratio_pct": eq,
            "credit_index": ci,
            "credit_index_12m_ago": ci12,
            "scorecard": sc
            and {k: sc[k] for k in ("id", "quarter", "colour", "otd_pct", "ppm", "open_8d_overdue", "score")},
            "we_pay_late_days": round(late["d"], 1) if late.get("d") is not None else None,
            "standard_payment_days": sup["payment_days"],
            "incoterm": sup["incoterm"],
            "contract": ctr
            and {
                "id": ctr["id"],
                "valid_to": ctr["valid_to"],
                "notice_days": ctr["notice_days"],
                "payment_days": ctr["payment_days"],
                "index_clause": clause and {k: clause[k] for k in ("id", "series", "material_share", "deadband_pct")},
            },
            "settle": {
                "renewals": len(hist),
                "avg_asked_pct": round(sum(asked) / len(asked), 2) if asked else None,
                "avg_settled_pct": round(sum(settled) / len(settled), 2) if settled else None,
            },
            "quote_remarks": remarks[:3],
        },
        "signals": signals,
        "archetype": archetype,
        "secondary": secondary,
        "archetype_scores": {k: round(v, 2) for k, v in scores.items()},
        "levers": levers,
        "avoid": list(arch["avoid"]),
        "tone": tone,
        "relationship": {**TIERS[tier], "cite_rivals": tier != "strategic"},
        "estimate": {
            "interest_rate": 0.15 if archetype == "cash_short" or scores["cash_short"] >= 0.4 else 0.08,
            "country_factor": {
                "DE": 1.0,
                "AT": 1.05,
                "CH": 1.1,
                "CZ": 0.82,
                "PL": 0.82,
                "HU": 0.82,
                "TR": 0.75,
                "CN": 0.7,
            }.get(sup["country"], 1.0),
        },
        "recent": {"documents": docs, "news": news},
        "digest": None,
        "learned": _fresh_learned(),
        "negotiations": [],
        "built": now(),
        "updated": now(),
    }
    if llm and (notes or news):
        persona["digest"] = llm.digest_notes(sup["name"], notes, [n["headline"] for n in news])
    return persona


def for_case(pkg, supplier_id, case, llm=None, name=None):
    """The persona to negotiate with: from the knowledge base, else built now and saved."""
    persona = load(supplier_id)
    if persona:
        return persona
    persona = build(pkg, supplier_id, llm, case) if pkg else stranger(supplier_id, case, name)
    if name and persona["name"] == supplier_id:
        persona["name"] = name
    return save(persona)


def _lever_answered(our_sheets, their_terms):
    """Which of our sheets the supplier answered: the one whose non-price terms it matched most."""
    best, best_n = None, 0
    for sheet in our_sheets:
        n = sum(1 for k, v in sheet.items() if k != "unit_price" and their_terms.get(k) == v)
        if n > best_n:
            best, best_n = sheet, n
    return best


def record(persona, case, events, result, observations=(), lessons=None, replay=None):
    """After a negotiation: what the supplier did, and what that teaches us about it."""
    sid = persona["supplier_id"]
    supplier_msgs = [m for m in events if m.get("from") != "buyer"]
    buyer_msgs = [m for m in events if m.get("from") == "buyer"]
    statuses = [m.get("status") for m in supplier_msgs]
    their_prices = [(m.get("term_sheets") or [{}])[0].get("terms", {}).get("unit_price") for m in supplier_msgs]
    our_prices = [(m.get("term_sheets") or [{}])[0].get("terms", {}).get("unit_price") for m in buyer_msgs]
    claims = {"verified": 0, "contradicted": 0, "irrelevant": 0, "duplicate": 0}
    for m in supplier_msgs:
        for c in m.get("claim_results") or []:
            claims[c.get("result")] = claims.get(c.get("result"), 0) + 1
    levers = {}
    for ours, theirs in zip(buyer_msgs, supplier_msgs[1:], strict=False):
        sheets = [s.get("terms", s) for s in ours.get("term_sheets") or []]
        answered = _lever_answered(sheets, (theirs.get("term_sheets") or [{}])[0].get("terms", {}))
        if answered and len(sheets) > 1:
            lever = next((k for k in answered if k != "unit_price" and answered[k] != sheets[0].get(k)), None)
            if lever:
                levers[lever] = levers.get(lever, 0) + 1
    deal_with_us = bool(result.get("deal")) and result.get("supplier_id") == sid
    outcome = (
        "accepted"
        if deal_with_us
        else "walked_away"
        if "walked_away" in statuses
        else "no_bid"
        if "no_bid" in statuses
        else "other_supplier"
        if result.get("deal")
        else "no_deal"
    )
    obs = list(observations)
    entry = {
        "case_id": case.get("case_id"),
        "type": case.get("type"),
        "goal": case.get("buyer", {}).get("category_goal"),
        "date": now(),
        "outcome": outcome,
        "score": result.get("score"),
        "c_open": result.get("c_open"),
        "c_deal": result.get("c_deal"),
        "c_best": result.get("c_best"),
        "rounds": len(buyer_msgs),
        "statuses": statuses,
        "their_prices": their_prices,
        "our_prices": our_prices,
        "lever_answered": levers,
        "claims": claims,
        "needs_approval": any(o.get("needs_approval") for o in obs),
        "moods": [o.get("mood") for o in obs if o.get("mood")],
        "rejected_themes": sorted({t for o in obs for t in o.get("rejected_themes") or []}),
        "lessons": lessons or [],
        "replay": replay,
    }
    persona.setdefault("negotiations", []).append(entry)
    learned = persona.setdefault("learned", _fresh_learned())
    learned["cases"] += 1
    learned["deals"] += int(deal_with_us)
    learned["walked_away"] += int(outcome == "walked_away")
    learned["final_offers"] += int("final_offer" in statuses)
    scores = [n["score"] for n in persona["negotiations"] if n.get("score") is not None]
    learned["avg_score"] = round(sum(scores) / len(scores), 3) if scores else None
    for k, v in claims.items():
        learned["claims"][k] = learned["claims"].get(k, 0) + v
    for k, v in levers.items():
        learned["lever_answered"][k] = learned["lever_answered"].get(k, 0) + v
    learned["needs_approval_seen"] += int(entry["needs_approval"])
    for mood in entry["moods"]:
        learned["moods"][mood] = learned["moods"].get(mood, 0) + 1
    learned["notes"] = (learned["notes"] + [f"{entry['case_id']}: {line}" for line in entry["lessons"]])[-12:]
    refresh(persona)
    return entry


def refresh(persona):
    """Re-derive archetype, levers and the guard from the data signals plus what we learned."""
    scores = dict(persona.get("archetype_scores") or {k: 0.0 for k in ARCHETYPES})
    learned = persona.get("learned") or _fresh_learned()
    if learned.get("needs_approval_seen"):
        scores["group_ladder"] = scores.get("group_ladder", 0) + 0.3
    lever = learned.get("lever_answered") or {}
    if lever.get("payment_days", 0) >= 1:
        scores["cash_short"] = scores.get("cash_short", 0) + 0.2 * lever["payment_days"]
    if lever.get("contract_months", 0) + lever.get("volume_per_year", 0) >= 1:
        scores["family_memory"] = scores.get("family_memory", 0) + 0.15
    ranked = sorted(scores.items(), key=lambda kv: -kv[1])
    archetype = ranked[0][0] if ranked[0][1] >= 0.4 else "neutral"
    persona["archetype"] = archetype
    persona["secondary"] = ranked[1][0] if ranked[1][1] >= 0.4 and archetype != "neutral" else None
    base = list(ARCHETYPES[archetype]["levers"])
    if persona["secondary"]:
        base += ARCHETYPES[persona["secondary"]]["levers"]
    answered = sorted(lever, key=lambda k: -lever[k])
    persona["levers"] = list(dict.fromkeys(answered + base))
    persona["avoid"] = list(ARCHETYPES[archetype]["avoid"])
    guard = persona.setdefault("relationship", dict(TIERS["standard"]))
    if learned.get("walked_away"):
        guard["max_price_pushes"] = max(
            1, TIERS[persona["importance"]["tier"]]["max_price_pushes"] - learned["walked_away"]
        )
        if "pushing after its final offer" not in persona["avoid"]:
            persona["avoid"].append("pushing after its final offer")
    if learned["claims"].get("contradicted"):
        persona["avoid"].append("figures it has already contradicted: re-check every ID")
    return persona


def append_negotiation(entry, supplier_id):
    NEGOTIATIONS.parent.mkdir(parents=True, exist_ok=True)
    with NEGOTIATIONS.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"supplier_id": supplier_id, **entry}, ensure_ascii=False) + "\n")


def write_index():
    """knowledge/personas/README.md: one line per supplier, for people."""
    rows = load_all()
    lines = [
        "# Supplier personas",
        "",
        "Built by `uv run negotiator kb build` from the data package; every negotiation appends to the",
        "supplier's file and refreshes its archetype and guard (`negotiations`, `learned`).",
        "",
        "| Supplier | Name | Category | Tier | Archetype | Tone | Levers | Cases | Avg score |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for p in rows:
        lr = p.get("learned") or {}
        lines.append(
            f"| {p['supplier_id']} | {p['name']} | {p.get('category') or ''} | {p['importance']['tier']} | "
            f"{p['archetype']}{' + ' + p['secondary'] if p.get('secondary') else ''} | {p['tone']} | "
            f"{', '.join(p['levers'][:3])} | {lr.get('cases', 0)} | "
            f"{'' if lr.get('avg_score') is None else lr['avg_score']} |"
        )
    KB_DIR.mkdir(parents=True, exist_ok=True)
    (KB_DIR / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return len(rows)
