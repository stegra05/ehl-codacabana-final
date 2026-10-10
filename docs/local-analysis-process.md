# Local company analysis and strategy experiments

This note describes the work completed locally on 10 October 2026. The company
snapshot is dated 30 September 2026. The analysis scripts and generated dashboard
are still in the local research workspace; this documentation PR does not publish
those artifacts or integrate them into the production buyer.

## 1. Read the official company evidence

The analysis opens the official `world.sqlite` database in read-only mode and
reads `company.md`. It aggregates annual and category spending and the latest
quarterly scorecards. FY2026 spending totals EUR 34,901,159.85 across 447 supplier
records. The package contains 46 detailed supplier profiles and 60 parts.

For each detailed supplier, it joins the supplier profile, financial intelligence,
spending and scorecard by supplier ID. It also reads the corresponding contracts
and source documents, using a 30 September cutoff for correspondence. SQL queries,
parameters and returned rows are retained with the output for traceability.

## 2. Calculate evidence, keeping estimates explicit

- **Payment behavior:** invoices without cash discounts paid from 1 October 2025
  through 30 September 2026. Compute signed days between payment and due date,
  their unweighted mean, and the share paid after the due date. This describes
  Hollerau's behavior as a buyer, not supplier delivery performance.
- **Price increases:** for documents with a recorded increase request, find the
  applicable supplier/part price and the latest available should-cost estimate.
  Normalize price and estimated cost to the same unit.
- **Estimated price-only margin:** `(unit price - estimated unit cost) / unit price`.
  This is not the supplier's actual margin or its hidden arena economics.
- **Weighted index proxy:** for each part's cost drivers, compare the index in the
  month before the current price became effective with the latest index available
  by September 2026. Sum each percentage change times its driver weight. Missing
  endpoints leave the proxy unavailable. Other cost components are held unchanged.
  Historical windows still need checking against the arena's claim rules.

For example, Brandlhuber's 9.5% request compares with an approximately 2.3% index
proxy, while Nordmark's 6.5% request compares with approximately 6.6%. These are
different starting points for research, not automatic acceptable price limits.

## 3. Cross-check the supplied profiles

The original `profiles.numbers` workbook was read without changing it. All 46
supplier IDs, FY2026 spending figures and latest OTD, PPM, score and color fields
matched the official detailed supplier records. Spending was also reconciled
against CSV totals, and index endpoints against `facts.json`.

Payment definitions remain unresolved: three date-window fields and four lateness
thresholds did not reproduce every supplied late-share value. The dashboard
therefore keeps the supplied metric and our calculated metric distinct.

## 4. Prepare three research inputs per supplier

| Packet | Contents |
|---|---|
| A | Structured supplier profile, financials, scorecard and spending |
| B | A plus company context, contracts and correspondence |
| C | B plus calculated metrics and their source references |

There are 138 packets for 46 suppliers. Their instructions ask an eventual model
to separate facts, calculations, hypotheses and unknowns, cite evidence, and
avoid inventing case requirements. No A/B/C model comparison has been run yet.

## 5. Test decision rules separately

The official scripted simulator was used without changing its supplier logic.
The initial naive baseline ran over local HTTP. An in-process adapter reproduced
its complete result objects, then exercised 13 policies across three cases and
six scenarios: 234 distinct runs. Six additional repeat controls matched.

The policies are nine [anchor/gap combinations](anchor-gap.md), accept opening,
walk away, guarded naive and guarded package-cost negotiation. Scenarios use the
original cases or change buyer inputs: 20% financing interest, a longer demand
horizon, triple freight rates, a mandatory payment term of at least 60 days, or
a synthetic alternative at 85% of the current unit price with full coverage.

Every run records case inputs, buyer actions, supplier trace, final terms, total
cost, score, rounds and diagnostic flags. Across the matrix there were zero
execution errors, 13 agreements violating mandatory conditions and 50 agreements
costing more than the available alternative. The guarded policies recorded zero
of either failure. These two failure counts need not represent disjoint runs.

The company dossiers were not inputs to these policies. No language model or
hosted supplier was called in this batch, and no practice quota was consumed.
Synthetic scenario scores are diagnostics, not official arena benchmarks.

## 6. Present the evidence in the dashboard

The local dashboard embeds the recorded JSON in a self-contained HTML file:

- **Overview:** company spending, concentration and risk signals.
- **Supplier dossiers:** profiles, computed metrics and original evidence.
- **Experiments:** policy comparisons, case/scenario filters and recorded moves.
- **Method & limits:** completed checks and unresolved research questions.

The local pipeline consists of `scripts/analyze_company.py`,
`scripts/review_profiles.py`, `scripts/run_local_baseline.py`,
`scripts/experiment_local.py` and `scripts/build_local_dashboard.py`. Generated
outputs live under `out/company-analysis/` in the research workspace.

## What remains

Connect supplier evidence to model-backed analysis and negotiation, measure the
benefit and latency of A/B/C inputs, validate on the free D01/D02 sandbox, and
retain code checks for mandatory conditions and total cost before acceptance.
The local results do not establish persuasion quality or hosted performance.
