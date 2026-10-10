# Learnings

What we know about the arena, its supplier bots and the data package, and what it means for the
agent. Basis, Saturday 10 October: 15 practice sessions covering all 10 hosted cases and 12
suppliers, 17 sandbox sessions, the team's simulator and sandbox experiments, and the data
package. Every euro figure and what-if score below was recomputed with `arena_kit.total_cost`. Evidence: `exports/` (every session, supplier thread,
e-mail and claim; schema in `exports/README.md`) and `analysis/explore.py` (the data package).

Add findings to the matching section, newest first: date, tag, the finding, its evidence (case,
session or data ID) and what it means for the agent. Tags: `arena` seen in a session, `data` from
the data package, `rules` from `docs/api.md` or the kit's code. Untested ideas go under
Hypotheses. Correct or delete entries that turn out wrong.

## Takeaways for the agent

1. **Stay below the supplier's counter until the end; it agrees the moment our sheet reaches the
   counter it would make.** D01: our 51.25 one cent under its 51.30 was agreed at once
   (sandbox `14ea35524959126f`). Moving a share of the gap each round keeps it conceding: the
   engine took the practice mean of best scores from 0.32 to 0.73.
2. **Verified claims that it "took into account" lower where it stops, most of all in round 1.**
   D01 with the same price path: no claims 50.00, delivery record 49.60, notice 49.60, should-cost
   49.30, three claims spread over rounds 48.90 (score 0.998). Which types count differs by
   supplier (table under Arguments and claims).
3. **Words move it too.** D01, identical sheets, no claims: plain 50.00, "firm" 49.90, warm and
   acknowledging its wage costs 49.60, "What would you need from us to move further on the
   price?" 49.40 (0.987). But a question repeated every round backfires: practice suppliers
   answered "volume!" where volume is fixed and stopped moving (P05, P18 v3). Answer what it
   asked; state a fixed volume as our full demand, with the figure.
4. **Patience is a budget of about 40 % cumulative gap** (sum over rounds of our sheet's distance
   to its counter, relative to its price): final offers at 41 to 42 % (D01 linear paths), 39 %
   (P07), 42 % (P08), 36 % (P18). Suppliers selling near our should-cost or with a pricing
   committee end much earlier: Nordmark walked away at 19 % (P02 v1), Ravensteiner gave its final
   offer in round 1 at a 15 % gap (P10 v1).
5. **Choose terms by C at the supplier's own valuation**, including a contract beyond our horizon
   (free for us, security for it) and the overtime a fully booked supplier charges for faster
   delivery (about 0.5 % of the price per day: Hrvelec, Ravensteiner). This alone moved P10 from
   a 42-day to a 56-day lead time.
6. **In relationship goals stop at the price where C is lowest.** D01: all claims at once pushed
   to 48.50 and scored 0.969; stopping near 48.90 scored 0.998, the relationship charge grows
   faster below.
7. **Only a supplier's standing sheet can be accepted** (an alternative returns 422). A better
   alternative is sent back as our sheet; it agrees and becomes standing (P10).
8. **Raw-material distributors refuse a fixed price beyond 12 months and refuse any deadband**
   (P08, P18): take their clause and negotiate the price; insisting on a deadband stalled them.
   But only when their sheet with the clause costs us less than their last one: Nordmark's copper
   clause came alone and cost 1.8 % of spend, score 0 (P02 `680eb11405186b42`,
   `d52ccdd3d2e07b3f`). That rule separates all 24 P02, P08 and P18 sessions correctly.
9. **RFQ: the arena answers one call per session at a time** and each thread's 60 s clock runs
   from its reply, so sends are serialized by deadline; the cheapest rival offer is a new,
   verified claim to every other bidder every round (P05 0.83, D02 0.73).
10. **The ceiling is lower than 0.9.** Best per case over all teams averages 0.82 (`/v1/live`,
    Saturday evening); practice C_best for P04 needs 4.93 against a frozen 4.94.

## Where we stand

Best score per hosted case, Saturday 22:30: mean 0.727 (team rank about 4 of 21 on the practice
board). Record = best of all teams on `/v1/live` at about 20:30 (house agent in brackets).

