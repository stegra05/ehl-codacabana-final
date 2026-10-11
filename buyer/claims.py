"""Data arguments, each one sentence with its figure next to its IDs, computed the way the arena
checks them (`docs/api.md`, What counts). Only arguments that push the price our way are kept;
a rising index or a should-cost above the quote would argue the supplier's case.

In the sandbox the case's refs point into a demo world our package does not hold: those are cited
without a figure, so the arena checks them against their own value."""

import re

SERIES_NAME = {
    "PPI-C2451": "Producer prices for iron castings",
    "PPI-C2452": "Producer prices for steel castings",
    "PPI-C2562": "Producer prices for machining",
    "PPI-C2594": "Producer prices for fasteners",
    "PPI-C2711": "Producer prices for electric motors",
    "PPI-C2611": "Producer prices for electronic components",
    "PPI-C2815": "Producer prices for bearings and gears",
    "PPI-C241": "Producer prices for basic iron and steel",
    "PPI-C2431": "Producer prices for cold-drawn bars",
    "PPI-C2219": "Producer prices for rubber products",
    "PPI-D351": "Electricity producer prices",
    "PPI-D35": "Energy supply producer prices",
    "LCI-C": "Manufacturing labour costs",
    "WB-CU": "Copper",
    "WB-NI": "Nickel",
    "WB-AL": "Aluminium",
    "WB-NGEU": "European natural gas",
    "CU-NOTATION": "The copper notation",
    "AS-14404": "The 1.4404 alloy surcharge",
    "AS-14301": "The 1.4301 alloy surcharge",
}


def months_back(month, n):
    y, m = (int(x) for x in month.split("-"))
    m -= n
    while m <= 0:
        m, y = m + 12, y - 1
    return f"{y}-{m:02d}"


def money(x):
    return f"EUR {x:.2f}"


def per_unit(fact):
    """Pieces a recorded price covers: 15 of 108 quotes and some orders are priced per 100 or 1000."""
    try:
        return int(fact.get("price_unit") or 1) or 1
    except (TypeError, ValueError):
        return 1


