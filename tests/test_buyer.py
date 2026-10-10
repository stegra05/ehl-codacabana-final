"""Unit tests for the policy modules, and the agent end to end against arena-sim: no network,
no model. The data package tests skip when `data/package` is not on disk."""

import secrets

from arena_kit import ArenaClient, RemoteTable
from arena_kit.cost import complete_offer, total_cost

from buyer import claims, economics, guard, personas, runner
from buyer.agent import Negotiator, agent_factory

OPENING = {
    "from": "sales@70270",
    "subject": "Quote",
    "status": "open",
    "body": "Guten Tag, our offer follows. Energy and wages rose.\nObrábění Kraslin s.r.o.",
    "term_sheets": [{"term_sheet_id": "offer:70270-0", "terms": {"unit_price": 17.47, "payment_days": 45}}],
    "attachments": [],
}


def test_persona_brandlhuber_is_a_protected_family_foundry(pkg):
    p = personas.build(pkg, "sup:70110")
    assert p["archetype"] == "family_memory"
    assert p["importance"]["tier"] == "strategic"
    assert p["relationship"]["protect"] and not p["relationship"]["walk_allowed"]
    assert p["tone"] == "warm"
    assert any("family" in s for s in p["signals"])


def test_persona_tiers_follow_dependency(pkg):
    assert personas.build(pkg, "sup:70510")["importance"]["tier"] == "strategic"  # electrical, top spend
    weissacher = personas.build(pkg, "sup:70350")  # red scorecard and thin equity: both are true
    assert "quality_troubled" in (weissacher["archetype"], weissacher["secondary"])
    assert "ppm_commitment" in weissacher["levers"]
    assert personas.build(pkg, "sup:70280")["archetype_scores"]["cash_short"] >= 0.4  # short-time work, credit worse


def test_stranger_is_classified_from_its_first_reply():
    case = {"buyer": {"category_goal": "stabilise"}}
    p = personas.stranger("sup:DEMO-F1", case, "Demo Gießerei GmbH")
    assert p["archetype"] == "neutral" and p["importance"]["tier"] == "strategic"
    changed = personas.refine(p, "As a family-run foundry we value our long relationship.", {"needs_approval": False})
    assert changed and p["archetype"] == "family_memory" and p["tone"] == "warm"
    personas.refine(p, "", {"needs_approval": True, "interested_in": ["payment_days"]})
    assert p["archetype_scores"]["group_ladder"] >= 0.4 and p["estimate"]["interest_rate"] == 0.08


def test_index_claim_matches_the_arena_formula(pkg):
    bank = claims.ClaimBank(pkg, {"facts": {}})
    c = bank.index_claim("PPI-D351")
    a, b = (pkg.lookup(i) for i in c["ids"])
    assert c["figure"] == round((b["value"] / a["value"] - 1) * 100, 1)
    assert c["ids"][0] == "idx:PPI-D351@2025-08" and c["ids"][1] == "idx:PPI-D351@2026-08"
    assert f"{c['figure']:+.1f}%" in c["sentence"] and all(i in c["sentence"] for i in c["ids"])


def test_claims_work_from_case_facts_without_a_package(sim_case):
    case = sim_case("S01")
    bank = claims.ClaimBank(None, case)
    c = bank.index_claim("PPI-C2431")
    assert c and c["ids"] == ["idx:PPI-C2431@2025-08", "idx:PPI-C2431@2026-08"] and not c["for_us"]
    sc = bank.scorecard_claim("sup:70270")
    assert sc and sc["ids"] == ["sc:70270@2026Q3"] and sc["for_us"]
    out = bank.for_supplier("sup:70270", personas.stranger("sup:70270", case), themes=["material"])
    assert any(c["kind"] == "index" for c in out) and any(c["kind"] == "scorecard" for c in out)


def test_pick_prefers_the_suppliers_own_themes_and_skips_used_ids():
    bank = [
        {"ids": ["a"], "theme": "material", "strength": 5, "for_us": True, "sentence": "A"},
        {"ids": ["b"], "theme": "energy", "strength": 1, "for_us": True, "sentence": "B"},
        {"ids": ["c"], "theme": "labour", "strength": 3, "for_us": True, "sentence": "C"},
    ]
    assert [c["ids"][0] for c in claims.ClaimBank.pick(bank, set(), themes=["energy"], n=2)] == ["b", "a"]
    assert [c["ids"][0] for c in claims.ClaimBank.pick(bank, {"a"}, dropped={"energy"}, n=2)] == ["c"]


