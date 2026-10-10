"""Data package exploration: supplier profiles, persona signals, price fairness, case triggers.

Run: uv run --with pandas python analysis/explore.py [data/package]
Writes analysis/out/*.csv and analysis/out/explore.json (input for the report page).
"""

import json
import re
import sqlite3
import sys
from pathlib import Path

import pandas as pd

PKG = Path(sys.argv[1] if len(sys.argv) > 1 else "data/package")
OUT = Path(__file__).parent / "out"
OUT.mkdir(exist_ok=True)
db = sqlite3.connect(PKG / "world.sqlite")


def q(sql):
    return pd.read_sql_query(sql, db)


# Persona signals in call notes, meeting notes and e-mails. The generator writes each trait with
# one or two fixed phrasings, so plain patterns classify every note.
SIGNALS = {
    "cash_need": r"pay earlier|bank is watching|cash and the banks|within 10 days|under pressure"
    r"|restructures|short-time work|lowers rating",
    "spare_capacity": r"second shift has been on hold|take additional parts|looks for new customers",
    "capacity_full": r"order intake is very strong|binding 12-month commitment"
    r"|cannot confirm your full forecast|fully booked|allocates volumes",
    "open_book": r"walk us through their calculation",
    "stale_costing": r"not followed his material|own spreadsheet",
    "partnership_2022": r"kept supplying at the old price",
    "reference_customer": r"important reference customer",
    "approval_2pct": r"above 2 % need the approval",
    "deprioritising_us": r"reviewing small accounts|not strategic|reorganising our range"
    r"|supply from stock only|sharpens its focus",
    "price_frozen": r"no room on price|not discounted|price list applies to all|discounts not possible",
    "hedged": r"bought their \w+ forward|covered at fixed prices|material covered until|secures power prices",
    "complains_late_pay": r"invoices are overdue",
}
LEVER = {
    "cash_need": "pay faster (14-30 days) for price; it values cash over list price",
    "spare_capacity": "offer volume / extra parts; idle capacity makes a lower price cheap for it",
    "capacity_full": "trade a firm 12-24 month commitment for price and allocation",
    "open_book": "ask for the cost breakdown XLSX, argue line by line vs should-cost",
    "stale_costing": "index data disarms it: show the real index path since its last price",
    "partnership_2022": "acknowledge 2022, frame the deal as partnership; avoid hard threats",
    "reference_customer": "it values the reference: tone and long-term framing move it",
    "approval_2pct": "keep each move small (2 % or less) or give it time for its committee",
    "deprioritising_us": "weak leverage: bundle volume, or use the alternative",
    "price_frozen": "price will not move: trade payment days, logistics, call-off flexibility",
    "hedged": "market index arguments are 'not our reality' until its hedge ends",
    "complains_late_pay": "our late payment hurt trust: promise and keep payment terms",
}


def notes():
    """Every supplier text with its signals: documents, quote remarks and news."""
    docs = q("SELECT id, date, kind, supplier_id, subject, file FROM documents")
    docs["body"] = [" ".join((PKG / f).read_text().splitlines()[4:]).strip() for f in docs.file]
    quotes = q("""SELECT id, quote_date date, 'quote remark' kind, supplier_id, 'Quote remark' subject,
                         remarks body FROM quotes WHERE remarks != ''""")
    news = q("""SELECT id, date, 'news' kind, supplier_id, headline subject, headline || '. ' || body body
                FROM news WHERE supplier_id != ''""")
    df = pd.concat([docs.drop(columns="file"), quotes, news], ignore_index=True)
    df["signals"] = [[k for k, pat in SIGNALS.items() if re.search(pat, b, re.I)] for b in df.body]
    return df


