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
| `buyer/claims.py` | claim bank: should-cost below its price, our order prices, falling cost-driver indices, notice period, forecast, scorecard, case rival quotes, hedge and open-book notes; rival offers in an RFQ |
| `buyer/personas.py` | owner type, persona signals from notes, letters, quote remarks and news, cost of money |
| `buyer/briefing.py` | the preparation agent's briefing, code only, recomputed every run: constraints, economics, market (other quotes and prices for the part, cost drivers with their index path, should-cost rows), supplier importance (sole source, tooling, class, spend, no fallback: strategic / important / standard), and the plan variables the fallback constants stood for: a full cost with its confidence, the floor price at the tier's or the case's margin, the C floor (cheapest allowed terms at the floor, the reference for the run), capture by goal and record, the opening bounds (tier gap, never below a binding floor; a price increase at most today's price plus the tier's share of the index-justified increase), the capture target price; after the run `assess` logs the C floor against the revealed C_best |
| `buyer/prep.py` | the preparation agent's model loop, before the session opens (no clock running): the briefing and the package's tables, then up to six lookups (SQL, ID, document) and a stance per supplier (assessment in words, what it values, arguments to lead with, capture and opening deltas, patience, tone, risks); code clamps every figure to its band and goes on without it when the model is late or silent |
| `buyer/policy.py` | per thread: anchor by goal, persona and the plan's bounds, a share of the gap per round paced by the rounds the clock and the round limit leave (30 % with rounds to spare, up to 50 % when the wave's clock leaves fewer), held low after a deep first concession, never below a binding floor, patience budget by importance, near-cost, fully booked and relationship-goal suppliers; closes at the capture target or the relationship optimum; adopts its counter terms when they cost us less, mirrors a better alternative, takes a required index clause; claims 3 in round 1, then 1 per round, the prep agent's kinds first; close on final offer, agreement or round limit |
| `buyer/reader.py` | the supplier's asks from its fixed sentences (volume, proof, faster payment, our target); no model |
| `buyer/writer.py`, `buyer/llm.py` | the e-mail: a model paragraph that answers the supplier's last e-mail and its asks (no digits, IDs or leaks, else the template), then code sentences with figures (the binding volume), claims and the proposal from code; the forecast rows as a CSV when proof is asked |
| `buyer/runner.py` | the preparation agent before the session opens; one message at a time per session, to the thread whose 60 s clock has run longest; the rounds each open thread may still play from the wave's cap, the measured round time and the open threads, passed to the policy; keepalive questions for finished bidders; rollback when a send times out; a guarded move resends our last sheet; the model's time budgeted so every live clock still gets a message; a terminal reply ends the case; accept the cheapest standing sheet that keeps the must-haves and beats the alternative (relationship charge included), after a refused close decide again on what stands; Live Final waves that never raise and resume a crashed case; `--cap` plays practice and sandbox like a wave |

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

Implemented in `buyer/briefing.py` (the variables) and `buyer/prep.py` (the model's stance): the
plan variables below are calculated per case and supplier from the data on every run, the model
proposes deltas within bands, and the run log assesses the C floor against the revealed C_best.

| Variable | Calculated from |
|---|---|
| full cost, confidence | own-plant should-cost (high), generic estimate scaled to the country (medium), else 80 % of the quote (low); a figure outside 0.3 to 1.3 of the quote is read per piece or dropped |
| floor price | full cost plus the case's sustainable margin (`stabilise`, `secure_supply`) or the tier margin (strategic 4 %, important 2 %, standard 0 %), as a price at our terms; binding only with a cost estimate and at most 95 % of the quote (P01, P02, P17 quote below our should-cost) |
| C floor | C of the cheapest allowed terms at the floor price: the reference for the run |
| capture | by goal (leverage 0.75, quality_first 0.65, stabilise 0.6, secure_supply 0.55, routine 0.5), +0.1 when its record shows it moves, -0.1 when frozen, booked or on an approval ladder, -0.15 near cost; the model's delta within ±0.15 |
| capture target | the price at our terms where C has captured that share of the room from its quote to the C floor; closes the thread when its counter reaches it (binding floors only, never within 2 % of its quote) |
| opening | the goal anchor (`policy.ANCHOR`), at most 10 % below a strategic partner's quote, never below a binding floor; a price increase at most today's price plus the tier's share (0.5 / 0.25 / 0) of the index-justified increase; the model's delta within -0.05 to +0.08 |
| patience | the cumulative gap budget: strategic 0.4, important 0.7, standard 1.0, lower for relationship goals, near cost and full capacity; the model's value within 0.15 to 1.0 |
| step | `policy.pace`: 30 % of the gap with rounds to spare, up to 50 % when the wave's clock leaves fewer rounds than the round limit |

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
