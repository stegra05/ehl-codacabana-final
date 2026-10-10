"""The model's moves against arena-sim with a scripted model: what it decides goes out through the
guard, out-of-bounds answers are clamped, and a broken model leaves the move to the code policy."""

import json
import secrets

from arena_kit import ArenaClient, RemoteTable

from buyer import runner
from buyer.runner import play_case


def client(sim_url):
    key = ArenaClient(sim_url).register(f"test-{secrets.token_hex(3)}", "sim")["api_key"]
    return ArenaClient(sim_url, key, rate=1000)


def model(answer):
    calls = []

    def complete(system, user, schema=None):
        calls.append(user)
        return json.dumps(answer(len(calls), user)) if callable(answer) else answer

    complete.calls = calls
    return complete


def play(sim_url, tmp_path, monkeypatch, complete):
    monkeypatch.setattr(runner, "RUNS", tmp_path)
    table = RemoteTable(client(sim_url))
    result = play_case(table, "case:S01", complete=complete)
    notes = json.loads(next(tmp_path.glob("*.json")).read_text())["notes"]
    return result, notes


def test_the_models_move_goes_out_guarded(sim_url, tmp_path, monkeypatch):
    def answer(n, user):
        return {
            "read": "it holds",
            "plan": "far below, then its counter",
            "action": "counter",
            "sheets": [{"row": "L0", "unit_price": 0.01 if n == 1 else 1e6}],
            "claims": ["C1", "C99"],
            "email": "Thank you for your offer. We value the partnership and propose a fair package.",
        }

    complete = model(answer)
    result, notes = play(sim_url, tmp_path, monkeypatch, complete)
    moves = [n for n in notes if n["what"] == "model_move"]
    assert moves and complete.calls
    assert any("clamped" in f for f in moves[0]["fixes"])  # never under the opening floor
    assert any("C99 dropped" in f for f in moves[0]["fixes"])  # no claim outside the bank
    sends = [n for n in notes if n["what"] == "send"]
    assert sends[0]["ours"] > 0.7 * sends[0]["theirs"]
    assert result["deal"]  # at its counter it agrees


def test_a_broken_model_leaves_the_move_to_the_code_policy(sim_url, tmp_path, monkeypatch):
    result, notes = play(sim_url, tmp_path, monkeypatch, model("not json"))
    assert any(n["what"] == "model_fallback" for n in notes)
    assert not any(n["what"] == "model_move" for n in notes)
    assert result["deal"]


def test_prose_with_a_figure_falls_back_to_the_template(sim_url, tmp_path, monkeypatch):
    def answer(n, user):
        return {
            "read": "",
            "plan": "",
            "action": "counter",
            "sheets": [{"row": "L1", "unit_price": 1e6}],
            "claims": [],
            "email": "We can pay in 14 days.",
        }

    result, notes = play(sim_url, tmp_path, monkeypatch, model(answer))
    assert any("prose dropped: template" in f for n in notes if n["what"] == "model_move" for f in n["fixes"])
    assert result["deal"]
