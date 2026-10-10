# Findings log

One row per batch. Caveat for every arena-sim row: its supplier concedes on a script, so scores there
measure plumbing, not tactics. Only sandbox and practice rows say anything about real suppliers.
Sandbox suppliers (`sup:DEMO-*`) live in their own data world: package IDs are unknown there.

| Date | Where | Cases | Observation or hypothesis | Result | Change |
|---|---|---|---|---|---|
| 2026-10-10 | sandbox | D01 | A package index claim (idx:LCI-C) cited to a demo supplier | `contradicted`: the demo world does not know package IDs; the case's own refs verified | A case whose refs the package does not know cites only its own facts and refs |
| 2026-10-10 | sandbox | D01 | Accepting as soon as the standing offer meets the target | 0.73 after 2 rounds, 8 rounds unused, supplier still moving | At the target, hold one more round while the supplier moves and rounds remain |
| 2026-10-10 | sandbox | D02 | Our sheets asked for 21 days' lead time though 35 costs us the same | the job shop priced overtime for the shorter lead time | Among equal-cost options, pick the value the supplier likes |
| 2026-10-10 | sandbox | D02 | Floor at 90 % of the quote without a should-cost clips the 12 % opening gap for standard suppliers | anchor 15.39 on a 17.10 quote; C_best was 27 % below C_open | Floor without should-cost = quote below the tier's opening gap plus 3 points |
| 2026-10-10 | sandbox | D02 | RFQ coordination: rival offer cited after the first reply, cheaper thread kept moving | `verified`; the dearer bidder (C1) did not move on it; deal with the cheaper (J1) at 0.37 | none yet: the gap to C_best is the price level, see the floor row |
| 2026-10-10 | sandbox | D01, D02 | Model latency with claude-opus-5-5 at low effort | reader plus writer 11 to 19 s per move | timeouts stay at 14 s reader, 16 s writer |
| 2026-10-10 | sandbox | D01 | Replay after the four changes above | 0.93 (from 0.73): all 3 claims verified, 4 rounds, deal at 49.90 on the supplier's final offer (from 50.90) | keep |
| 2026-10-10 | sandbox | D02 | Replay after the four changes above | 0.43 (from 0.37): lead time 35, deal at 15.00 EXW 14 days (from 15.30); C_best still 17 % lower, the floor without should-cost is the gap | parse the cost breakdown XLSX next |

## Open hypotheses (one per practice batch)

- The job shop in D02 attached a cost breakdown XLSX in round 1; parsing it into the full-cost
  estimate (policy 5, step 1) would set a real floor instead of a share of the quote.
- A supplier that names cheaper variants (material grade, tolerance, lot size) is information for
  engineering, not a term; asking for a quote on it costs a round.
