# Negotiation strategies: research for our buyer agent

Research report, 10 October 2026. Two inputs: (1) the literature on automated negotiation,
bargaining, procurement practice and LLM negotiators, gathered by ten parallel research agents;
(2) the 62 practice sessions logged by Saturday 21:00 (`logs/sessions/practice/`), read again to see which of those ideas
fit the arena's supplier bots. Each recommendation says what supports it and how to test it. Most
literature points were read from abstracts and summaries, not full papers: treat effect sizes as
directional (sources and confidence at the end).

## Summary

At the time of writing the price engine scored a mean of **0.73** over the ten hosted cases (best
run per case), with the gaps concentrated in P10 (0.68, 194k EUR from C_best), P08 (0.55, 79k),
P18 (0.49, 37k), P11 (0.71, 28k), P07 (0.75, 23k) and P02 (0.51, 23k). Since then: 0.776, with
P08 0.670, P18 0.621 and P02 0.735 (`learnings.md`, Where we stand).

What the traces show about the bots, in literature terms: a **behaviour-dependent conceder**
(Faratin, Sierra and Jennings' tactic family) that answers each of our steps with a smaller step
of its own, becomes a little more generous late, and ends the dance with `final_offer` once its
patience is used up. It ends the dance after 2 to 6 of our messages, so the 10-message limit
never binds. **The first counter decides most of the deal.**

Recommendations, ranked by expected gain against cost to build:

| # | Change | Why | Test |
|---|---|---|---|
| 1 | **Make round 1 count:** three equal-C sheets (MESO), the strongest claims, a precise anchor with a reason | the first counter holds 40 to 100 % of our final price cut; MESOs anchor harder and reveal priorities | sandbox D01/D02, then P07, P08, P18 |
| 2 | **Answer the supplier's stated need every message**, also when the term is fixed | P11 Kalwisz asked for faster payment five times ("you haven't addressed this at all"), then stopped at 45.50 | P11 replay |
| 3 | **Concede in currencies, not price:** hold one or two terms it values back from round 1 and spend one per round as our move | concessions are only answered after a move; logrolling moves price without paying price | sandbox, then P07 / P08 |
| 4 | **Spend patience in fewer, larger steps** | the bot gives back only 0.2 to 0.7 of each step and stops on a cumulative gap; many small steps burn patience without buying price | sweep `FRACTION` 0.3 / 0.5 / 0.7 on the sandbox (free) |
| 5 | **Expected-value acceptance after `final_offer`** | pushing after `final_offer` walked once (D01); the gain from one more step is small | not built: the agent always accepts a final offer that passes the gate |
| 6 | **Persona playbook** (table below): the right currency per supplier type | procurement practice and our persona signals agree | per case, one change per batch |
| 7 | **Writing rules for LLM counterparts:** warm, questions, reasons, trades, a story for the boss | largest LLM negotiation study: warmth and questions close deals, dominance causes impasses | wording only; check replies' back office |

What not to do: extreme anchors (walk-aways roughly triple), threats and dominance, bluffed
urgency or rivals, repeating an unchanged sheet, and anything that targets the bot's prompt
(prompt injection is an attack under the rules).

## 1. How the arena's suppliers concede

From the price paths of every logged thread (script logic: supplier price per reply, our price per
message, statuses). Values for the current engine's practice runs:

| Case | Supplier type | Anchor below quote | Its first move | Its step per our step (ρ) | Σ gap at `final_offer` | Deal below quote | Score |
|---|---|---|---|---|---|---|---|
| P07 | routine, family | 18 to 19 % | 2.6 to 3.5 % | 0.3 to 0.7 | 0.12 to 0.19 | 5.6 to 6.8 % | 0.73 to 0.75 |
| P08 | leverage, distributor | 21 % | 8 to 10 % | 0 to 1.0 | 0.09 to 0.23 | 7.3 to 11.6 % | 0.40 to 0.55 |
| P18 | leverage, distributor | 22 % (7 % once) | 7 to 10 % | 0 to 0.9 | 0.09 to 0.14 | 8.2 to 13.1 % | 0.25 to 0.49 |
| P01 | stabilise, price increase | 9 % | 2.4 to 3.5 % | 0.4 to 0.9, then 2 | 0.08 to 0.10 | 5.2 to 6.0 % | 0.90 to 0.97 |
| P11 | quality first, cash short | 12 % | 0 to 2 % | 0.3 to 0.6, then 0 | 0.15 to 0.18 | 3.2 % | 0.71 |
| P10 | secure supply, fully booked | 7 % | 1.6 % | 0.1 to 0.2 | 0.015 | 1.9 to 2.2 % | 0.67 to 0.68 |
| P02 | stabilise, near cost | 5 % (7 % walked) | -0.7 % | 0.05 to 0.4 | 0.03 | about 0 % | 0.46 to 0.51 |
| P03, P04 | price frozen | 4 % | 0.4 to 1.4 % | 0 | 0.04 to 0.06 | 0.4 to 1.4 % | 0.86 to 0.92 |

Findings:

1. **The first counter carries the deal.** In P08 and P18 its first counter already holds 75 to
   100 % of the final cut, in P07 and P01 about half. Later rounds add 0 to 4 points of the quote.
2. **It answers our steps at ρ < 1.** If we close the gap fully, the deal lands at
   `c1 - ρ / (1 + ρ) * (c1 - anchor)`: with ρ = 0.4 at 71 % of the way from our anchor to its first
   counter. Observed: 73 to 90 %, because `final_offer` usually comes before the gap closes.
3. **ρ grows late** (D01: 0.2 early, 1 to 2 in the last rounds), the time-dependent part of the
   tactic. `final_offer` cuts this off before we reach it.
4. **`final_offer` arrives early:** after 2 to 6 of our messages, at a cumulative gap of 0.09 to
   0.23 of its price (0.015 for the fully booked P10). The round limit never binds. The traces
   cannot yet separate a patience budget from a floor that our claims move (the same supplier
   stopped at 5.35 to 5.61 in P08 depending on our path, which points to patience).
5. **A shallow anchor gives a shallow first counter:** P18 opened at 7 % below and got 6.6 %, the
   worst run (0.25); at 22 % below it got 8 to 10 %.
6. **Pushing past `final_offer` risks the deal:** D01 walked away after one more sheet below its
   final (`D01_212404b7930bfc68`).

Consequences: the literature's default against unknown opponents (Boulware, hold early, concede
late) assumes the opponent keeps playing to the deadline. Ours does not, so its advice inverts:
win in round 1, then close the gap in few, deliberate steps before patience runs out.

