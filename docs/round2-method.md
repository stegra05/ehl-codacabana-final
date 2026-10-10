# Round 2: evidence, calibration and robustness

This is a local research experiment, not the production buyer. It calibrates
deterministic policy parameters; it does not train or fine-tune a language model.

## Protocol

1. Load the 46 official detailed supplier dossiers and each supplier's first
   current part price in sorted part order. These identify and scale synthetic
   cases; they do not determine case demand or hidden supplier economics.
2. Split suppliers by a fixed SHA-256 ordering: 27 calibration, 19 evaluation.
   All cases from a supplier remain in the same split.
3. Calibrate four policy families on three synthetic supplier behaviors and
   one seed. Try anchors 8%/20% and gaps 0.5%/2%: 1,296 runs in total.
4. Freeze the selected parameters before evaluation. Evaluate eight approaches
   on two new seeds and four supplier behaviors, including early final offers
   absent from calibration: 1,216 runs.
5. At the user's request, add fixed Anchor 30% cost/menu variants: 304 further
   runs on the same evaluation cases. This is exploratory reuse of evaluation
   data, not a fresh holdout or a new parameter-selection round.
6. Separately stress aggressive openings with a synthetic supplier that exits
   if its first offered package is worth less than 78% of its opening: 152 runs.
   That threshold is an invented stress assumption, not a fitted supplier fact.
7. Run 30 controls on the unchanged official simulator and six exact repeats.

## Approaches

- **Naive:** official default baseline, with no acceptance checks of its own.
- **Previous guarded:** previous naive policy plus the kit's closing checks.
- **Cost:** rank allowed non-price combinations by buyer cost.
- **Evidence:** use a financing-rate hypothesis to price packages with the same
  estimated supplier value, then choose the cheapest for the buyer.
- **Menu:** add up to two distinct payment packages within 2% of the cheapest
  proposed buyer cost, so the supplier can choose among up to three packages.
- **Robust:** meet the target supplier value across financing assumptions from
  4% to 30%, then offer a menu. This is deliberately more conservative.
- **Ablations:** the same calibrated menu parameters without documents, then
  without dossiers, to isolate the incremental effect of evidence inputs.

The evidence rule assumes 8% financing generically, 18% when the structured
credit index is at least 300, and 25% when matching dated documents mention cash
discounts or cash and bank pressure. These numbers and thresholds are experimental
heuristics, not measured rates. No supplier IDs have special policy logic.

Documents are data, not executable instructions. Future-dated or mismatched
supplier evidence is ignored. No estimated monetary claims, internal target or
reservation value is included in the supplier message. Evidence currently affects
package construction, not persuasive language. The full A/B/C model comparison,
cost-index argumentation and margin uncertainty remain untested.

For evidence policies, the anchor discounts reference supplier value. The unit
price can change with payment and freight so a menu's price discount is not always
equal to its anchor. The official `supplier_value` function does not assign cash
value to contract security. All acceptance uses mandatory-condition and available
alternative checks. Explicit terms in an opening quote remain a documented value
reference even if the PDF's standard-terms section is empty.

## Evaluation metric

`saving = (no_deal_cost - outcome_cost) / no_deal_cost`, averaged equally across
cases. If an alternative quote is supplied, its total cost defines no-deal cost.
Otherwise an explicitly synthetic full-horizon replacement at the fallback price,
DAP and 60-day payment defines it. No agreement counts as zero saving. An invalid
agreement also receives no-deal cost in this diagnostic, and a separate violation
flag. This is not the arena's score, C_best, or a monetary saving forecast.

The synthetic buyer varies demand, horizon, financing, freight, alternatives,
mandatory payment and impossible requirements. Hidden supplier financing, floor
and concession speed vary independently of the evidence heuristic. The simulator
does not reward cited text. Strategic relationship penalties, quality disputes,
real supplier reasoning and transport failures are outside this local matrix.

## Recorded findings

Across 152 evaluation cases per approach:

| Approach | Mean synthetic saving | Agreements | Mandatory failures | Worse than alternative |
|---|---:|---:|---:|---:|
| Naive | 4.03% | 152 | 32 | 28 |
| Previous guarded | 7.66% | 92 | 0 | 0 |
| Cost, calibrated | 7.73% | 92 | 0 | 0 |
| Evidence, one package | 7.61% | 93 | 0 | 0 |
| Evidence menu | 7.75% | 93 | 0 | 0 |
| Robust menu | 7.33% | 92 | 0 | 0 |
| Menu, Anchor 30% (exploratory) | 7.88% | 93 | 0 | 0 |

Evidence is not a universal improvement: the menu wins 16 paired comparisons,
loses 24 and ties 112 against the same menu without dossiers. Mean difference is
only +0.063 percentage points. It helps more against the synthetic cash-sensitive
supplier and hurts against price-only behavior. Do not interpret this as validated
supplier prediction or persuasion.

In the separate lowball-exit stress, the 20% menu closes 23/38 deals and the 30%
menu closes 0/38. The assumption is intentionally adverse to aggressive openings.
It demonstrates why zero acceptance violations does not imply zero commercial
risk. The ordinary matrix's modest 30% improvement does not establish an optimum.

