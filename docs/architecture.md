# Buyer architecture: the running system

Checked against `main` at `185ad65` on 10 October 2026. This page explains the implemented buyer. [Design](design.md) describes planned work; [learnings](learnings.md) records what practice showed; [system review](system-review.md) lists risks to investigate.

The buyer tries to minimize total cost over the case horizon. Unit price is only one part of that cost: uncovered demand, payment, freight, delivery, quality, tooling, index clauses and sometimes supplier relationship cost also matter. The final action is one accepted term sheet or a walk-away.

## System map

The live loop follows the supplied diagram. Solid arrows are runtime data or actions. Dashed arrows are optional wording or later human changes.

```mermaid
flowchart LR
    DATA["Data package<br/>supplier facts and documents"] --> NEG["Negotiator<br/>one per case"]
    COST["Cost engine<br/>score legal term options"] <--> NEG
    NEG <--> SIDE["Side<br/>memory for each supplier"]

    ARENA["Arena<br/>case, quotes, supplier replies"] --> RUN["Runner<br/>sessions, waves, 60 s clocks"]
    RUN --> NEG
    NEG --> WRITER["Writer<br/>terms, figures, claims"]
    MODEL["Optional model<br/>email paragraph"] -.-> WRITER
    WRITER --> ARENA
    NEG --> CLOSE{"Close gate<br/>best valid standing offer?"}
    CLOSE --> ARENA

    RUN --> NOTES["Run notes"]
    ARENA --> TRACE["Trace and back office"]
    NOTES --> REVIEW["Human review and next experiment"]
    TRACE --> REVIEW
    REVIEW -.-> NEG
```

### What each box does

| Box | Plain-language role | Where it lives |
|---|---|---|
| **Arena** | Supplies the case, opening quotes, supplier replies and final result. The kit handles API calls, session state and quote attachments. | `arena_kit.client`, `arena_kit.play`, [API brief](api.md) |
| **Runner** | Opens cases, chooses which supplier needs a reply, sends one message at a time within a case, watches clocks and runs final waves in parallel. | [`buyer/runner.py`](../buyer/runner.py), [`buyer/cli.py`](../buyer/cli.py) |
| **Data package** | Read-only supplier records, citable facts and documents. The Sunday release joins ID lookup; the package's SQL database stays separate. | `arena_kit.data.DataPackage`, [`buyer/claims.py`](../buyer/claims.py), [`buyer/personas.py`](../buyer/personas.py) |
| **Negotiator** | Owns one case's policy: sets up suppliers, reads replies, plans offers, selects claims and chooses the close action. | `Negotiator` in [`buyer/policy.py`](../buyer/policy.py) |
| **Side** | Remembers one supplier's quote, standard terms, profile, planned terms, offers, counters, asks and pending message. | `Side` in [`buyer/policy.py`](../buyer/policy.py) |
| **Cost engine** | Uses the kit's published cost function, estimates supplier value, searches allowed term combinations and rejects unacceptable deals. | [`buyer/economics.py`](../buyer/economics.py), `arena_kit.cost` |
| **Optional model** | Writes one middle paragraph in the email. It does not choose prices, terms, claims or accept actions. | [`buyer/llm.py`](../buyer/llm.py) |
| **Writer** | Assembles the code-chosen proposal, figures and cited claims into an email; prepares the model brief and template fallback. | [`buyer/writer.py`](../buyer/writer.py), `Negotiator.send` |
| **Close gate** | Finds the cheapest acceptable *standing* supplier sheet or walks away. It checks must-haves and estimated cost against the alternative. | `Negotiator.best_offer`, `Negotiator.close`, `economics.deal_cost` |
| **Trace and back office** | Hold the arena's full conversation, result and official cost breakdown after a session. | `buyer pull` in [`buyer/cli.py`](../buyer/cli.py) |
| **Human review** | Compares decisions with the result, records a finding, changes code and tests again. This is outside the live agent. | [`learnings.md`](learnings.md), [`analysis/explore.py`](../analysis/explore.py) |

## One case, from opening to close

