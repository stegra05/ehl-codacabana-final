"""Which agent plays a case: `buyer` is our policy (`policy.py`, played by `runner.py`), `naive`
the kit's baseline."""

from arena_kit.agents import NaiveAgent
from arena_kit.data import DataPackage

AGENTS = ("buyer", "naive")


def load_package(path):
    """The data package with its ID index built once, before parallel cases share it."""
    if not path:
        return None
    pkg = DataPackage(path)
    pkg.lookup("")
    return pkg


def naive_factory():
    return NaiveAgent
