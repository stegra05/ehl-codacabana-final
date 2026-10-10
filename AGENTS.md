# AGENTS.md

Rules for AI coding agents working in this repo. Humans follow them too.

- Hackathon repo (EHL Grand Finale, Munich, 10 to 11 Oct 2026). Submission deadline
  Sunday 12:00, pitch is six minutes including questions. Working demo first, polish second.
- Do not preserve backward compatibility. Remove obsolete paths instead of adding
  compatibility layers, fallbacks, or migrations.
- Choose the simplest implementation that fully meets the current requirement.
  No speculative abstractions, configuration, or indirection.
- Grow the system in layers: smallest version that works end to end, then add on
  top of a product that already works. Never trade a working product for
  unfinished complexity.
- Keep components modular and concerns separated.
- Prefer established libraries already in the project before adding new ones or
  writing your own implementation.
- Never commit secrets. API keys go into `.env` (gitignored).
- All changes go through a pull request against `main`, reviewed by one teammate.
  Branch naming: `<firstname>/<topic>`.
- No em-dashes in prose or user-facing copy.
- Be terse: after an action, state what changed in three lines or fewer.

## Challenge

Tacto Negotiation Arena (official brief: `docs/challenge.md`; API: `negotiation-agent/negotiation-arena-kit/brief/api.md`).
We are the procurement team of Hollerau Pumpenwerke; our agent negotiates by e-mail with supplier
bots and is scored on the total cost C of the accepted term sheet, per case and category goal.

Hard constraints:
- 60 seconds per message per thread, counted from the supplier's reply; three timeouts end a thread.
- Live Final Sunday 12:00: five waves of hidden cases, 8 minutes each, all cases of a wave in parallel,
  no human in the loop, the agent must not read the leaderboard or event feed. Code freeze at 12:00.
- Only term sheets bind; cited data IDs are checked (a wrong figure costs trust); a broken must-have scores 0.
- 200 practice sessions per rolling 24 hours; the sandbox (`case:D01`, `case:D02`) is free.
- Keys stay in `.env`. Our code: `negotiator/` (agent), `knowledge/` (supplier personas, learned after each case).
