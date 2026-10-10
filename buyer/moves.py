"""Probe moves: the experiments an operator picks from during a practice session.

Each option is a ready message (or an action) built in code from the case, the thread so far and
the data package: term sheets complete and snapped, every figure next to its data ID. The options
are ordered so the first is the default the console sends when the operator does not pick in time.
The plan runs from safe to risky: questions and documents, lever probes, data claims, a price
ladder, the estimated floor, then bluff, urgency and a deliberately wrong figure, then close.
"""

import functools
import json
import math
from dataclasses import dataclass, field

from arena_kit.cost import complete_offer, must_haves_ok, total_cost
from arena_kit.docs import standard_terms
from arena_kit.play import latest, moves_left, standing

SIGN_OFF = "\n\nBest regards\nHollerau Pumpenwerke, Purchasing"
# The direction of each lever that helps the supplier: probing it shows what the supplier will
# pay for it in price.
SUPPLIER_SIDE = {
    "payment_days": min,
    "contract_months": max,
    "volume_per_year": max,
    "effective_date": min,
    "lead_time_days": max,
    "ppm_commitment": max,
    "chargeback_eur_per_complaint": min,
}
DOCS = {
    "capacity": "Could you also send your delivery schedule and the earliest lead time you can confirm?",
    "rfq": "Could you also send your delivery schedule and the earliest lead time you can confirm?",
    "quality": "Please also send the 8D report and the ppm you can commit to.",
}
# An index that rose more than this argues for the supplier, not for us.
MAX_INDEX_PCT = 3.0
PLAN = ["open", "levers", "claims", "step", "levers", "claims", "step", "floor", "bluff", "close"]


@dataclass
class Option:
    key: str
    note: str
    message: dict
    costs: list = field(default_factory=list)  # C per term sheet, or of the accepted sheet
    claims: list = field(default_factory=list)  # claim keys this message uses
    levers: list = field(default_factory=list)  # levers this message probes


def _months_back(month, n):
    y, m = map(int, month.split("-"))
    m -= n
    while m <= 0:
        y, m = y - 1, m + 12
    return f"{y:04d}-{m:02d}"


