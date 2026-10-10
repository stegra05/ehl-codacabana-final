# Agent design

The target architecture of our buyer, merged from the team's planning notes (PRs #7 to #10,
10 Oct). What we learned in play is in `learnings.md`; this file says what we build.

**Status.** The branch `steffen/price-engine` plays a code-only policy with a model-written
paragraph (`buyer/policy.py`, run by `buyer/runner.py`): practice mean of best scores 0.73 (from
0.32), sandbox D01 0.99, D02 0.73. What it does is under "Implemented" below; the rest of this file
is the target design. Julian's draft two (`origin/julian/draft-two`) holds a richer stance and
reader design that is not merged. The architecture diagram is on page 1 of
[how-it-works.pdf](how-it-works.pdf).

## Implemented (price engine)

| Module | Job |
|---|---|
| `buyer/economics.py` | C of a sheet; the accept gate (`deal_cost`); what a sheet is worth to the supplier (`supplier_value` plus overtime for a faster delivery than it quoted); term planning: every allowed combination priced at the supplier's own valuation, lowest C, ties to the supplier's side; the relationship-optimal price |
| `buyer/claims.py` | claim bank: should-cost below its price, our order prices, each cost driver's largest fall over any window up to 12 months, notice period, forecast, scorecard, case rival quotes, hedge and open-book notes; rival offers in an RFQ |
| `buyer/personas.py` | owner type, persona signals from notes, letters, quote remarks and news, cost of money |
| `buyer/policy.py` | per thread: anchor by goal and persona, 30 % of the gap per round, held low after a deep first concession, patience budget for near-cost, fully booked and relationship-goal suppliers; adopts its counter terms when they cost us less, mirrors a better alternative, takes a required index clause; claims 3 in round 1, then 1 per round; close on final offer, agreement or round limit |
| `buyer/reader.py` | the supplier's asks from its fixed sentences (volume, proof, faster payment, our target); no model |
| `buyer/writer.py`, `buyer/llm.py` | the e-mail: a model paragraph that answers the supplier's last e-mail and its asks (no digits, IDs or leaks, else the template), then code sentences with figures (the binding volume), claims and the proposal from code; the forecast rows as a CSV when proof is asked |
| `buyer/runner.py` | one message at a time per session, to the thread whose 60 s clock has run longest; keepalive questions for finished bidders; rollback when a send times out; a guarded move resends our last sheet; the model's time budgeted so every live clock still gets a message; a terminal reply ends the case; accept the cheapest standing sheet that keeps the must-haves and beats the alternative (relationship charge included), after a refused close decide again on what stands; Live Final waves that never raise and resume a crashed case |

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
