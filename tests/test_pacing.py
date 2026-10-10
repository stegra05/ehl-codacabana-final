"""Pacing by the wave's clock: the share of the gap grows when the clock leaves fewer rounds than
the round limit; the runner derives the rounds from the cap, the measured round time and the open
threads; a capped case closes before the cap. No network, no model."""

import copy
import time

import pytest
from arena_kit import complete_offer
from arena_kit.sim import load_cases

from buyer import runner
from buyer.policy import FRACTION, MAX_FRACTION, Negotiator, pace


def test_pace_grows_as_the_clock_tightens():
    assert pace(9, 9) == FRACTION
    assert pace(9, 12) == FRACTION  # more rounds on the clock than the limit allows: the plain path
    assert pace(9, 0) == FRACTION  # no information: the plain path
    assert FRACTION < pace(9, 6) < pace(9, 4) <= MAX_FRACTION
    assert pace(9, 3) == MAX_FRACTION
    assert pace(9, 1) == MAX_FRACTION
    # the paced path ends where the plain path would have after `left` rounds
    assert (1 - pace(9, 6)) ** 6 == pytest.approx((1 - FRACTION) ** 9)


def test_rounds_by_clock():
    assert runner.rounds_by_clock(None, 0.0, 25, 3) is None
    # 480 s cap, 90 s close margin, 30 s rounds, 3 open threads: 390 / 90 = 4.33 rounds each
    assert runner.rounds_by_clock(480.0, 0.0, 30, 3) == pytest.approx(390 / 90)
    assert runner.rounds_by_clock(480.0, 0.0, 30, 1) == pytest.approx(13)
    assert runner.rounds_by_clock(100.0, 50.0, 30, 2) == 0.0  # inside the close margin


def offer(sheet_id, terms, status="open"):
    return {
        "from": "supplier",
        "status": status,
        "body": "Our offer.",
        "term_sheets": [{"term_sheet_id": sheet_id, "terms": terms}],
    }


def test_a_tight_clock_moves_further_in_a_round():
    case = copy.deepcopy(load_cases()["case:S01"])
    sid = case["suppliers"][0]
    quote = complete_offer(case, {"unit_price": 15.0, "payment_days": 60})

    def price_after_round_two(rounds):
        neg = Negotiator(case)
        threads = {sid: [offer("o1", quote)]}
        neg.setup(sid, threads[sid])
        first = neg.move(sid, threads, rounds=rounds)["message"]
        threads[sid] += [{**first, "from": "buyer"}, offer("o2", {**quote, "unit_price": 14.5})]
        second = neg.move(sid, threads, rounds=rounds)["message"]
        return first["term_sheets"][0]["terms"]["unit_price"], second["term_sheets"][0]["terms"]["unit_price"]

    a1, relaxed = price_after_round_two(None)
    b1, tight = price_after_round_two(2)
    assert a1 == b1  # the anchor does not depend on the clock
    assert tight > relaxed  # with two rounds left we move more of the gap
    assert tight < 14.5  # and stay below its counter


class SlowTable:
    """A supplier that answers at once; the wall clock is faked by the test."""

    session_id = "fake"

    def __init__(self, case, quote):
        self.case, self.quote, self.sent, self.closed = case, quote, 0, None

    def open(self, case_id):
        sid = self.case["suppliers"][0]
        return self.case, {sid: [offer("o0", self.quote)]}

    def send(self, sid, message):
        self.sent += 1
        price = round(self.quote["unit_price"] - 0.1 * self.sent, 2)
        return offer(f"o{self.sent}", {**self.quote, "unit_price": price})

    def close(self, sid, message):
        self.closed = message
        return {"deal": True, "terms": self.quote, "c_open": 1.0, "c_deal": 1.0, "c_best": 1.0, "score": 1.0}


def test_a_capped_case_closes_before_the_cap(tmp_path, monkeypatch):
    """Each round takes 40 s of (faked) wall clock; with a 300 s cap and a 90 s close margin the
    runner sends at most five messages, then accepts the standing sheet."""
    monkeypatch.setattr(runner, "RUNS", tmp_path)
    case = copy.deepcopy(load_cases()["case:S01"])
    quote = complete_offer(case, {"unit_price": 15.0, "payment_days": 60})
    table = SlowTable(case, quote)
    clock = {"t": 1000.0}
    monkeypatch.setattr(time, "time", lambda: clock["t"])
    monkeypatch.setattr(time, "monotonic", lambda: clock["t"])
    real_send = table.send

    def slow_send(sid, message):
        clock["t"] += 40
        return real_send(sid, message)

    table.send = slow_send
    result = runner.play_case(table, case["case_id"], deadline=1000.0 + 300)
    assert result["deal"]
    assert table.closed["action"]["type"] == "accept"
    assert table.sent == 6  # sends at 0, 40, ... 200 s; none past 210 s (the cap less the 90 s margin)
    assert clock["t"] <= 1000.0 + 300 - 60  # closed with time to spare
