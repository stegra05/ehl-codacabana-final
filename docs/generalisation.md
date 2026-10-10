# Generalisation to the Live Final

How well the agent on `steffen/price-engine` (commit `9182604`) should carry over to Sunday: new
suppliers, up to a third of cases mixing supplier and case types practice never showed, some
citing the 08:00 release. Research on Saturday 10 October, evening: the kit's code, all 21 case
files, `logs/runs/`, `exports/`, the data package, and our agent on `arena-sim`. No practice
quota spent. Same conventions as `learnings.md`: date, tag, finding, evidence, consequence.

## Verdict

The code runs on every case structure we know. Its tuning is in-sample and unmeasured beyond
the ten hosted cases. The biggest gaps for Sunday: new suppliers get a neutral profile because
the release's letters and news never reach the persona code; one exception loses a whole case
(or every later wave); four or more bidders time out.

| # | Risk | Damage | Fix | Effort |
|---|---|---|---|---|
| 1 | an exception in a move or the wave poll | a case at its alternative (0 in 6 of 21), or all later waves | catch per move, keep polling | small |
| 2 | release rows invisible to SQL; most suppliers without text | neutral profile for new suppliers | read release rows via the ID index; scan the supplier's e-mails | small to medium |
| 3 | 4 or more bidders | timeouts, lost patience, ended threads | stop sending to the worst bidders after round 1 | medium, a tactics decision |
| 4 | missed phrasings in `SIGNALS` | traits not detected | widen to word stems | small |
| 5 | `price_unit` ignored | wrong-direction rival or order-price claims | divide by `price_unit` | small |

## Findings

### Robustness

- 2026-10-10 `rules` **Every known case structure runs end to end.** All 21 public case files,
  including the nine never hosted (P06, P09, P12 to P17, P19), played through `arena-sim`
  in-process with our agent and the package, no model: no exception, 0 to 1 s per case. Covers
  bundles (P07 4 parts, P15 3), the 3-bidder RFQ, `tooling_eur` (P06) and up to 75 term
  combinations (P09). The sim's supplier is a fixed script, so this checks code paths, not
  tactics. → Worth a test in `tests/` that plays every case file from `GET /v1/cases` this way
  (load them into `Sim(cases, pkg.facts)`, strip the `hosted` key).
- 2026-10-10 `rules` **One exception loses a case.** `play_case` has no guard around
  `Negotiator.setup` or `move`. Fields a hidden case may lack crash it: a rival quote without
  `unit_price` (`claims.py` `rival_quote`), an index clause without `material_share`
  (`writer.py` `FIELDS`), a scorecard without `quarter` (`claims.py` `scorecard`), a month not in
  `YYYY-MM` (`months_back`). The session then sits until the wave cap, which scores the
  alternative (0 in D01, P05, P06, P10, P14, P17). → Catch per move; on error send our last
  sheet again with the template e-mail.
- 2026-10-10 `rules` **One error stops the final.** `runner.play_waves` re-raises any non-403
  `ArenaError` from the case-list poll, and a network error after the client's retries is not
  caught at all (`arena_kit/client.py` `_call`). Every later wave is then lost; no human may
  restart. → Catch everything in the poll loop, log, sleep, poll again; a crashed case resumes
  with `GET /v1/sessions/{sid}` (a second `POST` is a 409 naming the session).

### Timing

- 2026-10-10 `rules` **Four bidders or more time out.** The arena answers one call per session at
  a time (`arena_kit/client.py`: "a call may wait for another call on the same session first").
  Supplier replies took 19 s median, 28 s p90 (121 moves in `logs/runs/`); our writer 1.8 s
  median, 6.3 s max (73 calls, none failed, 7 dropped by the filter). A thread waits about
  (N - 1) x 21 s for its next message against a 60 s limit:

  | Bidders | Wait at median | Wait at p90 | Rounds per thread in 390 s |
  |---|---|---|---|
  | 2 | 23 s | 34 s | 9 / 6 |
  | 3 | 44 s | 66 s, late | 6 / 4 |
  | 4 | 65 s, late | late | 5 / 3 |

  P05 (3 bidders) had one late move in v5. No case file has more than 3 bidders, but hidden
  cases bring "new settings". → With 4 or more bidders, stop sending to the clearly worst ones
  after round 1; the writer's 20 s timeout matters little next to the supplier's reply time.

### Data and the Sunday release

