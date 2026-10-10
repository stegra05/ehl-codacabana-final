# Worklog (Steffen)

## What I did

- Data exploration
- Found out the difference between the local sim and the sandbox
    - Sandbox: 3 different personas, and we have no testing limit there

## Data exploration

- Most companies are in Germany, but there are also some in other countries (not many)
- There are category goals and strategies -> maybe 5 agents (details: [category-goals.md](category-goals.md)):
    - leverage
    - stabilise
    - secure_supply
    - quality_first
    - routine
- Every case states its category goal -> we need to find it before we negotiate
- Supplier relationship
    - There are sustainable margin rates that we must not undercut, otherwise we get a penalty
    - Only relevant for `secure_supply` and `stabilise` cases
- Additionally there are different personas according to company type -> only matters for the
  interaction with the bot, not for the price (details: [supplier-personas.md](supplier-personas.md))
    - Family company -> values trust
    - Group
    - Founder
    - Private
- There are news topics

## Ideas

- Supplier relationship: how is it calculated?
- When is the supplier relationship relevant? Always?
