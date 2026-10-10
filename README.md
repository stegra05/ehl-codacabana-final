# Codacabana: Tacto Negotiation Arena

Team Codacabana at the European Hackathon League Grand Finale, Munich, 10 to 11 October 2026,
Tacto track. Our AI buyer for Hollerau Pumpenwerke negotiates by e-mail with Tacto's supplier
bots and closes the deal with the lowest total cost, or walks away. Brief: `docs/challenge.md`.

## Setup

Python 3.12 and [uv](https://docs.astral.sh/uv/).

```sh
git config core.hooksPath .githooks   # secret scan, no pushes to main, Entire hooks
uv sync                               # the agent, Tacto's arena kit, pytest, ruff
cp .env.example .env                  # fill in the keys below
uv run arena data                     # data package into data/package
uv run arena me                       # the key works: team and practice quota
```

Environment variables (`.env.example`):

| Variable | What |
|---|---|
| `ARENA_URL` | `https://arena.tacto.ai` |
| `ARENA_API_KEY` | the team key from https://arena.tacto.ai/apply |
| `ARENA_DATA` | `data/package` |
| `LLM_PROVIDER`, `LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY` | the model: `openai` (any compatible endpoint) or `anthropic`; optional `LLM_EFFORT` |

## Run

```sh
uv run buyer play case:D01 -v                     # one sandbox case (free)
uv run buyer run --set practice --parallel 10     # every hosted practice case (counts against the quota)
uv run buyer pull --set practice                  # finished sessions with trace -> logs/sessions/
uv run buyer run --set final --parallel 10 -v     # the Live Final: start before 12:00, leave it running
```

## Approach

Today the agent is Tacto's reference `LLMAgent` behind our runner: code computes the total cost
C of every term sheet and refuses bad accepts, the model writes the e-mails. Our strategy replaces
it layer by layer in `buyer/agent.py`: plan in `docs/design.md`, findings in `docs/learnings.md`.

## Develop

Rules for people and coding agents: `AGENTS.md`.

```sh
uv run pytest -q                 # our agent end to end against the local arena simulator
uv run ruff check . && uv run ruff format .
```
