# Learnings

What we know about the arena, its supplier bots and the data package, and what it means for the
agent. Basis, Saturday 10 October: 15 practice sessions covering all 10 hosted cases and 12
suppliers, 17 sandbox sessions, and the data package. Every euro figure and what-if score below
was recomputed with `arena_kit.total_cost`. Evidence: `exports/` (every session, supplier thread,
e-mail and claim; schema in `exports/README.md`) and `analysis/explore.py` (the data package).

Add findings to the matching section, newest first: date, tag, the finding, its evidence (case,
session or data ID) and what it means for the agent. Tags: `arena` seen in a session, `data` from
the data package, `rules` from `docs/api.md` or the kit's code. Untested ideas go under
Hypotheses. Correct or delete entries that turn out wrong.

## Takeaways for the agent

1. **Choose terms by C, in code: no lever helps in every case.** The same move flips sign between
   cases. Covering 24 months lifted D01 from 0.20 to 0.73 but made P04 dearer. The copper index
   clause turned P02's price cut into a score of 0. Before every sheet, score each allowed
   combination with `total_cost`, with the supplier's standard terms for unstated fields, and
   keep must-haves and C_alt as hard guards.
2. **Cover the need where the deal beats the fallback.** Uncovered need costs the fallback price
   plus `fallback_risk_pct`. D01 (fallback 55.00, deal 50.90): 24 instead of 12 months, 0.20 to
   0.73. P04 (fallback 4.70, price frozen at 4.96): 24 months cost more than 12. P08 (5.72 + 3 %
   against 5.93 at 90 days): no difference. P10: 24 months unlocked the full 23,400 units a year
   instead of 19,890.
3. **Keep every sheet below the supplier's price until the price is right.** 15 of the 16 practice
   threads that reached `agreed` never moved price again ("Our agreed offer stands"). The one
   exception (P02) gave 0.7 % for 14-day payment. An instant `agreed` means we offered too much:
   Dralveck took our opening sheet in round 1 in both P05 runs. In P10 our own sheet raised an
   agreed 32.00 to 32.45.
4. **The floors sit far below where we stopped.** Expressed as a unit price at our deal's terms,
   C_best lies 7 to 22 % below our deal price in six cases: P05 -22 %, P18 -21 %, P10 -16 %,
   P08 -14 %, P07 -11 %, P11 -7 %. Tacto's house agent scored 0.74 on P02 and 0.75 on P08, where
   we got 0 and 0.11. Our probe offered the supplier's own price from round 2, so it never
   measured how far prices fall. That is the open experiment.
5. **Trade payment days at the supplier's rate against our 8 %.** Suppliers price 60 more days at
   their own cost of money (table under Supplier behaviour). Take the longest payment where that
   rate is below 8 %: P03 at +0.7 % for 90 days scores 0.68 instead of our 0.60. Pay faster only
   for a supplier that values cash far above 8 %. Every 30 days earlier than the reference 60
   costs us 0.67 % of spend.
6. **Refuse index clauses on series the case expects to rise.** A clause adds `material_share`
   times (expected move beyond the deadband + `index_risk_pct`) of spend. P02 (copper
   +5 %, risk 4 %, share 0.2): the clause costs 1.8 % of spend, Nordmark gave 1.5 % for it
   (374.32 to 368.70) and the deal scored 0. Its no-clause offer scores 0.21, the same clause
   with a 5 % deadband 0.55 (both before the relationship charge). P08 and P18 (AS-14404 +6 %,
   risk 1 %, share 0.45): the offered Preisgleitklausel costs 3.2 % of spend.
7. **Use the structural levers: start date, lead time, contract length.** Units bought before
   `effective_date` cost the current price. In P01, C_best equals paying about 138.20 (the ask
   was 138.55) with an April start and 90-day payment. We got 133.60 with a November start and
   14 days (0.64). Late delivery costs a flat `late_cost_per_day` per day: in P05, Hrvelec at 42
   days for 33.00 scores 0.30, while we paid its overtime premium for 35 days and scored 0.19.
   24-month contracts came free at P03, P04, P07 and P10.
8. **Read the supplier before the first move.** The persona traits in notes, quote remarks and
   news predicted behaviour. `price_frozen` suppliers never moved price, `cash_need` suppliers
   asked for faster payment, `capacity_full` suppliers charged overtime for speed (table under
   Persona signals). Every supplier asks "Which volume can you commit to?", also where volume is
   fixed: a stock phrase, not a lever.
