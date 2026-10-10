# Strategy notes: data, price estimate, architecture, tactics

Summary of the planning chat. Sources: `data/package/` (SQLite `world.sqlite` plus documents), `docs/api.md`, `docs/challenge.md`.

## 1. Data we have

| Group | Tables | What it holds |
|---|---|---|
| Supplier master | `suppliers`, `supplier_intel`, `scorecards`, `news`, `sourcing` | Terms, credit and financial health, quarterly delivery and quality scores, headlines, quota and tooling owner |
| Commercial history | `contracts`, `contract_clauses`, `negotiation_history`, `price_conditions`, `documents`, `rfqs`, `quotes` | Contracts and index clauses, past asks vs settlements, price history, letters, competing quotes |
| Transactions | `po_lines`, `goods_receipts`, `invoices`, `quality_notifications`, `spend_cube` | Orders, deliveries, payments, defects, spend |
| Parts and cost | `parts`, `should_cost`, `forecasts`, `forecast_lines`, `cost_drivers`, `index_series`, `index_values` | Part master, material/conversion/overhead split, demand forecast, market indices |

Market data (`index_series`, 33 series, Jan 2021 to Aug/Sep 2026): Eurostat producer prices (DE) and labour cost index, World Bank metals and EU gas, ECB FX (USD, PLN, CZK, HUF, TRY, CNY, CHF), SMARD day-ahead power, and derived copper and alloy surcharge series. `cost_drivers` weights them per part; `contract_clauses` holds index clauses.

Not in the data: insurance, and the seller persona (the persona is inferred from letters, call notes, past negotiation notes and live replies). Sunday 08:00 adds `data/release-sunday/`.

## 2. Price estimate inputs

| Input | What it is | Where we get it |
|---|---|---|
| Company scoring | Credit index and trend, equity ratio, size, ownership, audit grade, scorecard class, news. Risk and margin need. | `supplier_intel`, `scorecards`, `news` |
| Product quality | PPM, complaints, supplier-caused share, 8D speed, chargebacks. A direct cost term in C. | `quality_notifications`, `scorecards` (`ppm`, `qn_count`, `open_8d_overdue`) |
| Insurance | Not in data. Proxy: credit trend. Contract text may add clauses (unread). | Proxy: `supplier_intel.credit_index` vs `credit_index_12m_ago`; text: `contracts/*.md` |
| Demand forecast | Expected monthly need per part, and what the supplier has already seen. | `forecasts`, `forecast_lines` (`shared_with_suppliers`); the case file's `need_per_year` is binding |
| Relationship | Spend share, payment behaviour, past settlements, quota, tooling owner, contract. | `spend_cube`, `po_lines`, `invoices`, `negotiation_history`, `sourcing`, `contracts` |
| EU market data | Input-cost indices weighted per part, plus index clauses. | `index_series`, `index_values`, `cost_drivers`, `contract_clauses` |
| Time of delivery | Quoted vs real lead time and lateness. Late days cost money. | `parts`, `suppliers`, `quotes` (lead times); `po_lines` vs `goods_receipts` (actual) |
| Seller persona | Hidden bot character, inferred from correspondence and live replies. | `correspondence/`, `negotiation_history.note`, `supplier_intel.owner_type`, live thread, `buyer pull` traces |
| Should-cost | Material, conversion, overhead with a confidence level. Anchor and margin floor. | `should_cost` |
| Competing quotes | Other suppliers' offers, ceiling for price. Blank fields priced at standard terms. | `quotes`, `rfqs`, quote PDFs (`docs.standard_terms`) |
| Price history and baseline | What we paid before and the standard price. | `price_conditions`, `parts.standard_price` |
| Payment terms and skonto | Days to pay and the early-payment discount. A cheap lever. | `suppliers`, `contracts`, `quotes` |
| Freight and incoterm | Who carries transport and risk. A direct cost term in C. | `suppliers`, `contracts`, `quotes` (incoterm); freight rates in the case file |
| FX | Supplier billing currency and how the rate moved. | `suppliers.currency`, `ECB-*` in `index_values` |
| Tooling | Up-front tool cost and who owns it. | `quotes.tooling_eur`, `sourcing.tooling_owner` |
| Supplier margin floor | Lowest margin a healthy supplier can accept. Charged on strategic cases. | Derived from `should_cost`; `sustainable_margin_pct` in the case file |
| Our alternative | Caps what we should ever accept. | Case file `buyer` block (`alternative`, `fallback_unit_price`) |

