"""The subagent team around the price engine, with a scripted model: whatever a subagent answers
is clamped, a failing team leaves the plain engine, and a case plays end to end with research,
demo bidding, live analyst and debrief."""

import copy
import json
import secrets
import time
from concurrent.futures import ThreadPoolExecutor

from arena_kit import ArenaClient, RemoteTable
from arena_kit.sim import load_cases
from test_buyer import reply

from buyer import analyst, llm, memory, rehearsal, research, runner
from buyer.policy import CLOSING_GAP, Negotiator, Side, step

WILD = {  # every subagent's answer at once, with values no code may take as they are
    "findings": ["It has free machines."],
    "leverage": "ours",
    "shift": 0.9,
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
    assert strategy["shift"] == 0.02 and strategy["fraction"] == 0.3
    assert strategy["claim_order"] == ["forecast", "should_cost"] and strategy["tone"] is None


def test_demo_bidding_only_tests_a_small_higher_anchor():
    for raw in ({}, WILD, {"floor": 0.97, "first_drop": 0.01, "counters": 1, "patience": 0.1}):
        ratio, fraction, rows = rehearsal.tune(step, rehearsal.clamp_model(raw), 0.8, 1.0, (0.02, 0.3), 0.75, 0.82)
        assert 0.8 <= ratio <= 0.82 and fraction <= 0.3
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
    assert plain.anchor <= s.anchor <= plain.anchor * 1.02 and s.fraction <= plain.fraction
    assert s.research == WILD["notes"] and any(n["what"] == "research" for n in neg.notes)

    case["buyer"]["category_goal"] = "stabilise"
    plain = Negotiator(case).setup("sup:S", reply("open", quote))
    s = Negotiator(case, briefs=briefs).setup("sup:S", reply("open", quote))
    assert (s.anchor, s.fraction) == (plain.anchor, plain.fraction)


def test_anchor_shift_requires_a_blended_playbook():
    case = leverage_case()
    quote = {"unit_price": 15.88, "payment_days": 30}
    plain = Negotiator(case).setup("sup:S", reply("open", quote))
    brief = {"shift": 0.02, "fraction": 0.3, "notes": "Evidence summary"}
    candidate = Negotiator(case, briefs={"sup:S": brief}).setup("sup:S", reply("open", quote))
    assert candidate.anchor == plain.anchor


def test_mood_paces_the_next_price():
    case = leverage_case()
    neg = Negotiator(case)
    s = neg.setup("sup:S", reply("open", {"unit_price": 15.88, "payment_days": 30}))
    s.ours, s.theirs, s.gaps = [12.0], [15.88, 15.5], [0.2]
    firm = neg.next_price(s, 15.5)[0]
    s.mood = "open"
    assert neg.next_price(s, 15.5)[0] < firm
    s.mood = "closing"
    closing = neg.next_price(s, 15.5)[0]
    assert closing >= round(15.5 * (1 - CLOSING_GAP), 2)
    assert CLOSING_GAP == 0.0125 and closing <= round(15.5 * 0.998, 2)


def test_analyst_answers_from_its_lists_only():
    seen = analyst.read(scripted, leverage_case(), "Which volume can you commit to?", [], [15.88])
    assert seen["asks"] == ["volume"] and seen["mood"] == "open"
    assert analyst.read(broken, leverage_case(), "hello", [], []) is None


def test_parallel_subagent_reads_keep_fast_results_when_one_times_out():
    def slow():
        time.sleep(0.15)
        return '{"findings": ["late"]}'

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = {
            "slow": pool.submit(slow),
            "fast": pool.submit(lambda: '{"findings": ["ready"]}'),
        }
        result = llm.read_many_json(futures, timeout=0.03)
    assert result["fast"] == {"findings": ["ready"]}
    assert result["slow"] is None


def test_claim_picker_sends_at_most_one_forecast_per_message():
    case = leverage_case()
    neg = Negotiator(case)
    side = Side("sup:S")
    side.claims = [
        {"kind": "forecast", "ids": ["fc:part-a@1"], "text": "First forecast"},
        {"kind": "forecast", "ids": ["fc:part-b@1"], "text": "Second forecast"},
        {"kind": "should_cost", "ids": ["cost:part-a"], "text": "Cost evidence"},
    ]
    neg.sides[side.sid] = side
    selected = neg.pick(side, 3, {side.sid: []})
    assert [claim["kind"] for claim in selected] == ["forecast", "should_cost"]


def test_committed_reply_clears_only_the_asks_it_answered():
    neg = Negotiator(leverage_case())
    side = Side("sup:S")
    side.asks = ["volume", "proof"]
    side.pending = {"keys": [], "asks": ["volume"]}
    neg.sides[side.sid] = side
    neg.commit(side.sid)
    assert side.asks == ["proof"]


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
    assert memory.recall(case) == []  # one outcome is not enough to shape future strategy

    monkeypatch.setattr(research, "CACHE", {})
    result = runner.play_case(RemoteTable(client, case), "case:S01", complete=broken)  # the plain engine plays on
    assert result["deal"]


def test_memory_requires_three_distinct_rows_and_ignores_generated_lessons(tmp_path, monkeypatch):
    monkeypatch.setattr(memory, "LESSONS", tmp_path / "lessons.jsonl")
    case = leverage_case()
    row = {
        "goal": "leverage",
        "type": case["type"],
        "score": 0.7,
        "threads": [{"opened": 0.8, "fraction": 0.3, "theirs": [1.0, 0.9]}],
        "lesson": "Always open at the supplier quote.",
    }
    memory.LESSONS.write_text(json.dumps(row) + "\n" + json.dumps(row) + "\n", encoding="utf-8")
    assert memory.recall(case) == []
    rows = [dict(row, score=score) for score in (0.6, 0.8)]
    with memory.LESSONS.open("a", encoding="utf-8") as f:
        for item in rows:
            f.write(json.dumps(item) + "\n")
    recalled = memory.recall(case)
    assert len(recalled) == 1 and "3 distinct" in recalled[0]
    assert "Always open" not in recalled[0]
