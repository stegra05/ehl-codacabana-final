# Understanding anchor and gap

In the local strategy experiments, **anchor** is the discount requested in the
first counteroffer. **Gap** is the remaining price difference the buyer tolerates
before accepting the supplier's standing offer.

These are parameters of the kit's deterministic `NaiveAgent`, not model settings
or discounts selected from supplier research.

## Example: Anchor 20% / gap 1%

1. The supplier asks for EUR 100 per unit.
2. The buyer offers EUR 80: 20% below the supplier's opening price.
3. The supplier counters at EUR 90. The buyer offers EUR 85, halfway between its
   previous EUR 80 offer and the supplier's EUR 90 offer.
4. Negotiation continues. Suppose the buyer's last offer is EUR 88.20 and the
   supplier now asks for EUR 89. The difference is EUR 0.80, below 1% of EUR 89
   (EUR 0.89), so the buyer accepts the supplier's EUR 89 offer.

The normal price rules are:

```text
First counteroffer = supplier opening price * (1 - anchor)
Next counteroffer  = (supplier current price + buyer previous price) / 2
Accept when       = supplier current price - buyer previous price
                    <= supplier current price * gap
```

The gap is measured against the supplier's current price. It is not the final
discount or a target saving. The naive agent can also accept before reaching the
gap when the supplier marks the offer as agreed or final, or no moves remain.

## Reading the experiment labels

| Parameter | Values tested locally | Meaning of a higher value |
|---|---|---|
| Anchor | 3%, 10%, 20% | Request a larger opening discount |
| Gap | 0.5%, 1%, 3% | Tolerate a larger remaining price difference, tending to close earlier |

The three anchors and three gaps produce nine combinations. For example,
`Anchor 10% / gap 0.5%` starts 10% below the opening quote and normally waits
until the difference is at most 0.5% of the supplier's current price.

## What these experiments establish

The local dashboard compares mechanical negotiation rules against a scripted
supplier. The anchor/gap rules do not use company dossiers, correspondence, cost
indices or supplier profiles to choose their parameters or arguments. The
prepared A/B/C research packets have not yet been evaluated with a language model.

A higher simulator score is not a percentage saving or evidence that the same
opening discount will work against hosted supplier bots. The simulator reacts
mainly to price and does not fully represent supplier trade-offs.

The naive acceptance rule does not itself check mandatory conditions or whether
an available alternative is cheaper. The local **Guarded** variant adds those
checks before closing. **Package cost** additionally chooses permitted non-price
terms by total buyer cost. Those experimental variants are distinct from changing
the anchor or gap, and this document does not change the production agent.

Implementation reference: the pinned official kit's
[`NaiveAgent`](https://github.com/tacto-ai/negotiation-arena-kit/blob/1b5516bb95ef28e37f69aa446dc62168864bca53/starter-kit/arena_kit/agents/naive.py).
