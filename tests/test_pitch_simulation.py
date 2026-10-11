"""The UI demo must play the buyer and preserve its real cost-checked outcome."""

import math

from arena_kit import must_haves_ok, total_cost

from buyer import memory, research, runner
from pitch.simulate import generate


def test_ui_trace_plays_offline_and_keeps_production_state_untouched(monkeypatch):
    def no_network(*args, **kwargs):
        raise AssertionError("the UI test exporter must stay offline")

    monkeypatch.setattr("socket.create_connection", no_network)
    original = (memory.LESSONS, runner.RUNS, research.CACHE)
    lessons = memory.LESSONS.read_bytes() if memory.LESSONS.exists() else None
    trace = generate()
    assert (memory.LESSONS, runner.RUNS, research.CACHE) == original
    assert (memory.LESSONS.read_bytes() if memory.LESSONS.exists() else None) == lessons
    assert trace["source"] == "arena-kit simulator" and trace["model"] == "scripted fixtures"
    assert trace["sample_size"] == 1
    events, case, result = trace["events"], trace["case"], trace["result"]
    assert case["round_limit"] == 3
    assert {e["stage"] for e in events} == {
        "research",
        "rehearsal",
        "analyst",
        "negotiator",
        "writer",
        "close",
        "debrief",
    }
    assert events[0]["best"] is None and events[0]["suppliers"] == {}
    assert events[-2]["stage"] == "close" and events[-1]["stage"] == "debrief"
    assert not any(s["status"] == "accepted" for e in events[:-2] for s in e["suppliers"].values())
    sends = [e for e in events if e["stage"] == "writer"]
    assert sends
    for supplier in trace["suppliers"]:
        assert sum(e["supplier"] == supplier["id"] for e in sends) <= 3
    for event in sends:
        sheets = event["detail"]["message"]["term_sheets"]
        assert 1 <= len(sheets) <= 3
        for sheet in sheets:
            assert set(sheet["terms"]) == set(case["negotiable"])
            assert must_haves_ok(case, sheet["terms"])
    assert result["deal"] and result["must_haves_ok"]
    assert math.isclose(total_cost(case, result["terms"]), result["c_deal"], abs_tol=0.01)
    assert events[-1]["suppliers"][result["supplier_id"]]["status"] == "accepted"
