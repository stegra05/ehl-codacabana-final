"""The preparation agent's briefing and plan: importance tiers, the C floor, the capture target,
the opening bounds; the stance clamped; the plan built for every case file. The package tests run
only where `data/package` is unpacked (gitignored)."""

import copy
import json
from pathlib import Path

import pytest
from arena_kit import complete_offer
from arena_kit.sim import load_cases

from buyer import briefing, prep
from buyer.agent import load_package
from buyer.policy import Negotiator

PACKAGE = Path(__file__).parent.parent / "data" / "package"
CASES = Path(__file__).parent.parent / "logs" / "cases"


def offer(terms, status="open"):
    return [
        {
            "from": "supplier",
            "status": status,
            "body": "Our offer.",
            "term_sheets": [{"term_sheet_id": "o1", "terms": terms}],
        }
    ]


@pytest.fixture(scope="module")
def pkg():
    if not (PACKAGE / "facts.json").is_file():
        pytest.skip("no data package")
    return load_package(str(PACKAGE))


def practice(case_id):
    for case in json.loads((CASES / "practice.json").read_text()):
        if case["case_id"] == case_id:
            return {k: v for k, v in case.items() if k != "hosted"}
    raise KeyError(case_id)


def test_importance_without_a_package_is_standard():
    case = copy.deepcopy(load_cases()["case:S01"])
    assert briefing.importance(None, case, case["suppliers"][0])["tier"] == "standard"
    case["buyer"]["alternative"] = None
    assert briefing.importance(None, case, case["suppliers"][0])["why"] == ["no fallback in this case"]


def test_importance_tiers_from_the_package(pkg):
    strategic = briefing.importance(pkg, practice("case:P02"), "sup:70510")  # sole source, A, 9 % of spend
    assert strategic["tier"] == "strategic"
    assert "our only active source for this part" in strategic["why"]
    assert briefing.importance(pkg, practice("case:P07"), "sup:70610")["tier"] == "standard"  # 40 % of a C-part
    assert briefing.importance(pkg, practice("case:P08"), "sup:70710")["tier"] == "important"


def test_plan_on_every_case_file(pkg):
    """Every case file (hosted or not) gets a plan with a floor, a C floor and opening bounds."""
    for path in sorted(CASES.glob("*.json")):
        for case in json.loads(path.read_text()):
            case = {k: v for k, v in case.items() if k != "hosted"}
            current = case["buyer"].get("current_unit_price") or case["buyer"]["fallback_unit_price"]
            quote = complete_offer(case, {"unit_price": round(current * 1.1, 2)})
            for sid in case["suppliers"]:
                neg = Negotiator(case, pkg)
                s = neg.setup(sid, offer(quote))
                p = s.plan
                assert p["importance"]["tier"] in briefing.TIERS, case["case_id"]
                assert 0 < p["floor"] <= s.quote, case["case_id"]
                assert p["c_floor"] <= p["c_start"] + 1e-6 or not p["floor_binding"], case["case_id"]
                assert 0.4 <= p["capture"] <= 0.9
                assert p["opening_min"] <= s.anchor <= s.quote, case["case_id"]
                if p["opening_max"] is not None:
                    assert s.anchor <= p["opening_max"] + 0.01, case["case_id"]
                if s.target:
                    assert s.floor is None or s.target >= s.floor - 0.01
                    assert s.target < s.quote


def test_a_floor_near_its_quote_is_a_reference_not_a_bound(pkg):
    """Brandlhuber quotes below our should-cost plus margin: the floor stays off, the capture
    target too, and the opening is today's price plus half the justified increase."""
    case = practice("case:P01")
    quote = complete_offer(case, {"unit_price": 138.55, "effective_date": "2026-11-01", "payment_days": 30})
    s = Negotiator(case, pkg).setup("sup:70110", offer(quote))
    assert s.plan["importance"]["tier"] == "strategic"
    assert s.plan["cost_confidence"] == "high"
    assert not s.plan["floor_binding"]
    assert s.floor is None
    assert s.plan["justified"]["justified_pct"] < s.plan["justified"]["asked_pct"]
    assert s.anchor <= s.plan["opening_max"]


