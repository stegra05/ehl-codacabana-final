# AGENTS.md

Rules for AI coding agents in this repo. Humans follow them too.

Hackathon repo, EHL Grand Finale, Munich, 10 to 11 Oct 2026. Code freeze and Live Final Sunday
12:00. Working agent first, polish second.

## Rules

- Do not preserve backward compatibility. Remove obsolete paths instead of adding layers,
  fallbacks or migrations.
- Choose the simplest implementation that fully meets the current requirement. No speculative
  abstractions, configuration or indirection.
- Grow in layers on a product that already works. Never trade a working agent for unfinished
  complexity.
- Keep components modular and concerns separated.
- Read `arena_kit` (in `.venv`) before writing a helper: cost function, quote parsing, data lookup
  and runners exist. We wrap the kit, never patch it. Guide:
  https://github.com/tacto-ai/negotiation-arena-kit/tree/main/starter-kit
- Never commit secrets. Keys live in `.env`. Never print, log or paste the arena key anywhere.
- All changes go through a PR against `main`, reviewed by one teammate. Branch `<firstname>/<topic>`.
  Agents may commit, push their branch and `gh pr create`; never push to `main`, force-push or merge.
- Run `uv run pytest -q && uv run ruff check . && uv run ruff format --check .` before every PR.
- No em-dashes in prose or copy. Be terse: after an action, state what changed in three lines.

## The challenge

We are the purchasing team of Hollerau Pumpenwerke. Our agent negotiates by e-mail with Tacto's
supplier bots (LLM personas with hidden economics) and closes one term sheet per case, or walks.

- **Score** per case: `(C_open - C_deal) / (C_open - C_best)`, clipped to 0..1. C is total cost
  over the horizon (price, uncovered need, payment, freight, lead time, quality, tooling, index
  clause, relationship charge), computed exactly by `arena_kit.total_cost`. No deal scores the
  alternative (0 if none). A broken must-have scores 0.
- **Live Final**: five waves of hidden cases, 8 minutes each, a wave's cases in parallel. Wave
  score = mean case score x 100; total = sum. New suppliers; up to a third mix supplier and case
  types practice never shows; some cite the Sunday 08:00 data release.

**Hard rules, breaking one can disqualify us:**
- No human in the loop during the final. The runner starts before 12:00 and is left alone.
- Agent code never calls `/v1/events`, `/v1/events/stream`, `/screen`, `/v1/screen`,
  `/leaderboard`, `/v1/leaderboard`, `/results`, `/v1/results`.
- One key per team. No attacks on the arena or other teams (prompt-injecting bots counts).
- The final runs the commit we submit at 12:00. No pushes after that.

**Hard limits:**
- 60 s per message per thread from the supplier's reply; three timeouts in a row end the thread.
- 10 messages per thread, up to 3 term sheets per message, every sheet carries every `negotiable`
  field.
- Max 3 claim checks per message, one per sentence, ID and figure in the same sentence. A wrong
  figure or unknown ID is `contradicted` and costs trust.
- 10 calls/s and 10 open sessions per key.
- **Practice quota: 200 sessions per rolling 24 h for the whole team.** Sandbox (`case:D01`,
  `case:D02`) and the local simulator are free.

## Where things are