9. **Few claims, exact, and only against the supplier's own drivers.** 44 of 57 claims were
   verified, but only one moved price (P01, 1.20). Rising indices are read as support for the
   supplier. Write figures without thousands separators. In an RFQ a data ID counts once per
   case. No supplier sent a cost breakdown.
10. **Words without a sheet move change nothing, and outcomes are deterministic.** Bluff and
    urgency on an unchanged sheet left the price unchanged ("My call: hold"). The same moves give
    the same numbers, so a practice replay measures our change, and a rule-based supplier
    simulator built from the traces is feasible.

## Where we stand

Best score per hosted case. Mean 0.32, which would be 32 points per wave.

| Case | Type / goal | Ours | House / best team | Our deal | C_best as a price at our terms | What we missed |
|---|---|---|---|---|---|---|
| P01 | price increase / stabilise | 0.64 | 0.97 / 0.93 | 133.60, Nov start, 14 d | 138.20 at April start, 90 d | start date, payment days |
| P02 | price increase / stabilise | 0.00 | 0.74 / 0.29 | 368.70, 90 d, copper clause | 368.14 at 90 d, no clause | took the index clause |
| P03 | renewal / stabilise | 0.60 | | 438.21, 24 m, 30 d | 429.40 at 90 d (-2 %) | 90 d at +0.7 % (0.68) |
| P04 | renewal / routine | 0.00 | | 4.96, 24 m, 30 d | 4.93 at 90 d | price frozen above the 4.70 fallback; window 2,317 EUR |
| P05 | RFQ / leverage | 0.19 | | Hrvelec 33.98, 35 d lead, 14 d | 26.62 (-22 %) | price; paid for speed |
| P07 | bundling / routine | 0.56 | | 5.63, 24 m, 30 d | 5.02 at 90 d (-11 %) | price |
| P08 | raw material / leverage | 0.11 | 0.75 / 0.23 | 5.93, 12 m, 90 d | 5.10 at 24 m (-14 %) | price |
| P10 | capacity / secure supply | 0.60 | | 32.45, 24 m, 23,400/yr | 27.38 (-16 %) | price |
| P11 | quality / quality first | 0.46 | 0.31 / 0.41 | 47.00, 300 ppm, no chargeback | 43.77 (-7 %) | price |
| P18 | raw material / leverage | 0.06 | 0.39 / 0.39 | 6.00, 12 m, 90 d | 4.73 at 24 m (-21 %) | coverage (0.17), price |

House / best team: Tacto's house agent and the best team score from Tacto's Discord check-in on
Saturday afternoon. C_best as a price: the unit price at which our deal's terms, with full
coverage, the longest allowed payment, no index clause and the latest allowed start, cost exactly
C_best.

## Score and terms

- 2026-10-10 `rules` **Every session reveals C_best, also a walk-away**, plus our cost breakdown
  computed with the supplier's true numbers, relationship charge included. D01 walk-away after
  one message: c_open 448,810.67, c_best 408,623.99. → One session per case gives its target,
  and a relationship charge gives the supplier's true margin, i.e. its full cost.
- 2026-10-10 `rules` **Uncovered need** costs `fallback_unit_price` plus `fallback_risk_pct` % of
  it; coverage is `min(volume, need) x min(months / 12, horizon)`. Committed volume above the need
  is bought anyway; months beyond the horizon neither cost nor earn. Evidence and examples:
  takeaway 2.
- 2026-10-10 `rules` **Index clause** cost: `spend x material_share x (|path| - deadband)`, signed
  like the case's `index_paths`, plus `index_risk_pct` % of `spend x material_share` whenever a
  clause exists. Only a falling path larger than the risk charge makes a clause pay.
- 2026-10-10 `rules` **Late delivery** is `late_cost_per_day x days beyond need_lead_time_days`,
  one sum per case. Must-haves can cap the lead time (P05: at most 42 days).
- 2026-10-10 `rules` **Effective date:** units bought before it cost the current price, so a
  later start is worth months x volume x price step. Negotiable in D01, P01, P13. D01 at 50.90
  and 24 months: April instead of December start, 0.73 to 0.81; plus 60-day payment, 0.87.
