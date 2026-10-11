"""The reasoner: the reader (model first, regex fallback), the floor and ceiling arithmetic, the
move menu inside its bounds, the model's choice validated by code, and every case file played
through arena-sim with a fake model. No network, no real model."""

import copy
import json
import logging
import secrets
import time
from pathlib import Path

import pytest
from arena_kit import ArenaClient, RemoteTable, complete_offer
from arena_kit.sim import Sim, load_cases
from conftest import serve

from buyer import economics as eco
from buyer import reader, runner
from buyer.reasoner import Reasoner

CASES = Path(__file__).parent.parent / "logs" / "cases"

DISTRIBUTOR = """Dear customer,
Our terms: a price of €5.30 per unit, Zahlungsziel 45 days net, a contract term of 36 months, a Preisgleitklausel.
We checked the index change data you cited; it holds and we took it into account.
We checked the price history data you cited; it holds, but it does not change our calculation.
As a fixed price over 36 months is not possible, we must maintain the AS-14404 index clause.
A binding higher volume would help us and can improve the price.
Which volume can you commit to?
Which figures is that based on? Please send us the data."""

FOUNDRY = """Hello, we can move a bit: Our terms: a price of €45.50 per unit, a quality commitment of 800 ppm.
We checked the quality record data you cited; it holds and we took it into account.
We see your figures, but we cannot give up margin right now. Faster payment would help us more than anything.
Our standard Zahlungsziel is 60 days net. Faster payment is welcome; we can reflect it in the price.
This is our final offer (letztes Angebot). Please decide."""


# -- the reader ---------------------------------------------------------------------------------
def test_regex_fallback_reads_the_templated_lines():
    r = reader.read_regex(DISTRIBUTOR)
    assert r["counted"] == ["index"] and r["dismissed"] == ["order_history"]
    assert r["refused"] == ["index_clause"] and r["levers"] == ["volume_per_year"]
    assert set(r["asks"]) == {"volume", "proof"} and not r["final"]
    k = reader.read_regex(FOUNDRY)
    assert k["asks"] == ["payment"] and k["levers"] == ["payment_days"]
    assert k["counted"] == ["scorecard"] and k["final"] and k["cash"]


def test_model_reads_first_and_regex_is_only_the_fallback():
    answer = json.dumps(
        {"asks": ["payment"], "levers": ["payment_days"], "counted": ["scorecard"], "final": True, "cash": True}
    )
    r = reader.read(lambda system, user: f"Sure: {answer}", FOUNDRY, 5.0)
    assert r["source"] == "model" and r["levers"] == ["payment_days"]
    garbage = reader.read(lambda system, user: "I cannot help with that", FOUNDRY, 5.0)
    assert garbage["source"] == "regex" and garbage["levers"] == ["payment_days"]
    unknown = reader.read(lambda system, user: '{"asks": ["money"], "levers": ["bribe"], "final": "yes"}', FOUNDRY, 5.0)
    assert unknown["source"] == "model" and unknown["asks"] == [] and unknown["levers"] == [] and unknown["final"]

    def slow(system, user):
        time.sleep(3.0)
        return answer

    t0 = time.monotonic()
    late = reader.read(slow, FOUNDRY, 2.0)
    assert late["source"] == "regex" and time.monotonic() - t0 < 2.9
    assert reader.read(None, FOUNDRY)["source"] == "regex"


def test_a_model_that_rejects_the_fast_effort_is_asked_again_at_low(monkeypatch):
    import httpx

    from buyer import llm

    monkeypatch.setitem(llm._fast, "effort", "none")
    seen = []

    def complete(system, user, effort=None):
        seen.append(effort)
        if effort == "none":
            req = httpx.Request("POST", "https://example.test/v1/chat/completions")
            raise httpx.HTTPStatusError("400", request=req, response=httpx.Response(400, request=req))
        return '{"asks": ["payment"]}'

    assert llm.fast(complete)("s", "u") == '{"asks": ["payment"]}'
    assert seen == ["none", "low"]
    assert llm.fast(complete)("s", "u") and seen[-1] == "low"  # it keeps the working effort


