# Learnings

Observations from the arena and the data package, with evidence. An entry says what happened and
how often, not what to do; what the agent does is in `design.md`. Most entries rest on one to
three sessions with one supplier. The sandbox bots are deterministic per sheet path; the practice
suppliers vary 1 to 2 % between runs with the same sheets. Sessions: `exports/` (schema in
`exports/README.md`), `logs/sessions/`, `logs/runs/`. Tags: `arena` seen in a session, `data` from
the package, `rules` from `docs/api.md` or the kit.

## Where we stand (Saturday night)

Mean of best scores 0.776, rank 3 of 24 on the practice board (first 0.838); the last ten-case
validation run of one code version averaged 0.727. Record = best of all teams on `/v1/live`,
house agent in brackets; records average 0.84.

| Case | Goal | Ours | Deal | Record (house) |
|---|---|---|---|---|
| P01 | stabilise | 0.974 | 130.18, Nov, 14 d | 0.995 (0.966) |
| P02 | stabilise | 0.735 | 361.67, 90 d, CU clause 5 % deadband | 0.847 (0.740) |
| P03 | stabilise | 0.923 | 432.15, 90 d, 24 m | 0.936 (0.925) |
| P04 | routine | 0.860 | 4.94, 90 d, 36 m | 0.874 (0.860) |
| P05 | leverage RFQ | 0.828 | Dralveck 27.86, 14 d, 35 d | 0.824 (0.555) |
| P07 | routine | 0.751 | 5.35, 45 d, 36 m | 0.779 (0.782) |
| P08 | leverage | 0.670 | 5.26, AS-14404 clause | 0.916 (0.752) |
| P10 | secure_supply | 0.679 | 31.50, 56 d, 36 m | 0.702 (0.686) |
| P11 | quality_first | 0.710 | 45.50, 300 ppm | 0.807 (0.314) |
| P18 | leverage | 0.688 | 5.00, AS-14404 clause | 0.677 (0.386) |

Records decode to about P08 5.21 to 5.35 depending on the clause, P02 369.5, P11 44.9. How those
teams got there is unknown. C_best decodes to P08 5.10 fixed (4.94 with a 0 % clause), P18 4.73,
P02 368.34 at 90 days, P11 43.91 with chargeback 500, P10 28.21 at 42 days, P07 5.03, P04 4.93
against a frozen 4.94.

## Cost (`rules`)

- The category goal sets the rates: fallback risk leverage 3 %, routine 5 %, quality_first 8 %,
  stabilise 10 %, secure_supply 25 %; a relationship charge only in stabilise (sustainable margin
  0.5 to 8 %) and secure_supply (4 to 10 %). The charge grows with the square of the first 5
  missing margin points, so C has a minimum below the sustainable margin (D01: 2 points below its
  4 %). It also moves with payment terms (P02: 5,483 at 368.70 and 90 days, 901 at 366.41 and
  14 days).
- Uncovered need costs `fallback_unit_price` plus the risk rate; coverage is
  `min(volume, need) x min(months / 12, horizon)`. Volume above the need is bought anyway; months
  beyond the horizon neither cost nor earn.
- Index clause: `spend x material_share x (|path| - deadband)`, signed like `index_paths`, plus
  `index_risk_pct` of `spend x material_share` whenever a clause exists. A higher price with a
  clause can cost less in C than a lower fixed price: P18 5.40 at a 5 % deadband 259,116.84
  against 5.30 at 0 % 259,970.83 (`9b63768bad5febe5`).
- Late delivery: `late_cost_per_day x days beyond need_lead_time_days`. Must-haves can cap the
  lead time (P05: 42 days).
- Effective date: units before it cost the current price (D01 at 50.90: April instead of
  December start, 0.73 to 0.81; plus 60-day payment, 0.87). Our money: 8 %/yr, reference 60 days;
  30 days earlier costs 0.67 % of spend.
- Every session returns C_best and our cost breakdown with the supplier's true numbers; a
  relationship charge reveals its full cost. D01: at most 48.9. Nordmark: C at 358.00 (2,251,140)
  and at 361.67 (2,248,062) with the same clause and payment give its cost of money as about 0
  and its full cost as about 371.7, so C has its minimum near 361 for that structure; the record
  0.847 has a structure these two points do not explain.