## 2. Opening and anchoring

**Research.** The first offer anchors the settlement (Galinsky and Mussweiler 2001; NegotiationArena
found opening offers correlate with final prices, rho about 0.72, for LLM agents too). Precise
numbers anchor harder than round ones and signal preparation (Mason et al. 2013; Loschelder et al.
2017). Extreme offers backfire: 30 % walk-aways after an extreme opening against 11 % after a
moderate one (Schweinsberg et al. 2012), confirmed in a 2018 replication. The anchor loses power
when the recipient focuses on its own alternatives and target (Galinsky and Mussweiler).

**For us.**
- Keep the goal-based anchors (`ANCHOR` in `buyer/policy.py`: 0.78 leverage to 0.92 stabilise);
  they sit at the edge the research and our 20 vs 30 % sandbox test agree on. Never above 25 %
  below the quote.
- Make the anchor precise (4.76, not 4.75) and give it one reason the supplier can check: its own
  past price, a falling driver, a rival offer. Already true for the figures; keep the reason next
  to the price in the e-mail.
- Do not open shallow out of politeness: P18 at 7 % below was the worst run.

## 3. Multi-issue offers: MESOs and logrolling

**Research.** Multiple equivalent simultaneous offers (Leonardelli, Gu, McRuer, Medvec and
Galinsky 2019, six experiments) give stronger anchors, better outcomes for the offerer, more joint
gain and a friendlier relationship than one package; recipients read them as sincere. Guidance:
three offers, equal value to us, different mixes, all at or better than our target; the choice
reveals the counterpart's priorities. Automated negotiation does the same on iso-utility curves:
offer packages of equal own value and pick the one closest to the opponent's last offer (Faratin,
Sierra and Jennings 2002; Lai and Sycara). Package deals ("nothing agreed until everything is
agreed") turn a price fight into trades.

**For us.** The arena allows three sheets per message and the bot picks one and answers it
(`learnings.md`). Today we send one sheet per message.

- **Round 1: three sheets of equal C**, each at the anchor's C, varying the terms where the
  supplier's value differs from ours: payment days (its cost of money), contract length, lead
  time, ppm headroom, start date. `eco.plan_terms` already ranks term sets; take the best three
  distinct ones and set each price so C is equal.
- **Read the pick:** the chosen sheet tells us its priority; carry those terms forward (`adopt`
  already takes over terms from its counters).
- **Later rounds:** one sheet is enough unless a new lever opened. A second sheet that trades a
  term for price on its preferred axis is cheap information.
- Hold the walk-away and must-haves on every sheet: three sheets mean three chances for it to
  agree, so each one must be a deal we want (an `agreed` freezes the price).

## 4. Conceding: currency, size and pace

**Research.** ANAC winners pair a tough bidding curve with an opponent model and a lenient
acceptance near the deadline (Baarslag et al.; Fawkes 2013; Agent K 2010 extrapolates the opponent
from the mean and spread of its offers). Shrinking concessions make the counterpart expect a limit
and counter less ambitiously (Tey, Schaerer, Madan and Swaab 2021, seven studies). Deadline
research: agreements cluster at the deadline (Roth, Murnighan and Schoumaker 1988), but here the
supplier's own patience is the effective deadline. Procurement practice: never give a concession
without asking for something specific in return.

**For us.**
- **Concede in currencies the supplier values and we do not.** The bot gives nothing without a
  move from us; a move need not be price. Candidates by case, priced with `total_cost` and its
  `supplier_value`: a 24-month term where it is free to us (P03, P04, P07, P10), forecast and
  volume statements, ppm headroom below the must-have (P11: 300 ppm costs us about 7 EUR per ppm
  point a year; 1000 ppm would cost about 0.31 EUR per unit, which the supplier may value more),
  a later start where we are indifferent, faster payment only for suppliers whose rate exceeds
  our 8 %. Today `plan_terms` gives all of these in round 1. Hold back one or two and release
  one per round as the move, with the price step smaller or zero. Hypothesis: same final price
  with less patience spent.
- **Fewer, larger price steps.** With ρ between 0.2 and 0.7 and a cumulative-gap stop, our
  `FRACTION = 0.3` closes the gap slowly and pays patience for every open round. Sweep 0.3 / 0.5 /
  0.7 on the sandbox, which costs no quota.
- **Shrink our steps visibly** (Tey et al.): the supplier reads them as our limit. Our steps
  already shrink; keep it, and say in words which step is the last.
- **Never move on a round where it did not move**, except with a currency (holding is free; an
  unchanged sheet is "My call: hold" for both sides).

## 5. Acceptance and the end of a thread

**Research.** The standard rule is AC_next: accept when its offer is at least as good as what we
would send next (most common in ANAC, Baarslag et al.); winners add a time rule that relaxes near
the deadline. Bargaining theory gives the expected-value form: accept now when
`C_now <= (1 - p) * E[C_next] + p * C_alt`, with p the chance the next push ends the thread.

**For us.**
- AC_next is in place (`theirs <= ours[-1]` accepts). Keep it.
- After `final_offer`, p is high (one walk in our pushes so far) and the expected gain of one more
  step is small (0 to 1 % in our traces). The agent accepts (a push-after-final flag was
  planned, not built); test a push only across several cases; in cases without an alternative (D01, P05, P06, P10, P14, P17) never push.
- Prepare the worst acceptable sheet before message 9 so a late `final_offer` can be taken at once.

## 6. Estimating the floor

**Research.** Bayesian learning of the reservation price (Zeng and Sycara 1998), regression on the
opponent's concession curve (Hou 2004), Gaussian-process prediction of its next offers (IAMhaggler,
Williams et al. 2011). With three counters p1, p2, p3 and geometric decay, Aitken's formula gives
the limit: `R = p3 - (p3 - p2)^2 / ((p3 - p2) - (p2 - p1))`. Known failure: when step ratios rise
(slower than geometric) it underestimates the floor and pushes too hard. Every observed counter is
a hard upper bound on the floor.

