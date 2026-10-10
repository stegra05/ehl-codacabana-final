# Agent design

The target architecture of our buyer, merged from the team's planning notes (PRs #7 to #10,
10 Oct). What we learned in play is in `learnings.md`; this file says what we build.

**Status.** `main` plays the kit's `LLMAgent` behind our runner (`buyer/agent.py`). Julian's draft
two implements most of the design below on the unmerged branch `origin/julian/draft-two`
(`buyer/economics.py`, `claims.py`, `personas.py`, `llm.py`, `guard.py`, `runner.py`,
`thread.py`): sandbox D01 0.96, D02 0.54, no practice quota used. The architecture diagram is on
page 1 of [how-it-works.pdf](how-it-works.pdf).

## Principle

Code owns every number and every binding decision; the model reads replies and writes e-mails.
Score is total cost C, not price. Every step has a fallback that still sends a move within 60 s.

## A case

1. **Prepare** (before the first move, about 20 s): open the session, build a case brief: C_open,
   C_alt, target, walk-away, the lever table (C of each allowed option), a view of each supplier,
   and a claim bank of verified arguments. A stance call proposes per-supplier parameters; code
   clamps them.
2. **Negotiate**, one thread negotiator per supplier, in parallel. Each round:

   ```
   supplier reply
     -> READ    (model, hard timeout)  offer, intent, objections, statements
     -> CHECK   (code)  supplier statements against the data
     -> PLAN    (code)  candidate sheets scored with total_cost, filtered by must_haves_ok
     -> DECIDE  (code)  counter / accept / walk away, move size, claims
     -> WRITE   (model, hard timeout; template if late)  figures and IDs injected by code
     -> GUARD   (code)  every negotiable field, claim format, no leaks, no unplanned figures
   ```

3. **Close**: accept the best sheet that keeps every must-have and beats C_alt, or walk away;
   at the latest 90 s before the wave's 8-minute cap.
4. **Learn**: store the trace and what we learned per supplier for the next practice run.

## Modules

| Module | Job | Run by |
|---|---|---|
| Runner | polls the final's case list, one coordinator per case, restarts after a crash | code |
| Coordinator | case brief, starts thread negotiators, shared state, decides when to close | code |
| Economics | C of any sheet, floor, anchor, target, concession steps, accept gate | code |
| Personas | one profile per supplier: traits with evidence, levers, history | model offline, code live |
| Claim bank | arguments as sentences with figure and data ID, computed as the arena checks them | code |
| Reader / writer | supplier e-mail to JSON; move to e-mail | small model, hard timeout |
| Fact check | supplier statements: confirmed, contradicted, selective, unverifiable (not built) | code |
| Guard | blocks leaks, unknown IDs, unplanned figures, broken must-haves | code |
| Fallback cascade | unknown supplier or part: case facts, data search, category averages, its documents | code |

## What feeds the brief, by impact

| # | Data | Decides | Where |
|---|---|---|---|
| 1 | case file, quote PDF | C directly: need, horizon, rates, must-haves, alternative, options, standard terms | `GET /v1/cases`, `arena_kit.docs.standard_terms` |
| 2 | supplier cost floor | anchor, target, relationship charge | `should_cost`, cost-breakdown XLSX on request |
| 3 | index values of its cost drivers | justified price change, strongest claims | `cost_drivers`, `index_values`, `facts.json` |
| 4 | letters, notes, news | what moves it (cash, capacity, relationship), notice periods | `documents`, `correspondence/`, `news` |
| 5 | negotiation history | how far it usually moves | `negotiation_history` |
| 6 | intel, our invoices | archetype, payment lever | `supplier_intel`, `invoices`, `suppliers` (cash discount) |
| 7 | contracts and clauses | notice, index clauses, expiry, single sourcing | `contracts`, `contract_clauses`, `sourcing` |
| 8 | scorecards, QNs | quality lever | `scorecards`, `quality_notifications` |
| 9 | forecasts, PO prices, rival quotes | volume, price history, rival arguments | `forecast_lines`, `po_lines`, `quotes` |

The Sunday release (`data/release-sunday/`) and the case's own `facts` are read at runtime.

## Supplier estimate

`arena_kit.cost.supplier_value` prices a deal for the supplier from `standard`, `interest_rate`,
`ppm` and `extra`; `relationship_cost` needs `full_cost` and is 0 without it. So we estimate:

- **Full cost**: cost-breakdown XLSX, else `should_cost` moved by its drivers' index change, else
  quote minus an assumed margin. A relationship charge in a practice result reveals the true margin.
- **Cost of money**: cash discounts, cash-need notes, credit index, equity ratio. Seen rates: 0 to
  17 %/yr (`learnings.md`).
- **Extra**: overtime for speed (negative) or idle capacity filled by volume (positive), only from
  evidence. Volume, contract length and index clauses are not cash in `supplier_value`.

C_best estimate: the cheapest allowed sheet whose supplier value stays above its floor, or C_alt.

## Policy

A stance per supplier (opening gap, capture, margin, justified share, steps) proposed by the model
at case open, clamped by code to a range per tier and goal, logged with a reason. Fallback
constants when the stance call times out:

| Constant | Values |
|---|---|
| capture (share of possible saving before accepting) | leverage 0.75, quality_first 0.65, stabilise 0.6, secure_supply 0.55, routine 0.5 |
| opening gap below the quote (never below the floor) | strategic 5 %, important 8 %, standard 12 % |
| margin above full cost for the floor | case's `sustainable_margin_pct` in `stabilise` / `secure_supply`, else strategic 4 %, important 2 %, standard 0 % |
| justified share offered in round 1 of a price increase | strategic 0.5, important 0.25, standard 0 |
| concession steps, only after the supplier moved | 35, 25, 15, 10 % of the remaining gap |

Live signals adjust within bounds: approval needed shrinks steps (x0.7), high walk risk stops
price pushes. At the target, hold one more round while the supplier still moves.

## Build order

1. Accept and walk-away guard with `total_cost` and `must_haves_ok`.
2. Term search: every combination of allowed options, scored with standard terms for unstated
   fields. Fixes coverage and index-clause losses.
3. Supplier estimate: full cost and cost of money, giving target and walk-away.
4. Claim bank from `facts.json` and the index tables.
5. Persona reading and pacing.
6. Tune on practice traces, one change per batch.

## Generalise

- Branch on features (goal, must-haves, credit, cash signals, owner type, quote content), never on
  case or supplier IDs. No constants copied from one case.
- Hold out two or three practice cases for checking only.
- Test failure paths: late model call, malformed reply, a supplier that refuses everything,
  missing quote fields, a quote PDF without a standard-terms section.
- Change the agent only for a lesson seen in two cases or clearly general. Freeze early.

## Tactics

Use: data-backed anchors, requests framed as trades, two or three packages to watch the choice,
shrinking concessions with an ask in return, real rival offers cited by ID, a recap of every field
before closing.

Avoid: invented figures or rival offers (`contradicted`), bluffed urgency or walk-aways (no
effect, `learnings.md`), squeezing a weak supplier in `stabilise` / `secure_supply`, leaking
urgency, budget, target or a missing alternative. Prompt injection of supplier bots counts as an
attack on the arena: never.