- No alternative, so a walk-away scores 0: D01, P05, P06, P10, P14, P17. Contract length or volume
  is ours to pick in 14 of 21 cases. Only a standing sheet can be accepted (an alternative
  returns 422); a better alternative sent back as our sheet became standing (P10).
- The kit's `complete_offer` snaps values and can replace an explicit allowed `None` with the
  first option (`economics.quoted_offer` keeps a quoted package as quoted).

## Supplier behaviour (`arena`)

- **Round 1, D01 (sandbox foundry, 30 runs, quote 52.90):** anchors 44.0 to 48.5 without claims
  all got 51.30; should-cost claim alone 51.00, order prices alone 50.30, notice or scorecard
  alone 51.30, all three 50.00, the same three at anchor 48.88 50.40; anchor 37.03 got 52.30,
  50.60 got 51.40.
- **Round 1, distributors P08 and P18 (15 runs):** anchors 0.787 and 0.85 of the quote both got
  5.45 and 5.50; the same sheets gave 5.43 in one run and 5.57 in another. Falling-driver claims in
  round 1 (v10, 2 runs each): 5.40 and 5.30, and four counters instead of three. Hedge letter out
  of round 1: 5.52 (1 run). The forecast claim in place of the order prices next to the index:
  the same path 5.30, 5.20, 5.10 (1 run). A 5 % deadband clause sheet in round 1 got a first
  counter 1.5 to 2 % above the 0 % clause they add themselves (P08 5.60 to 5.64, P18 5.50; six
  runs on `steffen/elicit`).
- **Job shops in RFQs** dropped 12 to 15 % on their first counter (Dralveck 36.00 to 30.0 or
  30.5, Fuchsreiter 38.50 to 31.50, DEMO-J1 17.10 to 14.99). An anchor above a bidder's quote was
  agreed at once (P05 first run, 0.01). Dralveck agreed at our second sheet in every run: at a
  held anchor 27.86 (0.828) and 27.92 (0.822), at 28.03 to 28.07 after an 8 % step toward it
  (0.806 to 0.81). A 3 % deeper anchor (26.79) got a lower first counter (30.0), one more
  concession to 28.0 after the hold ("you only moved a few cents, but I want to keep our machines
  running"), then a walk-away at a cumulative gap of 39 % (`practice-v12-P05.log`, 0.746 on
  Fuchsreiter).
- **Later rounds.** D01: concessions of about min(0.8 x our move, 1.6 %, 0.8 %, 0.6 %, 0.4 %,
  0.2 % by round), final in round 6 at the latest or after a move of ours under 0.1 %; a constant
  sheet got no concession and a final in round 4. Donautal and Werdenfels: counters of +0.04 to
  +0.20; final in round 2 after a +1 % move, round 3 after a 30 % move, round 4 after three 30 %
  moves; a 55 % move got a hold and a higher price (5.55 to 5.58); 40 % got the same 0.10 as 30 %
  (2 runs); a slow walk of 12 % of the gap per round got five counters and 5.31 against four and
  5.33 to 5.39 (`50502ff781d898c6`). Leitner: 3.5 %, 2.2 %, 1.1 %, final in round 3 (5 of 5).
  Nordmark: 0.93, 0.88, 0.30, 0.07 EUR, "as you cannot commit to a binding higher volume, our
  flexibility is exhausted". Kalwisz: three steps of 0.50, then 45.50 at 300 ppm and at 800 ppm
  (`1f36a83c6e80e818`, `a74b89173c96c23c`); 300 ppm priced +0.50 over 1500. Ravensteiner: 2
  counters.
- **Counters per supplier over 115 practice threads:** Nordmark 1 to 6, Donautal 2 to 6,
  Werdenfels 2 to 6, Kalwisz 4 to 6. Its move as a share of our previous move (median, rounds 3
  on): Brandlhuber 0.62, Donautal 0.44, Werdenfels 0.45, Leitner 0.36, Nordmark 0.15, Kalwisz
  0.0, Selvbrunn and Wälzlager 0.0.
- **Cumulative gap at the final** (sum over rounds of our distance to its counter, relative):
  36 to 42 % (D01, P07, P08, P18); Nordmark walked at 19 % with sheets 2 to 7 % below its counter
  (P02 v1), Ravensteiner finalled in round 1 at 15 % (P10 v1). D01 walked after one sheet 0.1
  below its final ("absolute limit"). Nordmark, from an anchor of 345 with its clause: 351.05,
  349.85, 349.35, 349.05, then withdrew (`ea485d8c4db527aa`, 0).