**For us.** Useful as a secondary signal, not a stop rule: the bot stops on patience before its
floor, so a floor estimate mostly tells us whether a relationship charge is near (stabilise,
secure supply) and whether a large first concession means room (already `DEEP` in the policy).
The relationship charge in a finished practice result gives the supplier's true margin and cost
(`learnings.md`), which beats any curve fit for practice cases.

## 7. Procurement levers by supplier situation

**Research** (practice literature: Kraljic 1983, consultancy and CIPS sources; conventions, not
studies): classify the position first (leverage: compete and push price; bottleneck and strategic:
secure supply and joint value); answer a price-increase letter with a line-item breakdown weighted
by each driver's cost share; accept justified increases only index-linked or temporary; price
payment terms at both sides' cost of money; index clauses with a deadband of 3 to 5 %, a lag,
a cap, both directions and only the exposed cost share; threaten a second source only if it is
real; agree chargebacks before the dispute. Preferred-customer research (Schiele et al.): suppliers
reward attractive customers with capacity and price; forecast visibility and payment reliability
are what they ask for most. Collaborative but assertive buyers realise more value (Vantage
Partners survey, correlational).

**Playbook**, joined with our persona signals (`learnings.md`, Persona signals):

| Situation | Signal in the data | Give | Ask | Avoid |
|---|---|---|---|---|
| Cash short | "bank is watching", "pay earlier", cash discount | faster payment when its rate beats our 8 % (cash discounts imply 37 to 56 %/yr) | price | ignoring its ask when payment is fixed: say so and offer the next best currency |
| Fully booked | "fully booked", "allocates volumes" | its lead time, a firm 24-month volume, forecast | price at its standard speed | deep anchors (P10 patience 0.015), paying overtime for speed we do not value |
| Spare capacity | "second shift on hold" | volume, extra parts, long term | price | |
| Price frozen | "no room on price", "price list applies to all" | nothing on price | payment days, contract length, freight, start date | price pushes (no move, only lost patience) |
| Approval ladder | "above 2 % need the approval" | small steps (2 % or less), a reason the rep can forward to its boss | | one big ask that goes to a committee |
| Index-driven distributor | material share in its quote, clause offered | contract length only with a clause we can live with | deadband, share limited to material, falling series only | taking a 0 % deadband clause on a rising series (P02: score 0) |
| Price increase letter | letter above its drivers' index move | the index-weighted justified part, later start | notice period, start date, split | citing indices that rose (they confirm its case) |
| Stabilise, near cost | own-plant should-cost close to the quote | the price with the lowest C incl. relationship charge | terms | squeezing below sustainable margin (charge grows with the square) |
| Quality first | high scorecard ppm | | low ppm commitment, chargeback at least `cost_per_defect` | trading quality away for price unless C says so |