Proposed estimate: should-cost plus index drift gives target and floor, adjusted for supplier risk and relationship, with competing quotes as ceiling. Always scored with `arena_kit.total_cost`.

## 3. Demand and volume

- Need is given per case: `need_per_year`, `horizon_years` (at most 3), `fallback_unit_price`, `fallback_risk_pct`.
- `covered = min(V, N) * years`. Uncovered need costs `fallback_unit_price * (1 + risk%)`.
- Do not assume more or less is better. When the exact need cannot be hit, compute it per case: build candidate volumes and lengths and pick the one with the lowest `total_cost`. Underbuy costs the fallback price plus risk per unit; overbuy costs price, freight, payment interest and PPM per unit with no coverage.
- Commitment beyond the horizon neither costs nor earns, so match contract length to the horizon.
- In the brief's example, a 12-month deal at the same price for a 24-month need costs more than the opening quote and scores 0. It depends on the fallback price, so check with `total_cost`.
- Break-even per unit, as a sanity check only: overbuy beats underbuy when `P + freight_per_unit < fallback_unit_price * (1 + fallback_risk_pct/100)`. The decision still comes from `total_cost`, because the supplier's price may change with volume.
- Surplus units beyond `N` add no coverage but still cost price, freight, payment interest and the PPM term (`committed` drives all of them).
- Volume vs length: coverage is `min(V, N) * years`. A short contract at full annual volume covers less than a long one, so match length to the horizon first, then volume.
- Volume as a lever (checked in `arena_kit/cost.py`, `supplier_value`): volume is not a direct term in the supplier's value. It enters only through `supplier["extra"]` (EUR per unit, "idle capacity a larger volume fills", default 0), which is our own estimate, and through tooling spread over `sold = V * years` (more volume lowers tooling per unit). Contract length and index clauses count as security, not cash.
- So a larger volume only helps the supplier-margin estimate if we set `extra` from evidence (idle capacity in its news, letters or scorecards). Do not assume it. The hidden C_best uses the supplier's real economics, which may value volume more than our estimate.
- `relationship_cost` is 0 without a supplier estimate (`full_cost`, `interest_rate`, `standard`). To price the margin charge on `stabilise` and `secure_supply` cases, `prepare` must build that estimate from `should_cost` and the supplier's quote.
- Never state the need or the fallback price in an e-mail.

## 4. Proposed architecture

Code owns numbers, the model owns words. Per move, inside `decide`:

```
supplier reply
  -> READ    (LLM, short timeout)  quote, intent, objections, tone
  -> STATE   (code)  known terms, unstated fields at standard terms, supplier cost floor
  -> PLAN    (code)  candidate term sheets scored with total_cost, filtered by must_haves_ok
  -> DECIDE  (code)  accept / counter / walk away vs alternative, move size
  -> WRITE   (LLM, short timeout)  e-mail from template, figures and IDs injected by code
  -> GUARD   (code)  claim checks, all fields present, no leaks
  -> send    (deterministic fallback if any model step times out)
```

Modules: `prepare` (supplier profile before the session), price estimate, offer generator, policy, language, guard.

Build order:
1. Accept / walk-away guard with `total_cost` and `must_haves_ok`.
2. Code-computed offer generator.
3. Supplier profile and price estimate.
4. Persona reading and lever choice.
5. Tune on practice logs (`buyer pull`).

Suggested split: A pipeline and guard, B data and estimate, C offers and policy, D prompts and log analysis.

## 5. Strategies to maximise score