class ClaimBank:
    """Arguments for one case. `pkg` is the data package (or None); the case's own `facts` win."""

    def __init__(self, pkg, case):
        self.pkg, self.case = pkg, case
        self.facts = case.get("facts") or {}
        self.refs = list(case.get("refs") or [])

    def fact(self, ref):
        """The case's own fact, else the package's row (the Sunday release included), else None:
        a ref neither knows (the sandbox's demo world, a hidden case's new IDs) is cited without
        a figure by `demo_refs`. Every lookup is keyed by the case's part or supplier, so a known
        part keeps its drivers, forecasts and should-cost whatever the case's refs are."""
        if ref in self.facts:
            return self.facts[ref]
        return None if self.pkg is None else self.pkg.lookup(ref)

    def ids(self, prefix):
        out = set() if self.pkg is None else set(self.pkg.ids(prefix))
        out |= {k for k in self.facts if k.startswith(prefix)}
        out |= {r for r in self.refs if r.startswith(prefix)}
        return sorted(out)

    def query(self, sql, params=()):
        if self.pkg is None:
            return []
        try:
            return self.pkg.query(sql, params)
        except Exception:  # noqa: BLE001 - a package without SQLite: facts only
            return []

    # -- single arguments ------------------------------------------------------------------
    def should_cost(self, part, sid, quote):
        best = None
        for ref in self.ids("cost:"):
            f = self.fact(ref)
            if not f or f.get("part") != part or not f.get("unit_cost"):
                continue
            if ref.endswith("-" + sid.split(":")[-1]):
                best = (ref, f)
                break
            if best is None and "-" not in ref.split(":")[-1]:
                best = (ref, f)
        if not best:
            return None
        ref, f = best
        if quote and f["unit_cost"] >= quote * 0.98:
            return None  # above or near its price: argues its case
        return {
            "kind": "should_cost",
            "ids": [ref],
            "text": f"Our bottom-up should-cost estimate for this part is {money(f['unit_cost'])} per unit ({ref}).",
            "strength": 5,
        }

    def order_history(self, part, sid, quote):
        rows = self.query(
            "SELECT id FROM po_lines WHERE part_id = ? AND supplier_id = ? ORDER BY order_date DESC LIMIT 3",
            (part, sid),
        )
        facts = [(r["id"], self.fact(r["id"])) for r in rows]
        facts = [(i, f) for i, f in facts if f and f.get("unit_price")]
        if len(facts) < 2:
            return None
        prices = [f["unit_price"] for _, f in facts]
        unit = per_unit(facts[0][1])
        if quote and min(prices) / unit >= quote:
            return None  # the figure stays as recorded (per 100 or 1000 where priced so): that is what is checked
        ids = [i for i, _ in facts]
        each = f" per {unit} units" if unit != 1 else ""
        if len(set(prices)) == 1:
            text = f"Our last {len(ids)} orders for this part were at {money(prices[0])}{each} ({', '.join(ids)})."
        else:
            listed = " and ".join(money(p) for p in prices)
            text = f"Our last orders for this part were at {listed}{each} ({', '.join(ids)})."
        return {"kind": "order_history", "ids": ids, "text": text, "strength": 4}

    def notice(self):
        doc = self.case.get("trigger_doc")
        f = self.fact(doc) if doc else None
        if not f or f.get("days") is None:
            return None
        ctr = next((r for r in self.refs if r.startswith("ctr:") and "#" not in r), None)
        c = self.fact(ctr) if ctr else None
        if not c or c.get("days") is None or f["days"] >= c["days"]:
            return None
        text = (
            f"Your letter gives {f['days']} days' notice ({doc}); our agreement provides for {c['days']} days ({ctr})."
        )
        return {"kind": "notice", "ids": [doc, ctr], "text": text, "strength": 5}

    def move12(self, series):
        """The series' change over the last twelve months as a share (what suppliers cite), or None."""
        ids = self.ids(f"idx:{series}@")
        if not ids:
            return None
        m2 = ids[-1].split("@")[-1]
        a, b = self.fact(f"idx:{series}@{months_back(m2, 12)}"), self.fact(ids[-1])
        if not a or not b or not a.get("value") or not b.get("value"):
            return None
        return b["value"] / a["value"] - 1

    def index_change(self, series):
        """The largest fall of a series over any window of up to 12 months ending at its latest
        month (the window the arena checks). AS-14404 rose 5.9 % in twelve months but fell 5.5 %
        from June to September 2026: the second is the argument the distributors "take into
        account", the first would argue their case."""
        ids = self.ids(f"idx:{series}@")
        if not ids:
            return None
        m2 = ids[-1].split("@")[-1]
        b = self.fact(ids[-1])
        if not b or not b.get("value"):
            return None
        best = None
        for back in range(1, 13):
            m1 = months_back(m2, back)
            a = self.fact(f"idx:{series}@{m1}")
            if not a or not a.get("value"):
                continue
            pct = (b["value"] / a["value"] - 1) * 100
            if best is None or pct < best[0]:
                best = (pct, m1)
        if best is None or best[0] > -0.5:
            return None  # a rising driver confirms the supplier's case
        pct, m1 = best
        name = SERIES_NAME.get(series, f"The index {series}")
        return {
            "kind": "index",
            "ids": [f"idx:{series}@{m1}", f"idx:{series}@{m2}"],
            "text": f"{name} changed {pct:.1f}% from {m1} to {m2} (idx:{series}@{m1}, idx:{series}@{m2}).",
            "strength": 4 + min(3.0, abs(pct) / 2),  # a falling driver outranks notes and orders
        }

    def drivers(self, part):
        return [r["series_id"] for r in self.query("SELECT series_id FROM cost_drivers WHERE part_id = ?", (part,))]

    def forecast(self, part):
        ids = self.ids(f"fc:{part.split(':')[-1]}@")
        f = self.fact(ids[-1]) if ids else None
        if not f or (f.get("change_pct") or 0) <= 0:
            return None
        text = f"Our forecast for this part is up {f['change_pct']:.1f}% ({ids[-1]})."
        return {"kind": "forecast", "ids": [ids[-1]], "text": text, "strength": 2}

    def rival_quote(self, part, sid, price):
        """A quote of this case from another supplier, cheaper than this supplier's price."""
        out = []
        for ref in self.refs:
            f = self.fact(ref) if ref.startswith("quote:") else None
            if not f or f.get("part") != part or f.get("supplier") == sid or not price or not f.get("unit_price"):
                continue
            unit = per_unit(f)
            if f["unit_price"] / unit < price:
                each = f"per {unit} units" if unit != 1 else "per unit"
                out.append(
                    {
                        "kind": "rival",
                        "ids": [ref],
                        "text": f"We hold another quote for this part at {money(f['unit_price'])} {each} ({ref}).",
                        "strength": 6,
                        "rival": True,
                    }
                )
        return out

    def signal_notes(self, sid):
        """Its own words in our notes that weaken its case: material bought forward at fixed prices,
        an offer to open its calculation. Context for the person reading, not a checked figure."""
        out = []
        # through the ID index, not the SQL tables: the Sunday release's letters reach only the index
        docs = [(ref, self.fact(ref) or {}) for ref in self.ids("doc:")]
        docs = sorted((d for d in docs if d[1].get("supplier") == sid), key=lambda d: str(d[1].get("date")))
        hedged = r"covered at fixed prices|bought (their|our) [\w ,-]{1,60} forward|material covered until"
        for ref, d in reversed(docs):
            try:
                text = self.pkg.document(ref)
            except (FileNotFoundError, UnicodeDecodeError):
                text = ""
            if re.search(hedged, text, re.I):
                out.append(
                    {
                        "kind": "hedged",
                        "ids": [ref],
                        "text": f"Your letter of {d.get('date')} ({ref}) says your material is covered at fixed "
                        "prices, so recent index movements do not reach your costs yet.",
                        "strength": 5,
                    }
                )
            if re.search(r"walk (us|you) through (their|our) calculation", text, re.I):
                out.append(
                    {
                        "kind": "open_book",
                        "ids": [ref],
                        "text": f"In our call of {d.get('date')} ({ref}) you offered to walk us through your "
                        "calculation; we would welcome that now.",
                        "strength": 4,
                    }
                )
        seen, uniq = set(), []
        for c in out:
            if c["kind"] not in seen:
                seen.add(c["kind"])
                uniq.append(c)
        return uniq

    def scorecard(self, sid, quality):
        ids = self.ids(f"sc:{sid.split(':')[-1]}@")
        if not ids:
            return None
        f = self.fact(ids[-1])
        if f is None:  # demo world: cite without a figure
            text = f"We have reviewed your delivery performance in our supplier scorecard ({ids[-1]})."
            return {"kind": "scorecard", "ids": [ids[-1]], "text": text, "strength": 2}
        quarter = f.get("quarter") or ids[-1].split("@")[-1]
        if quality:
            if (f.get("ppm") or 0) < 1000:
                return None
            text = f"Your deliveries ran at {f['ppm']} ppm in {quarter} ({ids[-1]})."
        else:
            if (f.get("otd_pct") or 100) >= 90:
                return None
            text = f"Your on-time delivery was {f['otd_pct']}% in {quarter} ({ids[-1]})."
        return {"kind": "scorecard", "ids": [ids[-1]], "text": text, "strength": 2}

    def demo_refs(self):
        """Refs the package cannot resolve: cited without a figure."""
        words = {
            "cost": ("should_cost", "Our bottom-up should-cost estimate for this part is on file ({ids}).", 5),
            "po": ("order_history", "We compared your offer with our recent order prices for this part ({ids}).", 4),
        }
        out = []
        for kind, (name, text, strength) in words.items():
            ids = [r for r in self.refs if r.startswith(f"{kind}:") and self.fact(r) is None]
            if ids:
                out.append(
                    {"kind": name, "ids": ids[:3], "text": text.format(ids=", ".join(ids[:3])), "strength": strength}
                )
        doc = self.case.get("trigger_doc")
        ctr = next((r for r in self.refs if r.startswith("ctr:")), None)
        if doc and ctr and self.fact(doc) is None and self.case.get("type") == "price_increase":
            text = f"Your letter ({doc}) gives less notice than our agreement provides for ({ctr})."
            out.append({"kind": "notice", "ids": [doc, ctr], "text": text, "strength": 5})
        return out

    # -- per supplier ----------------------------------------------------------------------
    def for_supplier(self, sid, quote):
        """Every argument for this supplier that pushes our way, strongest first."""
        case, out = self.case, []
        quality = case.get("type") == "quality" or case["buyer"].get("category_goal") == "quality_first"
        single = len(case.get("parts") or []) == 1  # a bundle's price is not one part's order price
        for part in case.get("parts") or []:
            history = self.order_history(part, sid, quote) if single else None
            out += [c for c in (self.should_cost(part, sid, quote), history) if c]
            out += [c for c in (self.index_change(s) for s in self.drivers(part)) if c]
            out += self.rival_quote(part, sid, quote)
            if c := self.forecast(part):
                out.append(c)
        if c := self.notice():
            out.append(c)
        out += self.signal_notes(sid)
        if c := self.scorecard(sid, quality):
            out.append(c)
        out += self.demo_refs()
        seen, uniq = set(), []
        for c in sorted(out, key=lambda c: -c["strength"]):
            if tuple(c["ids"]) not in seen:
                seen.add(tuple(c["ids"]))
                uniq.append(c)
        return uniq


def rival_offer(sid, offer_id, price):
    """Another bidder's standing offer in this session, citable to the others."""
    return {
        "kind": "rival",
        "ids": [offer_id],
        "text": f"Another bidder offers {money(price)} per unit for this part ({offer_id}).",
        "strength": 7,
        "rival": True,
        "from": sid,
    }