## 8. RFQs with two or three bidders

**Research.** Competition is worth more than negotiating skill: one extra bidder beats an optimally
negotiated deal (Bulow and Klemperer 1996). For complex, non-standard contracts, negotiation beats
a pure price auction because terms differ per bidder (Bajari, McMillan and Tadelis 2009). One
best-and-final round works; repeated ones teach bidders to hold back (practice sources).

**For us.** The current design matches: compare bids on total C, cite the cheapest rival's real
standing offer (a new argument every round), keep losing threads alive as the alternative.
Additions: one explicit best-and-final message per bidder near the end, not several; push the
bidder with the lowest C first and keep others warm with a question about capacity or delivery.
P05 is at 0.83, so RFQs are not where the points are.

## 9. Writing for LLM counterparts

**Research.** The largest AI negotiation competition (Vaccaro et al. 2025, about 120k to 180k
negotiations): warm agents beat cold ones on deal rate, joint value and counterpart satisfaction;
dominance claimed value but raised impasses; positivity, gratitude and questions predicted deals.
Buyers are harder for LLMs than sellers, and splitting a coded offer generator from an LLM narrator
lifted buyer deal rates from 27 % to 89 % (OG-Narrator, Xia et al. 2024): our architecture.
Asking about interests improves joint outcomes even when only one side does it (Thompson 1991).
Disappointment draws concessions, anger backfires on value disputes (Van Kleef). Objective
criteria and trades over positions (Fisher and Ury). LLMs drift toward a user who argues a side
(sycophancy rose from 50 to 79 % in one benchmark): a calm, reasoned position held over rounds
can move them, which is persuasion, not injection.

**Writing rules** for `buyer/writer.py` and the paragraph prompt in `buyer/llm.py`:

1. Open with one sentence that acknowledges its last message, specifically (what it moved, what it
   asked for).
2. Answer every request it made, even with no: "Payment terms are fixed in this agreement; what
   we can offer instead is ..." (P11).
