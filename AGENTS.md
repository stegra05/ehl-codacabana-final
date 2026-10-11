# AGENTS.md

Hackathon repo, EHL Grand Finale, Munich. Our agent buys for Hollerau Pumpenwerke: it negotiates
by e-mail with Tacto's supplier bots and closes one term sheet per case, or walks. Score per case:
`(C_open - C_deal) / (C_open - C_best)`, C computed exactly by `arena_kit.total_cost`. The Live
Final is five waves of hidden cases, 8 minutes each, new suppliers and case types included.

## Principles

- Code owns every binding number (sheet, accept, walk away) and checks it with `total_cost` and
  `must_haves_ok`; the model owns words.
- Branch on what the data says about a supplier, never on a case or supplier ID.
- Every move goes out within 60 s, whatever fails.
- Evidence over opinion: a finding carries its session or data ID and its sample size. One run
  is a data point, not a law.
- Try anything on the simulator or sandbox; they are free.

## Hard rules (breaking one can disqualify us)

- No human in the loop during the final. The runner starts before 12:00 and is left alone; the
  final runs the commit submitted at 12:00.
- Agent code never calls `/v1/events`, `/v1/events/stream`, `/screen`, `/v1/screen`,
  `/leaderboard`, `/v1/leaderboard`, `/results`, `/v1/results`.
- One key per team, in `.env`, never printed or logged. No attacks on the arena or other teams,
  prompt-injecting bots included.
- Arena limits: 60 s per message from the supplier's reply, three timeouts end a thread; 10
  messages per thread, up to 3 term sheets per message, every sheet carries every `negotiable`
  field; max 3 claim checks per message, ID and figure in one sentence; 10 calls/s, 10 open
  sessions; 200 practice sessions per rolling 24 h for the team (`case:D01`, `case:D02` and the
  simulator are free).

## Repo

- PRs against `main`, one reviewer, branch `<firstname>/<topic>`; never push to `main`.
  `uv run pytest -q && uv run ruff check . && uv run ruff format --check .` before a PR.
- `docs/learnings.md` observations with evidence; `docs/design.md` what the agent does;
  `docs/architecture.md` the module map; `docs/challenge.md`, `api.md`, `submission.md` Tacto's
  brief, API and hand-in.
- `buyer/` the agent (`policy.py` decides, `runner.py` plays a case, `economics.py` C and terms,
  `claims.py`, `personas.py`, `writer.py`, `llm.py`); `research.py`, `rehearsal.py`, `analyst.py`
  and `memory.py` provide the subagent team; `tests/` run against `arena-sim`;
  `logs/sessions/`, `logs/runs/` traces; `exports/` Saturday's sessions as CSV; `analysis/`.
- `arena_kit` (in `.venv`) has the cost function, quote parsing, data lookup and runners; the MCP
  server `arena-data` gives SQL over the data package.

```sh
uv sync                                          # Python 3.12
uv run arena data                                # data package into data/
uv run arena me                                  # key and quota
uv run buyer play case:D01 -v                    # sandbox, free
uv run buyer play case:P01 -v                    # practice, 1 of 200
uv run buyer run --set practice --parallel 10    # all hosted practice cases
uv run buyer pull --set practice                 # finished sessions into logs/sessions/
uv run arena-sim serve --no-clock --data data/package
cd pitch && npm install && npm run dev           # pitch monitor: replays one session, → steps
```

Sunday: 08:00 `uv run arena data`; check `DataPackage("data/package").release` is set, list the
release's `data/*.csv` (they reach `ids`, `lookup` and `document`, not SQL) and run
`uv run pytest -q` with it in place. 11:30 checklist in `docs/submission.md`. Before 12:00 from
`main`: `uv run buyer run --set final --parallel 10 -v 2>&1 | tee logs/final.log`, then submit
the hash.