| Case | Goal | Ours | Session | Deal | Record (house) | What limits us |
|---|---|---|---|---|---|---|
| P01 | stabilise | 0.974 | `4cc256188e1cd8af` | 130.18, Nov, 14 d | 0.995 (0.966) | agreed at our sheet in round 4 |
| P02 | stabilise | 0.507 | `3ad1d67f26aac5e7` | 371.88, 90 d | 0.847 (0.740) | Nordmark settles near 371.9 after round 1 |
| P03 | stabilise | 0.923 | `c7fcc4c7ae8f4e9a` | 432.15, 90 d, 24 m | 0.936 (0.925) | price frozen |
| P04 | routine | 0.860 | `81e9fd209c3fd659` | 4.94, 90 d, 36 m | 0.874 (0.860) | C_best needs 4.93 |
| P05 | leverage RFQ | 0.828 | `917135b8156fb8a3` | Dralveck 27.86, 14 d, 35 d | 0.824 (0.555) | ours is the record |
| P07 | routine | 0.751 | `cacd5028b34d30dc` | 5.35, 45 d, 36 m | 0.779 (0.782) | final offer in round 3 |
| P08 | leverage | 0.549 | `7701b00c7a9a8b3e` | 5.35, AS-14404 clause | 0.732 (0.752) | final offer in round 2 to 4 |
| P10 | secure_supply | 0.679 | `7c4f1855794797d6` | 31.50, 56 d, 36 m | 0.702 (0.686) | fully booked, final early |
| P11 | quality_first | 0.710 | `3ac9ee6cf673cf7c` | 45.50, 300 ppm | 0.807 (0.314) | wants faster payment, which is fixed |
| P18 | leverage | 0.485 | `6a39d7511267e0ff` | 5.30, AS-14404 clause | 0.677 (0.386) | final offer in round 2 to 3 |

## Score and terms

- 2026-10-10 `rules` **The category goal sets the rates of C**, not the case type (P13 is a price
  increase under `leverage`, P06 an RFQ under `stabilise`). From all 21 case files:

  | Goal | Fallback risk | Relationship charge | Push for |
  |---|---|---|---|
  | `leverage` | 3 % (D02: 5 %) | no | price: rival quotes, should-cost, indices |
  | `routine` | 5 % | no | price and a quick close; small stakes |
  | `quality_first` | 8 % | no | low `ppm_commitment`, chargeback at least `cost_per_defect` |
  | `stabilise` | 10 % | yes, sustainable margin 0.5 to 8 % | structure: term, start date, payment, fair clause |
  | `secure_supply` | 25 % | yes, 4 to 10 % | full coverage and lead time first, then price |

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

- 2026-10-10 `arena` **The round-1 counter is a cap plus claims, not a reaction to the anchor.**
  D01 (quote 52.90), 30 sandbox runs: anchors 44.0 to 48.5 without claims all got 51.30 (-3.0 %);
  a should-cost claim alone 51.00, the order prices alone 50.30, notice or scorecard alone 51.30,
  all three 50.00; the same three claims at anchor 48.88 got 50.40. An insulting anchor (37.03)
  got less (52.30), a shallow one (50.60) 51.40. Words ("what would you need") left the counter at
  51.30 and moved the final (49.40 against 50.00). Distributors (P08, P18): anchor 0.787 of the
  quote got -8 to -10 % in 13 runs; the same sheets and claims gave 5.43 in one run and 5.57 in
  another (supplier-side noise of about 1 %); the order prices and the scorecard "do not change
  our calculation", the forecast is "taken into account" without a visible effect. → Open near
  0.8 of the quote in leverage cases (deeper buys nothing and costs patience), put the claims
  that count into round 1, and treat single-run differences under 2 % as noise.
