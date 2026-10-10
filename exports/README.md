# Exports: the Saturday probe sessions as tables

Every session we played on Saturday 10 October: 15 practice sessions (all 10 hosted cases) and 17
sandbox sessions, joined with the case files and the data package. What we learned from them is
in `docs/learnings.md`. Money is EUR over the case horizon; C is the arena's total cost
(`arena_kit.total_cost`), lower is better. This is a snapshot: the probe and the script that built
it (`buyer/autoprobe.py`, `analysis/export.py`) are in the closed PR #5, commit `03c51bc`.

| File | One row per | Use it for |
|---|---|---|
| `sessions.csv`, `.jsonl` | session | outcomes: score, C open/deal/alt/best, deal terms, cost breakdown |
| `threads.csv`, `.jsonl` | supplier in a session | supplier profile from the data next to what it did |
| `messages.jsonl` | e-mail, both directions | the full negotiation: terms with C, status, claims, reasons, back office |
| `claims.csv` | data argument we made | which arguments the arena verified, and for whom |

Join keys: `session_id` (+ `supplier_id`, + `round`). `set` is `practice` or `sandbox`.

## How we played

`method` in `sessions`:

- `autoprobe v1`: a fixed experiment per supplier thread, then the cheapest valid close. Its steps
  are `probe_step` in `messages` and `probe_steps` in `threads`:
  - `open`: questions and documents (cost breakdown, delivery schedule or 8D), our anchor price
  - `ours`: up to 3 sheets at the supplier's price, each with one lever moved our way
  - `theirs`: up to 3 sheets a step below, each with one lever moved its way
  - `claims`: up to 3 verified data arguments with a concession
  - `step`: concessions until `final_offer` or `agreed`; `push`: one ask after `agreed`
  - `keepalive`: a short question so a waiting RFQ thread does not time out
- `scripted probe (resumed by hand)`: an earlier version of the same steps (P01, first P10 run).
- `sandbox A/B: <variant>`: D01 with identical sheets, round 3 varied (`baseline`, `bluff`,
  `urgency`).
- `kit naive agent`: the kit's `NaiveAgent`.

## sessions

| Column | Meaning |
|---|---|
| `score` | `(c_open - c_deal) / (c_open - c_best)`, clipped 0..1; no deal scores the alternative |
| `c_open`, `c_deal`, `c_alt`, `c_best` | C of the best opening quote, our deal, our alternative, the best package any supplier would accept (hidden floor, revealed after the session) |
| `gap_to_best_eur` | `c_deal - c_best`: money left on the table |
| `implied_price_at_deal_terms` | the unit price at which our deal's other terms would cost exactly `c_best`; it keeps the deal's coverage, so for an under-covered deal (P08, P18) it mixes coverage and price |
| `deal_*` | the closed terms (unstated fields filled with the supplier's standard terms) |
| `cost_*` | `c_deal` by part: price, uncovered_need, fallback_risk, payment_terms, freight, late_delivery, quality, tooling, index_clause, index_risk, relationship |

## threads

| Column | Meaning |
|---|---|
| `country`, `owner_type`, `credit_index`, `scorecard_colour`, `data_signals` | from the data package (`analysis/explore.py`, `analysis/out/profiles.csv`); signals are persona traits found in notes, letters and news, e.g. `cash_need`, `price_frozen`, `capacity_full` |
| `should_cost` | the package's `should_cost` table, the supplier's own plant if modelled |
| `opening_price`, `final_price`, `price_move_pct` | its first and last unit price in the thread |
| `opening_vs_should_cost_pct` | how far its quote sits above (+) or below (-) the should-cost |
| `final_status`, `first_agreed_round` | `open`, `agreed`, `final_offer`, `walked_away`; the round it first said `agreed` |
| `documents`, `sent_cost_breakdown` | attachments it sent |
| `probe_steps` | our experiment sequence (see above) |
| `questions`, `backoffice_calls` | its recurring questions; its internal decisions ("My call: counter / hold / accept") |

## messages

Fields: `round`, `actor` (`buyer` / `supplier`), `probe_step` and `probe_note` (what our message
tested), `action` (`accept` / `walk_away`), `status`, `sheets` (`[{terms, c}]`: our term sheets, or
its standing sheet), `claims_made` (typed as the arena read them), `claim_results`, `missing_fields`,
`signals` (reply delay, validity), `reasons` (the supplier's reasons in words, hidden figures as `…`),
`backoffice` (its roles talking internally that round), `text` (the e-mail).

## claims

`type` (`index_change`, `quality_record`, `delivery_record`, `should_cost`, `volume_change`,
`notice`, ...), `refs` (data IDs), `asserted` (our figure as the arena parsed it), `result`
(`verified`, `contradicted`, `duplicate`, `irrelevant`).