3. One or two reasons per message, each a checkable fact next to its ID; more reasons dilute.
4. Frame every move as a trade: "If you can do X, we can do Y."
5. Ask one open question about its constraints ("What would make a price near X work for your
   planning?"). No "why" questions.
6. Express disappointment at the gap, never anger at the person.
7. Give the rep a forwardable rationale for its boss: figure, source, what we give in return.
8. Name our last step as last, once, and mean it.
9. No urgency, budget, target or missing alternative; no threats; no fake rivals; nothing aimed at
   the bot's instructions.

## 10. Experiment plan

The sandbox (D01, D02) is free and deterministic, so one run per variant measures the change.
Practice quota only for changes that won there; one change per batch.

| Order | Experiment | Where | Read out |
|---|---|---|---|
| 1 | `FRACTION` 0.3 / 0.5 / 0.7 | D01, D02 | final price, rounds to `final_offer`, Σ gap |
| 2 | Round 1 with three equal-C sheets against one | D01, D02, then P07, P08, P18 | first counter, which sheet it picked |
| 3 | Hold back one currency (contract length or forecast) for round 2 or 3 | D01, then P07, P10 | its step after a currency move against a price move |
| 4 | Explicit answer to its stated need | P11 | price after round 2; back office tone |
| 5 | ppm headroom as currency | P11 | price per ppm point given against our 7 EUR |
| 6 | One push after `final_offer` (not built) | cases with an alternative only | walks against gain |

Record each result in `learnings.md` (tag `arena`), including the ones that fail.

## Sources and confidence

High: our own traces (`logs/sessions/`, every number in section 1 recomputed from them).
Medium: peer-reviewed results read from abstracts or reliable summaries. Low: practitioner and
vendor sources, conventions rather than evidence; numbers in section 7 are of this kind.

- Galinsky and Mussweiler 2001, first offers as anchors, JPSP 81(4): https://www.semanticscholar.org/paper/4593e56e2f94f5ffc75789ddacdfbe3670481cbe
- Mason, Lee, Wiley and Ames 2013, precise offers, JESP 49(4): https://business.columbia.edu/press-release/cbs-press-releases/new-research-shows-asking-precise-not-round-number-during
- Schweinsberg, Ku, Wang and Pillutla 2012, extreme anchors, JESP 48: https://www.martinschweinsberg.com/content/files/2022/03/Publication-2012-Schweinsberg-Ku-Wang-Pillutla-JESP-in-press.pdf
- Tey, Schaerer, Madan and Swaab 2021, decreasing concessions, OBHDP 165: https://ideas.repec.org/a/eee/jobhdp/v165y2021icp153-166.html
- Leonardelli et al. 2019, MESOs, OBHDP 152: https://ideas.repec.org/a/eee/jobhdp/v152y2019icp64-83.html ; guide: https://www.pon.harvard.edu/daily/business-negotiations/how-to-use-mesos-in-business-negotiations
- Faratin, Sierra and Jennings 2002, similarity-based trade-offs, AI 142: https://spiral.imperial.ac.uk/entities/publication/fc2ffe91-2e01-463e-a64b-8b633e74c5ba
- Baarslag et al., acceptance conditions and BOA: https://homepages.cwi.nl/~baarslag/pub/Acceptance_conditions_in_automated_negotiation.pdf ; https://homepages.cwi.nl/~baarslag/pub/Decoupling_Negotiating_Agents_to_Explore_the_Space_of_Negotiation_Strategies.pdf
- Baarslag et al. 2016, learning about the opponent: https://link.springer.com/article/10.1007/s10458-015-9309-1
- Zeng and Sycara, Bayesian learning in negotiation: https://cdn.aaai.org/Symposia/Spring/1996/SS-96-01/SS96-01-019.pdf
- Williams et al. 2011, IAMhaggler: https://www.ijcai.org/Proceedings/11/Papers/080.pdf
- Roth, Murnighan and Schoumaker 1988, deadline effect (via): https://www.cambridge.org/core/journals/experimental-economics/article/bargaining-under-time-pressure-from-deadlines/F388EC46629F094DDB48A96AE00F8DCC
- Bulow and Klemperer 1996, auctions versus negotiations: https://www.nber.org/papers/w4608
- Bajari, McMillan and Tadelis 2009, auctions versus negotiations in procurement: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=414255
- Bianchi et al. 2024, NegotiationArena: https://arxiv.org/abs/2402.05863
- Vaccaro et al. 2025, Advancing AI negotiations: https://arxiv.org/abs/2503.06416
- Xia et al. 2024, bargaining abilities of LLMs, OG-Narrator: https://aclanthology.org/2024.findings-acl.213/
- Thompson 1991, information exchange: https://www.kellogg.northwestern.edu/academics-research/research/detail/1991/information-exchange-in-negotiation
- Van Kleef, emotions as social information: https://www.sciencedirect.com/science/article/abs/pii/S0022103110002830
- Morris et al. 2002, schmooze or lose: https://www.researchwithrutgers.com/en/publications/schmooze-or-lose-social-friction-and-lubrication-in-e-mail-negoti/
- Preferred customer status, Hüttinger, Schiele and Veldman 2012: https://eprints.glos.ac.uk/2191
- Vantage Partners, customer-supplier negotiation study: https://www.vantagepartners.com/insights/customer-supplier-negotiation-study
- Price increase requests (practice): https://artofprocurement.com/blog/addressing-supplier-cost-increase-requests-can-you-beat-the-market ; https://www.rolandberger.com/en/Insights/Publications/Managing-supplier-claims-for-price-increases-in-the-procurement-process.html
- Price adjustment clauses (practice): https://www.tacto.ai/en/procurement-glossary-downloads/raw-material-price-adjustment-clause
