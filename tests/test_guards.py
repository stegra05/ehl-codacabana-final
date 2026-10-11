"""The accept gate on every closing path, terminal results, the writer's time on the supplier clocks
and a bundle without a should-cost. Fake tables, no network, no model."""

import copy
import time

import pytest
from arena_kit import complete_offer
from arena_kit.client import ArenaError
from arena_kit.docs import standard_terms
from arena_kit.sim import load_cases

from buyer import economics as eco
from buyer import llm, runner
from buyer.policy import Negotiator, Side, std_terms


def s01(price=15.0):
    case = copy.deepcopy(load_cases()["case:S01"])
    return case, complete_offer(case, {"unit_price": price, "payment_days": 60})


def offer(sheet_id, terms, status="offer"):
    return {
        "from": "supplier",
        "status": status,
        "body": "Our offer.",
        "term_sheets": [{"term_sheet_id": sheet_id, "terms": terms}],
    }


def action(decision):
    return decision["message"]["action"]


def test_close_walks_when_the_alternative_is_cheaper():
    case, terms = s01(15.0)
    case["buyer"]["alternative"] = {
        "kind": "rfq",
        "terms": complete_offer(case, {"unit_price": 14.0, "payment_days": 60}),
    }
    neg = Negotiator(case)
    assert action(neg.close({"sup:a": [offer("ts1", terms)]})) == {"type": "walk_away"}
    cheaper = {**terms, "unit_price": 13.0}
    assert action(neg.close({"sup:a": [offer("ts2", cheaper)]})) == {"type": "accept", "term_sheet_id": "ts2"}


def test_relationship_charge_reverses_the_accept():
    case, terms = s01(15.0)
    b = case["buyer"]
    b.update(category_goal="stabilise", relationship_eur_per_point=2000, sustainable_margin_pct=15)
    b["alternative"] = {"kind": "rfq", "terms": complete_offer(case, {"unit_price": 15.2, "payment_days": 60})}
    neg = Negotiator(case)
    threads = {"sup:a": [offer("ts1", terms)]}
    assert action(neg.close(threads))["type"] == "accept"  # no full-cost estimate: no charge
    neg.sides["sup:a"] = side = Side("sup:a")
    side.est = eco.estimate(case, {}, 0.08, full_cost=14.9)  # a margin far below 15 %
    assert eco.deal_cost(case, terms, {}) is not None
    assert eco.deal_cost(case, terms, {}, side.est) is None
    assert action(neg.close(threads)) == {"type": "walk_away"}


def test_broken_sheets_are_skipped_not_fatal():
    case, terms = s01(15.0)
    neg = Negotiator(case)
    threads = {
        "sup:a": [offer("bad1", {"unit_price": None})],
        "sup:b": [offer("bad2", {**terms, "unit_price": "n/a"})],
        "sup:c": [offer("good", terms)],
    }
    assert action(neg.close(threads)) == {"type": "accept", "term_sheet_id": "good"}


class FakeTable:
    session_id = "fake"

    def __init__(self, case, threads, send=None, close=None, missed=None):
        self.case, self.threads = case, threads
        self._send, self._close, self._missed = send, close, missed
        self.closed = []

    def open(self, case_id):
        return self.case, self.threads

    def send(self, sid, message):
        return self._send(sid, message)

    def close(self, sid, message):
        self.closed.append((sid, message))
        return self._close(sid, message)

    def missed(self, sid, error):
        return self._missed(sid, error)


def test_a_terminal_send_ends_the_case_without_a_close(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "RUNS", tmp_path)
    case, terms = s01(15.0)
    sid = case["suppliers"][0]
    ended = {"deal": False, "end_reason": "all_walked_away"}

    def close(sid, message):
        raise AssertionError("close after a terminal result")

    table = FakeTable(case, {sid: [offer("ts1", terms)]}, send=lambda s, m: {"result": ended}, close=close)
    assert runner.play_case(table, case["case_id"]) == ended
    assert table.closed == []