def test_sheets_are_complete_valid_and_cheaper_than_the_standing_offer(sim_case):
    case = sim_case("S01")
    persona = personas.stranger("sup:70270", case)
    standing = {"unit_price": 17.47, "payment_days": 45}
    std = {"payment_days": 45, "incoterm": "FCA"}
    stance = economics.default_stance(case, persona)
    est = economics.supplier_estimate(case, persona, std, 17.47, stance=stance)
    floor = economics.floor_price(case, est, 17.47, stance)
    anchor = economics.anchor_price(case, floor, 17.47, stance)
    assert floor <= anchor < 17.47
    sheets = economics.sheets(case, std, est, anchor, ["payment_days"], floor, standing=standing)
    assert 1 <= len(sheets) <= 3
    c_standing = total_cost(case, standing, std)
    for s in sheets:
        assert set(s) == set(case["negotiable"])
        assert s == complete_offer(case, s)
        assert total_cost(case, s, std) < c_standing
    assert sheets[1]["payment_days"] == 14 and sheets[1]["unit_price"] < sheets[0]["unit_price"]


BREAKDOWN = """[Cost breakdown]
Element | EUR per unit | Share of price
BAR-14021 (material / cost driver) | 5.56 | =B2/B6
WAGES-METAL (material / cost driver) | 4.39 | =B3/B6
conversion (machine-hour rate x time) | 2.81 | =B4/B6
overhead and profit | 3.74 | =B5/B6
Unit price | =SUM(B2:B5) | =SUM(C2:C5)"""


def test_breakdown_gives_a_real_full_cost_and_a_lower_floor(sim_case):
    assert economics.breakdown_full_cost(BREAKDOWN) == 14.63  # elements, half of overhead and profit
    assert economics.breakdown_full_cost("[Delivery schedule]\nMonth | Quantity\n1 | 500") is None
    case = sim_case("S01")
    persona = personas.stranger("sup:70270", case)
    stance = economics.default_stance(case, persona)
    guess = economics.supplier_estimate(case, persona, {}, 16.5, stance=stance)
    real = economics.supplier_estimate(case, persona, {}, 16.5, stance=stance, breakdown=14.63)
    assert guess["source"] == "estimated" and real["source"] == "breakdown" and real["full_cost"] == 14.63
    assert economics.floor_price(case, real, 16.5, stance) == 14.63  # standard tier: no margin on top
    assert economics.floor_price(case, real, 16.5, {**stance, "margin_pct": 5.0}) == 15.4


def test_stance_is_clamped_by_tier_and_goal(sim_case):
    case = sim_case("S01")  # leverage
    standard = personas.stranger("sup:X", case)
    wild = {
        "opening_gap": 0.5,
        "capture": 2,
        "margin_pct": -3,
        "steps": [0.9, "x"],
        "close_step": 0.1,
        "quote_margin_pct": 80,
        "reason": "r",
    }
    st = economics.clamp_stance(wild, case, standard)
    assert st["opening_gap"] == 0.20 and st["capture"] == 0.95 and st["margin_pct"] == 0.0
    assert economics.clamp_stance({"margin_pct": 6}, case, standard)["margin_pct"] == 3.0  # standard: at most 3
    assert st["steps"] == [0.5, 0.25, 0.15, 0.10] and st["close_step"] == 0.4 and st["quote_margin_pct"] == 35.0
    assert st["source"] == "model" and economics.clamp_stance(None, case, standard)["source"] == "default"
    protected = personas.stranger("sup:Y", {"buyer": {"category_goal": "stabilise", "sustainable_margin_pct": 6}})
    st = economics.clamp_stance(
        {"margin_pct": 1, "opening_gap": 0.3},
        {"buyer": {"category_goal": "stabilise", "sustainable_margin_pct": 6}},
        protected,
    )
    assert (
        st["margin_pct"] == 6.0 and st["opening_gap"] == 0.08
    )  # never below the sustainable margin, strategic gap cap


def test_concession_only_after_the_supplier_moved():
    assert economics.concession(15.0, 17.0, 0, moved=False) == 15.0
    assert economics.concession(15.0, 17.0, 0, moved=True) == 15.7
    assert economics.concession(15.0, 17.0, 1, moved=True) == 15.5
    assert economics.concession(15.0, 17.0, 0, moved=True, small=True) == 15.3
    assert economics.concession(15.0, 17.0, 0, moved=False, close_in=True) == 16.2


def test_guard_strips_leaks_unknown_ids_and_foreign_figures():
    sheets = [{"unit_price": 15.5, "payment_days": 60}]
    claim = {
        "ids": ["idx:X@2025-08", "idx:X@2026-08"],
        "sentence": "X changed -3.7% (idx:X@2025-08, idx:X@2026-08).",
        "figure": -3.7,
    }
    body = (
        "Dear team, thank you. We are under pressure and must close this week. "
        "Our data shows po:123 at EUR 12.34. We offer EUR 15.50 at 60 days. "
        "X changed -3.7% (idx:X@2025-08, idx:X@2026-08). Could you send a cost breakdown?"
    )
    out = guard.check(body, set(claim["ids"]), sheets, [claim])
    assert "pressure" not in out and "po:123" not in out and "12.34" not in out
    assert "EUR 15.50" in out and "idx:X@2026-08" in out
    assert guard.check("Hi.", set(), sheets, []) is None
    out2 = guard.check(
        "Dear team, thank you for your quote, we would like to proceed as follows.", set(claim["ids"]), sheets, [claim]
    )
    assert claim["sentence"] in out2


