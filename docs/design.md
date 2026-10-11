# Agent design

What the buyer does today. Observations behind it are in `learnings.md`; the module map with
every file is `architecture.md`; the diagram is on page 1 of [how-it-works.pdf](how-it-works.pdf).

## Principle

Code owns every number and every binding decision; the model reads replies and writes words.
Score is total cost C, not price. Every step has a fallback that still sends a move within 60 s.

## A case

1. **Prepare**: open the session, read the quote and standard terms, build the supplier's
   profile and the claim bank, estimate its full cost and cost of money, plan the opening terms
   and price.
2. **Negotiate**, one thread per supplier, in parallel. Each round: read the reply (its sheets,
   asks, signals), plan candidate sheets with `total_cost` and `must_haves_ok`, decide counter,
   accept or walk, write the e-mail (model paragraph with a hard timeout, template if late),
   guard every field and claim, send.
3. **Close**: accept the best standing sheet that keeps every must-have and beats C_alt, or walk;
   at the latest 90 s before the wave's 8-minute cap.

## Modules

| Module | Job |
|---|---|
| `buyer/economics.py` | C of a sheet; the accept gate; a quoted package kept exactly as quoted (`quoted_offer`); what a sheet is worth to the supplier (`supplier_value`, overtime for faster delivery); term planning: every allowed combination priced at the supplier's valuation, lowest C, ties to the supplier's side; the relationship-optimal price; the index-clause trade (the supplier's clause value capped at 8 % of the price, none for a hedged supplier) |
| `buyer/claims.py` | claim bank: should-cost below its price, our order prices, each cost driver's largest fall over any window up to 12 months, notice period, forecast, scorecard, case rival quotes, hedge and open-book notes; rival offers in an RFQ |
| `buyer/personas.py` | owner type, persona signals from notes, letters, quote remarks, news and the supplier's own e-mails, cost of money |
| `buyer/policy.py` | per thread: anchor by goal and signals, a share of the gap per round, held after a deep first concession, a patience budget for near-cost, fully booked and relationship-goal suppliers; adopts a quoted package when it beats our plan at equal value to the supplier, mirrors a better alternative, takes or offers an index clause; the supplier's asks from its fixed sentences (volume, proof, faster payment, our target); claims 3 in round 1, then 1 per round; deduplicates forecasts from the same period and suppresses unchanged offers; evaluates explicit supplier needs as complete, must-have-safe packages only when total cost improves; closes on final offer, agreement or round limit |
| `buyer/writer.py`, `buyer/llm.py` | the e-mail: a model paragraph answering the supplier's last e-mail and asks (no digits, IDs or leaks, else a deterministic fallback), then code sentences with figures, claims and the proposal; forecast rows as CSV when proof is asked; tracks model attempts, successes, timeouts, rejections and deadline skips |
| `buyer/runner.py` | one message at a time per session, to the thread whose 60 s clock has run longest; keepalive questions for finished bidders; rollback when the arena refuses a send; a non-repeating fallback for failed policy moves; the model's time budgeted so every live clock gets a message; Live Final waves never raise and resume a crashed case |

When a relationship-goal counter reaches or falls below our estimated target, the policy stops
offering and the close gate evaluates the supplier's standing sheet.

## Subagent team

Before negotiation, `buyer/research.py` assigns four specialists to supplier data groups and has a
lead choose up to two allowed term trades, claim order and tone. `buyer/rehearsal.py` prepares
possible supplier arguments and evidence-based responses. During negotiation,
`buyer/analyst.py` classifies each reply for tone and a steady, hold or argue tactic; code still
controls price and terms.
After a case, `buyer/memory.py` writes a debrief to `buyer/lessons.jsonl` for later research. All
model output is bounded and validated; failures fall back to code-owned behavior.

## Supplier estimate

`arena_kit.cost.supplier_value` prices a deal for the supplier from `standard`, `interest_rate`,
`ppm` and `extra`; `relationship_cost` needs `full_cost`. We estimate full cost from
`should_cost` moved by its drivers' index change, capped at the quote less the sustainable margin
in relationship goals; cost of money from owner type, cash signals and cash discounts; overtime
from capacity signals. The Sunday release (`data/release-sunday/`) and the case's own `facts` are
read at runtime through the ID index.

[agentic-approach.md](agentic-approach.md) is a proposal for a model-chosen tactic inside these
boundaries; not implemented.