# -- the arithmetic --------------------------------------------------------------------------------
def s01():
    case = copy.deepcopy(load_cases()["case:S01"])
    terms = complete_offer(case, {"unit_price": 15.0, "payment_days": 60})
    return case, terms


def test_ceiling_is_where_c_meets_the_alternative_and_never_above_the_quote():
    case, terms = s01()
    est = eco.estimate(case, {}, 0.07)
    case["buyer"]["alternative"] = {
        "kind": "rfq",
        "terms": complete_offer(case, {"unit_price": 14.0, "payment_days": 60}),
    }
    cap = eco.ceiling(case, terms, {}, est, 15.0)
    assert cap < 15.0
    assert abs(eco.cost(case, eco.at_price(terms, cap), {}, est) - eco.c_alt(case)) < 50
    case["buyer"]["alternative"] = {"kind": "none"}
    assert eco.ceiling(case, terms, {}, est, 15.0) == 15.0


def test_indifference_price_values_payment_days_at_our_cost_of_money():
    case, terms = s01()
    est = eco.estimate(case, {}, 0.07)
    faster = {**terms, "payment_days": 30}
    p = eco.indifference_price(case, terms, faster, 15.0, {}, est)
    # 30 days earlier costs us interest_rate x 30 / 360 of the spend: the price must fall by that
    expected = 15.0 * (1 - case["buyer"]["interest_rate"] * 30 / 360)
    assert abs(p - expected) < 0.02
    assert eco.cost(case, eco.at_price(faster, p), {}, est) <= eco.cost(case, eco.at_price(terms, 15.0), {}, est) + 1


def test_lever_trades_find_surplus_where_the_supplier_values_a_term_more_than_it_costs_us():
    case, terms = s01()
    est = eco.estimate(case, {}, 0.20)  # a cash-short supplier: money now is worth 20 % a year to it
    rows = eco.lever_trades(case, terms, 15.0, {}, est, ["payment_days"])
    faster = [r for r in rows if r["value"] < 60]
    assert faster and all(r["surplus"] > 0 for r in faster)  # it would take less than the term costs us
    for r in rows:
        assert eco.must_haves_ok(case, eco.at_price(r["terms"], r["ours"]), {})
    cheap = eco.estimate(case, {}, 0.0)  # money is worth nothing to it: faster payment has no surplus,
    rows = eco.lever_trades(case, terms, 15.0, {}, cheap, ["payment_days"])  # a longer term is free for it
    assert all(r["surplus"] < 0 for r in rows if r["value"] < 60)
    assert all(r["surplus"] > 0 for r in rows if r["value"] > 60)


def test_planner_asks_for_the_payment_term_cheaper_for_us_when_the_supplier_valuation_is_a_guess():
    """P18: the planner guessed 7.5 % a year for a family firm and asked for 45 days where Werdenfels
    priced payment at zero. Packages within the tolerance of the best C that differ only in payment
    days: the longest term; every other term keeps the planner's choice."""
    case, _ = s01()
    case["term_options"]["payment_days"] = [14, 30, 45, 60, 90]
    quote = complete_offer(case, {"unit_price": 15.0, "payment_days": 30})
    est = eco.estimate(case, {"payment_days": 30, "incoterm": "DAP"}, 0.075)
    terms, _ = eco.plan_terms(case, {}, est, quote, 15.0 * 0.8)
    assert terms["payment_days"] == 90
    dear = eco.estimate(case, {"payment_days": 30, "incoterm": "DAP"}, 0.40)  # cash worth 40 % a year to it
    terms, _ = eco.plan_terms(case, {}, dear, quote, 15.0 * 0.8)
    assert terms["payment_days"] < 60  # outside the tolerance the supplier's valuation decides


# -- the menu and the choice ------------------------------------------------------------------------
def reply(terms, body="Our offer.", status="open", offer="offer:S-1"):
    return {
        "from": "supplier",
        "status": status,
        "body": body,
        "term_sheets": [{"term_sheet_id": offer, "terms": terms}],
    }


