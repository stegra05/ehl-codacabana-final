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
| 2026-10-10 | sandbox | D01, D02 | Model-proposed stance (opening gap, capture, margin, steps) instead of the constants, clamped by tier | D01 0.84 (from 0.93), D02 0.32 (from 0.43): the model opened 7 % below the quote and left 5 % margin on top of the 14 % it estimated in the quote; the closer then accepted at 77 % of a shallow target while the supplier still moved | margin for a standard supplier clamped to 0 to 3 %; the prompt carries the concessions seen so far (10 to 25 % with rivals, 5 to 6 % for the strategic foundry); the closer waits a round while the supplier moves |
| 2026-10-10 | sandbox | D02 | Cost breakdown XLSX parsed into the full cost mid-case | full cost 14.53 on a 17.10 quote; floor 15.48 to 15.29, target lowered | keep; the floor on the breakdown is the real one |
| 2026-10-10 | sandbox | D02 | Calibrated stance prompt (concessions seen so far in it), standard margin clamped to 3 %, closer waits while the supplier moves | 0.54 (best so far): anchor 14.02, breakdown raised the floor to the real 14.33, rival cited three times and verified, final offer 14.50 after 5 rounds | keep |
| 2026-10-10 | sandbox | D01 | Same stance twice gave the same 0.84: the floor, not the model, bound the anchor; the persona's 8 % strategic margin sat above the case's 4 % sustainable margin | floor 50.60 on a 52.90 quote, the foundry agreed at once at 50.37 | the margin we leave is the case's sustainable margin (plus a small tier margin elsewhere); the draft-one tier margins are gone |
| 2026-10-10 | sandbox | D01 | Replay with the sustainable-margin floor and the calibrated stance | 0.96 (best so far): floor 48.49, anchor 48.60, three probe sheets, the foundry agreed at 49.65 in round 4 | keep |

## Open hypotheses (one per practice batch)

- A supplier that names cheaper variants (material grade, tolerance, lot size) is information for
  engineering, not a term; asking for a quote on it costs a round.
