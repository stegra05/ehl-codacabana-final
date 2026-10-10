"""AI suggestions for the probe console: a model proposes a few complete next moves, code checks them.

The model sees what the kit's LLMAgent sees (case, letter, facts, every thread with C per standing
sheet) plus the probe's state: what this thread has tried and the arguments code has prepared.
Each suggestion passes the kit's guard: term sheets completed and snapped, unknown data IDs
dropped, an accept refused if it breaks a must-have or loses to the alternative.
"""

import json
import re

from arena_kit.agents import LLMAgent
from arena_kit.cost import total_cost
from arena_kit.docs import standard_terms
from arena_kit.play import standing

from .moves import Option

SYSTEM = """You assist a purchasing operator who probes an industrial supplier (an LLM persona with
hidden economics) in a PRACTICE negotiation. The goal of this session is to LEARN how this supplier
behaves - its floor, what levers it values (payment days, contract length, volume, dates, index
clause), which data arguments move it, how it reacts to tone - while still closing a decent deal.

Propose exactly 3 DIFFERENT next moves for the given thread, each testing something else. Reply
with ONE JSON object and nothing else:
{"suggestions": [{"label": "short name", "tests": "what we learn from the reply",
  "action": "send", "subject": "...", "body": "...", "term_sheets": [{"unit_price": 0.0, "...": "..."}]},
 {"label": "...", "tests": "...", "action": "accept"}]}

- action: "send", "accept" (takes the supplier's standing sheet) or "walk_away" (ends the case).
- term_sheets: 0-3 packages over the negotiable fields; only they bind. Vary one lever per sheet
  when you test what the supplier values.
- Cite data only by IDs from FACTS or PREPARED ARGUMENTS, figure and ID in the same sentence, at
  most 3 arguments per message. A wrong figure or unknown ID costs trust.
- Plain business e-mail, at most 120 words, signed "Hollerau Pumpenwerke, Purchasing", no
  placeholders. Do not repeat what the thread already tried unless the reply invites it."""


class Suggester:
    def __init__(self, complete, package=None):
        self.agent = LLMAgent(complete, package)

    def suggest(self, case, supplier_id, threads, prober):
        """Up to 3 checked Options; raises if the model fails."""
        if self.agent.case_id != case["case_id"]:
            self.agent.case_id, self.agent.brief = case["case_id"], self.agent.prepare(case)
        tried = prober.used.get(supplier_id, [])
        prepared = "\n".join(c["text"] for c in prober.claims)
        user = (
            f"{self.agent.render(case, threads)}\n\nPREPARED ARGUMENTS (verified against the data)\n{prepared}"
            f"\n\nTHIS THREAD ({supplier_id}) HAS TRIED: {tried or 'nothing yet'}"
            f"\nShould-cost estimate: {prober.should_cost(supplier_id)}\nPropose 3 moves for {supplier_id}."
        )
        text = self.agent.complete(SYSTEM, user)
        raw = json.loads(re.search(r"\{.*\}", text, re.S).group(0)).get("suggestions", [])
        events = threads[supplier_id]
        out = []
        for i, d in enumerate(raw[:3], 1):
            checked = self.agent.guard(case, threads, {**d, "supplier_id": supplier_id})
            if not checked:
                continue
            msg = checked["message"]
            if action := msg.get("action"):
                costs = [total_cost(case, standing(events)[1], standard_terms(events))]
                if action["type"] == "walk_away":
                    costs = []
            else:
                costs = [total_cost(case, s["terms"], standard_terms(events)) for s in msg["term_sheets"]]
            note = f"{d.get('label', '')} | tests: {d.get('tests', '')}"
            out.append(Option(f"a{i}", note, msg, costs))
        return out