- 2026-10-10 `rules` **Our money:** 8 % a year and reference 60 days in all 21 cases. Paying 30
  days earlier costs 0.67 % of spend.
- 2026-10-10 `rules` **Relationship charge** (`stabilise`, `secure_supply`) grows with the square
  of the first 5 missing margin points, so the cheapest deal sits below the sustainable margin
  (D01: about 2 points below its 4 %) unless the supplier's cost floor binds first. It also
  moves with payment terms: P02 carried 5,483 at 368.70 and 90 days, 901 at 366.41 and 14 days.
- 2026-10-10 `arena` D01's deal at 50.90 carried no relationship charge, so the foundry's margin
  there was at least the sustainable 4 % and its full cost at most about 48.9. Its C_best implies
  49.55 (30 days, December start) to 50.13 (60 days, April start).
- 2026-10-10 `rules` In 14 of 21 case files contract length or volume is ours to pick or left to
  the supplier's standard terms: D01, D02, P03, P04, P07, P08, P09, P10, P14 to P19.
- 2026-10-10 `rules` No alternative, so walking away scores 0: D01, P05, P06, P10, P14, P17.

## Supplier behaviour

- 2026-10-10 `arena` **Deterministic.** Nine D01 sandbox runs with identical sheets gave
  identical prices (52.90, 52.00, 51.50, then `final_offer` 51.50); replays of P04 and P11
  matched round for round. Only the wording varies. → Repeats measure wording, not behaviour.
- 2026-10-10 `arena` **`agreed` freezes the price.** 16 of 19 practice threads reached `agreed`,
  ten of them in round 1 or 2, because our probe opened near the supplier's price and then
  offered its own price with our levers. After that, claims, concessions and pushes all got "Our
  agreed offer stands"; only P02 moved, 0.7 % for 14-day payment. Price moves while the status
  is `open`, as a counter to a sheet below its price.
- 2026-10-10 `arena` **Never offer at or above a price the supplier has quoted or agreed.** P05
  first run: our opening (35.76) sat above Hrvelec's 31.50 quote, Hrvelec agreed at once and the
  case scored 0.01. P10: after `agreed` at 32.00 our sheet at 32.45 closed at 32.45.
- 2026-10-10 `arena` **With several sheets the supplier picks one and answers that one** (D02,
  P03, P08). One lever per sheet shows what it values.
- 2026-10-10 `arena` **Concessions shrink and need a move from us.** D01 answered four
  content-free "we need a better price" e-mails with 52.90, 51.90, 51.40, 51.10, 50.90 and kept
  every other term as we sent it. Repeating the same sheet buys nothing ("My call: hold"); D02's
  Polish shop held 15.30 for three rounds, then sent `final_offer`.