- 2026-10-10 `rules` **The release reaches only part of the agent.** `DataPackage` finds
  `data/release-sunday/` next to the package, merges its `facts.json` (new IDs only) and puts its
  `data/*.csv` rows into the ID index for `lookup` and `ids`, never into SQLite
  (`arena_kit/data.py`, `_ids`). `personas.profile()`, `Negotiator.full_cost()` and the claims
  built from SQL (`po_lines`, `cost_drivers`, `documents`, `suppliers`) never see release rows,
  and document files resolve against the package root, not the release. Release IDs can still be
  cited. `design.md` says the release is "read at runtime"; that holds for `facts.json` only.
  → Read release rows through `pkg.ids(prefix)` / `pkg.lookup` (each row carries `root`) in
  `profile()` and the document claims. Check the CSV schema at 08:00.
- 2026-10-10 `data` **Most suppliers have no text.** Of 447 suppliers, 46 have documents, 31 news,
  18 quote remarks; the other 401 get the neutral profile (rate 7 %, no signals). A new supplier
  in the final is one of them or unknown to the package. → Its own e-mails and the release are
  the only persona source.
- 2026-10-10 `data` 15 of 108 quotes are priced per 100 (13) or per 1000 (2) pieces
  (`quotes.price_unit`). Rival-quote and order-history claims compare `unit_price` with the
  supplier's per-piece price without converting. → Divide by `price_unit` before comparing.
- 2026-10-10 `rules` **Structures only in unplayed cases** (case files): `tooling_eur` negotiable
  and lead time at most 84 days (P06), chargeback in the alternative (P12), index series PPI-C241
  in a clause (P16), fixed payment in a quality case (P12), a 3-part bundle (P15). Every case type
  and category goal appears in at least one hosted case. Only `incoterm` (D02) lies outside the
  fields the planner knows.

### Persona signals

- 2026-10-10 `data` **The patterns are not fitted to the practice suppliers**: the package's text
  is generated and its phrases recur, so all 10 suppliers of the unplayed cases get at least one
  trait. They miss other forms of the same phrases: "restructuring programme with its banks"
  (sup:70150), "negotiating with its banks" (sup:70280), "lowered its rating" (sup:70310),
  "bought their nickel and alloys forward" (sup:70730), "advertising free machine capacity"
  (sup:70250), "allocated in line with last year's call-offs" (sup:70410). "I cannot sign
  anything that lowers our margin now" (5 call notes) is a trait with no pattern. → Widen to word
  stems before the release adds new wording.
- 2026-10-10 `arena` **Supplier e-mails carry traits too:** 13 of 220 supplier e-mails in
  `exports/messages.jsonl` match `SIGNALS` (price_frozen sup:70530; spare_capacity sup:70210,
  70250, DEMO-J1; capacity_full sup:70240; cash_need sup:70210), including a sandbox supplier the
  package does not know. → Scanning each reply gives unknown suppliers a profile (untested in
  play).

### Tuning

- 2026-10-10 `arena` **Out-of-sample performance is unmeasured.** The 0.727 mean is in-sample:
  every constant was tuned on the same ten hosted cases and the other nine cannot be played.
  Runs of one case spread widely across v1 to v6 (P18 0.25 to 0.49 over seven runs, P08 0.40 to
  0.55), and with a model-written paragraph the wording changes per run while wording moves the
  price (`learnings.md`, takeaway 3). → Treat single-run moves below about 0.1 as noise.
- 2026-10-10 `rules` **Evidence behind each constant** in `buyer/policy.py` (from `git log -p`):

  | Constant | Cases behind it | Risk |
  |---|---|---|
  | `ANCHOR` leverage 0.78 | P05, P08 / P18 (one template) | medium |
  | `ANCHOR` routine 0.82 | P07 (P04 overridden by price_frozen) | medium to high |
  | `ANCHOR` quality_first 0.88 | P11 | medium |
  | `ANCHOR` stabilise 0.92, secure_supply 0.88 | none: always overridden in practice | high, untested |
  | `FRACTION` 0.3 | D01, D02, all hosted cases | low |
  | `DEEP` 0.06 | P05 (two job shops), D02 | medium |
  | price_frozen 0.95 | P03, P04 | low to medium |
  | capacity_full 0.93, budget 0.16, overtime 0.005 | P10, P05 sup:70240 | medium |
  | `near_cost` 0.97, budget 0.14 | P02 | high |

  → A hidden `stabilise` or `secure_supply` case with no override opens at an anchor never played.

## Sunday 08:00 checklist

1. `uv run arena data`; confirm `DataPackage("data/package").release` is not `None`.
2. List the release's `data/*.csv` and their columns; count supplier IDs new vs in the package.
3. Run every case file through `arena-sim` again with the release loaded.
