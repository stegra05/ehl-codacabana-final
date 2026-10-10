import json
from pathlib import Path

from arena_kit.cost import complete_offer, total_cost

from negotiator import claims, economics, guard, personas
from negotiator.agent import Negotiator

SIM_CASES = (
    Path(__file__).resolve().parents[1] / "negotiation-agent/negotiation-arena-kit/starter-kit/arena_kit/sim_cases"
)


def sim_case(name):
    return json.loads((SIM_CASES / f"{name}.json").read_text())


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


def test_record_learns_from_a_negotiation(pkg, no_kb):
    p = personas.build(pkg, "sup:70270")
    case = sim_case("S01")
    events = [
        {"from": "sales@70270", "status": "open", "term_sheets": [{"terms": {"unit_price": 17.5, "payment_days": 45}}]},
        {
            "from": "buyer",
            "term_sheets": [
                {"terms": {"unit_price": 15.7, "payment_days": 60}},
                {"terms": {"unit_price": 15.5, "payment_days": 14}},
            ],
        },
        {
            "from": "sales@70270",
            "status": "final_offer",
            "term_sheets": [{"terms": {"unit_price": 16.4, "payment_days": 14}}],
            "claim_results": [{"index": 0, "result": "verified"}],
        },
    ]
    result = {"deal": True, "supplier_id": "sup:70270", "score": 0.6, "c_open": 100, "c_deal": 90, "c_best": 80}
    entry = personas.record(
        p, case, events, result, observations=[{"needs_approval": True, "mood": "cool"}], lessons=["x"]
    )
    assert entry["outcome"] == "accepted" and entry["lever_answered"] == {"payment_days": 1}
    assert p["learned"]["cases"] == 1 and p["learned"]["claims"]["verified"] == 1
    assert p["learned"]["needs_approval_seen"] == 1
    assert p["levers"][0] == "payment_days"
    assert p["learned"]["notes"] == ["case:S01: x"]


def test_index_claim_matches_the_arena_formula(pkg):
    bank = claims.ClaimBank(pkg, {"facts": {}})
    c = bank.index_claim("PPI-D351")
    a, b = (pkg.lookup(i) for i in c["ids"])
    assert c["figure"] == round((b["value"] / a["value"] - 1) * 100, 1)
    assert c["ids"][0] == "idx:PPI-D351@2025-08" and c["ids"][1] == "idx:PPI-D351@2026-08"
    assert f"{c['figure']:+.1f}%" in c["sentence"] and all(i in c["sentence"] for i in c["ids"])


def test_pick_prefers_the_suppliers_own_themes_and_skips_used_ids():
    bank = [
        {"ids": ["a"], "theme": "material", "strength": 5, "for_us": True, "sentence": "A"},
        {"ids": ["b"], "theme": "energy", "strength": 1, "for_us": True, "sentence": "B"},
        {"ids": ["c"], "theme": "labour", "strength": 3, "for_us": True, "sentence": "C"},
    ]
    assert [c["ids"][0] for c in claims.ClaimBank.pick(bank, set(), themes=["energy"], n=2)] == ["b", "a"]
    assert [c["ids"][0] for c in claims.ClaimBank.pick(bank, {"a"}, dropped={"energy"}, n=2)] == ["c"]


def test_sheets_are_complete_valid_and_cheaper_than_the_standing_offer(pkg):
    case = sim_case("S01")
    persona = personas.build(pkg, "sup:70270")
    standing = {"unit_price": 17.47, "payment_days": 45}
    std = {"payment_days": 45, "incoterm": "FCA"}
    est = economics.supplier_estimate(pkg, case, persona, std, 17.47)
    floor = economics.floor_price(case, persona, est, 17.47)
    anchor = economics.anchor_price(case, persona, floor, 17.47)
    assert floor <= anchor < 17.47
    sheets = economics.sheets(case, persona, std, est, anchor, ["payment_days"], floor, standing=standing)
    assert 1 <= len(sheets) <= 3
    c_standing = total_cost(case, standing, std)
    for s in sheets:
        assert set(s) == set(case["negotiable"])
        assert s == complete_offer(case, s)
        assert total_cost(case, s, std) < c_standing
    assert sheets[1]["payment_days"] == 14 and sheets[1]["unit_price"] < sheets[0]["unit_price"]


def test_concession_only_after_the_supplier_moved():
    assert economics.concession(15.0, 17.0, 0, moved=False) == 15.0
    assert economics.concession(15.0, 17.0, 0, moved=True) == 15.7
    assert economics.concession(15.0, 17.0, 1, moved=True) == 15.5
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


def test_decide_opens_with_an_anchor_and_claims_without_a_model(pkg, no_kb):
    case = sim_case("S01")
    opening = {
        "from": "sales@70270",
        "subject": "Quote",
        "status": "open",
        "body": "Guten Tag, our offer follows. Energy and wages rose.\nObrábění Kraslin s.r.o.",
        "term_sheets": [{"term_sheet_id": "offer:70270-0", "terms": {"unit_price": 17.47, "payment_days": 45}}],
        "attachments": [],
    }
    threads = {"sup:70270": [opening]}
    agent = Negotiator(pkg, llm=None, kb=False)
    d = agent.decide(case, threads)
    msg = d["message"]
    assert d["supplier_id"] == "sup:70270" and msg["term_sheets"]
    assert msg["term_sheets"][0]["terms"]["unit_price"] < 17.47
    assert all(i in msg["body"] for i in msg["refs"])
    assert "Hollerau Pumpenwerke" in msg["body"] and not guard.LEAK.search(msg["body"])


def test_end_to_end_against_the_simulator(pkg, sim, no_kb):
    from arena_kit.client import ArenaClient
    from arena_kit.play import RemoteTable

    from negotiator import runner

    url, state, clock = sim
    key = ArenaClient(url).register("Codacabana test", "sim")["api_key"]
    client = ArenaClient(url, key)
    agent = Negotiator(pkg, llm=None, kb=True)
    result = runner.play_case(RemoteTable(client), "case:S01", agent)
    assert result["deal"] is True
    assert result["c_deal"] < result["c_open"]
    assert result["score"] > 0
    persona = personas.load("sup:70270")
    assert persona["learned"]["cases"] == 1 and persona["negotiations"][0]["outcome"] == "accepted"
    assert (no_kb / "negotiations.jsonl").exists()