@pytest.mark.parametrize(
    ("dear", "last"),
    [(15.3, {"type": "accept", "term_sheet_id": "dear"}), (16.0, {"type": "walk_away"})],
)
def test_a_refused_close_decides_again_with_the_guards(dear, last):
    """The accepted sheet is gone (409): the next choice is the other supplier's while it beats the
    alternative, else a walk-away; never a bad deal."""
    case, terms = s01(15.0)
    case["buyer"]["alternative"] = {
        "kind": "rfq",
        "terms": complete_offer(case, {"unit_price": 15.5, "payment_days": 60}),
    }
    threads = {"sup:a": [offer("cheap", terms)], "sup:b": [offer("dear", {**terms, "unit_price": dear})]}

    def close(sid, message):
        if message["action"].get("term_sheet_id") == "cheap":
            raise ArenaError(409, "offer withdrawn")
        return {"deal": message["action"]["type"] == "accept"}

    def missed(sid, error):
        return {"from": "arena", "status": "walked_away", "term_sheets": [], "body": "(gone)"}

    table = FakeTable(case, threads, close=close, missed=missed)
    runner.close(table, "case:S01", Negotiator(case), threads)
    assert [m["action"] for _, m in table.closed] == [{"type": "accept", "term_sheet_id": "cheap"}, last]


def test_writer_budget_leaves_time_for_every_live_clock():
    replied = {"a": 0.0, "b": 0.0, "c": 20.0}
    # a: 25 s left; b: must still get a message after a 10 s send, 15 s; c: 35 s
    assert runner.writer_budget("a", replied, ["a", "b", "c"], 10, now=30) == pytest.approx(15)
    assert runner.writer_budget("a", replied, ["a"], 10, now=0) == llm.TIMEOUT_S  # capped
    assert runner.writer_budget("a", replied, ["a", "b"], 10, now=44) < llm.MIN_S  # no model
    assert runner.writer_budget("a", replied, ["a", "b"], 10, now=0) == llm.TIMEOUT_S


def test_paragraph_is_bounded_by_wall_clock():
    calls = []

    def slow(system, user):
        calls.append(1)
        time.sleep(3)
        return "A fine paragraph."

    t0 = time.monotonic()
    assert llm.paragraph(slow, "brief", 2.2) is None
    assert time.monotonic() - t0 < 2.8
    assert llm.paragraph(slow, "brief", 1.0) is None  # no time: not even called
    assert len(calls) == 1


def test_a_bundle_has_no_should_cost():
    """One component's cost is not the bundle's unit cost: no full cost, so no relationship target."""
    case, terms = s01(15.0)
    sid = case["suppliers"][0]
    case["buyer"]["category_goal"] = "stabilise"
    case["facts"]["cost:320050"] = {"part": case["parts"][0], "unit_cost": 12.0, "supplier": sid}
    events = [offer("ts1", terms)]

    single = Negotiator(case).setup(sid, events)
    assert single.est.get("full_cost") == 12.0

    case["parts"] = case["parts"] + ["part:320051"]
    bundle = Negotiator(case).setup(sid, events)
    assert "full_cost" not in bundle.est
    assert bundle.target is None


def test_an_unparseable_quote_line_keeps_the_other_standard_terms():
    # the kit raises on a value it does not expect; one odd line must not drop the whole quote,
    # nor the supplier at the close (`best_offer` skips a supplier whose cost raises)
    text = (
        "Quote\nOur standard terms (apply to everything not stated above)\n"
        "Payment terms (days net) none\nLead time (days) 42\nIncoterm FCA"
    )
    events = [{"from": "sales@1", "attachments": [{"name": "quote.pdf", "text": text}]}]
    with pytest.raises(ValueError):
        standard_terms(events)
    assert std_terms(events) == {"lead_time_days": 42, "incoterm": "FCA"}


def test_a_document_that_cannot_be_read_never_costs_the_case():
    class Table:
        def attachment(self, attachment_id):
            raise ValueError("not a PDF")

    message = {"attachments": [{"attachment_id": "att:1", "name": "quote.pdf"}]}
    runner.fetch(Table(), "case:X", message)  # logged, not raised: the case goes on
    assert "text" not in message["attachments"][0]