def thread_after_counter(complete, body=FOUNDRY, counter=14.5):
    case, quote = s01()
    neg = Reasoner(case, complete=complete)
    events = [reply(quote)]
    s = neg.setup("sup:S", events)
    first = neg.move("sup:S", {"sup:S": events})
    events += [{**first["message"], "from": "buyer"}, reply({**quote, "unit_price": counter}, body, offer="offer:S-2")]
    return case, neg, s, events


def test_menu_stays_inside_the_bounds_and_a_trade_pays_both_sides():
    case, neg, s, events = thread_after_counter(None)
    theirs = neg.their_price(s, events[-1]["term_sheets"][0]["terms"])
    s.read = reader.read_regex(FOUNDRY)
    neg.absorb(s)
    menu = neg.menu(s, theirs, 8)
    ids = {o["id"] for o in menu}
    assert "step" in ids and not ({"small", "large"} & ids)  # the price step is the code's, not the model's
    step = next(o for o in menu if o["id"] == "step")
    code_price, _ = neg.next_price(s, theirs)
    assert step["price"] == code_price
    for o in menu:
        assert o["price"] < theirs
        assert eco.must_haves_ok(case, eco.at_price(o["terms"], o["price"]), s.std)
        if o["terms"] == s.terms:
            assert s.ours[-1] < o["price"] <= (s.ceiling or theirs)
    trades = [o for o in menu if o["id"].startswith("trade:payment_days=")]
    assert trades, ids  # it named faster payment as its lever
    assert all(o["c"] <= step["c"] + 1 for o in trades)  # the trade never costs us more than the plain step


def test_the_model_choice_is_validated_and_a_bad_answer_takes_the_code_move():
    picked = {}

    def complete(system, user):
        if "OPTIONS" not in user:  # the reader call: it is short of cash, so money now is worth more to it
            return json.dumps({"asks": ["payment"], "levers": ["payment_days"], "counted": ["scorecard"], "cash": True})
        picked["brief"] = user
        return json.dumps({"option": "trade:payment_days=30", "claims": 2, "reason": "it asked for it"})

    case, neg, s, events = thread_after_counter(complete)
    neg.writer_s = 15.0
    move = neg.move("sup:S", {"sup:S": events})
    sheet = move["message"]["term_sheets"][0]["terms"]
    assert sheet["payment_days"] == 30 and s.terms["payment_days"] == 30
    assert sheet["unit_price"] < 14.5
    assert "BOUNDS" in picked["brief"] and "trade:payment_days=30" in picked["brief"]
    assert any(n["what"] == "reason" and n["option"] == "trade:payment_days=30" for n in neg.notes)
    sent = next(n for n in neg.notes if n["what"] == "send" and n.get("trade"))
    assert sent["trade"][0] == "payment_days" and "Faster payment" in sent["trade"][1]  # its words, for the e-mail
    assert len(move["message"]["refs"]) <= 2

    case, neg, s, events = thread_after_counter(lambda system, user: '{"option": "give_everything", "claims": 9}')
    neg.writer_s = 15.0
    planned = dict(s.terms)
    move = neg.move("sup:S", {"sup:S": events})
    sheet = move["message"]["term_sheets"][0]["terms"]
    assert all(sheet[k] == v for k, v in planned.items() if k != "unit_price")  # the code's own terms
    assert sheet["unit_price"] == neg.next_price(s, 14.5)[0] or sheet["unit_price"] < 14.5
    assert not any(n["what"] == "reason" and n["option"] != "step" for n in neg.notes)


