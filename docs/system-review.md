# System review

Review snapshot: `julian/second-branch` at `3c02621`, 10 October 2026. This is an assessment of the running buyer, with specific places to inspect before changing it. The [architecture review](architecture.md) maps the live path and every module. [Design](design.md) describes additional planned components; [learnings](learnings.md) holds practice evidence.

## What works now

| Property | Evidence | Why it matters |
|---|---|---|
| Numeric decisions stay in code | `buyer/economics.py`, `buyer/policy.py`; kit `total_cost` and `must_haves_ok` | The optional model cannot choose a price or accept a sheet. |
| A close uses the best acceptable standing sheet | `Negotiator.best_offer`, `deal_cost`; `tests/test_guards.py` | A broken must-have or a sheet above the alternative is rejected by the final decision gate. |
| A late or broken writer leaves a move | `llm.paragraph`, `writer.email`; model-timeout test | The policy can send a template when the model fails. |
| Cases and waves contain most errors | `runner.play_case`, `play_all`, `play_waves`; `tests/test_waves.py` | One supplier setup or case failure need not end other work. |
| Known case structures run through the simulator | `tests/test_cases.py` over the available `logs/cases/` files | This checks integration for bundles, RFQs and term options, though the supplier is scripted. |
| Practice gives measurable outcomes | `buyer pull`, `logs/sessions/`, `exports/`, `docs/learnings.md` | Team members can compare actual cost and score with the arena result. |

The reported hosted-case mean of best scores, 0.727, is in-sample across ten practice cases as recorded in [learnings](learnings.md). It does not establish performance on Sunday's unseen cases. The architecture has no autonomous learning stage; a person reviews traces and changes code between runs.

## Review findings, in order

These are review targets, not implemented changes. A risk is marked **observed** when a cited trace or measurement supports it, and **code path** when the implementation makes it possible but live impact has not been measured.

| ID | Priority | Finding | Evidence | Next review step |
|---|---|---|---|---|
| R1 | P0 | The final gives a crashed case only two `play_case` attempts. If both fail, the future stores an exception and the wave loop never submits that case again, even if its cap remains open. | `runner.play_waves.one`; code path | Reproduce two transient failures in `tests/test_waves.py` and decide how many resumptions fit the remaining cap. |
| R2 | P0 | The writer budget reserves one measured send for each other live thread, but messages are sent serially. The last of four bidders can wait through several sends. Saturday's measured reply times were 19 s median and 28 s p90. | `runner.writer_budget`, `play_case`; [generalisation timing](generalisation.md#timing); observed timing, code path for four bidders | Simulate four slow suppliers with running 60 s clocks; review whether to stop work on weak bidders after round one. |
| R3 | P0 | Sunday release facts and CSV rows enter the kit's ID index, but SQL queries still use Saturday's database. New supplier owner data, should-cost, orders and cost drivers may be invisible to SQL-based policy paths. Persona text does scan release documents by ID. | kit `DataPackage._ids`; `ClaimBank.query`, `Negotiator.full_cost`, `personas.profile`; code path | Inspect the release schema at 08:00 and trace one new supplier from lookup through profile, claims and estimate. |
| R4 | P1 | Quote attachments are fetched at case open and just before close, not immediately after each supplier reply. `standard_terms` reads only fetched quote text, so a revised quote PDF can be invisible during intervening term planning. | `runner.play_case`; kit `fetch_documents`, `standard_terms`; code path | Test a reply with a changed quote attachment and compare the next move's cost with the eventual close cost. |
| R5 | P1 | Outgoing correctness is distributed across planner, claim bank, writer and close gate. There is no single check immediately before `table.send` for every negotiable field, claim count and reference, or for unsupported commitments in the optional paragraph. | `Negotiator.send`, `writer.email`, `llm.FORBIDDEN`; code path | Add a review case that collects every outgoing move from the simulator and checks the arena's message rules; decide whether a small pre-send guard is warranted. |
| R6 | P1 | A relationship charge is included only when `full_cost` is estimated. With no estimate, `economics.cost` passes no supplier estimate to the kit. The close gate then sees a lower cost than the arena may score. This matters most for bundles and unknown suppliers. | `economics.cost`, `Negotiator.setup`; `test_a_bundle_has_no_should_cost`; code path | Compare recorded back-office relationship cost against the pre-close estimate on all relationship cases. Keep unknown cost explicit in run notes. |
| R7 | P2 | Supplier asks use four regex classes, and persona traits use fixed text patterns. Wording outside those patterns may be missed; a model paragraph cannot repair a term or claim decision. | `reader.ASKS`, `personas.SIGNALS`; code path | Sample unseen release text and final replies, record misses, then widen only patterns backed by examples. |
| R8 | P2 | `runner.save` records decisions and the final score, while full arena traces need `buyer pull`. The run notes do not carry a structured duration for every model call and send. | `runner.save`, `llm.paragraph`, `cli.pull`; code path | Check whether the current logs answer which step used each 60 s clock and which terms drove the cost gap. Add only missing fields. |