- 2026-10-10 `arena` **Bluff and urgency move nothing** on an unchanged sheet (D01, three runs
  each): same final price, back office "My call: hold". The words register ("built on mutual
  reliability, not on pressure").
- 2026-10-10 `arena` **Payment days are priced at the supplier's own cost of money:**

  | Supplier | Case | 30 to 90 days | Its rate |
  |---|---|---|---|
  | Donautal, Werdenfels (raw-material distributors) | P08, P18 | free | 0 |
  | Selvbrunn | P03 | +0.7 % | about 4 %/yr |
  | Nordmark | P02 | +1.0 % | about 6 %/yr |
  | Wälzlager-Zentrum | P04 | +1.2 % | about 7 %/yr |
  | Leitner | P07 | +1.4 % | about 8.5 %/yr |
  | Hrvelec (45 to 90 days) | P05 | +1.5 to 2.1 % | 12 to 17 %/yr |

- 2026-10-10 `arena` **24 months is often free:** P03, P04, P07 and P10 took it at their price
  ("valuable planning security"). The raw-material distributors (P08, P18) refused 24 months at
  a fixed price and offered a Preisgleitklausel on AS-14404 instead.
- 2026-10-10 `arena` **Price-frozen suppliers refuse every trade for price:** P03 refused 426.98
  with 36 months, 14-day payment or 20 % more volume; P04 refused 4.71 with 36 months or 14-day
  payment. P03: "Our management has frozen all price reductions until December. We can talk
  about the terms instead".
- 2026-10-10 `arena` **Full suppliers charge for speed:** Hrvelec quoted 31.50 at 52 days lead
  time, 33.00 at 42 and 34.50 at 35 (with 90-day payment): "it means overtime so the price would
  go up". Ravensteiner: 32.00 at 56 days, 35.00 at 35. In the capacity case P10 the opening
  covered 19,890 of 23,400 units a year; 24 months unlocked the full volume.
- 2026-10-10 `arena` **No supplier sent a cost breakdown** (0 of 12, also those marked
  `open_book`). Delivery schedules (P05, P10) and the 8D report (P11) came on request, a quote
  PDF with every changed offer. Only the sandbox job shop (D02) sent a breakdown.
- 2026-10-10 `arena` **Suppliers open with data too:** D01 cited WAGES-METAL +3.1 % as 28 % of
  its cost; P02, P08 and P18 cited their rising material indices.
- 2026-10-10 `arena` **The back office shows each decision** in plain words ("My call: counter",
  "hold", "accept", "final offer") and routes questions to roles (freight forwarder, finance).
- 2026-10-10 `arena` **A session does not pause:** when our process stopped mid-case, P01's
  thread kept running into timeouts until we resumed it with the kit. Three in a row end the
  thread.

## Arguments and claims

- 2026-10-10 `arena` **Verified is not convincing.** Of 57 claims, 44 were verified, 11
  duplicate and 2 contradicted. Only P01 moved: 134.80 to 133.60 after the notice claim and two
  index claims ("we did not know that, a fair point"). Others: "Your figures confirm our case:
  that driver rose" for indices, "it holds, but it does not change our calculation" for
  scorecards. → Never cite an index that rose.
- 2026-10-10 `arena` **No thousands separators:** "2,637 ppm" was read as 2.637 and came back
  `contradicted` ("does not match the records. That costs trust", P11). Write 2637.
- 2026-10-10 `arena` **In an RFQ a data ID counts once per case:** the same index IDs cited to a
  second bidder came back `duplicate` (P05). Only rival quotes and offers may go to every bidder.
- 2026-10-10 `data` P01's letter gives 51 days' notice (`doc:20260911-70110-P01`); the contract
  requires 90 and fixes prices per calendar year (`ctr:4600070110`, clause `#3.1`). Verified in
  P01; supports a later start.
- 2026-10-10 `data` Citable counters: industrial power -43 % on 2022 (`news:20260912-30`), iron
  castings +1.8 % year on year (`news:20260914-31`), forecast `fc:310010@2026-09` +10.1 %.
- 2026-10-10 `data` Case alternatives are `quote:72000xx` in `facts.json`, but the case file's
  alternative terms set C_alt and can differ (P01: lead time 70 in the case, 56 in the quote,
  plus tooling 1,500 and 2,376 ppm).

## Data package

- 2026-10-10 `data` Price letters overshoot the index-weighted cost move of the part's drivers:
  P01 +9.5 % against +2.3 %, P13 +7.0 % against +4.0 %, P17 +8.0 % against +5.5 %. P02 +6.5 %
  against +6.6 % is fair.
- 2026-10-10 `data` Some incumbents sell below should-cost today (estimate error about 5 %):
  P17 -8.4 %, P02 -7.6 %, P01 -4.8 %. All `stabilise`: pushing them lower adds relationship
  charge.
- 2026-10-10 `data` 225 past renewals asked +1.4 % on average and settled -1.1 %; the median
  settled 0.0 % and 82 % ended flat or lower (`negotiation_history`).
- 2026-10-10 `data` Second-source quotes are 8 to 21 % above the incumbent; exceptions are the
  DN 65 flange (+1.9 %, sup:70240) and the coupling hub (+9.6 %). A switch threat is a bluff in
  most cases.
- 2026-10-10 `data` We pay late: Saalach 19 days, Wälzhammer 16, Lindlbauer 13 on average; seven
  suppliers sent an overdue-invoice letter (`invoices`, documents ending `-P`).
- 2026-10-10 `data` Cash discounts in the vendor master show what cash is worth to four
  suppliers: 2 to 3 % for 16 to 20 days earlier, 37 to 56 % a year (sup:70210, 70230, 70280,
  70350).
- 2026-10-10 `data` Own-plant should-cost (about 5 % error) exists for P01, P02, P03, P09, P10,
  P14, P17, the `stabilise` and `secure_supply` cases that need it; German-base estimates for
  the RFQs P05 and P06; nothing for the other ten.
- 2026-10-10 `data` Five suppliers once sold below full cost to keep the volume (sup:70110,
  70120, 70130, 70160, 70550, `negotiation_history`).
- 2026-10-10 `data` Each persona trait is written in one or two fixed phrases across call notes,
  meeting notes, quote remarks and news, so plain patterns classify every note (`SIGNALS` in
  `analysis/explore.py`). Holiday, ISO, contact-person, packaging and trade-fair mails are noise.

## Persona signals

Phrases from `SIGNALS` in `analysis/explore.py`; levers are hypotheses until the arena column
shows evidence.

| Trait | Phrase in the data | Lever | Seen in the arena |
|---|---|---|---|
| `price_frozen` | "no room on price", "not discounted", "price list applies to all" | payment days, logistics, contract length | no price move, every trade refused (P03, P04) |
| `cash_need` | "pay earlier", "bank is watching", "within 10 days", "short-time work" | faster payment for price | asked for faster payment (P05 Fuchsreiter, P11 Kalwisz), took the 14-day sheet (P01). Dralveck asked too; its only cash signal is a 2 % cash discount for 10 days |
| `capacity_full` | "order intake is very strong", "fully booked", "allocates volumes" | a firm 12 to 24 month commitment | overtime premium for speed (P05 Hrvelec, P10 Ravensteiner) |
| `spare_capacity` | "second shift has been on hold", "take additional parts" | volume, extra parts | "We have free capacity for your parts" (P05) |
| `stale_costing` | "not followed his material", "own spreadsheet" | the real index path since its last price | conceded 1.20 after index and notice claims (P01) |
| `open_book` | "walk us through their calculation" | ask for the cost breakdown | no breakdown sent (P04, P08, P18) |
| `hedged` | "bought their ... forward", "covered at fixed prices" | index arguments fail until the hedge ends | untested |
| `approval_2pct` | "above 2 % need the approval" | moves of 2 % or less per round | untested |
| `partnership_2022` | "kept supplying at the old price" | acknowledge 2022, partnership framing | untested |
| `reference_customer` | "important reference customer" | tone, long-term framing | untested |
| `deprioritising_us` | "reviewing small accounts", "not strategic" | bundle volume or use the alternative | untested |
| `complains_late_pay` | "invoices are overdue" | promise and keep payment terms | untested |

## Practical

- 2026-10-10 `rules` Case files of all 21 cases come free from `GET /v1/cases` (no session, no
  quota). Hosted for practice: P01, P02, P03, P04, P05, P07, P08, P10, P11, P18; the other nine
  exist as case files only. Our probe used 15 practice sessions.
- 2026-10-10 `rules` The kit's `llm_from_env` reads `LLM_PROVIDER`, `LLM_MODEL` and `LLM_API_KEY`
  (not `OPENAI_API_KEY`); without `LLM_MODEL`, `buyer play` with our agent fails before the
  first move. `gpt-6-luna` answered a short call in 2.0 s and wrote three move suggestions in
  12 s. Tacto: their house agent runs on a small, cheap model, and reading the data beats a
  bigger model.
- 2026-10-10 `rules` In an RFQ every thread's 60-second clock runs while we work on another.
  A waiting thread needs a message, e.g. a short question about validity, or it collects
  timeouts; our probe kept waiting threads alive this way (D02, P05).
- 2026-10-10 `rules` `arena-sim` plays a scripted supplier: good for plumbing and timing, not
  for tactics.

## Hypotheses (untested in the arena)

- Prices fall much further when every sheet stays below the supplier's price and concessions
  are slow (house agent 0.75 on P08, ours 0.11 after agreeing in round 2).
- Cash-short suppliers give more price for 14 to 30 days payment than the 0.67 % per 30 days it
  costs us.
- Citing the best rival offer moves RFQ bidders; our probe never cited offers.
- Suppliers with "approval above 2 %" notes move at most 2 % per round.
- Stale-costing suppliers concede after a verified falling-index claim; hedged suppliers answer
  index claims with "not our reality" until the hedge ends.
- The cost floor is full cost; the five that once sold below full cost may go lower.
