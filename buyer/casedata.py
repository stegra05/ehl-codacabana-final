"""What the data says about a case: should-cost, verified claims, our anchor price, valid sheets.

`CaseData` reads the data package once per case: the should-cost of its parts (the supplier's own
plant if modelled), every data argument with its figure and IDs (index moves below MAX_INDEX_PCT,
late notice, scorecards, should-cost, forecast), and builds term sheets that carry every negotiable
field and keep the must-haves.
"""

from arena_kit.cost import complete_offer, must_haves_ok
from arena_kit.docs import standard_terms
from arena_kit.play import standing

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


def _months_back(month, n):
    y, m = map(int, month.split("-"))
    m -= n
    while m <= 0:
        y, m = y - 1, m + 12
    return f"{y:04d}-{m:02d}"


class CaseData:
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

    def sheet(self, terms, events):
        sheet = complete_offer(self.case, {**standard_terms(events), **terms})
        for m in self.case["buyer"].get("must_haves", []):  # never probe with a sheet we could not take
            if m["field"] in sheet and not must_haves_ok(self.case, sheet):
                allowed = self.case.get("term_options", {}).get(m["field"]) or [m["value"]]
                ok = [o for o in allowed if must_haves_ok(self.case, {**sheet, m["field"]: o})]
                sheet[m["field"]] = min(ok, key=lambda o: abs(o - m["value"])) if ok else m["value"]
        return sheet

    def anchor(self, supplier_id, events):
        """Our opening price: the current price if the supplier asks for more, else 8 % below its
        quote; never below 97 % of the should-cost."""
        _, terms = standing(events)
        price = terms.get("unit_price") or 0
        current = self.case["buyer"].get("current_unit_price")
        a = current if current and current < price else price * 0.92
        sc = self.should_cost(supplier_id)
        return round(max(a, 0.97 * sc) if sc else a, 2)