def supplier_profiles(docs):
    sup = q("""
        SELECT s.id, s.name, s.country, s.category, s.payment_days, s.skonto_days, s.skonto_pct,
               s.incoterm, s.abc_class, i.owner_type, i.group_parent, i.staff, i.turnover_eur,
               i.turnover_band, i.equity_ratio_pct, i.credit_index, i.credit_index_12m_ago,
               i.vda63_grade
        FROM suppliers s JOIN supplier_intel i ON i.supplier_id = s.id WHERE s.detail = 'full'""")
    spend = q("""SELECT supplier_id id, spend_eur spend_fy26 FROM spend_cube WHERE fiscal_year='FY2026'""")
    spend = spend.groupby("id", as_index=False).sum()
    sc = q("""SELECT supplier_id id, otd_pct, otd_confirmed_pct, ppm, score, colour, open_8d_overdue
              FROM scorecards WHERE quarter='2026Q3'""")
    trend = q("""SELECT supplier_id id, group_concat(colour, '>') colour_trend
                 FROM (SELECT * FROM scorecards ORDER BY quarter) GROUP BY supplier_id""")
    # How late Hollerau pays, last 12 months (sup:71999 is the old record of sup:70210)
    pay = q("""
        SELECT CASE supplier_id WHEN 'sup:71999' THEN 'sup:70210' ELSE supplier_id END id,
               AVG(julianday(paid_date) - julianday(due_date)) days_late,
               AVG(julianday(paid_date) - julianday(due_date) > 5) share_late
        FROM invoices WHERE paid_date IS NOT NULL AND discount_taken = 0 AND invoice_date >= '2025-10-01'
        GROUP BY 1""")
    neg = q("""SELECT supplier_id id, COUNT(*) renewals, AVG(asked_pct) avg_asked,
                      AVG(settled_pct) avg_settled, AVG(asked_pct - settled_pct) avg_give
               FROM negotiation_history WHERE type = 'annual renewal' GROUP BY 1""")
    news = q("SELECT supplier_id id, group_concat(topic, ', ') news FROM news GROUP BY 1")
    sig = docs.explode("signals").dropna(subset=["signals"])
    sig = sig.groupby("supplier_id")["signals"].apply(lambda s: sorted(set(s))).rename("signals")
    p = sup
    for t in (spend, sc, trend, pay, neg, news):
        p = p.merge(t, on="id", how="left")
    p = p.merge(sig, left_on="id", right_index=True, how="left")
    p["signals"] = p["signals"].apply(lambda s: s if isinstance(s, list) else [])
    p["credit_change"] = p["credit_index"] - p["credit_index_12m_ago"]  # higher index = worse
    return p.sort_values("spend_fy26", ascending=False)


def price_fairness():
    """Per part and incumbent: current price, should-cost margin, index-implied change since the
    current price took effect, and what the supplier asks (trigger letters)."""
    cur = q("""
        SELECT pc.part_id, pc.supplier_id, pc.price, pc.price_unit, pc.valid_from, p.description,
               p.category, p.abc_class, s.country
        FROM price_conditions pc JOIN parts p ON p.id = pc.part_id JOIN suppliers s ON s.id = pc.supplier_id
        WHERE pc.valid_from = (SELECT MAX(valid_from) FROM price_conditions x
                               WHERE x.part_id = pc.part_id AND x.supplier_id = pc.supplier_id
                               AND x.valid_from <= '2026-09-30')""")
    sc = q("""SELECT part_id, supplier_id sc_supplier, cost_base, unit_cost, price_unit sc_unit,
                     confidence_pct FROM should_cost""")
    # Country factor for German-base should-cost (company.md rule of thumb, midpoints)
    factor = {"DE": 1.0, "AT": 1.05, "CH": 1.05, "CZ": 0.825, "PL": 0.825, "HU": 0.825, "TR": 0.75, "CN": 0.7}
    df = cur.merge(sc, on="part_id", how="left")
    own = df["sc_supplier"].notna()
    df = df[~own | (df["sc_supplier"] == df["supplier_id"])]
    df["full_cost_est"] = df["unit_cost"] * df["price_unit"] / df["sc_unit"]
    df.loc[~own, "full_cost_est"] *= df.loc[~own, "country"].map(factor).fillna(1.0)
    df["margin_pct"] = (df["price"] - df["full_cost_est"]) / df["price"] * 100

    # Index-implied change: cost-driver weights x index move from the month before the current
    # price took effect to each series' latest month.
    drivers = q("SELECT part_id, series_id, weight FROM cost_drivers")
    iv = q("SELECT series_id, month, value FROM index_values")
    last = iv.sort_values("month").groupby("series_id").last()
    moves = []
    for r in df.itertuples():
        ref_month = pd.Period(r.valid_from, "M") - 1
        tot = 0.0
        for d in drivers[drivers.part_id == r.part_id].itertuples():
            s = iv[(iv.series_id == d.series_id) & (iv.month <= str(ref_month))]
            if s.empty:
                continue
            tot += d.weight * (last.loc[d.series_id, "value"] / s.iloc[-1]["value"] - 1)
        moves.append(tot * 100)
    df["index_move_pct"] = moves
    return df