def test_a_lever_only_the_model_sees_is_not_traded():
    """P18: the model read the supplier's own "Zahlungsziel 90 days net" as a payment lever; the patterns
    did not. Without the patterns' agreement there is no trade option, and the opening is never clipped."""
    terms_body = "Our terms: a price of EUR 5.30 per unit, Zahlungsziel 90 days net, a contract term of 36 months."

    def complete(system, user):
        if "OPTIONS" not in user:
            return json.dumps({"asks": [], "levers": ["payment_days"], "counted": ["index"], "cash": True})
        return json.dumps({"option": "trade:payment_days=14", "claims": 1, "reason": "x"})

    case, neg, s, events = thread_after_counter(complete, body=terms_body)
    neg.writer_s = 15.0
    opening = events[1]["term_sheets"][0]["terms"]["unit_price"]
    assert opening == s.anchor  # the opening went out at the anchor
    move = neg.move("sup:S", {"sup:S": events})
    assert move["message"]["term_sheets"][0]["terms"]["payment_days"] == s.terms["payment_days"]
    assert s.levers == []
    assert not any(n["what"] == "reason" and n["option"].startswith("trade") for n in neg.notes)


def test_claims_the_supplier_dismissed_go_last_and_counted_kinds_first():
    case, neg, s, events = thread_after_counter(None)
    s.claims = [
        {"kind": "order_history", "ids": ["po:1"], "text": "po", "strength": 4},
        {"kind": "forecast", "ids": ["fc:1"], "text": "fc", "strength": 2},
        {"kind": "scorecard", "ids": ["sc:1"], "text": "sc", "strength": 2},
    ]
    s.dismissed, s.counted = {"order_history"}, {"scorecard"}
    assert [c["kind"] for c in neg.pick(s, 3, {"sup:S": events})] == ["scorecard", "forecast", "order_history"]


def test_fixed_payment_and_a_cash_ask_get_an_honest_on_time_commitment():
    case, quote = s01()
    case["negotiable"].remove("payment_days")
    case["fixed_terms"]["payment_days"] = 60
    neg = Reasoner(case)
    events = [reply(quote, FOUNDRY)]
    s = neg.setup("sup:S", events)
    s.pay_record = (135, 126, 8.8)
    move = neg.move("sup:S", {"sup:S": events})
    body = move["message"]["body"]
    assert "Payment is fixed at 60 days" in body
    assert "126 of your last 135 invoices" in body and "pay every invoice on the due date" in body
    assert "pay reliably" not in body


def test_the_cli_entry_points_take_the_negotiator_class():
    import inspect

    for fn in (runner.play_case, runner.play_all, runner.play_waves):
        assert "negotiator" in inspect.signature(fn).parameters, fn.__name__


# -- every case file through arena-sim with the reasoner and a fake model -------------------------------
def all_cases():
    out = {}
    for path in sorted(CASES.glob("*.json")):
        for case in json.loads(path.read_text()):
            out[case["case_id"]] = {k: v for k, v in case.items() if k != "hosted"}
    return out


@pytest.fixture(scope="module")
def arena():
    cases = all_cases()
    with serve(Sim(cases, clock=lambda: 1_000_000.0)) as url:
        key = ArenaClient(url).register(f"test-{secrets.token_hex(3)}", "sim")["api_key"]
        yield ArenaClient(url, key, rate=1000), cases


def fake_model(system, user):
    """Reads like a model that always asks for faster payment, chooses the first trade else the step."""
    if "OPTIONS" not in user:
        return json.dumps({"asks": ["payment"], "levers": ["payment_days"], "counted": ["index"], "dismissed": []})
    trade = next((line.split(":", 1)[0].strip("- ") for line in user.split("\n") if line.startswith("- trade:")), None)
    return json.dumps({"option": trade or "large", "claims": 2, "reason": "test"})


@pytest.mark.parametrize("case_id", sorted(all_cases()))
def test_every_case_plays_through_with_the_reasoner(arena, case_id, tmp_path, monkeypatch, caplog):
    client, cases = arena
    monkeypatch.setattr(runner, "RUNS", tmp_path)
    with caplog.at_level(logging.ERROR, logger="buyer"):
        result = runner.play_case(RemoteTable(client), case_id, complete=fake_model, negotiator=Reasoner)
    assert not caplog.records, [r.getMessage() for r in caplog.records]
    assert "deal" in result
    if result["deal"]:
        assert 0 <= result["score"] <= 1
