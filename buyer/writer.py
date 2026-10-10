"""E-mails from templates: every figure and ID comes from code, the wording stays polite and
factual. Never mentions urgency, a budget, our alternative's absence or our target."""

FIELDS = {
    "payment_days": lambda v: f"payment {v} days net",
    "contract_months": lambda v: f"{v} months" if v else "a single order",
    "volume_per_year": lambda v: f"{v} units a year",
    "lead_time_days": lambda v: f"lead time {v} days",
    "effective_date": lambda v: f"valid from {v}",
    "incoterm": lambda v: f"delivery {v}",
    "tooling_eur": lambda v: f"tooling EUR {v:.0f}" if v else "no tooling charge",
    "ppm_commitment": lambda v: f"{v} ppm",
    "chargeback_eur_per_complaint": lambda v: f"chargeback EUR {v:.0f} per complaint",
    "index_clause": lambda v: (
        f"price follows {v['series']} on {round(v['material_share'] * 100)}% of the price, "
        f"deadband {v['deadband_pct']}%"
        if v
        else "fixed price"
    ),
}


def describe(case, sheet):
    parts = [f"EUR {sheet['unit_price']:.2f} per unit"]
    for field in case["negotiable"]:
        if field != "unit_price" and field in sheet and field in FIELDS:
            parts.append(FIELDS[field](sheet[field]))
    return ", ".join(parts)


def email(case, sheets, claims, question=None, first=False, moved=False, warm=True):
    lines = ["Dear Sir or Madam,", ""]
    if first:
        lines.append("Thank you for your offer and for the time your team has put into it.")
    elif moved:
        lines.append("Thank you for your reply and for the step you have taken.")
    else:
        lines.append("Thank you for your reply.")
    if warm:
        lines.append("We value our cooperation and would like to reach an agreement that works for both sides.")
    if claims:
        lines.append("")
        lines += [c["text"] for c in claims]
    lines.append("")
    if len(sheets) == 1:
        lines.append(f"On this basis we propose: {describe(case, sheets[0])}.")
    else:
        lines.append("On this basis we propose one of these packages:")
        lines += [f"- Option {chr(65 + i)}: {describe(case, s)}" for i, s in enumerate(sheets)]
    if question:
        lines += ["", question]
    lines += ["", "Kind regards,", "Hollerau Pumpenwerke, Purchasing"]
    return "\n".join(lines)


def keepalive():
    return (
        "Dear Sir or Madam,\n\nthank you for your offer, which we are reviewing internally. Could you confirm "
        "how long it remains valid?\n\nKind regards,\nHollerau Pumpenwerke, Purchasing"
    )
