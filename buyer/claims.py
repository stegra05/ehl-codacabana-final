"""Claim bank: pre-verified data arguments, each one sentence with its figure next to its IDs.

The arena checks every cited ID against facts.json and the case's own facts; a wrong figure or an
unknown ID is `contradicted` and costs trust. So every figure is computed here exactly as the
arena computes it, and the model only chooses the wording around the sentences it is given.
Facts come from the package's facts.json (the Sunday release included), the case's `facts` and
its `refs`; SQL is used only for lookups the facts do not carry (cost drivers, order lines, news).
"""

import re

SERIES_THEME = {
    "PPI-D351": "energy",
    "PPI-D35": "energy",
    "SMARD-DA": "energy",
    "WB-NGEU": "energy",
    "LCI-C": "labour",
    "PPI-C241": "material",
    "PPI-C2431": "material",
    "WB-CU": "material",
    "WB-NI": "material",
    "WB-AL": "material",
    "WB-FEORE": "material",
    "CU-NOTATION": "material",
    "AS-14404": "material",
    "AS-14301": "material",
}
# When a part has no cost-driver row (a stranger's part), the series to answer a theme with.
THEME_SERIES = {"energy": ["PPI-D351"], "labour": ["LCI-C"], "material": ["PPI-C241"]}
SERIES_NAME = {
    "PPI-C2451": "Producer prices for iron castings",
    "PPI-C2452": "Producer prices for steel castings",
    "PPI-C2562": "Producer prices for machining",
    "PPI-C2511": "Producer prices for metal structures",
    "PPI-C2594": "Producer prices for fasteners",
    "PPI-C2711": "Producer prices for electric motors",
    "PPI-C2732": "Producer prices for wires and cables",
    "PPI-C2611": "Producer prices for electronic components",
    "PPI-C2612": "Producer prices for loaded boards",
    "PPI-C2815": "Producer prices for bearings and gears",
    "PPI-C241": "Producer prices for basic iron and steel",
    "PPI-C2431": "Producer prices for cold-drawn bars",
    "PPI-C2219": "Producer prices for rubber products",
    "PPI-C2813": "Producer prices for pumps and compressors",
    "PPI-D351": "Electricity producer prices",
    "PPI-D35": "Energy supply producer prices",
    "LCI-C": "Manufacturing labour costs",
    "WB-CU": "Copper",
    "WB-NI": "Nickel",
    "WB-AL": "Aluminium",
    "WB-NGEU": "European natural gas",
    "WB-FEORE": "Iron ore",
    "SMARD-DA": "Day-ahead power prices",
    "CU-NOTATION": "The copper notation",
    "AS-14404": "The 1.4404 alloy surcharge",
    "AS-14301": "The 1.4301 alloy surcharge",
}
THEME_WORDS = {
    "energy": re.compile(r"energy|electricit|power|gas\b", re.I),
    "labour": re.compile(r"wage|labour|labor|salar|personnel|staff cost", re.I),
    "material": re.compile(r"material|steel|iron|copper|nickel|alloy|scrap|raw", re.I),
    "freight": re.compile(r"freight|transport|logistic", re.I),
    "quality": re.compile(r"quality|ppm|complaint|defect|8d", re.I),
    "volume": re.compile(r"volume|quantit|forecast", re.I),
    "capacity": re.compile(r"capacity|lead time|backlog|order book", re.I),
    "currency": re.compile(r"currency|exchange rate|euro|usd|czk|pln|huf|try\b", re.I),
}
ID_RE = re.compile(r"\b(?:idx|quote|offer|sc|qn|po|cost|fc|news|doc|ctr):[\w.:@#/-]*\w")


def themes_in(text):
    """The cost themes a text names (a letter blaming energy and wages: energy, labour)."""
    return [t for t, rx in THEME_WORDS.items() if rx.search(text or "")]


def months_back(month, n):
    y, m = (int(x) for x in month.split("-"))
    m -= n
    while m <= 0:
        m, y = m + 12, y - 1
    return f"{y}-{m:02d}"


def _claim(kind, theme, ids, sentence, figure=None, strength=1.0, for_us=True):
    return {
        "kind": kind,
        "theme": theme,
        "ids": ids,
        "sentence": sentence,
        "figure": figure,
        "strength": strength,
        "for_us": for_us,
    }


