"""The subagent team around the price engine, with a scripted model: whatever a subagent answers
is checked, a failing team leaves the plain engine, and a case plays end to end with research,
demo bidding, live analyst and debrief."""

import copy
import json
import secrets

from arena_kit import ArenaClient, RemoteTable
from arena_kit.sim import load_cases
from test_buyer import reply

from buyer import analyst, llm, memory, personas, rehearsal, research, runner
from buyer import economics as eco
from buyer.policy import Negotiator, Side

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


def test_no_findings_no_trades(monkeypatch):
    monkeypatch.setattr(research, "CACHE", {})
    monkeypatch.setattr(memory, "recall", lambda case: [])
    brief = research.briefs(leverage_case(), None, scripted)["sup:S"]  # no package: the analysts saw nothing
    assert brief["trades"] == [] and not brief["findings"]
    assert brief["notes"] == WILD["notes"]  # tone and notes for the writer still come through


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


def test_explicit_cash_need_gets_only_a_cost_checked_earlier_payment_trade():
    case = leverage_case()
    neg = Negotiator(case)
    s = neg.setup("sup:S", reply("open", QUOTE))
    s.est["interest_rate"] = 0.5
    s.asks = ["payment"]
    main = eco.complete_offer(case, {"unit_price": QUOTE["unit_price"], "payment_days": 60})
    trades = neg.need_trade_sheets(s, main)
    assert trades
    assert all(t["payment_days"] < main["payment_days"] for t in trades)
    assert all(eco.must_haves_ok(case, t, s.std) for t in trades)
    assert all(eco.deal_cost(case, t, s.std, s.est) is not None for t in trades)
    assert all(eco.cost(case, t, s.std, s.est) < eco.cost(case, main, s.std, s.est) for t in trades)


