"""The subagent team around the price engine, with a scripted model: whatever a subagent answers
is checked, a failing team leaves the plain engine, and a case plays end to end with research,
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
from buyer import economics as eco
from buyer.policy import Negotiator, Side, feedback

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
    "would_help": ["payment_days", "unit_price", "bogus"],
    "points": ["Faster payment would help us more than anything.", "We need 14 days.", 3],
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
    s.tactic = "argue"
    assert neg.next_price(s, 15.5) == (steady, claims + 1)


def test_analyst_answers_from_its_lists_only():
    seen = analyst.read(scripted, leverage_case(), "Which volume can you commit to?", [], [15.88], ["Wages rose."])
    assert (seen["mood"], seen["tactic"], seen["argument"], seen["asks"]) == ("irritated", "hold", 1, ["volume"])
    assert seen["would_help"] == [] and seen["points"] == ["Faster payment would help us more than anything."]
    seen = analyst.read(scripted, leverage_case(), "x", [], [], fields=["payment_days", "lead_time_days"])
    assert seen["would_help"] == ["payment_days"]  # only terms of the case
    assert analyst.read(scripted, leverage_case(), "hello", [], [])["argument"] == 0  # nothing to match
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


def test_its_feedback_on_our_evidence_is_read_from_its_own_sentences():
    body = (
        "We checked the price history data you cited; it holds, but it does not change our calculation. "
        "We checked the should cost data you cited; it holds and we took it into account. "
        "As to the delivery record data you cited, we did not know that - a fair point. "
        "We have verified the competitive offer you cited and have adjusted our pricing accordingly. "
        "Our price follows our main cost drivers."
    )
    assert feedback(body) == ({"should_cost", "scorecard", "rival"}, {"order_history"})


def test_evidence_it_waved_off_is_not_cited_again_and_what_it_counted_comes_first():
    neg = Negotiator(leverage_case())
    side = Side("sup:S")
    side.claims = [
        {"kind": "order_history", "ids": ["po:1"], "text": "a"},
        {"kind": "forecast", "ids": ["fc:1"], "text": "b"},
        {"kind": "index", "ids": ["idx:1"], "text": "c"},
    ]
    side.dismissed, side.counted = {"order_history", "index"}, {"index"}
    assert [c["kind"] for c in neg.pick(side, 3, {side.sid: []})] == ["index", "forecast"]


def test_a_term_it_says_would_help_goes_on_the_table_once_at_no_cost_to_us():
    case = leverage_case()
    neg = Negotiator(case)
    s = neg.setup("sup:S", reply("open", QUOTE))
    main = eco.at_price(s.terms, s.anchor)
    s.wants = ["payment_days", "lead_time_days"]  # the second is not negotiable here
    (sheet,) = neg.want_sheet(s, main)
    assert sheet["payment_days"] == min(case["term_options"]["payment_days"])  # the fastest payment
    assert eco.cost(case, sheet, s.std, s.est) <= eco.cost(case, main, s.std, s.est)
    assert neg.want_sheet(s, main) == []  # offered once
    facts = neg.team_facts(s, False, False, [sheet])
    assert any("includes an option" in f for f in facts)


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
    assert json.loads((tmp_path / "lessons.jsonl").read_text())["lesson"] == WILD["lesson"]

    monkeypatch.setattr(research, "CACHE", {})
    result = runner.play_case(RemoteTable(client, case), "case:S01", complete=broken)  # the plain engine plays on
    assert result["deal"]