class Prober:
    """Builds the options for one thread. Keeps what each thread has used so far."""

    def __init__(self, case, package=None):
        self.case, self.package = case, package
        self.facts = (package.facts if package else {}) | case.get("facts", {})
        self.used = {}  # supplier -> [option keys sent]
        self.claims_used = set()
        self.claims = self._claims()

    # ---------- data ----------

    def _q(self, sql, *params):
        try:
            return self.package.query(sql, params) if self.package else []
        except Exception:  # sandbox suppliers are not in the package
            return []

    def should_cost(self, supplier_id):
        """Summed should-cost of the case's parts: the supplier's own plant if modelled, else the
        German cost base. None if the package has no estimate."""
        total = 0.0
        for part in self.case["parts"]:
            rows = self._q("SELECT supplier_id, unit_cost, price_unit FROM should_cost WHERE part_id = ?", part)
            if not rows:
                return None
            row = next((r for r in rows if r["supplier_id"] == supplier_id), rows[0])
            total += row["unit_cost"]
        return round(total, 2)

    def _index_claims(self):
        out = []
        drivers = {}
        for part in self.case["parts"]:
            for r in self._q("SELECT series_id, weight FROM cost_drivers WHERE part_id = ?", part):
                drivers[r["series_id"]] = max(drivers.get(r["series_id"], 0), r["weight"])
        for series in drivers:
            months = sorted(k.split("@")[1] for k in self.facts if k.startswith(f"idx:{series}@"))
            if not months:
                continue
            m1 = months[-1]
            m0 = _months_back(m1, 12)
            a, b = self.facts.get(f"idx:{series}@{m0}"), self.facts.get(f"idx:{series}@{m1}")
            if not (a and b and a["value"]):
                continue
            pct = round((b["value"] / a["value"] - 1) * 100, 1)
            ids = (f"idx:{series}@{m0}", f"idx:{series}@{m1}")
            text = f"{series} changed {pct:+.1f} % from {m0} to {m1} ({ids[0]}, {ids[1]})."
            out.append({"key": f"idx {series} {pct:+.1f}%", "text": text, "refs": list(ids), "pct": pct})
        return out

    def _claims(self):
        """Every argument the data supports for this case, best for us first."""
        out = sorted((c for c in self._index_claims() if c["pct"] < MAX_INDEX_PCT), key=lambda c: c["pct"])
        c = self.case
        doc = self.facts.get(c.get("trigger_doc") or "")
        for ref in c.get("refs", []):
            ctr = self.facts.get(ref) if ref.startswith("ctr:") else None
            if doc and ctr and doc.get("days") and ctr.get("days") and doc["days"] < ctr["days"]:
                text = (
                    f"Your letter gives {doc['days']} days notice, while our contract requires "
                    f"{ctr['days']} days ({c['trigger_doc']}, {ref})."
                )
                out.insert(
                    0, {"key": f"notice {doc['days']}<{ctr['days']}d", "text": text, "refs": [c["trigger_doc"], ref]}
                )
        quality = c["type"] == "quality"
        for sup in c["suppliers"]:
            sid = sup.split(":")[1]
            rows = sorted((k for k in self.facts if k.startswith(f"sc:{sid}@")), reverse=True)[:4]
            if rows:
                vals = [self.facts[k]["ppm" if quality else "otd_pct"] for k in rows]
                mean = sum(vals) / len(vals)
                what = (
                    f"your complaint rate averaged {mean:,.0f} ppm"
                    if quality
                    else f"your on-time delivery averaged {mean:.1f} %"
                )
                text = f"Over the last four scorecards {what} ({', '.join(rows)})."
                out.append({"key": f"scorecard {sid}", "text": text, "refs": rows, "supplier": sup})
        for part in c["parts"]:
            pid = part.split(":")[1]
            if cost := self.facts.get(f"cost:{pid}"):
                text = f"Our should-cost estimate for this part is EUR {cost['unit_cost']:.2f} per unit (cost:{pid})."
                out.append({"key": f"should-cost {cost['unit_cost']:.2f}", "text": text, "refs": [f"cost:{pid}"]})
            fcs = sorted(k for k in self.facts if k.startswith(f"fc:{pid}@"))
            if fcs:
                f = self.facts[fcs[-1]]
                text = f"Our forecast for this part changed {f['change_pct']:+.1f} % ({fcs[-1]})."
                out.append({"key": f"forecast {f['change_pct']:+.1f}%", "text": text, "refs": [fcs[-1]]})
        return out

    # ---------- term sheets ----------

    def _sheet(self, terms, events):
        sheet = complete_offer(self.case, {**standard_terms(events), **terms})
        for m in self.case["buyer"].get("must_haves", []):  # never probe with a sheet we could not take
            if m["field"] in sheet and not must_haves_ok(self.case, sheet):
                sheet[m["field"]] = m["value"]
        return sheet

    def _cost(self, sheet, events):
        return total_cost(self.case, sheet, standard_terms(events))

    def anchor(self, supplier_id, events):
        """Our opening price: the current price if the supplier asks for more, else 8 % below its
        quote; never below 97 % of the should-cost."""
        _, terms = standing(events)
        price = terms.get("unit_price") or 0
        current = self.case["buyer"].get("current_unit_price")
        a = current if current and current < price else price * 0.92
        sc = self.should_cost(supplier_id)
        return round(max(a, 0.97 * sc) if sc else a, 2)

    def _our_last(self, events):
        for m in reversed(events):
            if m.get("from") == "buyer" and m.get("term_sheets"):
                return m["term_sheets"][0]["terms"]
        return None

    # ---------- options ----------

    def option(self, key, note, body, sheets, events, **extra):
        message = {
            "subject": f"Re: {self.case['title']}"[:300],
            "body": f"Dear Sir or Madam,\n\n{body}{SIGN_OFF}",
            "term_sheets": [{"terms": s} for s in sheets],
            "refs": [r for c in extra.pop("claim_rows", []) for r in c["refs"]],
        }
        return Option(key, note, message, [self._cost(s, events) for s in sheets], **extra)

    def _lever_value(self, f):
        opts = self.case["term_options"][f]
        if f == "index_clause":
            return next((o for o in opts if o and o.get("deadband_pct") == 0), opts[-1])
        return SUPPLIER_SIDE[f]([o for o in opts if o is not None])

    def options(self, supplier_id, threads):
        """Every option for this thread's next move; the first is the default."""
        events = threads[supplier_id]
        sheet_id, terms = standing(events)
        price = terms.get("unit_price") or 0
        anchor = self.anchor(supplier_id, events)
        ours = self._our_last(events)
        last = (ours or {}).get("unit_price") or anchor
        at = lambda p, **more: self._sheet({**terms, **more, "unit_price": round(p, 2)}, events)  # noqa: E731
        opt = functools.partial(self.option, events=events)
        out = {}

        ask = "Thank you for your offer. Could you send us a cost breakdown for this part? "
        ask = (ask + DOCS.get(self.case["type"], "")).strip() + "\nWhat would you need from us to move on price?"
        out["open"] = opt("open", f"questions + documents, anchor {anchor}", ask, [at(anchor)])
        out["ask"] = opt("ask", "questions + documents, no term sheet", ask, [])

        levers = [f for f in self.case["negotiable"] if f in SUPPLIER_SIDE and self.case.get("term_options", {}).get(f)]
        levers += ["index_clause"] if "index_clause" in self.case["negotiable"] else []
        probed = [k.split(":")[1] for k in self.used.get(supplier_id, []) if k.startswith("levers")]
        tried = {f for k in probed for f in k.split(",")}
        fresh = ([f for f in levers if f not in tried] or levers)[:3]
        if fresh:
            mid = (last + price) / 2
            body = "We have put together alternative packages. Which of them works best for you, and at what price?"
            sheets = list({json.dumps(x): x for x in (at(mid, **{f: self._lever_value(f)}) for f in fresh)}.values())
            key = f"levers:{','.join(fresh)}"
            out[key] = opt(key, f"price {mid:.2f}, one lever each toward the supplier", body, sheets, levers=fresh)

        mine = [c for c in self.claims if c.get("supplier", supplier_id) == supplier_id]
        rows = [c for c in mine if c["key"] not in self.claims_used]
        if rows := rows[:3]:
            body = "We have looked at the figures.\n" + "\n".join(c["text"] for c in rows) + "\nOur offer is below."
            out["claims"] = opt(
                "claims",
                "; ".join(c["key"] for c in rows),
                body,
                [at(last + (price - last) / 3)],
                claim_rows=rows,
                claims=[c["key"] for c in rows],
            )

        for pct in (1, 2, 4):
            closer = "Thank you. We can move closer, see below."
            out[f"step-{pct}"] = opt(f"step-{pct}", f"their price -{pct} %", closer, [at(price * (1 - pct / 100))])
        if ours:
            out["split"] = opt(
                "split",
                "meet in the middle of our last and their price",
                "Let us meet in the middle.",
                [at((last + price) / 2)],
            )
        if sc := self.should_cost(supplier_id):
            out["floor"] = opt(
                "floor", f"should-cost {sc} + 3 %", "One more proposal, based on our cost analysis.", [at(sc * 1.03)]
            )

        hold = [self._sheet(ours or terms, events)]
        real = (self.case["buyer"].get("alternative") or {}).get("kind") not in (None, "none")
        out["bluff"] = opt(
            "bluff",
            "walk-away threat on our last sheet" + ("" if real else " (no real alternative)"),
            "If we cannot get closer to this, we will move the volume to another source.",
            hold,
        )
        out["urgency"] = opt(
            "urgency",
            "urgency leak on our last sheet",
            "Frankly, we need to close this quickly: our line depends on these parts. Can you meet us here?",
            hold,
        )
        if idx := next((c for c in self.claims if "pct" in c), None):
            wrong = dict(idx, text=idx["text"].replace(f"{idx['pct']:+.1f} %", f"{idx['pct'] - 4:+.1f} %"))
            body = wrong["text"] + "\nOur offer is below."
            out["wrong"] = opt("wrong", f"index figure 4 pp off ({idx['key']})", body, hold, claim_rows=[wrong])

        if sheet_id:
            std = standard_terms(events)
            broken = "" if must_haves_ok(self.case, terms, std) else " BREAKS A MUST-HAVE"
            out["accept"] = Option(
                "accept",
                f"accept {sheet_id}{broken}",
                {"action": {"type": "accept", "term_sheet_id": sheet_id}},
                [total_cost(self.case, terms, std)],
            )
        out["walk"] = Option("walk", "walk away (ends the case)", {"action": {"type": "walk_away"}})

        default = self._default(supplier_id, events, out)
        return [out[default]] + [o for k, o in out.items() if k != default]

    def c_alt(self):
        alt = self.case["buyer"].get("alternative") or {}
        return total_cost(self.case, alt["terms"]) if alt.get("terms", {}).get("unit_price") else math.inf

    def _default(self, supplier_id, events, out):
        """The next plan step this thread has not used; close when the rounds run out or the
        supplier says agreed or final_offer."""
        used = self.used.get(supplier_id, [])
        if moves_left(self.case, events) <= 0 or latest(events).get("status") in ("agreed", "final_offer"):
            step = "close"
        else:
            step = PLAN[min(len(used), len(PLAN) - 1)]
        if step == "close":
            acc = out.get("accept")
            return "accept" if acc and "MUST-HAVE" not in acc.note and acc.costs[0] < self.c_alt() else "walk"
        if step == "levers":
            step = next((k for k in out if k.startswith("levers")), "step-2")
        return {"step": "step-2"}.get(step, step) if step in out or step == "step" else "step-2"

    def sent(self, supplier_id, option):
        self.used.setdefault(supplier_id, []).append(option.key)
        self.claims_used.update(option.claims)