## Reproduce and inspect

From the local research checkout:

```sh
vendor/tacto/starter-kit/.venv/bin/python -m unittest discover -s tests
vendor/tacto/starter-kit/.venv/bin/python -m scripts.robustness_lab
python3 scripts/build_round2_dashboard.py
```

Open `out/company-analysis/round2/dashboard.html`. The directory also contains
the split manifest, frozen parameters, calibration/evaluation JSONL, lowball stress
records, report, input/source hashes and official controls. Generated files remain
gitignored. The original round-1 dashboard links to round 2.

The separate `scripts/test_sandbox_round2.py` runner only allows D01/D02, records
every move, closes its own session after an exception, and uses a bounded session
deadline. `--run` compares 20% and 30% menus on both free hosted demo cases. It uses
generic supplier assumptions because demo suppliers have no matching company
dossiers. Hosted outcomes must be reported separately from the local matrix.

The first online integration attempt uncovered a missing reference payment term
when all terms were stated explicitly and the quote PDF had no separate standard
section. The runner closed that session without a deal. A regression test now
covers this shape, and the restarted comparison preserves the earlier failure log.

Online D01 results: Anchor 20% scored 0.926642 (EUR 411,572 total cost);
Anchor 30% scored 0.859833 (EUR 414,256.83). D02 Anchor 20% scored 0.383288,
and Anchor 30% scored 0.303253. Two-demo means are 0.654965 and 0.581543.
All four agreements passed the arena's mandatory-condition check. Practice quota
remained at 15 used and 185 remaining. These four completed comparisons plus the
earlier failed integration attempt were free sandbox sessions.
The D01 direction is opposite to the small average gain for 30% in the local
matrix. One run per setup against stochastic bots cannot establish causation.


## Adaptive extension and controlled ablation

We tested four policies on 190 identical cases each: the same 19 evaluation
suppliers, fresh seeds 401/503, and five behaviors including lowball exit. This
makes 760 evaluations plus 12 separate unchanged official simulator controls.
Supplier identities were reused, so this is exploratory, not a new holdout.

The dynamic policy chooses 30% only for leverage cases with a cheaper admissible
explicit alternative and no inferred cash pressure; otherwise it starts at 20%.
Concessions depend on supplier movement and remaining messages. An ablation keeps
these adaptive concessions but always opens at 20%.

| Policy | Mean synthetic saving | Deals / runs | Worst saving | S01-S03 mean score |
|---|---:|---:|---:|---:|
| Fixed menu 20% | 7.509% | 111 / 190 | -0.393% | 0.576418 |
| Fixed menu 30% | 5.921% | 89 / 190 | -0.393% | 0.672029 |
| Dynamic anchor and concessions | 7.840% | 115 / 190 | -0.393% | 0.712417 |
| Fixed 20%, adaptive concessions | 7.840% | 115 / 190 | -0.393% | 0.712417 |

All four had zero mandatory-condition or explicit-alternative violations. The two
adaptive policies produced identical per-case result objects. The dynamic policy
used 20% for 135 openings and 30% for 25; 30 cases ended before an opening offer.
The observed +0.330 percentage-point improvement over fixed menu 20% is supported
by adaptive concessions; switching anchors has no demonstrated incremental benefit.
This is not evidence that 20% is universally optimal. Neither adaptive policy has
been tested online, and no language model was trained.

The worst saving exposes another limitation: an acceptance check against an
explicit alternative does not guarantee improvement over a synthetic replacement
baseline when no such alternative is supplied. The diagnostic can be negative
without an acceptance-policy violation. These new averages include a fifth
supplier behavior and cannot be compared directly with the original round-2 mean.

Run `python -m scripts.test_adaptive_round2` with the kit environment, then
`python3 scripts/build_research_dashboard.py`. The self-contained English report
is `out/company-analysis/research-dashboard.html`; it embeds the company and both
earlier dashboards. Ten regression tests and Ruff passed. The summary and both
embedded reports were checked in Safari. The pre-adaptive policy source is retained
locally alongside round-2 outputs to preserve its recorded source hash.

## Main problems and their implications

1. **Unsafe baseline acceptance.** The naive policy closed invalid and dominated
   deals. Code must validate full terms, must-haves and total cost before acceptance.
2. **Simulation realism.** Scripted price behavior and invented financing rules
   cannot establish real supplier response or persuasion. High local scores are
   not estimates of the hosted practice leaderboard.
3. **Aggression is conditional.** 30% gained slightly in the original local matrix,
   failed the adverse lowball scenario and scored lower in both hosted demo runs.
4. **Incomplete supplier economics.** Document-derived financing rates and margin
   proxies are hypotheses. Evidence ablations showed small, mixed benefits.
5. **Integration assumptions.** A valid quote without a separate standard-terms
   section caused one failed D01 attempt. The explicit opening quote now supplies
   that reference, with a regression test.
6. **Commercial performance remains uneven.** D02 scored only 0.383 / 0.303;
   valid deals alone do not demonstrate good supplier selection or package value.
