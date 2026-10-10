"""Every case file we know (practice, hosted or not, and the sandbox) plays through arena-sim with
our agent: no exception on any case structure (bundles, 3-bidder RFQs, tooling, index clauses,
75 term combinations). The sim's supplier is a script, so this checks code paths, not tactics."""

import json
import logging
import secrets
from pathlib import Path

import pytest
from arena_kit import ArenaClient, RemoteTable
from arena_kit.sim import Sim
from conftest import serve

from buyer import runner

CASES = Path(__file__).parent.parent / "logs" / "cases"


def all_cases():
    out = {}
    for path in sorted(CASES.glob("*.json")):
        for case in json.loads(path.read_text()):
            case = {k: v for k, v in case.items() if k != "hosted"}
            out[case["case_id"]] = case
    return out


@pytest.fixture(scope="module")
def arena():
    cases = all_cases()
    with serve(Sim(cases, clock=lambda: 1_000_000.0)) as url:
        key = ArenaClient(url).register(f"test-{secrets.token_hex(3)}", "sim")["api_key"]
        yield ArenaClient(url, key, rate=1000), cases


@pytest.mark.parametrize("case_id", sorted(all_cases()))
def test_every_case_plays_through(arena, case_id, tmp_path, monkeypatch, caplog):
    client, cases = arena
    monkeypatch.setattr(runner, "RUNS", tmp_path)
    with caplog.at_level(logging.ERROR, logger="buyer"):
        result = runner.play_case(RemoteTable(client), case_id)
    assert not caplog.records, [r.getMessage() for r in caplog.records]  # no guarded failure either
    assert "deal" in result
    if result["deal"]:
        assert 0 <= result["score"] <= 1