def triggers(docs, prof, fair):
    t = q("""SELECT id, date, kind, supplier_id, part_ids, subject, asked_pct, asked_price,
                    effective_date FROM documents WHERE id LIKE '%-P__' ORDER BY id""")
    t["case"] = t["id"].str[-3:]
    rows = []
    for r in t.itertuples():
        parts = (r.part_ids or "").split(";")
        f = fair[(fair.supplier_id == r.supplier_id) & (fair.part_id.isin(parts))]
        p = prof[prof.id == r.supplier_id]
        alts = q(f"""SELECT supplier_id, status FROM sourcing WHERE part_id IN ({",".join(repr(x) for x in parts)})
                     AND supplier_id != '{r.supplier_id}'""")
        subj = r.subject.lower()
        kind = (
            "price_increase"
            if pd.notna(r.asked_pct)
            else "index_clause"
            if "surcharge" in subj
            else "renewal"
            if "renewal" in subj
            else "capacity"
            if "capacity" in subj
            else "quality"
            if "escalation" in subj
            else "kit"
            if "kit" in subj
            else "rfq"
            if r.kind == "rfq"
            else "other"
        )
        rows.append(
            {
                "case": r.case,
                "type": kind,
                "supplier": r.supplier_id,
                "name": p["name"].iloc[0] if len(p) else "",
                "parts": r.part_ids,
                "asked_pct": r.asked_pct,
                "index_move_pct": round(f["index_move_pct"].mean(), 1) if len(f) else None,
                "margin_pct": round(f["margin_pct"].mean(), 1) if len(f) else None,
                "colour": p["colour"].iloc[0] if len(p) else None,
                "days_late": round(p["days_late"].iloc[0], 1) if len(p) else None,
                "signals": p["signals"].iloc[0] if len(p) else [],
                "margin_at_ask_pct": round((1 - f["full_cost_est"].mean() / r.asked_price) * 100, 1)
                if pd.notna(r.asked_price) and len(f) and f["full_cost_est"].notna().all()
                else None,
                "alternatives": "; ".join(sorted({f"{a.supplier_id} ({a.status})" for a in alts.itertuples()})),
            }
        )
    return pd.DataFrame(rows)


def negotiation_events():
    return q("""SELECT n.*, s.category, s.country FROM negotiation_history n
                JOIN suppliers s ON s.id = n.supplier_id""")


def main():
    docs = notes()
    prof = supplier_profiles(docs)
    fair = price_fairness()
    trig = triggers(docs, prof, fair)
    neg = negotiation_events()
    spend = q("""SELECT fiscal_year, c.category, SUM(spend_eur) spend,
                        SUM(CASE WHEN s.detail='full' THEN spend_eur ELSE 0 END) detailed
                 FROM spend_cube c JOIN suppliers s ON s.id = c.supplier_id GROUP BY 1, 2""")
    idx = q("""SELECT v.series_id, s.name, v.month, v.value FROM index_values v
               JOIN index_series s ON s.id = v.series_id WHERE v.month >= '2021-01'""")
    quotes = q("""SELECT q.*, r.purpose FROM quotes q JOIN rfqs r ON r.id = q.rfq_id""")
    # Second-source quotes against the incumbent's current price: how credible is the alternative?
    alt = quotes[quotes.purpose == "second-source benchmark"].merge(
        fair[["part_id", "supplier_id", "price", "description"]].rename(
            columns={"supplier_id": "incumbent", "price": "incumbent_price"}
        ),
        on="part_id",
    )
    alt = alt[alt.incumbent != alt.supplier_id]
    alt["premium_pct"] = (alt.unit_price / alt.incumbent_price - 1) * 100

    for name, df in dict(profiles=prof, fairness=fair, triggers=trig, notes=docs).items():
        df.to_csv(OUT / f"{name}.csv", index=False)
    payload = {
        "profiles": prof,
        "fairness": fair,
        "triggers": trig,
        "negotiations": neg,
        "spend": spend,
        "index": idx,
        "quotes": quotes,
        "alt_quotes": alt[
            [
                "part_id",
                "description",
                "incumbent",
                "incumbent_price",
                "supplier_id",
                "unit_price",
                "premium_pct",
                "payment_days",
                "lead_time_days",
            ]
        ],
        "notes": docs[["id", "date", "kind", "supplier_id", "subject", "body", "signals"]],
    }
    payload = {k: json.loads(v.to_json(orient="records")) for k, v in payload.items()}
    payload["levers"] = LEVER
    (OUT / "explore.json").write_text(json.dumps(payload))
    template = (Path(__file__).parent / "report.html").read_text()
    (OUT / "report.html").write_text(template.replace("__DATA__", json.dumps(payload)))

    pd.set_option("display.width", 250, "display.max_columns", 30, "display.max_rows", 100)
    print(
        prof[
            [
                "id",
                "name",
                "country",
                "category",
                "spend_fy26",
                "colour",
                "otd_pct",
                "ppm",
                "days_late",
                "avg_asked",
                "avg_settled",
                "credit_change",
                "signals",
            ]
        ].to_string()
    )
    print(trig.to_string())


if __name__ == "__main__":
    main()