| Path | What |
|---|---|
| `docs/learnings.md` | **read first**: what we know about the arena, suppliers and data, with evidence |
| `docs/design.md` | the agent we are building: modules, data, policy, build order |
| `docs/challenge.md`, `api.md`, `submission.md` | Tacto's brief, API and cost formula, hand-in (upstream copies) |
| `buyer/policy.py`, `runner.py` | the price engine: per-thread policy and the supplier's asks; the loop that plays a case and the Live Final waves (`docs/design.md`, Implemented) |
| `buyer/economics.py`, `claims.py`, `personas.py`, `writer.py`, `llm.py` | C and term planning, claim bank, persona signals, e-mail composition, model paragraph |
| `buyer/cli.py` | `buyer play`, `buyer run`, `buyer pull`, `--agent naive` |
| `tests/` | end to end against `arena-sim`, no network, no model |
| `exports/` | Saturday probe sessions as CSV/JSONL; schema in `exports/README.md` |
| `analysis/explore.py` | data package exploration: profiles, persona signals, report page |
| `data/package/` | the data package (gitignored); Sunday also `data/release-sunday/` |
| `logs/sessions/<set>/` | finished sessions with trace and back office (gitignored; Saturday's committed with `-f`) |
| `logs/runs/`, `logs/practice-v*.log` | our decisions per move (anchor, terms, claims, prices) and the practice run logs |

The MCP server `arena-data` (`.mcp.json`) gives SQL, ID lookup and documents over the package.

## Commands

```sh
uv sync                                         # install (Python 3.12)
uv run arena data                               # data package into data/
uv run arena me                                 # key works? quota left?
uv run buyer play case:D01 -v                   # sandbox: free
uv run buyer play case:P01 -v                   # practice: costs 1 of the team's 200
uv run buyer run --set practice --parallel 10   # all hosted practice cases: costs 10
uv run buyer pull --set practice                # finished sessions -> logs/sessions/
uv run arena-sim serve --no-clock --data data/package   # local API, scripted supplier
uv run --with pandas python analysis/explore.py # data package -> analysis/out/
```

`--agent naive` plays the kit's baseline instead of ours.

## Working on the negotiation agent

- **Code owns numbers, the model owns words.** Every binding value (sheet, accept, walk away) is
  computed or checked in code with `total_cost` and `must_haves_ok`; every figure in an e-mail
  comes from code next to its data ID.
- **Never accept** a sheet that breaks a must-have or costs more than the alternative. Price
  unstated fields at the supplier's standard terms (`arena_kit.docs.standard_terms`).
- **Read the supplier.** What moves it is in the data (call notes, letters, news, quote remarks,
  payment history, scorecards). Trade what is cheap for us for what it values.
- **Score every lever per case.** The same term helps in one case and hurts in the next
  (coverage, payment days, start date, index clause, contract length).
- **Generalise.** No logic keyed on case or supplier IDs; runtime knowledge from the data package
  is fine if it works for unseen suppliers.
- **Don't leak** urgency, budget, a missing alternative or the target price.
- **Every model call has a hard timeout** well under 60 s, and the move still goes out if it
  fails. Measure latency per move.

## The learning loop

1. Try on the simulator or sandbox first. Spend practice quota only on a change you expect to
   help; check `uv run arena me` before batch runs.
2. After practice: `uv run buyer pull`, read `logs/sessions/` (trace, back office, cost breakdown).
3. Find why C_deal missed C_best, change the agent, score candidate sheets offline, play again.
4. Record each finding in `docs/learnings.md` in the same PR: date, tag (`arena` / `data` /
   `rules`), finding, evidence (session, case or data ID), consequence for the agent. Untested
   ideas go under Hypotheses; correct or delete entries that turn out wrong. Design changes go
   into `docs/design.md`. No new doc files without a reason.

## Sunday

- 08:00: `uv run arena data` again; the release lands in `data/release-sunday/`. Check that
  `DataPackage("data/package").release` is not `None`, list the release's `data/*.csv` and their
  columns (they reach `ids`, `lookup` and `document`, not SQL), count new supplier IDs, and run
  `uv run pytest -q` (every case file through `arena-sim`) with the release in place.
- 09:00: pre-flight, one practice case through the final machine and setup.
- 11:30: checklist in `docs/submission.md` (key, data, LLM credits, power, no sleep, log file).
- Before 12:00, from `main`: `uv run buyer run --set final --parallel 10 -v 2>&1 | tee logs/final.log`,
  then submit that commit hash on ehl.gg.