- 2026-10-10 `arena` **After round 1 each supplier concedes a capped step per round and stops
  after a fixed number of counters.** D01: caps of about 1.6 %, 0.8 %, 0.6 %, 0.4 %, 0.2 % in
  rounds 2 to 6 (0.8 x our move below the cap), final offer in round 6 at the latest or right
  after a move of ours under 0.1 %. Donautal and Werdenfels: 3 counters (r2 +0.04 to +0.20, r3
  0 to +0.15), final in round 2 after a +1 % move, in round 3 after 30 % of the gap, in round 4
  after three 30 % moves (P08 `f9e9b6dc7ed8e47d`); a move of 55 % of the gap got a hold and a
  higher price (P08 `5d30fbf219bdc50a` 5.55 to 5.58, P18 `f038c7d05bfee4d6`). Leitner (P07):
  3 counters of 3.5 %, 2.2 %, 1.1 %, final in round 3 in all 5 runs. Nordmark (P02): 4 counters
  of 0.93, 0.88, 0.30, 0.07 EUR at a cumulative gap of only 0.03, its reason "as you cannot
  commit to a binding higher volume, our flexibility is exhausted". Kalwisz (P11): three steps
  of 0.50 then holds at 45.50 "for 300 ppm and 0 chargeback" (it priced 300 ppm at +0.50 over
  1500 ppm, `587fe8dcbf9f6c9c`). Ravensteiner (P10): 2 counters. → The round count, not the
  gap, ends most threads: make every round count, move 25 to 35 % of the gap, never under 1 %
  and never over 50 %.
- 2026-10-10 `rules` **What C_best is made of** (price at which a term combination reaches
  C_best, relationship charge 0): P08 5.10 fixed at 90 days, 24 or 36 months (5.06 with the 5 %
  deadband clause, about 4.94 with the 0 % clause); P18 4.73 fixed (4.69 at 5 % deadband); P02
  368.34 at 90 days without a clause; P11 43.91 with chargeback 500 (43.77 at 300 ppm, 0); P10
  28.21 at 23400 units, 24 months, 42 days (27.50 at 56 days); P07 5.03 at 90 days. The records
  on `/v1/live` decode to P08 5.35 fixed or 5.30 at a 5 % deadband or 5.21 at 0 % (ours: 5.35 at
  0 %), P18 5.23 fixed or 5.07 at 0 % (ours 5.30 at 0 %), P02 about 369.5 (ours 371.88), P11
  about 44.9 (ours 45.50). Donautal priced the 5 % deadband at +0.12 on 5.45, exactly our cost
  of the clause at the case's +6 % path, so the clause type is no arbitrage: the gap is price.
- 2026-10-10 `arena` **The asks the bots repeat** (829 supplier e-mails): "Which volume can you
  commit to?" 152, "A binding higher volume would help us" 62, faster payment 69 (Kalwisz five
  times in one thread, then "you just ignore it" and a final offer), proof of the forecast or
  "Which figures is that based on? Please send us the data." 30. A volume confirmation in words
  registered: "We appreciate the confirmation of the full volume commitment, which allows us to
  review our pricing" (D02 `7e0d70250aee7673`), "please provide the binding volume figures so we
  can properly account for this" (D01 `101f032a24f98a58`). → `buyer/reader.py` reads the asks;
  the e-mail states the binding volume with the figure, answers a fixed payment term plainly and
  attaches the forecast rows when proof is asked (v8, effect to be measured).

