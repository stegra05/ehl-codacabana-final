"""The subagent team around the price engine, with a scripted model: whatever a subagent answers
is clamped, a failing team leaves the plain engine, and a case plays end to end with research,
demo bidding, live analyst and debrief."""

import copy
import json
import secrets

from arena_kit import ArenaClient, RemoteTable
from arena_kit.sim import load_cases
from test_buyer import reply, sim_url  # noqa: F401 - the arena-sim fixture

from buyer import analyst, memory, rehearsal, research, runner
from buyer.policy import CLOSING_GAP, Negotiator, step

WILD = {  # every subagent's answer at once, with values no code may take as they are
    "findings": ["It has free machines."],
    "leverage": "ours",
    "shift": -0.9,
    "fraction": 9,
    "claim_order": ["bogus", "forecast", "should_cost"],
    "tone": "angry",
    "notes": "A small shop that wants steady work.",
    "reason": "test",
    "floor": 0.1,
    "first_drop": 0.12,
    "step": "much",
    "counters": 4,
    "patience": 0.4,
    "eager": True,
    "asks": ["volume", "bogus"],
    "mood": "open",
    "lesson": "Hold low against a shop that keeps conceding.",
}


def scripted(system, user):
    return json.dumps(WILD) if "JSON only" in system else "We value the cooperation with your team."


def broken(system, user):
    raise RuntimeError("model down")


def leverage_case():
    case = copy.deepcopy(load_cases()["case:S01"])
    case["buyer"]["category_goal"] = "leverage"
    return case


def test_playbook_and_strategy_are_clamped():
    model = rehearsal.clamp_model(WILD)
    assert model["floor"] == 0.7 and model["step"] == rehearsal.MODEL["step"][2] and model["eager"]
    strategy = research.clamp(WILD)
    assert strategy["shift"] == -0.05 and strategy["fraction"] == 0.3
    assert strategy["claim_order"] == ["forecast", "should_cost"] and strategy["tone"] is None


def test_demo_bidding_never_opens_higher_or_moves_faster():
    for raw in ({}, WILD, {"floor": 0.97, "first_drop": 0.01, "counters": 1, "patience": 0.1}):
        ratio, fraction, rows = rehearsal.tune(step, rehearsal.clamp_model(raw), 0.8, 1.0, (0.0, 0.3), 0.75, 0.8)
        assert 0.75 <= ratio <= 0.8 and fraction <= 0.3
        assert all(0.7 <= price <= 1.0 for _, _, price, _ in rows)


def test_briefs_survive_a_broken_model(monkeypatch):
    monkeypatch.setattr(research, "CACHE", {})
    case = leverage_case()
    assert research.briefs(case, None, None) == {}
    assert research.briefs(case, None, broken) == {}


def test_brief_tunes_a_leverage_thread_and_leaves_a_relationship_one(monkeypatch):
    monkeypatch.setattr(research, "CACHE", {})
    case = leverage_case()
    quote = {"unit_price": 15.88, "payment_days": 30}
    briefs = research.briefs({**case, "suppliers": ["sup:S"]}, None, scripted)
    plain = Negotiator(case).setup("sup:S", reply("open", quote))
    neg = Negotiator(case, briefs=briefs)
    s = neg.setup("sup:S", reply("open", quote))
    assert s.anchor <= plain.anchor and s.fraction <= plain.fraction  # lower and slower at most
    assert s.research == WILD["notes"] and any(n["what"] == "research" for n in neg.notes)

    case["buyer"]["category_goal"] = "stabilise"
    plain = Negotiator(case).setup("sup:S", reply("open", quote))
    s = Negotiator(case, briefs=briefs).setup("sup:S", reply("open", quote))
    assert (s.anchor, s.fraction) == (plain.anchor, plain.fraction)


def test_mood_paces_the_next_price():
    case = leverage_case()
    neg = Negotiator(case)
    s = neg.setup("sup:S", reply("open", {"unit_price": 15.88, "payment_days": 30}))
    s.ours, s.theirs, s.gaps = [12.0], [15.88, 15.5], [0.2]
    firm = neg.next_price(s, 15.5)[0]
    s.mood = "open"
    assert neg.next_price(s, 15.5)[0] < firm
    s.mood = "closing"
    assert neg.next_price(s, 15.5)[0] >= round(15.5 * (1 - CLOSING_GAP), 2)


def test_analyst_answers_from_its_lists_only():
    seen = analyst.read(scripted, leverage_case(), "Which volume can you commit to?", [], [15.88])
    assert seen["asks"] == ["volume"] and seen["mood"] == "open"
    assert analyst.read(broken, leverage_case(), "hello", [], []) is None


def test_case_plays_with_the_team_and_leaves_a_lesson(sim_url, tmp_path, monkeypatch):  # noqa: F811
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
