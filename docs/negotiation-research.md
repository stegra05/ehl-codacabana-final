# Negotiation research: ideas from the literature

Gathered 10 October 2026 by ten parallel research agents. Most points were read from abstracts
and summaries, so treat effect sizes as directional. Nothing here has been tested in the arena
unless `learnings.md` says so. Use it as a source of ideas.

## Opening and anchoring

The first offer anchors the settlement (Galinsky and Mussweiler 2001; NegotiationArena found
opening offers correlate with final prices, rho about 0.72, for LLM agents too). Precise numbers
anchor harder than round ones and signal preparation (Mason et al. 2013; Loschelder et al. 2017).
Extreme offers raise walk-aways: 30 % after an extreme opening against 11 % after a moderate one
(Schweinsberg et al. 2012, replicated 2018). The anchor loses power when the recipient focuses on
its own alternatives and target.

## Multi-issue offers

Multiple equivalent simultaneous offers (Leonardelli et al. 2019, six experiments): three
packages of equal value to the offerer, different mixes, all at or better than target. Stronger
anchor, better outcome for the offerer, more joint gain, read as sincere; the choice reveals the
counterpart's priorities. Automated negotiation does the same on iso-utility curves: packages of
equal own value, pick the one closest to the opponent's last offer (Faratin, Sierra and Jennings
2002; Lai and Sycara). Package deals ("nothing agreed until everything is agreed") turn a price
fight into trades. Logrolling: concede on the issue the other side values more and you value less.

## Conceding

ANAC winners pair a tough bidding curve with an opponent model and a lenient acceptance near the
deadline (Baarslag et al.; Agent K extrapolates the opponent from the mean and spread of its
offers). Shrinking concessions make the counterpart expect a limit and counter less ambitiously
(Tey et al. 2021, seven studies). Agreements cluster at the deadline (Roth, Murnighan and
Schoumaker 1988). Procurement practice: a concession asks for something specific in return.

## Acceptance

AC_next: accept when the offer is at least as good as what you would send next (most common in
ANAC), with a time rule that relaxes near the deadline. Expected-value form: accept now when
`C_now <= (1 - p) * E[C_next] + p * C_alt`, with p the chance the next push ends the thread.

## Estimating the floor

Bayesian learning of the reservation price (Zeng and Sycara 1998), regression on the concession
curve (Hou 2004), Gaussian-process prediction of the next offers (IAMhaggler, Williams et al.
2011). With three counters p1, p2, p3 and geometric decay, Aitken's limit:
`R = p3 - (p3 - p2)^2 / ((p3 - p2) - (p2 - p1))`; it underestimates when step ratios rise. Every
observed counter is an upper bound on the floor.

## Procurement practice

Kraljic 1983 and consultancy sources, conventions rather than studies: classify the position
(leverage: compete and push price; bottleneck and strategic: secure supply and joint value);
answer a price-increase letter with a line-item breakdown weighted by each driver's cost share;
accept justified increases index-linked or temporary; price payment terms at both sides' cost of
money; index clauses with a deadband of 3 to 5 %, a lag, a cap, both directions, only the exposed
share; a second-source threat only if real; chargebacks agreed before the dispute. Preferred
customer research (Schiele et al.): suppliers reward attractive customers with capacity and
price; forecast visibility and payment reliability are what they ask for most. Collaborative but
assertive buyers realise more value (Vantage Partners, correlational).

## RFQs

One extra bidder beats an optimally negotiated deal (Bulow and Klemperer 1996). For complex
contracts negotiation beats a pure price auction because terms differ per bidder (Bajari,
McMillan and Tadelis 2009). One best-and-final round works; repeated ones teach bidders to hold
back.

## Writing for LLM counterparts

The largest AI negotiation competition (Vaccaro et al. 2025, about 120k to 180k negotiations):
warm agents beat cold ones on deal rate, joint value and satisfaction; dominance claimed value but
raised impasses; positivity, gratitude and questions predicted deals. Buyers are harder for LLMs
than sellers; splitting a coded offer generator from an LLM narrator lifted buyer deal rates from
27 % to 89 % (OG-Narrator, Xia et al. 2024). Asking about interests improves joint outcomes even
when only one side does it (Thompson 1991). Disappointment draws concessions, anger backfires on
value disputes (Van Kleef). Objective criteria and trades over positions (Fisher and Ury). LLMs
drift toward a user who argues a side (sycophancy 50 to 79 % in one benchmark): a calm, reasoned
position held over rounds can move them. Targeting the bot's instructions is an attack under the
arena rules.

## Sources

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