- 2026-10-10 `arena` **Pushing past a final offer ends the case.** D01: one more sheet 0.1 below
  its final 49.70 and the foundry walked away, no deal (sandbox `212404b7930bfc68`, "we have
  reached the absolute limit"). → Accept a final offer that passes the gate; never push it.

- 2026-10-10 `arena` **How it concedes (D01, controlled runs, sandbox):** a constant sheet gets
  no concession and a final offer in round 4 (`d2afbf478253fa57`); each round it concedes about
  min(0.8 x our move, a cap that shrinks by round: 0.5, 0.3, 0.2, 0.2, 0.1); a very low anchor
  (37.03) costs patience and ends higher (50.40). Round 1 counters were the same for anchors 44
  to 47 (51.30). → Most of the movement comes from round-1 claims and terms; later rounds add a
  few percent while our moves are large enough.
- 2026-10-10 `arena` **A large first concession means a deep floor** (job shops: Dralveck 36.00
  to 30.50, Fuchsreiter 38.50 to 31.50 in P05; DEMO-J1 17.10 to 14.99 in D02). Meeting them with
  30 % of the gap triggered agreement at our sheet in round 2; holding low got D02 from 0.48 to
  0.63.
- 2026-10-10 `arena` **Timeouts:** a late message counts as a round and as "no move" ("Without
  movement from your side we cannot move either", P05 v2). Once a job shop answered a timeout
  with a lower price (DEMO-J1, "sharpened my pencil"), but a deliberate timeout on D01 gave
  nothing (0.983 against 0.988). P10 v1: a crash after its final offer let the clock run out and
  Ravensteiner withdrew.
- 2026-10-10 `arena` **Walk-away without a final offer:** Nordmark (P02 v1, `b85685a51d797c60`)
  withdrew in round 4 when our sheets sat 2 to 7 % below its counter, below its full cost; back
  office "My call: final_offer ... we withdraw". With small gaps (v2 on) it gives a final offer
  at about 372 in round 4 instead.

- 2026-10-10 `arena` **Deterministic.** Nine D01 sandbox runs with identical sheets gave
  identical prices (52.90, 52.00, 51.50, then `final_offer` 51.50); replays of P04 and P11
  matched round for round. Only the wording varies. → Repeats measure wording, not behaviour;
  the "stochastic bots" caveat in the PR #7 sandbox comparison does not apply.
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

- 2026-10-10 `arena` **Which claims a supplier takes into account** (practice v1 to v6, claim
  results and reasons):

  | Claim | Taken into account | No effect or irrelevant |
  |---|---|---|
  | volume forecast `fc:` | every supplier tried | a second `fc:` ID: "already taken into account" |
  | should-cost `cost:` | D01, D02 J1, P01, P05 Fuchsreiter, P10 | above its price (never cite) |
  | falling cost-driver index | P01, P05, P11 ("we did not know that") | an index outside its drivers, ECB currency rates: irrelevant |
  | notice period `doc:` + `ctr:` | D01, P01 | |
  | delivery or quality record `sc:` | D01, P01, P05, P11 | P07, P08, P18 ("does not change our calculation") |
  | rival offer `offer:` (RFQ) | P05, D02 (every round, new offer ID) | D02 C1 "does not change our calculation" at times |
  | our order prices `po:` | D01 | P02, P03, P04, P08, P18 |
  | its own older quote outside the case refs | | irrelevant ("does not concern this part or our company") |
  | another supplier's order prices | | irrelevant |

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

## Agent experiments

- 2026-10-10 `rules` **v8 (robustness and the reader), no quota spent.** All 21 case files
  (the nine never hosted included) and both sandbox cases play through `arena-sim` with the
  agent and no guarded error (`tests/test_cases.py`). New: every move and setup is guarded (a
  failed move resends our last sheet, a third failure closes the thread on the best standing
  sheet), the final's poll loop never raises and a crashed case is resumed once with its path
  rebuilt from the thread (`Negotiator.restore`), the Sunday release's letters and news reach the
  persona profile through the kit's `ids` and `document`, supplier e-mails are scanned for the
  same traits, quotes and orders priced per 100 or 1000 are compared per piece and cited as
  recorded, an unknown Incoterm or a scorecard without a quarter no longer breaks a move, the
  cost-breakdown question (answered "we do not share" 12 of 12 times) is gone.

- 2026-10-10 `arena` **The price engine (branch `steffen/price-engine`), practice v1 to v6** (47
  sessions): v1 (terms by C, goal anchors, 30 % path, claims) took the mean of best scores from
  0.32 to 0.66; v2 to v6 added mirroring alternatives, overtime valuation, the RFQ scheduler,
  rival offers every round and a model-written paragraph (0.73). What did not help: a patience
  budget for every supplier (P08, P18 fell), a milder anchor for suppliers with a pricing
  committee (P07, P18 fell), currency claims (irrelevant), switching a required index clause to
  a 5 % deadband (refused). Run logs `logs/practice-v1.log` to `-v6.log`, decisions per move in
  `logs/runs/`.

- 2026-10-10 `arena` **Julian's draft two** (`origin/julian/draft-two`, design in `design.md`)
  on the sandbox: D01 0.73 → 0.93 → 0.96, D02 0.37 → 0.54 over five runs. What moved it: a floor
  at the case's `sustainable_margin_pct` instead of a flat 8 % (D01 0.84 → 0.96); the first
  model-proposed stance was more cautious than the constants (D02 0.32) until calibrated; holding
  one more round while the supplier still moves; among equal-C options, the one the supplier
  prefers (35 days' lead time instead of 21, which the job shop priced as overtime). Latency
  11 to 19 s per move (reader plus writer, `claude-opus-5-5` at low effort), stance call 9 to 11 s
  once per case. Cheaper variants need engineering approval and never became a binding sheet.
  Every score above matches a session in `uv run buyer pull --set sandbox`.
- 2026-10-10 `arena` **Opening 20 % below beat 30 %** on the sandbox with a guarded, cost-ranked
  `NaiveAgent` (PR #7): D01 0.93 against 0.86, D02 0.38 against 0.30 (one run each, matched
  in the pulled sandbox sessions).
- 2026-10-10 `rules` **The kit's `NaiveAgent` accepts bad deals** on the local simulator: 32 of 152
  agreements broke a must-have, 28 cost more than the alternative. Adding the `must_haves_ok` and
  C_alt guards removed both. Adaptive concessions (by supplier movement and messages left) beat
  fixed halving; switching the anchor by supplier risk added nothing, and no credit, equity or
  scorecard measure predicted when 30 % beats 20 % (PR #7, commit `ad2e0b6`). The simulator
  ignores documents and persona, so these results check mechanics, not persuasion.
- 2026-10-10 `arena` A quote PDF without a separate standard-terms section left the reference
  payment term empty and broke a D01 run (PR #7). → Fall back to the quote's explicit terms.

## Data package

- 2026-10-10 `data` Size: 447 suppliers, 46 with a detailed profile (`supplier_intel`), 60 parts,
  33 index series (2021-01 to 2026-09), 300 negotiation events, 1,033 quality notifications.
- 2026-10-10 `data` Owner types of the 46 profiled suppliers, with the brief's persona: family 22
  (about 140 staff, "remembers how you treated it"), group 9 (about 1,300 staff, best credit,
  "an approval ladder"), founder 9 (about 30 staff, weakest credit, "needs cash and work"),
  private 6 (about 300 staff). Lower credit index is better: group 164, founder 251 on average.

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
- 2026-10-10 `rules` Our writer (`buyer/llm.py`) posts to an OpenAI-compatible chat completions
  endpoint: `LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY`, `LLM_EFFORT` (not `OPENAI_API_KEY`,
  `LLM_PROVIDER` is not read); without `LLM_MODEL` the e-mails use the template. `gpt-6-luna` answered a short call in 2.0 s and wrote three move suggestions in
  12 s. Tacto: their house agent runs on a small, cheap model, and reading the data beats a
  bigger model.
- 2026-10-10 `rules` In an RFQ every thread's 60-second clock runs while we work on another.
  A waiting thread needs a message, e.g. a short question about validity, or it collects
  timeouts; our probe kept waiting threads alive this way (D02, P05).
- 2026-10-10 `rules` `arena-sim` plays a scripted supplier: good for plumbing and timing, not
  for tactics.

## Hypotheses (untested in the arena)

- Records on P02 (0.85) and P08 (0.73) come from a lower round-1 counter, not from later rounds:
  our later rounds converge to the same price whatever the gap (P02 371.9 in v4 to v6).
- Three sheets of equal C for us in round 1 reveal what each lever is worth to the supplier
  (payment, lead time, ppm) and could lift P10 and P11.
- The close response of a final case carries `c_best`; calibrating anchors between waves from it
  is possible but needs a rules check first.
- Persona-specific wording beyond the generic paragraph (cash need, partnership 2022, reference
  customer) moves the round-1 counter.
- Prices fall much further when every sheet stays below the supplier's price and concessions
  are slow (house agent 0.75 on P08, ours 0.11 after agreeing in round 2).
- Cash-short suppliers give more price for 14 to 30 days payment than the 0.67 % per 30 days it
  costs us.
- Citing the best rival offer moves RFQ bidders; our probe never cited offers.
- Suppliers with "approval above 2 %" notes move at most 2 % per round.
- Stale-costing suppliers concede after a verified falling-index claim; hedged suppliers answer
  index claims with "not our reality" until the hedge ends.
- The cost floor is full cost; the five that once sold below full cost may go lower.
- A faster payment package beats a deeper price anchor for cash-short suppliers; test 20 / 30 %
  openings against standard / early payment as a 2x2, several runs per credit stratum.
- A `selective` rebuttal (naming the cost driver the supplier left out of its letter) moves more
  than a plain index claim.