### Current safeguards and their limits

- `deal_cost` checks must-haves and the alternative at close. `plan_terms` and term adoption also check must-haves. A central outbound validator would make the same invariants visible at one boundary, including the fallback path.
- `llm.paragraph` rejects digits, data IDs and a list of leak phrases, then returns to the template. It cannot prove that every remaining sentence is supported by the brief. The model's paragraph has no authority over numeric decisions.
- `runner.play_case` catches setup and move exceptions per supplier. A non-409 send error still escapes to the case-level retry; this is an intentional containment boundary to review against transient network failures.
- `Negotiator.safe` keeps partial data from stopping setup, but a silent fallback can change economics. Its exception is logged; the review should correlate those events with scores.

### Earlier notes that need a status update

[Generalisation](generalisation.md) describes an older price-engine snapshot. Three of its identified issues now have code paths that address them: per-move exceptions are guarded in `runner.play_case`, `personas.supplier_texts` scans release document IDs, and `ClaimBank` normalises recorded quote prices by `price_unit` when comparing them. Release SQL visibility, four-bidder timing and out-of-sample tuning remain open review topics. Treat the older document's risk table as historical evidence, not as the current implementation status.

## Functional review checklist

| Stage | Verify with a trace or test |
|---|---|
| Intake | Does every supplier's latest quote attachment yield the standard terms used to price its standing sheet? Are unknown Incoterms handled conservatively? |
| Data | Can an unseen supplier's release ID, document and cost evidence be found through the same access path? Which SQL-only fields are absent? |
| Estimate | Does the estimated supplier value explain a term trade? Is the full-cost estimate based on that supplier or generic data? |
| Plan | Does each outgoing sheet contain every `negotiable` field and satisfy must-haves? Is `plan_terms` fast enough for a hidden case with more options? |
| Read | Which supplier requests were detected, answered in code, answered in the paragraph, or missed? |
| Claims | Does each sentence pair a correct figure with its citable ID and stay within the arena's per-message limit? Are rival offers still standing? |
| Clock | From each supplier reply, how long until our next send starts and completes? What happens as bidder count or reply latency grows? |
| Close | Which standing sheet had minimum estimated C, which alternative set the ceiling, and what did the back office charge after close? |
| Recovery | On a 409, timeout, network error or case restart, is the pending state rolled back and reconstructed from arena messages? |
| Learning | Can a teammate explain `C_deal - C_best` by term, claim, price path and supplier response before changing a constant? |

## Small improvement sequence

1. **Protect the live final.** Resolve R1 and R2 with local fake tables and wave tests. Keep the current case runner working while changing one failure path at a time.
2. **Read the Sunday release.** Inspect its schema, then resolve only the SQL visibility gaps that affect live profiles, claims or cost estimates. Confirm that the package and release stay read-only.
3. **Make the boundary auditable.** Resolve R4 and R5 with one collected-move test, then add a small guard only if a failing path is demonstrated.
4. **Calibrate with outcomes.** Use pulled back-office costs to check R6 and the cost gap. Change negotiation constants only after a simulator or sandbox pass and evidence in more than one supplier or case.
5. **Improve understanding.** Resolve R7 and R8 using actual missed replies and latency traces. Record tested findings in `learnings.md` and update `design.md` when the architecture changes.

Practice sessions use the team's rolling quota. Use `arena-sim` or `case:D01` and `case:D02` first. Before any PR, run `uv run pytest -q && uv run ruff check .` and have a teammate review it, as required by [`AGENTS.md`](../AGENTS.md).