def test_a_binding_floor_bounds_the_sheet(pkg):
    """P10: an own-plant cost well below the quote binds; no sheet goes below it and the capture
    target sits between floor and quote."""
    case = practice("case:P10")
    quote = complete_offer(
        case, {"unit_price": 32.2, "volume_per_year": 19890, "contract_months": 12, "lead_time_days": 56}
    )
    neg = Negotiator(case, pkg)
    s = neg.setup("sup:70410", offer(quote))
    assert s.plan["floor_binding"] and s.floor == s.plan["floor"]
    assert s.floor < s.target < s.quote * briefing.TARGET_BELOW_QUOTE
    s.ours.append(s.floor - 1.0)  # pretend we sat below the floor
    price, _ = neg.next_price(s, theirs=s.quote, left=9, rounds=9)
    assert price >= s.floor


def test_the_stance_is_clamped_and_applied(pkg):
    case = practice("case:P08")
    raw = {
        "sup:70710": {
            "assessment": "A distributor that prices off the alloy surcharge; acknowledge its index exposure.",
            "values": ["a long contract", 42, None],
            "lead_with": ["index", "nonsense", "should_cost"],
            "capture_delta": 0.9,
            "opening_gap_delta": -1,
            "patience": 0.05,
            "tone": "loud",
            "risks": ["final offer early"],
        },
        "sup:other": {"assessment": "ignored"},
    }
    stance = prep.clamp(raw, case["suppliers"])
    assert list(stance) == ["sup:70710"]
    st = stance["sup:70710"]
    assert st["capture_delta"] == 0.15 and st["opening_gap_delta"] == -0.05 and st["patience"] == 0.15
    assert st["values"] == ["a long contract", "42"] and st["lead_with"] == ["index", "should_cost"]
    assert st["tone"] is None
    quote = complete_offer(case, {"unit_price": 6.05, "payment_days": 30, "contract_months": 12, "index_clause": None})
    plain = Negotiator(case, pkg).setup("sup:70710", offer(quote))
    neg = Negotiator(case, pkg)
    neg.stance = stance
    s = neg.setup("sup:70710", offer(quote))
    assert s.budget == 0.15
    assert s.plan["capture"] == min(0.9, plain.plan["capture"] + 0.15)
    assert s.plan["opening_gap"] == pytest.approx(plain.plan["opening_gap"] - 0.05)
    assert [c["kind"] for c in s.claims][:1] == ["index"] or not any(c["kind"] == "index" for c in s.claims)
    digits = prep.clamp({"sup:70710": {"assessment": "We pay 30 days late."}}, case["suppliers"])
    assert digits["sup:70710"]["assessment"] == ""  # figures never reach the e-mail writer


def test_prep_loop_runs_lookups_then_takes_the_stance(pkg):
    case = practice("case:P02")
    brief = briefing.prepare(case, pkg, Negotiator(case, pkg).bank)
    answers = iter(
        [
            "not json at all",
            '{"query": "SELECT id FROM suppliers WHERE id = \'sup:70510\'"}',
            '{"document": "doc:nope"}',
            'Here you are: {"stance": {"sup:70510": {"assessment": "A group supplier with an approval ladder.", '
            '"values": ["planning security"], "lead_with": ["index"], "capture_delta": -0.1, "patience": 0.3, '
            '"tone": "firm"}}}',
        ]
    )
    seen = []

    def complete(system, user):
        seen.append(user)
        return next(answers)

    out = prep.run(complete, case, pkg, brief)
    assert list(out["stance"]) == ["sup:70510"]
    assert out["stance"]["sup:70510"]["capture_delta"] == -0.1
    assert len(out["steps"]) == 2
    assert "sup:70510" in out["steps"][0]["result"]
    assert out["steps"][1]["result"].startswith("error")
    assert "RESULT:" in seen[-1]  # the lookups' results reached the next turn


def test_prep_loop_gives_up_on_a_slow_model():
    case = copy.deepcopy(load_cases()["case:S01"])

    def slow(system, user):
        import time

        time.sleep(3)
        return '{"stance": {}}'

    out = prep.run(slow, case, None, {}, budget_s=2.5)
    assert out["stance"] == {}
    assert out["took_s"] < 3.5
    assert prep.run(None, case, None, {}) == {}
