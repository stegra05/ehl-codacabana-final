import contextlib
import socket
import threading
import time

import pytest
import uvicorn
from arena_kit.sim import Sim, create_app, load_cases


@contextlib.contextmanager
def serve(sim):
    """arena-sim on a free local port; yields its URL."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(create_app(sim), port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        time.sleep(0.01)
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join()


@pytest.fixture
def sim_url():
    """The kit's sim cases with a clock that never moves (no 60-second timeouts)."""
    with serve(Sim(load_cases(), clock=lambda: 1_000_000.0)) as url:
        yield url