- **`agreed` freezes the price:** after it, claims and pushes got "Our agreed offer stands"
  (16 of 19 early threads); P02 moved 0.7 % for 14-day payment once; a sheet above an agreed
  price closed at the higher price (P10).
- **Words, D01, identical sheets, 1 run each:** plain 50.00, "firm" 49.90, warm and acknowledging
  its wage costs 49.60, "What would you need from us to move further?" 49.40. The same question
  every round on practice got "volume!" where volume was fixed, then no movement (P05, P18).
  Bluff and urgency on an unchanged sheet: same price, "built on mutual reliability, not on
  pressure" (3 runs each). Content-free "we need a better price" e-mails still got 52.90, 51.90,
  51.40, 51.10, 50.90. A fully model-written e-mail (figures and IDs guarded, `steffen/elicit`
  `086acb8`, 2 runs each): P02 0.733 and P18 0.630 to the cent as the template, P11 45.50, P08
  0.60 and 0.57 against 0.56 (spread of identical runs 0.47 to 0.67).
- **Asks** (829 supplier e-mails): "Which volume can you commit to?" 152, "A binding higher
  volume would help us" 62, faster payment 69 (Kalwisz five times, then "you just ignore it" and a
  final), proof of the forecast 30. Answering them in words registered ("allows us to review our
  pricing", "we have factored your confirmed volume") with prices inside the usual spread (v8,
  P02, P11). Kalwisz read our payment history: "we often see late payments".
- **Reply delay and shop size** (125 sessions): 4 to 5 days and no validity: founder-run job
  shops, conceded up to 22 %; 2 to 3 days: family firms, 1.6 to 13 %; 1 to 2 days: groups, 0 to
  12 %.
- **Several sheets:** the supplier picks one and answers it (D02, P03, P08). Offered a fixed sheet
  and a clause sheet in one message, Nordmark picked the clause (`91d2b5ad7501ce55`).
- **Timeouts** count as a round and "no move"; DEMO-J1 once answered one with a lower price; a
  deliberate one on D01 gave nothing (1 run). A crash after a final offer let the clock run out
  and Ravensteiner withdrew; a session does not pause while our process is down. Supplier
  replies take 19 s median, 28 s p90 (121 moves); our writer 1.8 s median, 6.3 s max; with N
  bidders a thread waits about (N - 1) x 21 s between our messages (3 bidders: 44 s, 66 s at p90;
  P05 had one late move).
- **Payment days at the supplier's own rate:** distributors 0 (free), Selvbrunn about 4 %/yr,
  Nordmark 6 % (about 0 by its cost breakdown), Wälzlager 7 %, Leitner 8.5 %, Hrvelec 12 to 17 %
  (45 to 90 days +1.5 to 2.1 %).
