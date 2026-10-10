"""Which agent plays a case. Our strategy grows here; until then `buyer` is the kit's LLMAgent."""

from arena_kit.agents import LLMAgent, NaiveAgent, llm_from_env
from arena_kit.data import DataPackage

AGENTS = ("buyer", "naive")


def agent_factory(name, data=None, complete=None):
    """A function that returns a fresh agent per case. `data`: the unpacked data package;
    `complete(system, user) -> str`: the model (default: from .env via `llm_from_env`)."""
    if name == "naive":
        return NaiveAgent
    package = None
    if data:
        package = DataPackage(data)
        package.lookup("")  # build the ID index once, before parallel agents share it
    complete = complete or llm_from_env()
    return lambda: LLMAgent(complete, package)