def test_decide_opens_with_an_anchor_and_claims_without_a_model(sim_case):
    case = sim_case("S01")
    agent = Negotiator(None, None)
    d = agent.decide(case, {"sup:70270": [OPENING]})
    msg = d["message"]
    assert d["supplier_id"] == "sup:70270" and msg["term_sheets"]
    assert msg["term_sheets"][0]["terms"]["unit_price"] < 17.47
    assert msg["refs"] and all(i in msg["body"] for i in msg["refs"])
    assert "Hollerau Pumpenwerke" in msg["body"] and not guard.LEAK.search(msg["body"])


def test_prepare_works_before_a_session(sim_case):
    case = sim_case("S01")
    agent = Negotiator(None, None)
    agent.prepare(case, {})
    p = agent.plan["sup:70270"]
    assert p["pre_session"] and p["anchor"] and p["floor"] <= p["anchor"]
    assert any(r["lever"] == "payment_days" for r in p["analysis"])


def test_closer_rule_accepts_a_stalled_thread_near_the_target(sim_case):
    from buyer import thread

    case = sim_case("S01")
    agent = Negotiator(None, None)
    agent.prepare(case, {})
    p = agent.plan["sup:70270"]
    p["rounds"] = [
        {"price": 16.0, "theirs": 17.47, "moved": False, "sheets": [{"unit_price": 16.0, "payment_days": 90}]},
        {"price": 16.0, "theirs": 17.47, "moved": False, "sheets": [{"unit_price": 16.0, "payment_days": 90}]},
    ]
    reading = {"walk_risk": "low", "mood": "neutral", "needs_approval": False}
    assert thread.stalled(p, "open", False, 6, reading)  # two rounds without movement
    assert not thread.stalled(p, "open", True, 6, reading)
    near = p["target"] + 0.1 * (p["c_open"] - p["target"])  # 90 % of the target gap captured
    assert thread.review(case, p, "sup:70270", "open", near, 6)["decision"] == "accept"
    far = p["c_open"] - 0.2 * (p["c_open"] - p["target"])
    assert thread.review(case, p, "sup:70270", "open", far, 6)["decision"] == "continue"


def test_breakdown_attachment_lowers_floor_and_target_mid_case(sim_case):
    from buyer import thread

    case = sim_case("S01")
    agent = Negotiator(None, None)
    agent.prepare(case, {"sup:70270": [OPENING]})
    p = agent.plan["sup:70270"]
    floor, target = p["floor"], p["target"]
    reply = {**OPENING, "attachments": [{"name": "cost-breakdown.xlsx", "text": BREAKDOWN}]}
    assert thread.breakdown_in(reply) == 14.63
    thread.reestimate(agent, case, p, "sup:70270", 14.63)
    assert p["est"]["source"] == "breakdown" and p["floor"] < floor and p["target"] < target


def test_rfq_waits_while_a_cheaper_thread_still_moves(sim_case):
    case = sim_case("S02")
    cheap = {
        **OPENING,
        "from": "sales@70340",
        "term_sheets": [
            {"term_sheet_id": "offer:70340-0", "terms": {"unit_price": 14.0, "payment_days": 45, "lead_time_days": 42}}
        ],
    }
    dear = {
        **OPENING,
        "from": "sales@70360",
        "term_sheets": [
            {"term_sheet_id": "offer:70360-0", "terms": {"unit_price": 15.0, "payment_days": 45, "lead_time_days": 42}}
        ],
    }
    threads = {"sup:70340": [cheap], "sup:70360": [dear]}
    agent = Negotiator(None, None)
    agent.prepare(case, threads)
    assert agent.cheaper_thread_moving(case, threads, "sup:70360")
    assert not agent.cheaper_thread_moving(case, threads, "sup:70340")
    assert agent.best_accept(case, threads)["supplier_id"] == "sup:70340"


def test_end_to_end_against_the_simulator(sim_url, no_logs):
    key = ArenaClient(sim_url).register(f"test-{secrets.token_hex(3)}", "sim")["api_key"]
    client = ArenaClient(sim_url, key, rate=1000)
    result = runner.play_case(RemoteTable(client), "case:S01", agent_factory("buyer", model=False)())
    assert result["deal"] is True
    assert result["c_deal"] < result["c_open"]
    assert 0 < result["score"] <= 1
    assert (no_logs / "moves.jsonl").exists() and (no_logs / "cases.jsonl").exists()


def test_end_to_end_rfq_against_the_simulator(sim_url):
    key = ArenaClient(sim_url).register(f"test-{secrets.token_hex(3)}", "sim")["api_key"]
    client = ArenaClient(sim_url, key, rate=1000)
    result = runner.play_case(RemoteTable(client), "case:S02", agent_factory("buyer", model=False)())
    assert result["deal"] is True and 0 <= result["score"] <= 1