class ClaimBank:
    """Arguments for one case, per supplier, ranked; `pick` hands out the next ones to cite."""

    def __init__(self, pkg, case):
        self.pkg, self.case = pkg, case
        self.case_facts = case.get("facts") or {}
        self.refs = list(case.get("refs") or [])
        # A case whose refs the package does not know at all (the sandbox's demo world) lives in
        # another data world: package IDs would come back contradicted there, so only its own
        # facts and refs are cited.
        self.foreign = bool(self.refs) and pkg is not None and not any(pkg.lookup(r) for r in self.refs)
        if self.foreign:
            self.pkg = None

    def fact(self, ref):
        return self.case_facts.get(ref) or (self.pkg.lookup(ref) if self.pkg else None)

    def ids(self, prefix):
        """Every citable ID with this prefix: the package, the case's facts and its refs."""
        out = set(self.pkg.ids(prefix)) if self.pkg else set()
        out |= {k for k in self.case_facts if k.startswith(prefix)}
        out |= {r for r in self.refs if r.startswith(prefix)}
        return sorted(out)

    def query(self, sql, params=()):
        try:
            return self.pkg.query(sql, params) if self.pkg else []
        except Exception:  # no SQLite in the package: facts only
            return []

    def series_for(self, theme):
        """Series that answer a theme: the defaults, plus any series the case's facts carry."""
        in_case = {k.split(":")[1].split("@")[0] for k in self.case_facts if k.startswith("idx:")}
        return list(
            dict.fromkeys(THEME_SERIES.get(theme, []) + sorted(s for s in in_case if SERIES_THEME.get(s) == theme))
        )

    def last_month(self, series):
        ids = self.ids(f"idx:{series}@")
        return ids[-1].split("@")[-1] if ids else None

    def index_claim(self, series, weight=1.0):
        """The change of one series over the last 12 months of its data, as the arena checks it."""
        m2 = self.last_month(series)
        if not m2:
            return None
        m1 = months_back(m2, 12)
        a, b = self.fact(f"idx:{series}@{m1}"), self.fact(f"idx:{series}@{m2}")
        if not a or not b or not a.get("value"):
            return None
        pct = (b["value"] / a["value"] - 1) * 100
        name = SERIES_NAME.get(series, f"The index {series}")
        return _claim(
            "index",
            SERIES_THEME.get(series, "market"),
            [f"idx:{series}@{m1}", f"idx:{series}@{m2}"],
            f"{name} changed {pct:+.1f}% from {m1} to {m2} (idx:{series}@{m1}, idx:{series}@{m2}).",
            figure=round(pct, 1),
            strength=abs(pct) * max(weight, 0.2) + (2.0 if pct <= 0 else 0.0),
            for_us=pct <= 0,
        )

    def driver_changes(self, part):
        """[(series, weight, change_pct)] for the part's cost drivers: the basis of a justified increase."""
        out = []
        for r in self.query("SELECT series_id, weight FROM cost_drivers WHERE part_id = ?", (part,)):
            c = self.index_claim(r["series_id"], r["weight"])
            if c:
                out.append((r["series_id"], r["weight"], c["figure"]))
        return out

    def should_cost(self, part, supplier_id):
        """The should-cost fact for a part: the supplier-specific one first, else the general one."""
        best = None
        for ref in self.ids("cost:"):
            f = self.fact(ref)
            if not f or f.get("part") != part or not f.get("unit_cost"):
                continue
            if f.get("supplier") == supplier_id:
                return ref, f
            if not f.get("supplier") and best is None:
                best = (ref, f)
        return best

    def scorecard_claim(self, supplier_id, quality=False):
        ids = self.ids(f"sc:{supplier_id.split(':')[-1]}@")
        f = self.fact(ids[-1]) if ids else None
        if not f:
            return None
        ref = ids[-1]
        if quality:
            text = f"Your deliveries ran at {f['ppm']} ppm in the twelve months to {f['quarter']} ({ref})."
        else:
            text = f"Your on-time delivery was {f['otd_pct']}% in the twelve months to {f['quarter']} ({ref})."
        bad = f.get("colour") in ("red", "amber")
        return _claim(
            "scorecard",
            "quality",
            [ref],
            text,
            figure=f["ppm"] if quality else f["otd_pct"],
            strength=3.0 if bad else 0.5,
            for_us=bad,
        )

    def should_cost_claim(self, part, supplier_id):
        found = self.should_cost(part, supplier_id)
        if not found:
            return None
        ref, f = found
        return _claim(
            "should_cost",
            "price",
            [ref],
            f"Our should-cost estimate for this part is EUR {f['unit_cost']:.2f} per unit ({ref}).",
            figure=f["unit_cost"],
            strength=2.5,
        )

    def po_claim(self, part, supplier_id):
        """Our last orders for the part: the case's po refs, else the package's order lines."""
        rows = [
            (r["id"], self.fact(r["id"]))
            for r in self.query(
                "SELECT id FROM po_lines WHERE part_id = ? AND supplier_id = ? "
                "AND price_note IS NOT 'stale_condition' ORDER BY order_date DESC LIMIT 3",
                (part, supplier_id),
            )
        ]
        rows += [(ref, self.fact(ref)) for ref in self.ids("po:") if ref not in {r[0] for r in rows}]
        rows = [(i, f) for i, f in rows if f and f.get("supplier") == supplier_id and f.get("part") == part]
        rows = sorted(rows, key=lambda r: r[1].get("date") or "", reverse=True)[:3]
        if len(rows) < 2:
            return None
        ids = [i for i, _ in rows]
        distinct = sorted({round(f["unit_price"], 2) for _, f in rows})
        if len(distinct) == 1:
            text = f"Our last {len(rows)} orders for this part were at EUR {distinct[0]:.2f} ({', '.join(ids)})."
        else:
            prices = " and ".join(f"EUR {f['unit_price']:.2f}" for _, f in rows)
            text = f"Our last orders for this part were at {prices} ({', '.join(ids)})."
        return _claim("po_history", "price_history", ids, text, strength=1.5)

    def notice_claim(self, supplier_id):
        doc = self.case.get("trigger_doc")
        f = self.fact(doc) if doc else None
        if not f or f.get("days") is None:
            return None
        ctr = next((r for r in self.refs if r.startswith("ctr:") and "#" not in r), None)
        if not ctr:
            rows = self.query(
                "SELECT id FROM contracts WHERE supplier_id = ? ORDER BY valid_to DESC LIMIT 1", (supplier_id,)
            )
            ctr = rows[0]["id"] if rows else None
        c = self.fact(ctr) if ctr else None
        if not c or c.get("days") is None:
            return None
        short = f["days"] < c["days"]
        return _claim(
            "notice",
            "notice",
            [doc, ctr],
            f"Your letter gives {f['days']} days' notice ({doc}); our agreement provides for {c['days']} days ({ctr}).",
            figure=f["days"],
            strength=4.0 if short else 0.3,
            for_us=short,
        )

    def forecast_claim(self, part):
        ids = self.ids(f"fc:{part.split(':')[-1]}@")
        f = self.fact(ids[-1]) if ids else None
        if not f or f.get("change_pct") is None or f["change_pct"] <= 0:
            return None
        return _claim(
            "forecast",
            "volume",
            [ids[-1]],
            f"Our forecast for this part changed {f['change_pct']:+.1f}% ({ids[-1]}).",
            figure=f["change_pct"],
            strength=1.0 + f["change_pct"] / 10,
        )

    def news_claims(self, supplier_id):
        rows = self.query(
            "SELECT id, topic, headline FROM news WHERE supplier_id = ? AND topic <> 'noise' "
            "ORDER BY date DESC LIMIT 2",
            (supplier_id,),
        )
        return [
            _claim("news", "context", [r["id"]], f"We read that {r['headline'].rstrip('.')} ({r['id']}).", strength=0.8)
            for r in rows
            if self.fact(r["id"])
        ]

    def quote_claims(self, supplier_id, part, their_price=None):
        out = []
        for ref in self.refs:
            f = self.fact(ref) if ref.startswith("quote:") else None
            if f and f.get("supplier") == supplier_id and f.get("part") == part:
                out.append(
                    _claim(
                        "quote",
                        "price_history",
                        [ref],
                        f"Your quote of {f.get('date')} was at EUR {f['unit_price']:.2f} per unit ({ref}).",
                        figure=f["unit_price"],
                        strength=1.2,
                    )
                )
        alt = self.case.get("buyer", {}).get("alternative") or {}
        f = self.fact(alt["ref"]) if alt.get("kind") == "quote" and alt.get("ref") else None
        if f and f.get("supplier") != supplier_id and f.get("part") == part:
            out.append(
                _claim(
                    "alternative",
                    "competition",
                    [alt["ref"]],
                    f"We hold a quote at EUR {f['unit_price']:.2f} per unit for this part ({alt['ref']}).",
                    figure=f["unit_price"],
                    strength=3.0,
                    for_us=their_price is None or f["unit_price"] < their_price,
                )
            )
        return out

    def ref_only_claims(self):
        """Refs the case points to that no fact resolves (a stranger's data): cited without a
        figure, the arena takes the data's own value, so the claim is true by construction."""
        words = {
            "sc": "We have reviewed your delivery performance in our supplier scorecard ({ids}).",
            "cost": "We have a bottom-up should-cost estimate for this part ({ids}).",
            "po": "We have compared your offer with our recent order prices for this part ({ids}).",
            "fc": "Our latest forecast for this part is on file ({ids}).",
        }
        out = []
        for kind, text in words.items():
            ids = [r for r in self.refs if r.startswith(f"{kind}:") and not self.fact(r)]
            if ids:
                out.append(_claim(f"ref_{kind}", "context", ids[:3], text.format(ids=", ".join(ids[:3])), strength=0.4))
        return out

    def rival_claims(self, supplier_id, threads):
        """Other bidders' standing offers in this session (RFQ): citable to everyone but their author,
        and only when cheaper than the supplier's own standing offer."""
        from arena_kit.play import latest, standing

        out = []
        mine = standing(threads[supplier_id])[1].get("unit_price") if supplier_id in threads else None
        for sid, events in threads.items():
            if sid == supplier_id or latest(events).get("status") in ("walked_away", "no_bid"):
                continue
            offer_id, terms = standing(events)
            if offer_id and terms.get("unit_price") and (mine is None or terms["unit_price"] < mine):
                out.append(
                    _claim(
                        "rival",
                        "competition",
                        [offer_id],
                        f"Another bidder quotes EUR {terms['unit_price']:.2f} per unit for this part ({offer_id}).",
                        figure=terms["unit_price"],
                        strength=3.5,
                    )
                )
        return out

    def for_supplier(self, supplier_id, persona, threads=None, themes=()):
        """Every claim that fits this case and this supplier, strongest first. `themes`: what the
        supplier's letter or quote blames, answered with the matching series when the part has
        no cost-driver row."""
        case, goal = self.case, self.case.get("buyer", {}).get("category_goal")
        guard = persona.get("relationship", {})
        parts = case.get("parts") or []
        their_price = None
        if threads and supplier_id in threads:
            from arena_kit.play import standing

            their_price = standing(threads[supplier_id])[1].get("unit_price")
        out = []
        for part in parts:
            drivers = self.driver_changes(part)
            for series, weight, _ in drivers:
                if c := self.index_claim(series, weight):
                    out.append(c)
            if not drivers:
                for theme in themes:
                    for series in self.series_for(theme):
                        if c := self.index_claim(series, 0.3):
                            out.append(c)
            if goal in ("leverage", "routine") or case.get("type") in ("rfq", "bundling"):
                if (c := self.should_cost_claim(part, supplier_id)) and not guard.get("protect"):
                    out.append(c)
            if case.get("type") in ("price_increase", "renewal", "raw_material"):
                if c := self.po_claim(part, supplier_id):
                    out.append(c)
            if c := self.forecast_claim(part):
                out.append(c)
            out += self.quote_claims(supplier_id, part, their_price)
        if case.get("type") == "price_increase":
            if c := self.notice_claim(supplier_id):
                out.append(c)
        quality_case = case.get("type") == "quality" or goal == "quality_first"
        if c := self.scorecard_claim(supplier_id, quality=quality_case):
            if quality_case or c["for_us"]:
                out.append(c)
        out += self.news_claims(supplier_id)
        if len(case.get("suppliers") or []) == 1:
            out += self.ref_only_claims()
        if goal in ("stabilise", "secure_supply"):
            out = [c for c in out if c["theme"] != "competition"]
        seen, uniq = set(), []
        for c in sorted(out, key=lambda c: -c["strength"]):
            key = tuple(c["ids"])
            if key not in seen:
                seen.add(key)
                uniq.append(c)
        return uniq

    @staticmethod
    def pick(claims, used_ids, themes=(), dropped=(), n=2, only_for_us=True):
        """The next `n` claims: unused IDs, not on a theme the supplier rejected, the ones that
        answer its own stated reasons first, then by strength."""

        def fit(c):
            return (c["theme"] in themes, c["strength"])

        out = []
        for c in sorted(claims, key=fit, reverse=True):
            if any(i in used_ids for i in c["ids"]) or c["theme"] in dropped:
                continue
            if only_for_us and not c["for_us"] and c["theme"] not in themes:
                continue
            out.append(c)
            if len(out) >= n:
                break
        return out
