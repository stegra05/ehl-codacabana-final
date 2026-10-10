"""The subagent team around the price engine, with a scripted model: whatever a subagent answers
is checked, a failing team leaves the plain engine, and a case plays end to end with research,
demo bidding, live analyst and debrief."""

import copy
import json
import secrets

from arena_kit import ArenaClient, RemoteTable
from arena_kit.sim import load_cases
from test_buyer import reply

from buyer import analyst, memory, rehearsal, research, runner
from buyer import economics as eco
from buyer.policy import CLOSE_IN, Negotiator

QUOTE = {"unit_price": 15.88, "payment_days": 30}
WILD = {  # every subagent's answer at once, with values no code may take as they are
    "findings": ["It has free machines."],
    "leverage": "ours",
    "trades": [
        {"field": "payment_days", "value": 14, "why": "it is short of cash"},
        {"field": "unit_price", "value": 1.0, "why": "cheaper"},
        {"field": "payment_days", "value": 999, "why": "not an option"},
        "junk",
    ],
    "claim_order": ["bogus", "forecast", "should_cost"],
    "tone": "angry",
    "notes": "A small shop that wants steady work.",
    "reason": "test",
    "arguments": ["Our wages rose.", "Material is up 12 %.", 7],
    "weak_points": ["Our machines stand idle."],
    "wants": ["faster payment"],
    "rebuttals": [{"to": 1, "answer": "Wages are a small share of this part."}, {"to": 9, "answer": "x"}],
    "press": ["You mentioned free capacity."],
    "mood": "irritated",
    "tactic": "hold",
    "argument": 1,
    "asks": ["volume", "bogus"],
    "lesson": "Offer faster payment to a shop short of cash.",
}


def scripted(system, user):
    return json.dumps(WILD) if "JSON only" in system else "We value the cooperation with your team."


def broken(system, user):
    raise RuntimeError("model down")


def leverage_case():
    case = copy.deepcopy(load_cases()["case:S01"])
    case["buyer"]["category_goal"] = "leverage"
    case["negotiable"] = ["unit_price", "payment_days"]
    case["fixed_terms"].pop("payment_days", None)
    case["term_options"]["payment_days"] = [14, 30, 60]
    return {**case, "suppliers": ["sup:S"]}


def test_strategy_and_playbook_are_checked():
    strategy = research.clamp(WILD, leverage_case())
    assert [(t["field"], t["value"]) for t in strategy["trades"]] == [("payment_days", 14)]
    assert strategy["claim_order"] == ["forecast", "should_cost"] and strategy["tone"] is None
    view = rehearsal.supplier_view(WILD)
    assert view["arguments"] == ["Our wages rose."]  # a line with a figure, and junk, are dropped
    book = rehearsal.playbook(view, WILD)
    assert book["rebuttals"] == ["Wages are a small share of this part."] and book["press"] == WILD["press"]
    assert rehearsal.playbook(view, WILD, informed=False)["press"] == []  # no data, no "our records show"


def test_briefs_survive_a_broken_model(monkeypatch):
    monkeypatch.setattr(research, "CACHE", {})
    assert research.briefs(leverage_case(), None, None) == {}
    assert research.briefs(leverage_case(), None, broken) == {}


def test_a_trade_sheet_costs_us_what_the_main_sheet_costs(monkeypatch):
    monkeypatch.setattr(research, "CACHE", {})
    case = leverage_case()
    briefs = research.briefs(case, None, scripted)
    plain = Negotiator(case).setup("sup:S", reply("open", QUOTE))
    neg = Negotiator(case, briefs=briefs)
    s = neg.setup("sup:S", reply("open", QUOTE))
    assert (s.anchor, s.terms) == (plain.anchor, plain.terms)  # the team moves no price
    main = eco.at_price(s.terms, s.anchor)
    s.trades = [{"field": "payment_days", "value": v, "why": ""} for v in case["term_options"]["payment_days"]]
    for sheet in neg.trade_sheets(s, main):
        assert sheet["payment_days"] != main["payment_days"]
        c, c_main = eco.cost(case, sheet, s.std, s.est), eco.cost(case, main, s.std, s.est)
        assert c <= c_main and c_main - c < 0.01 * c_main


def test_tactic_paces_the_next_price_and_adds_evidence():
    neg = Negotiator(leverage_case())
    s = neg.setup("sup:S", reply("open", QUOTE))
    s.ours, s.theirs, s.gaps = [12.0], [15.88, 15.5], [0.2]
    steady, claims = neg.next_price(s, 15.5)
    s.tactic = "hold"
    assert neg.next_price(s, 15.5)[0] < steady
    s.tactic = "close_in"
    assert steady < neg.next_price(s, 15.5)[0] <= round(12.0 + CLOSE_IN * 3.5, 2)  # further, never a jump
    s.tactic = "argue"
    assert neg.next_price(s, 15.5) == (steady, claims + 1)


def test_analyst_answers_from_its_lists_only():
    seen = analyst.read(scripted, leverage_case(), "Which volume can you commit to?", [], [15.88], ["Wages rose."])
    assert (seen["mood"], seen["tactic"], seen["argument"], seen["asks"]) == ("irritated", "hold", 1, ["volume"])
    assert analyst.read(scripted, leverage_case(), "hello", [], [])["argument"] == 0  # nothing to match
    assert analyst.read(broken, leverage_case(), "hello", [], []) is None


def test_case_plays_with_the_team_and_leaves_a_lesson(sim_url, tmp_path, monkeypatch):
    key = ArenaClient(sim_url).register(f"test-{secrets.token_hex(3)}", "sim")["api_key"]
    client = ArenaClient(sim_url, key, rate=1000)
    monkeypatch.setattr(runner, "RUNS", tmp_path)
    monkeypatch.setattr(memory, "LESSONS", tmp_path / "lessons.jsonl")
    monkeypatch.setattr(research, "CACHE", {})
    case = load_cases()["case:S01"]
    result = runner.play_case(RemoteTable(client, case), "case:S01", complete=scripted)
    assert result["deal"] and 0 <= result["score"] <= 1
    notes = json.loads(next(tmp_path.glob("S01_*.json")).read_text())["notes"]
    assert {"research", "analyst"} <= {n["what"] for n in notes}
    assert memory.recall(case)[0].endswith(WILD["lesson"])

    monkeypatch.setattr(research, "CACHE", {})
    result = runner.play_case(RemoteTable(client, case), "case:S01", complete=broken)  # the plain engine plays on
    assert result["deal"]