def test_supplier_need_trade_respects_must_haves_and_never_buys_surplus_volume():
    case = leverage_case()
    need = case["buyer"]["need_per_year"]
    case["negotiable"].append("volume_per_year")
    case["fixed_terms"].pop("volume_per_year", None)
    case["term_options"]["volume_per_year"] = [need // 2, need, need * 2]
    neg = Negotiator(case)
    s = neg.setup("sup:S", reply("open", QUOTE))
    s.asks = ["volume"]
    main = eco.complete_offer(
        case, {"unit_price": QUOTE["unit_price"], "payment_days": 60, "volume_per_year": need // 2}
    )
    trade = neg.need_trade_sheets(s, main)
    assert trade and all(t["volume_per_year"] == need for t in trade)
    assert all(eco.cost(case, t, s.std, s.est) < eco.cost(case, main, s.std, s.est) for t in trade)
    case["buyer"]["must_haves"] = [{"field": "volume_per_year", "op": "<=", "value": need // 2}]
    assert neg.need_trade_sheets(s, main) == []


def test_claim_picker_uses_one_forecast_argument_per_period_then_allows_new_evidence():
    neg = Negotiator(leverage_case())
    side = neg.setup("sup:S", reply("open", QUOTE))
    same_period = [
        {"kind": "forecast", "ids": ["fc:360010@2026-09"], "text": "Forecast for part A", "strength": 3},
        {"kind": "forecast", "ids": ["fc:360011@2026-09"], "text": "Forecast for part B", "strength": 2},
        {"kind": "forecast", "ids": ["fc:360010@2026-10"], "text": "New month for part A", "strength": 2},
        {"kind": "should_cost", "ids": ["cost:part-a"], "text": "Cost evidence", "strength": 5},
    ]
    side.claims = same_period
    chosen = neg.pick(side, 3, {side.sid: []})
    assert chosen == [same_period[0], same_period[2], same_period[3]]
    side.pending = {
        "state": "open",
        "keys": same_period[0]["ids"],
        "families": neg.claim_families(same_period[0]),
    }
    neg.commit(side.sid)
    assert neg.pick(side, 3, {side.sid: []}) == [same_period[2], same_period[3]]


def test_unchanged_offer_guard_tolerates_rounding_but_detects_term_changes():
    previous = {"unit_price": 45.43, "payment_days": 60, "volume_per_year": 100}
    assert Negotiator.same_offer(previous, {**previous, "unit_price": 45.434})
    assert not Negotiator.same_offer(previous, {**previous, "unit_price": 45.45})
    assert not Negotiator.same_offer(previous, {**previous, "payment_days": 30})


def test_move_stops_when_its_primary_sheet_would_repeat():
    case = leverage_case()
    sid = "sup:S"
    terms = eco.complete_offer(case, {"unit_price": 15.0, "payment_days": 30})
    event = {
        "from": "supplier",
        "status": "offer",
        "body": "Our offer.",
        "term_sheets": [{"terms": {**terms, "unit_price": 15.5}}],
    }
    neg = Negotiator(case)
    side = Side(sid)
    side.terms = terms
    side.ours = [15.0]
    side.theirs = [16.0, 15.5]
    side.last_reply = event
    expected = neg.next_price(side, 15.5)[0]
    side.last_sent_terms = eco.at_price(terms, expected)
    neg.sides[sid] = side
    assert neg.move(sid, {sid: [event]}) is None
    assert side.state == "done"
    assert neg.notes[-1]["what"] == "no_progress"


def test_model_failure_fallback_answers_known_ask_without_repeating_offer():
    case = leverage_case()
    case["negotiable"].remove("payment_days")
    case["fixed_terms"]["payment_days"] = 30
    sid = "sup:S"
    side = Side(sid)
    side.std = {}
    side.asks = ["payment"]
    side.last_sent_terms = eco.complete_offer(case, {"unit_price": 15.0})
    neg = Negotiator(case)
    neg.sides[sid] = side
    events = {sid: [{"from": "supplier", "subject": "Re: offer", "body": "Can you pay sooner?"}]}
    result = neg.fallback_move(sid, events)
    assert result["message"]["term_sheets"] == []
    assert "Payment is fixed at 30 days" in result["message"]["body"]


def test_model_metrics_report_rejection_rate():
    before = llm.metrics_snapshot()
    assert llm.paragraph(lambda system, brief: "We can reduce the price by 5 percent.", "brief") is None
    metrics = llm.metrics_since(before)
    assert metrics["writer.attempted"] == 1
    assert metrics["writer.rejected"] == 1
    assert metrics["writer.failure_rate"] == 1.0


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

    def stale(system, user):
        return json.dumps({**WILD, "tactic": "close_in"})

    assert analyst.read(stale, leverage_case(), "hello", [], [])["tactic"] == "steady"
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
    assert WILD["lesson"] in memory.LESSONS.read_text()
    recalled = memory.recall(case)
    assert recalled and WILD["lesson"] not in recalled[0]  # the lead reads the run, not one run's moral

    monkeypatch.setattr(research, "CACHE", {})
    result = runner.play_case(RemoteTable(client, case), "case:S01", complete=broken)  # the plain engine plays on
    assert result["deal"]


def test_release_letters_are_read():
    assert "price_frozen" in personas.signals_in("our price list 2027 applies to all customers without exception")
    assert "price_frozen" in personas.signals_in("our board has ruled out individual price reductions")
    assert "price_frozen" in personas.signals_in("we can no longer grant individual price reductions")
    assert "price_frozen" in personas.signals_in("prices will be set centrally by the group")
    assert "hedged" in personas.signals_in(
        "we bought our bright and cold-drawn bar requirement forward at fixed prices"
    )
    assert personas.signals_in("we are happy to discuss individual price reductions for volume") == []


class Release:
    """A package whose SQL tables know nothing of the Sunday release: only the ID index does."""

    rows = {
        "doc:new": {"supplier": "sup:S", "date": "2026-10-08", "type": "letter", "title": "Prices"},
        "doc:old": {"supplier": "sup:S", "date": "2026-03-01", "type": "email", "title": "Holiday shutdown"},
        "doc:other": {"supplier": "sup:T", "date": "2026-10-09", "type": "letter", "title": "Prices"},
        "news:new": {"supplier": "sup:S", "date": "2026-10-06", "headline": "Sold to a group"},
    }

    def ids(self, prefix):
        return [k for k in self.rows if k.startswith(prefix)]

    def lookup(self, ref):
        return self.rows.get(ref)

    def document(self, ref):
        return f"text of {ref}"

    def query(self, sql, params=(), limit=None):
        return []


def test_research_reads_the_release_through_the_id_index():
    assert research.letters(Release(), "sup:S") == ["2026-10-08 letter: text of doc:new"]  # routine mail is left out
    assert research.news(Release(), "sup:S") == ["2026-10-06: Sold to a group. text of news:new"]
    persona = research.digest(Release(), {"parts": [], "trigger_doc": None}, "sup:S", "persona")
    assert "text of doc:new" in persona and "Sold to a group" in persona and "doc:other" not in persona
