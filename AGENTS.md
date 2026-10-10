# AGENTS.md

Rules for AI coding agents working in this repo. Humans follow them too.

- Hackathon repo (EHL Grand Finale, Munich, 10 to 11 Oct 2026). Code freeze and Live Final
  Sunday 12:00. Working agent first, polish second.
- Do not preserve backward compatibility. Remove obsolete paths instead of adding
  compatibility layers, fallbacks, or migrations.
- Choose the simplest implementation that fully meets the current requirement.
  No speculative abstractions, configuration, or indirection.
- Grow the system in layers: smallest version that works end to end, then add on
  top of a product that already works. Never trade a working product for
  unfinished complexity.
- Keep components modular and concerns separated.
- Prefer established libraries already in the project before adding new ones or
  writing your own implementation. Read `arena_kit` (in `.venv`) before writing a helper:
  the cost function, quote parsing, data lookup and the runners already exist.
- Never commit secrets. Keys go into `.env` (gitignored). Never print, log or paste the
  arena key anywhere (code, logs, issues, Discord, PR text).
- All changes go through a pull request against `main`, reviewed by one teammate.
  Branch naming: `<firstname>/<topic>`.
- No em-dashes in prose or user-facing copy.
- Be terse: after an action, state what changed in three lines or fewer.

## Challenge: Tacto Negotiation Arena

We are the purchasing team of Hollerau Pumpenwerke, a fictional German pump maker. Our agent
negotiates by e-mail with Tacto's supplier bots (LLM personas with hidden economics) and closes
one term sheet per case, or walks away. Full text: `docs/challenge.md` (brief), `docs/api.md`
(API, claim checks, cost formula), `docs/submission.md`. Upstream:
https://github.com/tacto-ai/negotiation-arena-kit, FAQ: https://arena.tacto.ai/faq.

**Score.** Per case `(C_open - C_deal) / (C_open - C_best)`, clipped to 0..1. C is the total
cost in euros over the case horizon: price, uncovered need, payment terms, freight, lead time,
quality, tooling, index clause, and in `stabilise` / `secure_supply` cases a charge for leaving
the supplier below a sustainable margin. Not price. `arena_kit.total_cost` computes C exactly.
No deal scores the alternative (0 if none). A broken must-have scores 0.

**Live Final.** Sunday 12:00, five waves of hidden cases, 8 minutes each, all cases of a wave in
parallel. New suppliers; up to a third combine supplier and case types practice never shows.
Some cite the Sunday 08:00 data release. Wave score = mean case score x 100; total = sum.

**Hard rules (breaking one can disqualify us):**
- No human in the loop during the final. The runner is started before 12:00 and left alone.
- Agent code never calls `/v1/events`, `/v1/events/stream`, `/screen`, `/v1/screen`,
  `/leaderboard`, `/v1/leaderboard`, `/results`, `/v1/results`. Those are for people.
- One key per team. No attacks on the arena or other teams.
- The final runs the commit we submit at 12:00. No pushes after that.

**Hard limits:**
- 60 seconds per message per thread, counted from the supplier's reply. A late message is a
  timeout; three in a row end the thread. Heavy work happens before a session is opened.
- 10 messages per thread (case `round_limit`), up to 3 term sheets per message, every term sheet
  carries every `negotiable` field.
- Max 3 claim checks per message; one argument per sentence, ID and figure in the same sentence.
  An unknown ID or wrong figure is `contradicted` and costs trust.
- 10 calls per second and 10 open sessions per key.
- **Practice quota: 200 sessions per rolling 24 h for the whole team, shared across all
  machines.** Sandbox (`case:D01`, `case:D02`) and the local simulator are free.

## Repo map

| Path | What |
|---|---|
| `buyer/agent.py` | which agent plays a case; our strategy grows here (today: the kit's `LLMAgent`) |
| `buyer/cli.py` | `buyer play`, `buyer run`, `buyer pull` |
| `tests/` | end to end against `arena-sim`, no network, no model |
| `docs/` | brief, API, submission guide (copied from upstream) |
| `data/package/` | the data package, gitignored; `uv run arena data` fetches it (Sunday also `data/release-sunday/`) |
| `logs/sessions/<set>/` | finished sessions with trace and back office, gitignored; `uv run buyer pull` fetches them |

`arena_kit` (Tacto's starter kit) is a git dependency pinned in `pyproject.toml`. We do not patch
it; we wrap it. Its README is the best guide to its modules:
https://github.com/tacto-ai/negotiation-arena-kit/tree/main/starter-kit

## Commands

```sh
uv sync                                         # install (Python 3.12)
uv run arena data                               # data package into data/ (again Sunday after 08:00)
uv run arena me                                 # key works? quota left?
uv run pytest -q && uv run ruff check .         # before every PR
uv run buyer play case:D01 -v                   # sandbox: free, real supplier bots
uv run buyer play case:P01 -v                   # practice: costs 1 of the team's 200
uv run buyer run --set practice --parallel 10   # all 10 hosted practice cases: costs 10
uv run buyer pull --set practice                # every finished session -> logs/sessions/
uv run buyer run --set final --parallel 10      # the Live Final, Sunday before 12:00
uv run arena-sim serve --no-clock --data data/package   # local API with a scripted supplier
```

`--agent naive` plays the kit's baseline instead of ours. The MCP server `arena-data`
(`.mcp.json`) gives coding agents SQL, ID lookup and documents over the data package.

## Working on the negotiation agent

- **Code owns numbers, the model owns words.** Every binding value (term sheets, accept,
  walk away) is computed or checked in code with `total_cost` and `must_haves_ok`. Every figure
  in an e-mail comes from code, next to its data ID. The model reads the supplier and writes.
- **Never accept** a term sheet that breaks a must-have or costs more than the alternative.
  Price unstated fields at the supplier's standard terms from its quote PDF (`docs.standard_terms`).
- **Generalise, don't memorise.** No logic keyed on practice case IDs or supplier IDs. Knowledge
  derived from the data package at runtime is fine; it must also work for unseen suppliers.
- **Read the supplier.** What moves it is in the data: call notes, letters, news, quote
  remarks, payment history, scorecards. Trade what is cheap for us (payment days, contract
  length, volume, dates) for what it values.
- **Don't leak** urgency, budget, a missing alternative or the target price.
- **Every model call has a hard timeout** well under 60 s, and the move still goes out if it
  fails. Measure latency per move.

## The learning loop

1. Try on the simulator or the sandbox first. Spend practice quota only on a change you expect
   to help, and check `uv run arena me` before batch runs: teammates share the 200.
2. After practice: `uv run buyer pull`, then read `logs/sessions/`. The trace holds the supplier's
   reasons for every move, the back office its internal discussion, the result the cost breakdown.
3. Find why C_deal missed C_best (which lever, which argument, which timing), change the agent,
   score candidate term sheets offline with `total_cost`, then play again.
4. Write what you learned about supplier behaviour into the PR description, so the team and
   the pitch can use it.

## Sunday

- 08:00: `uv run arena data` again; the release lands in `data/release-sunday/`.
- 09:00: pre-flight, one practice case through the final machine and setup.
- 11:30: checklist in `docs/submission.md` (key, data, LLM credits, power, no sleep, log file).
- Before 12:00: start `uv run buyer run --set final --parallel 10 -v 2>&1 | tee logs/final.log`
  from `main`, submit that commit hash on ehl.gg.
