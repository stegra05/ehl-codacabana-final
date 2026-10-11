"""The Live Final loop end to end on arena-sim: waves appear one after another in the case list,
every case of a wave plays within its cap, a poll error is polled again, a crashed case is resumed,
and the loop ends when the last wave has closed. No network, no model."""

import secrets

from arena_kit import ArenaClient
from arena_kit.client import ArenaError

from buyer import runner


class FinalClient(ArenaClient):
    """The sim's client with a scripted final: `cases("final")` is 403 before the first wave, then
    lists each wave's cases as open with seconds left, then as closed; one poll fails outright."""

    def __init__(self, url, key, waves):
        super().__init__(url, key, rate=1000)
        self.waves, self.polls = waves, 0

    def cases(self, set_="practice"):
        if set_ != "final":
            return super().cases(set_)
        self.polls += 1
        if self.polls == 1:
            raise ArenaError(403, "the final has not started")
        if self.polls == 3:
            raise ArenaError(500, "a hiccup")
        step = 1 + (self.polls - 2) // 2  # a new wave every second poll; one past the last closes it
        out = []
        for w, ids in enumerate(self.waves, start=1):
            if w > step:
                continue
            open_ = w == step
            for cid in ids:
                out.append({"case_id": cid, "wave": w, "open": open_, "seconds_left": 480 if open_ else 0})
        return out


def final_client(sim_url, waves):
    key = ArenaClient(sim_url).register(f"test-{secrets.token_hex(3)}", "sim")["api_key"]
    return FinalClient(sim_url, key, waves)


def test_play_waves_plays_every_wave(sim_url, tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "RUNS", tmp_path)
    waves = [["case:S01", "case:S02"], ["case:S03"]]
    out = runner.play_waves(final_client(sim_url, waves), waves=2, parallel=3, poll=0.05)
    assert set(out) == {"case:S01", "case:S02", "case:S03"}
    for case_id, result in out.items():
        assert not isinstance(result, Exception), (case_id, result)
        assert "deal" in result


def test_a_crashed_case_is_resumed_while_its_cap_leaves_time(sim_url, tmp_path, monkeypatch):
    """Transient failures (a network blip, a broken reply) must not end a final case: the runner
    opens it again as long as the cap leaves time, and the case still closes."""
    monkeypatch.setattr(runner, "RUNS", tmp_path)
    monkeypatch.setattr(runner, "RETRY_S", 0)
    real, crashes = runner.play_case, {"left": 3}

    def flaky(*args, **kwargs):
        if crashes["left"] > 0:
            crashes["left"] -= 1
            raise RuntimeError("blip")
        return real(*args, **kwargs)

    monkeypatch.setattr(runner, "play_case", flaky)
    out = runner.play_waves(final_client(sim_url, [["case:S01"]]), waves=1, parallel=1, poll=0.05)
    assert crashes["left"] == 0
    assert "deal" in out["case:S01"]


def test_a_case_that_keeps_crashing_returns_its_error(sim_url, tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "RUNS", tmp_path)
    monkeypatch.setattr(runner, "RETRY_S", 0)
    monkeypatch.setattr(runner, "RETRY_MAX", 3)
    calls = {"n": 0}

    def broken(*args, **kwargs):
        calls["n"] += 1
        raise RuntimeError("down")

    monkeypatch.setattr(runner, "play_case", broken)
    out = runner.play_waves(final_client(sim_url, [["case:S01"]]), waves=1, parallel=1, poll=0.05)
    assert calls["n"] == 3
    assert isinstance(out["case:S01"], RuntimeError)