7. **Validation and readiness.** Only one online run per setup, reused suppliers
   in exploratory extensions, unresolved payment-metric definitions, no completed
   model-backed A/B/C comparison, and no production-scaffold integration yet.

D01 is a free hosted price-increase demo with one foundry supplier. D02 is a free
hosted RFQ demo with two competing suppliers. S01-S03 are local scripted cases;
practice cases are separate and consume the shared quota. No practice or final
session was opened by this research batch.


## Does supplier weakness predict gains from a 30% anchor?

The user hypothesis was that weaker firms accept more aggressive openings. We tested paired 30% minus 20% outcomes, separating financial indicators from operational scorecards. This analysis measures final agreement and synthetic saving, not direct first-offer acceptance or a supplier willingness parameter.

We reused 152 original paired cases and 190 fresh-seed paired cases. These are 342 pairs, or 684 recorded negotiations, on 19 suppliers, not 342 independent firms. A sensitivity slice removes the 38 invented lowball-exit cases from the fresh batch. No new online or practice sessions were opened.

| Group | Suppliers | Original effect, pp | Fresh seeds, same behaviors, pp | Fresh seeds including exit stress, pp |
|---|---:|---:|---:|---:|
| Credit index >=300 (existing risk heuristic) | 2 | +0.045 | +0.000 | -0.330 |
| Credit index <300 | 17 | +0.144 | -0.045 | -1.736 |
| Equity ratio <33.95% | 13 | +0.133 | +0.006 | -1.206 |
| Equity ratio >=33.95% | 6 | +0.135 | -0.140 | -2.418 |
| Red scorecard | 5 | +0.202 | +0.150 | -1.727 |
| Amber scorecard | 4 | +0.590 | +0.096 | -0.907 |
| Green scorecard | 10 | -0.084 | -0.190 | -1.791 |

Positive effects mean higher mean synthetic saving with 30%. Red scorecards show a small positive association in both four-behavior batches. This does not establish willingness to concede: the supplier simulation does not read scorecard quality or financial fragility when generating reservation prices and financing. Profile information changes some buyer assumptions and starting terms; synthetic shocks and latent economics can confound these group patterns. All five red suppliers landed in the 19-supplier evaluation split, another coverage limitation.

The original overall effect was +0.133 pp, with a supplier-bootstrap 95% interval of [-0.168, +0.436]. On fresh seeds with the same four behaviors it was -0.040 pp [-0.297, +0.158]. The bootstrap uses 4,000 supplier-level resamples, seed 601. It describes this synthetic sample and does not supply real-world generalization guarantees, especially for groups of two suppliers.

Spearman correlations were computed on supplier mean paired effects, for credit index, equity ratio, credit deterioration, on-time delivery, defect PPM and scorecard score. Two-sided permutation p-values use 1,999 permutations. No correlation survives Benjamini-Hochberg correction across the 18 exploratory comparisons (smallest adjusted q = 0.270). The fresh-seed equity association appears when exit stress is included and disappears when it is removed. A significant raw p-value here would not establish causality.

All 22 agreements lost by 30% relative to 20% in the fresh-seed batch came from the deliberately imposed lowball-exit behavior. Excluding it, both anchors close 89/152 cases. This measures sensitivity to an assumed reaction, not the real probability that a financially weak supplier exits.

### Stronger document evidence: cash preference and margin resistance

Across all 46 dossiers, dated through 30 September 2026, exact phrase extraction finds 16 suppliers offering a cash discount for earlier payment, two with explicit cash-and-bank pressure visit notes, and five explicitly resisting a reduction in margin despite asking for earlier payment. The groups overlap. These are fictional challenge documents, not independent market observations.

- Wimbacher: green scorecard, credit index 231, equity ratio 39.9%; liquidity note `doc:20260802-70130-M1` asks for earlier payment and rejects lower margin.
- Kalwisz: red scorecard, credit index 225, equity ratio 39.1%; `doc:20260715-70140-M1` expresses the same condition.
- Weißacher: red scorecard, credit index 343, equity ratio 24.9%; `doc:20260912-70350-M1` also resists margin reduction.

These counterexamples show why operational quality, cash pressure and negotiating flexibility cannot be treated as one good/bad rating. Early payment can create value for a cash-constrained supplier while a pure price cut destroys margin. A blanket weak-firm -> 30% rule is unsupported.

### What to test next

Keep anchor selection separate from package value and acceptance checks. Test a 2x2 comparison of 20%/30% openings and standard/earlier-payment packages, holding the rest of the policy fixed and using several runs per financial-risk stratum. Record total cost, final agreement, supplier exit, quality and delivery obligations, and sustainable-margin effects. Add genuinely new suppliers before selecting a rule. Hosted D01/D02 can validate mechanics but lack matched company dossiers; this batch cannot validate that financial-risk interaction online.

Reproduce with `python3 scripts/analyze_anchor_relationship.py`. Full paired rows, profile indicators, source document IDs, correlation tests and input hashes are in `out/company-analysis/round2/anchor-risk-analysis.json`. The consolidated English dashboard includes the group comparison. Research code remains local; published findings are separate from production integration.