1. **Enter.** `buyer play` runs one case; `buyer run` runs a set. `cli.main` loads `.env`, one `ArenaClient`, one shared `DataPackage` ID index and an optional model client. `--agent naive` selects the kit baseline instead of this buyer.
2. **Open.** `runner.play_case` opens a `RemoteTable` session and fetches opening quote attachments. Each case gets one `Negotiator`; each supplier thread gets one `Side`.
3. **Plan.** `Negotiator.setup` reads the standing quote and standard terms, supplier signals and available cost evidence. `economics.plan_terms` tries the allowed non-price combinations, prices them at equal estimated supplier value, keeps must-haves, and chooses the lowest buyer cost. The policy sets an opening anchor and builds a ranked claim bank.
4. **Pick a thread.** The runner serves the supplier whose reply has waited longest; opening quote price breaks a first-round tie. Calls within a session are serial. A finished bidder can receive a keepalive while other bidders continue. The optional model gets at most 15 seconds and can be skipped when another thread's 60 second clock is tight.
5. **Read and decide.** `Negotiator.move` reads structured supplier sheets, detects volume, proof, payment and price questions by fixed patterns, and updates persona signals. It may adopt a complete, valid supplier package when it beats the current plan at equivalent supplier value. Otherwise `next_price` starts at the anchor and usually moves 30% of the gap toward the counter, with special patience and relationship-cost rules.
6. **Write and send.** The policy selects up to three data-backed claims on the first move, then up to one per later move. Code writes all figures, claim IDs and term sheets. The model may add a paragraph; a late, empty, long or filtered paragraph falls back to a template. `RemoteTable.send` delivers the message and waits for the supplier's reply.
7. **Recover or finish.** On a send 409, the policy rolls back its pending state and reads the arena's current reply. A terminal send result ends the case. Before a final wave's cap, the runner stops negotiating with 90 seconds left, refetches recent quote attachments and calls the close gate. A close 409 triggers another read and guarded choice, up to three tries. The final wave loop gives a crashed case one resume attempt.
8. **Review later.** `runner.save` writes decision notes and the result under `logs/runs/`. `buyer pull` stores the full trace and back office under `logs/sessions/`. A teammate uses those records for the next experiment.

### What is binding

The kit's `complete_offer` fills normal planned sheets to the case's negotiable fields. When mirroring a supplier alternative, `economics.quoted_offer` preserves its exact effective package instead of snapping its values. At close, `economics.deal_cost` requires a price, `must_haves_ok` and cost below the buyer's alternative. Its cost uses `arena_kit.total_cost` with this buyer's supplier estimate, so an unknown full cost can make the relationship charge uncertain.

Only the first supplier sheet in its latest reply is a standing sheet that can be accepted. A better alternative sheet must first be sent back so the supplier makes it standing. The model's paragraph is nonbinding, but its wording still matters; [system review](system-review.md) covers the missing central outbound check.

## Every Python file in `buyer/`

| File | Responsibility and main interfaces |
|---|---|
| [`__init__.py`](../buyer/__init__.py) | Marks `buyer` as the package. It contains only a package docstring and makes no decisions. |
| [`cli.py`](../buyer/cli.py) | Command entry point. `main` parses `play`, `run` and `pull`; `load_package` builds the shared ID index; `pull` saves completed sessions, traces and back office. It also selects the kit's naive baseline when requested. |
| [`runner.py`](../buyer/runner.py) | Live orchestration. `play_case` schedules supplier turns and sends messages; `writer_budget` protects clocks; `close` retries a refused close; `play_all` runs practice cases; `play_waves` polls and runs final waves; `save` writes run notes. |
| [`policy.py`](../buyer/policy.py) | The negotiation state machine. `Side` stores one supplier's state; `Negotiator.setup` builds its plan, `move` responds to a reply, `next_price` paces concessions, `pick` chooses claims, `send` assembles a move, `commit` and `rollback` track delivery, and `best_offer` and `close` choose the final action. `asks` reads fixed-form email requests. |
| [`economics.py`](../buyer/economics.py) | All cost and term math. `cost` wraps the kit's total cost; `estimate` models supplier economics; `plan_terms` scores allowed packages; `value` and `price_for_value` compare packages at equal supplier value; `quoted_offer` validates an exact supplier package; `relationship_optimum` handles cases where a lower price raises relationship cost; `deal_cost` is the accept gate. |
| [`claims.py`](../buyer/claims.py) | The citable argument bank. `ClaimBank` looks up facts and IDs, builds sentences about should-cost, orders, indexes, forecasts, notice, supplier notes, scorecards and rival quotes, then ranks them through `for_supplier`. `rival_offer` cites another bidder's current standing sheet. |
| [`personas.py`](../buyer/personas.py) | Supplier reading. `supplier_texts` gathers notes, letters, news and quote remarks; `signals_in` detects traits such as cash need or full capacity; `profile` derives owner, country, signals, cost of money and email tone. Unknown suppliers get a neutral profile. |
| [`writer.py`](../buyer/writer.py) | Email composition. `describe` names the code-chosen terms; `statements` writes binding volume or fixed-payment answers; `facts` and `brief` constrain what the model may say; `email` combines paragraph, claims and proposal; `keepalive_message` handles a waiting bidder. |
| [`llm.py`](../buyer/llm.py) | Optional model connection. `complete_from_env` builds the chat-completions caller; `paragraph` enforces a 15 second wall-clock ceiling and drops output with digits, IDs or leak phrases. The template works when no model is configured or the call fails. |

The buyer wraps `arena_kit`; it does not patch it. [`design.md`](design.md) separates planned agent components from this implemented path. [`system-review.md`](system-review.md) records the failure paths and improvement order. [A more agentic buyer](agentic-approach.md) proposes one bounded next step.
