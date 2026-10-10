"""The Live Final loop end to end on arena-sim: waves appear one after another in the case list,
every case of a wave plays within its cap, a poll error is polled again, and the loop ends when
the last wave has closed. No network, no model."""

import secrets
import socket
import threading
import time

import pytest
import uvicorn
from arena_kit import ArenaClient
from arena_kit.client import ArenaError
from arena_kit.sim import Sim, create_app, load_cases

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


@pytest.fixture
def sim_url():
    sim = Sim(load_cases(), clock=lambda: 1_000_000.0)
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(create_app(sim), port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        time.sleep(0.01)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join()


def test_play_waves_plays_every_wave(sim_url, tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "RUNS", tmp_path)
    key = ArenaClient(sim_url).register(f"test-{secrets.token_hex(3)}", "sim")["api_key"]
    waves = [["case:S01", "case:S02"], ["case:S03"]]
    client = FinalClient(sim_url, key, waves)
    out = runner.play_waves(client, waves=2, parallel=3, poll=0.05)
    assert set(out) == {"case:S01", "case:S02", "case:S03"}
    for case_id, result in out.items():
        assert not isinstance(result, Exception), (case_id, result)
        assert "deal" in result
