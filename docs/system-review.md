# System review

Reviewed against `main` at `185ad65`, 10 October 2026. This is an assessment of the running buyer. Risks are code paths to inspect, not rules. The [architecture review](architecture.md) maps the live path and every module. [Design](design.md) describes additional planned components; [learnings](learnings.md) holds practice evidence.

## What works now

| Property | Evidence | Why it matters |
|---|---|---|
| Numeric decisions stay in code | `buyer/economics.py`, `buyer/policy.py`; kit `total_cost` and `must_haves_ok` | The optional model cannot choose a price or accept a sheet. |
| A close uses the best acceptable standing sheet | `Negotiator.best_offer`, `deal_cost`; `tests/test_guards.py` | A broken must-have or a sheet above the alternative is rejected by the final decision gate. |
| A late or broken writer leaves a move | `llm.paragraph`, `writer.email`; model-timeout test | The policy can send a template when the model fails. |
| Cases and waves contain most errors | `runner.play_case`, `play_all`, `play_waves`; `tests/test_waves.py` | One supplier setup or case failure need not end other work. |
| Known case structures run through the simulator | `tests/test_cases.py` over the available `logs/cases/` files | This checks integration for bundles, RFQs and term options, though the supplier is scripted. |
| Practice gives measurable outcomes | `buyer pull`, `logs/sessions/`, `exports/`, `docs/learnings.md` | Team members can compare actual cost and score with the arena result. |

The latest ten-case hosted validation run averaged 0.727; the best score recorded for each hosted case averaged 0.776. Both are in-sample results in [learnings](learnings.md) and do not establish performance on Sunday's unseen cases. The architecture has no autonomous learning stage; a person reviews traces and changes code between runs.

## Review findings, in order

These are review targets, not implemented changes. A risk is marked **observed** when a cited trace or measurement supports it, and **code path** when the implementation makes it possible but live impact has not been measured.

| ID | Priority | Finding | Evidence | Next review step |
|---|---|---|---|---|
| R1 | P0 | The final gives a crashed case only two `play_case` attempts. If both fail, the future stores an exception and the wave loop never submits that case again, even if its cap remains open. | `runner.play_waves.one`; code path | Reproduce two transient failures in `tests/test_waves.py` and decide how many resumptions fit the remaining cap. |
| R2 | P0 | The writer budget subtracts one measured send from each other thread's clock, but messages are sent serially. The last of four bidders can wait through several sends. Saturday's measured reply times were 19 s median and 28 s p90. | `runner.writer_budget`, `play_case`; [practice timing](learnings.md#practical); observed timing, code path for four bidders | Simulate four slow suppliers with running 60 s clocks; review whether to stop work on weak bidders after round one. |
| R3 | P0 | Sunday release facts and CSV rows enter the kit's ID index, but SQL queries still use Saturday's database. New supplier owner data, should-cost, orders and cost drivers may be invisible to SQL-based policy paths. Persona text does scan release documents by ID. | kit `DataPackage._ids`; `ClaimBank.query`, `Negotiator.full_cost`, `personas.profile`; code path | Inspect the release schema at 08:00 and trace one new supplier from lookup through profile, claims and estimate. |
| R4 | P1 | Quote attachments are fetched at case open and just before close, not immediately after each supplier reply. `standard_terms` reads only fetched quote text, so a revised quote PDF can be invisible during intervening term planning. | `runner.play_case`; kit `fetch_documents`, `standard_terms`; code path | Test a reply with a changed quote attachment and compare the next move's cost with the eventual close cost. |
| R5 | P1 | Outgoing correctness is distributed across planner, claim bank, writer and close gate. There is no single check immediately before `table.send` for every negotiable field, claim count and reference, or for unsupported commitments in the optional paragraph. | `Negotiator.send`, `writer.email`, `llm.FORBIDDEN`; code path | Add a review case that collects every outgoing move from the simulator and checks the arena's message rules; decide whether a small pre-send guard is warranted. |
| R6 | P1 | A relationship charge is included only when `full_cost` is estimated. With no estimate, `economics.cost` passes no supplier estimate to the kit. The close gate then sees a lower cost than the arena may score. This matters most for bundles and unknown suppliers. | `economics.cost`, `Negotiator.setup`; `test_a_bundle_has_no_should_cost`; code path | Compare recorded back-office relationship cost against the pre-close estimate on all relationship cases. Keep unknown cost explicit in run notes. |
| R7 | P2 | Supplier asks use four regex classes, and persona traits use fixed text patterns. Wording outside those patterns may be missed; a model paragraph cannot repair a term or claim decision. | `policy.ASKS`, `personas.SIGNALS`; code path | Sample unseen release text and final replies, record misses, then widen only patterns backed by examples. |
| R8 | P2 | `runner.save` records decisions and the final score, while full arena traces need `buyer pull`. The run notes do not carry a structured duration for every model call and send. | `runner.save`, `llm.paragraph`, `cli.pull`; code path | Check whether the current logs answer which step used each 60 s clock and which terms drove the cost gap. Add only missing fields. |

### Current safeguards and their limits

- `deal_cost` checks must-haves and the alternative at close. `plan_terms` and term adoption also check must-haves. A central outbound validator would make the same invariants visible at one boundary, including the fallback path.
- `llm.paragraph` rejects digits, data IDs and a list of leak phrases, then returns to the template. It cannot prove that every remaining sentence is supported by the brief. The model's paragraph has no authority over numeric decisions.
- `runner.play_case` catches setup and move exceptions per supplier. A non-409 send error still escapes to the case-level retry; this is an intentional containment boundary to review against transient network failures.
- `policy.safe` keeps partial data from stopping setup, but a fallback can change economics. Its exception is logged; the review should correlate those events with scores.