- **Contract length and clauses:** P03, P04, P07, P10 took 24 months at their price; in P10 it
  unlocked the full volume. Distributors refused 24 months fixed ("cannot maintain a fixed price
  for a 24-month term") and every deadband, offering an AS-14404 clause instead. Keeping our fixed
  sheet while they countered with their clause: P18 closed at 5.00 with the clause (0.688,
  `e86f454a59ff98f0`) against 5.10 in four sessions that took it (0.621); P08 5.25 (0.659,
  `22f82a186bc4fb08`) against 5.30 to 5.38 (one session each). Nordmark's copper clause alone
  cost 1.8 % of spend (0, 2 runs); with a 5 % deadband at 358.00 it agreed at once, 4.3 % below
  its fixed 374.06, the clause costing us 0.8 % of spend; the round-1 clause menu on
  `steffen/elicit` reached 362.02 in round 1 (0.733, 3 runs). Donautal priced a 5 % deadband at
  +0.12 on 5.45, equal to our cost at the case's +6 % path; a clause in round 1, two clause
  sheets, a fixed 24-month ask at 5.35 and a forecast statement all ended 5.36 to 5.39. Fit
  across all clauses seen: the supplier values a clause at `material_share x (driver's 12-month
  change - deadband)` (Nordmark 8.5 %, distributors 0.4 to 2.7 %); by that fit P14 would gain 21 %
  and P16 2 % (unplayed; P14's supplier says its material is bought forward).
- **Price-frozen suppliers** refused every trade for price (P03: 36 months, 14-day payment, 20 %
  more volume; P04 likewise), "we can talk about the terms instead".
- **Full suppliers charge for speed:** Hrvelec 31.50 at 52 days, 33.00 at 42, 34.50 at 35;
  Ravensteiner 32.00 at 56, 35.00 at 35.
- **Quality:** chargeback 500 offered to Kalwisz twice (next to 300 ppm at the same price, then
  at its own price) got 300 ppm and 0 chargeback both times; at its scorecard rate of about 2400
  ppm the chargeback would cost it 1.19 per unit against the 0.50 it charges for 300 ppm.
  Chargeback 500 at 1500 or 2500 ppm and 45.00 would score 0.816.
- No cost breakdown from any of 12 suppliers (12 of 12 "we do not share"); schedules and an 8D
  report came on request; the D02 sandbox shop sent a breakdown. Suppliers cite their own rising
  indices in round 1 (D01 WAGES-METAL +3.1 % as 28 % of cost; P02, P08, P18).
- **RFQ:** one call per session at a time, each thread's 60 s clock runs from its reply; a
  waiting thread needs a message or it collects timeouts. The cheapest rival offer was verified
  as a claim for every other bidder every round (P05 0.83, D02 0.73).

## Claims (`arena`)

- Taken into account: forecast `fc:` (all), should-cost `cost:` (D01, D02 J1, P01, P05, P10),
  falling driver (P01, P05, P11 "we did not know that"), notice `doc:` + `ctr:` (D01, P01),
  scorecard `sc:` (D01, P01, P05, P11), rival `offer:` (P05, D02), order prices `po:` (D01).
  "Does not change our calculation": `sc:` and `po:` at P02, P03, P04, P07, P08, P18. Irrelevant:
  an index outside its drivers, currency rates, another supplier's prices, its own older quote.
- 57 claims in v1 to v6: 44 verified, 11 duplicate, 2 contradicted. Verified moved the price
  visibly once (P01 134.80 to 133.60). A rising index got "Your figures confirm our case".
- The arena checks an index over any two months up to 12 apart, ending within the last 12
  (AS-14404 +5.9 % over 12 months, -5.5 % from 2026-06; PPI-C2431 -2.3 % from June; PPI-D351
  -6.1 % from 2025-11).
- D01, same path, 1 run each: no claims 50.00, one claim 49.30 to 49.60, three spread over rounds
  48.90 (0.998), all at once 48.50 (0.969, relationship charge).
- "2,637" was read as 2.637 and `contradicted`. A data ID counts once per case in an RFQ; rival
  offers may go to every bidder.
- `data` P01: letter gives 51 days' notice (`doc:20260911-70110-P01`), contract requires 90
  (`ctr:4600070110` `#3.1`). Counters: power -43 % on 2022 (`news:20260912-30`), castings +1.8 %
  (`news:20260914-31`), forecast `fc:310010@2026-09` +10.1 %. The case file's alternative terms,
  not the quote, set C_alt (P01: lead time 70 against 56).

## Experiments, a log (`arena`)

- v14, no quota: every case file through setup on the sim; P14 and P17 hit rules with one supplier
  behind them (clause trade on a hedged supplier, near-cost branch without a relationship
  target). PR #18: a target refresh clipped by the opening quote sent a 344.50 closing proposal on
  P02 before any claim (`b3daba378f139d09`, relationship cost 115,657); a 0.2 % proximity rule
  closed P01 at 131.40 instead of 130.98 (`4f234bc3a5fee132`); adopting any cheaper counter
  worsened 225 of 576 simulator pairs. Ten-case validation run of that version: 0.727.
- v12 held anchor after a job shop's deep drop: P05 0.828. v11 clause trade: P02 0.735 (1 run).
  v10 falling-driver claims: P08 0.670, P18 0.621 (2 runs each). v8 and v9 (12 runs): first
  counters unchanged by anchor or claims, 40 % move = 30 % move, run-to-run spread 5.26 to 5.57 on
  P08. 24 practice runs since v8: the last mean gain above 0.01 came with v10.
- v8: all 21 case files play through `arena-sim`; the Live Final per-case path ran D01 through
  `RemoteTable` with a 480 s deadline (49.70, 0.988, 113 s).
- v1 to v6 (47 sessions): 0.32 to 0.66 to 0.73; no gain seen in one batch each from a patience
  budget for all, a milder anchor for committee suppliers, currency claims, a 5 % deadband on a
  required clause.
- Julian's draft two (sandbox): D01 0.73 to 0.96, D02 0.37 to 0.54; floor at the case's
  sustainable margin, one more round while it still moves, the supplier's favourite among equal-C
  options. 11 to 19 s per move with `claude-opus-5-5`.
- PR #7 (sandbox, 1 run each): opening 20 % below beat 30 %. The kit's `NaiveAgent` accepts
  must-have breaks and deals above the alternative without guards.

## Data package (`data`)

447 suppliers, 46 profiled (family 22, group 9, founder 9, private 6), 60 parts, 33 index series
to 2026-09, 300 negotiation events. 46 suppliers have documents, 31 news, 18 quote remarks; the
other 401 get the neutral profile (rate 7 %, no signals). Price letters overshoot the
index-weighted driver move (P01 +9.5 against +2.3 %, P13 +7.0 against +4.0, P17 +8.0 against
+5.5; P02 fair). Incumbents below should-cost: P17 -8.4 %, P02 -7.6 %, P01 -4.8 %. 225 renewals:
asked +1.4 %, settled -1.1 %, 82 % flat or lower. Second-source quotes 8 to 21 % above the
incumbent (DN 65 flange +1.9 %). We pay late (Saalach 19 days, Wälzhammer 16, Lindlbauer 13);
seven overdue letters. Cash discounts imply 37 to 56 %/yr for four suppliers. Should-cost exists
for P01, P02, P03, P09, P10, P14, P17, estimates for P05, P06. Five suppliers once sold below full
cost. Persona traits appear as one or two fixed phrases (`SIGNALS` in `buyer/personas.py`); seen
in the arena: `price_frozen` (no trade, P03, P04), `cash_need` (asked for faster payment, P05,
P11; took 14 days, P01), `capacity_full` (overtime for speed, P05, P10), `spare_capacity` ("free
capacity", P05), `stale_costing` (conceded after index and notice claims, P01), `open_book` (no
breakdown). Untested: `hedged`, `approval_2pct`, `partnership_2022`, `reference_customer`,
`deprioritising_us`, `complains_late_pay`. Structures only in unplayed case files: `tooling_eur`
negotiable and lead time at most 84 days (P06), chargeback in the alternative (P12), PPI-C241 in
a clause (P16), fixed payment in a quality case (P12), a 3-part bundle (P15), `incoterm` (D02).

## Practical (`rules`)

All 21 case files come free from `GET /v1/cases`; hosted for practice: P01 to P05, P07, P08, P10,
P11, P18. The Sunday release (`data/release-sunday/`) reaches the kit's ID index (`ids`,
`lookup`, `document`) and the persona texts, not SQLite: owner type, cash discount, quote
remarks, should-cost, order prices and cost drivers of a new supplier are invisible to SQL reads.
The writer posts to an OpenAI-compatible endpoint (`LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY`,
`LLM_EFFORT`); without a model the template is used. `arena-sim` is a scripted supplier:
plumbing and timing, not tactics.

## Open questions

- What lowers the round-1 counter? Records on P02 and P08 sit below any first counter we have
  seen; our later rounds converge to the same price whatever the gap.
- Several sheets of equal C in round 1, one lever each, to read what the supplier values.
- Persona-specific wording; D01 moved 1.2 % on words alone, the practice suppliers did not move
  on a fully model-written e-mail.
- A rebuttal naming the driver a price letter left out (P01, P13, P17 overshoot).
- Faster payment for cash-short suppliers against its 0.67 % per 30 days cost to us.
- Moves sized to the supplier's observed cap instead of a share of the gap.
- Clause variants the distributors never saw: a second driver, a cap, a shorter fixed period.
- What price-frozen suppliers give "on the terms instead".
- Timing inside the 60 s window; a pause gave nothing once and a lower price once.
- `c_best` in a final case's close response, if the rules allow using it between waves.
- Hedged, stale-costing and approval-ladder suppliers; the floor of those that sold below cost.
- With four or more bidders, which threads to keep alive.