1. Protect the floor: never break a must-have, never accept a deal costing more than the alternative, cover the full need, fill every field, always have a fallback move within 60 s, walk away when no deal is better.
2. Optimise total cost, not price. Trade cheap levers (payment days, length, volume up to need, dates) for expensive ones.
3. Read the supplier. Confirmed by `api.md`: a cash-short supplier trades a lower price for faster payment. Hypotheses to test in practice: a near-monopolist barely moves on price (use volume and length), a supplier that needs boss approval prefers complete packages.
4. Argue with evidence: index series, should-cost, real competing quotes. Max 3 claim checks per message, ID and figure in the same sentence.
5. Move with discipline: credible ambitious opening, shrinking concessions with a request in return, up to 3 term sheets per message, keep message reserve (limit 10).
6. Case types: push hard on `leverage` and `routine`; do not squeeze the supplier below a sustainable margin on `stabilise` and `secure_supply`; on `quality_first` the PPM commitment and chargebacks are cost terms in C, so price them with `total_cost` (how suppliers react is untested).
7. Do not leak urgency, budget, target price or a missing alternative.
8. Process: test on simulator and sandbox first, spend the 200 practice sessions on changes we expect to help, generalise (no logic keyed on IDs), freeze a working version early.

## 6. Human-style tactics

- Rapport: specific true opener, mirror their register, acknowledge their constraint before asking.
- Framing: shared problem, requests as trades, anchors with a reason.
- Pacing: do not concede on the first push, shrinking steps, one firm point, only true deadlines.
- Information: open questions, 2 to 3 packages and watch the choice, never give urgency or budget.
- Pushback: ask what would make it a yes, make approval easy, step back when defensive.
- Closing: recap every field, confirm, then close.

## 7. Pressure tactics: what to use and avoid

Use: data-backed anchoring, reciprocity, small commitments first, real competing quotes cited by ID, package pressure.

Avoid: fake figures or fake competing offers (claim check marks them `contradicted`), fake urgency or bluffed walk-aways, squeezing a weak supplier on strategic cases (margin charge), emotional pressure (the bots have hidden economics and hard limits, so we expect it to fail; untested).

Out of bounds (AGENTS.md hard rules, can disqualify): calling the forbidden endpoints (`/v1/events`, `/screen`, `/leaderboard`, `/results`), attacks on the arena or other teams. We treat prompt-injecting or jailbreaking the supplier bots as an attack and do not do it. Leaking our own urgency, budget, target price or lack of alternative is not a disqualification but weakens our position.

## 8. Preventing overfitting

The final uses new suppliers, and up to a third of its cases combine supplier and case types that practice never shows.

- No logic keyed on practice case IDs or supplier IDs. Runtime knowledge from the data package is fine if it works for unseen suppliers.
- Branch on features (goal type, must-haves, credit trend, cash position, owner type, scorecard, quote content), not names.
- No hard-coded numbers from one case. Express them as rules computed from the supplier's own data (should-cost, margin gap, index move).
- Prefer a few principled rules over many special cases.
- Hold out 2 or 3 practice cases for checking only, never for design.
- Add mixed-type simulator cases (for example cash-short supplier in `secure_supply`, near-monopolist in `leverage`) using the format in `arena_kit/sim_cases`.
- Test failure paths: late model call, malformed reply, supplier that refuses everything, missing quote fields.
- Change the agent only for lessons seen in at least two cases or clearly general. Do not tune prompts to the exact wording one bot used.
- A single practice run is noisy. Compare averages over several cases and use the baseline on the same cases.
- Keep the code-side guard (must-haves, alternative, completeness) and the deterministic fallback independent of strategy.
- Read Sunday release data from `data/release-sunday/` at runtime. Verify in the 09:00 pre-flight.
- Freeze early. A simple agent that generalises beats a tuned one that breaks on new types.

## 9. Open items

- Read `contracts/*.md` for insurance or liability clauses.
- Add mixed-type simulator cases to catch overfitting early.
- Implement step 1 of the build order and agree the module interfaces.
- Write the tactics section of the writer prompt, with the guard rules.
