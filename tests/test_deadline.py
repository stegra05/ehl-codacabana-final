"""A wave's cap leaves room for one more round as slow as the slowest so far: the case closes before
the cap instead of starting a round that ends after it. Fake table with slow replies, no model."""

import copy
import time

from arena_kit import complete_offer
from arena_kit.sim import load_cases

from buyer import runner


class SlowTable:
    """One supplier that concedes a little every round; each reply takes `reply_s`."""

    session_id = "fake"

    def __init__(self, case, reply_s):
        self.case, self.reply_s = case, reply_s
        self.sid = case["suppliers"][0]
        self.price, self.closed_at = 16.0, None

    def sheet(self):
        terms = complete_offer(self.case, {"unit_price": self.price, "payment_days": 60})
        return {
            "from": "supplier",
            "status": "open",
            "body": "Our offer.",
            "term_sheets": [{"term_sheet_id": f"ts{self.price}", "terms": terms}],
        }

    def open(self, case_id):
        return self.case, {self.sid: [self.sheet()]}

    def send(self, sid, message):
        time.sleep(self.reply_s)
        self.price = round(self.price - 0.05, 2)
        return self.sheet()

    def close(self, sid, message):
        self.closed_at = time.time()
        return {"deal": message["action"]["type"] == "accept"}


def test_the_case_closes_before_a_round_would_cross_the_cap(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "RUNS", tmp_path)
    monkeypatch.setattr(runner, "CLOSE_BEFORE_CAP_S", 0.1)  # the fixed margin alone is too short here
    monkeypatch.setattr(runner, "ROUND_MARGIN_S", 0.05)
    case = copy.deepcopy(load_cases()["case:S01"])
    table = SlowTable(case, reply_s=0.4)
    cap = time.time() + 1.5
    result = runner.play_case(table, case["case_id"], deadline=lambda: cap)
    assert result["deal"]
    assert table.closed_at < cap
