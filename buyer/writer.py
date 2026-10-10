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
        f"price follows {v.get('series')} on {round((v.get('material_share') or 0) * 100)}% of the price, "
        f"deadband {v.get('deadband_pct') or 0}%"
        if v
        else "fixed price"
    ),
}


def describe(case, sheet):
    parts = [f"EUR {sheet['unit_price']:.2f} per unit"]
    for field in case["negotiable"]:
        if field != "unit_price" and field in sheet and field in FIELDS:
            parts.append(FIELDS[field](sheet[field]))
    fixed = case.get("fixed_terms") or {}
    volume = sheet.get("volume_per_year") or fixed.get("volume_per_year") or case["buyer"]["need_per_year"]
    months = sheet.get("contract_months") or fixed.get("contract_months")
    span = f" over {months} months" if months else ""
    if "volume_per_year" not in case["negotiable"]:
        parts.append(f"for our full demand of {volume} units a year{span}")
    return ", ".join(parts)


# Sandbox D01, identical sheets, only the words varied: plain 50.00, firm 49.90, warm 49.60,
# asking what it needs 49.40 (docs/learnings.md). Asking invites the trade it wants.
ASK = "What would you need from us to move further on the price? We are open to discussing any term that helps you."


def email(case, sheets, claims, statements=(), first=False, moved=False, warm=True, paragraph=None):
    """The e-mail: our words (the model's paragraph, else the template's), then the code sentences
    that answer its asks (figures without IDs), the data arguments and the proposal exactly as code
    computed them."""
    lines = ["Dear Sir or Madam,", ""]
    if first:
        lines.append("Thank you for your offer and for the time your team has put into it.")
    elif moved:
        lines.append("Thank you for your reply and for the step you have taken; we appreciate it.")
    else:
        lines.append("Thank you for your reply.")
    if paragraph:
        lines.append(paragraph)
    elif warm:
        lines.append(
            "We value our cooperation and we understand the cost pressure on your side; we want an agreement "
            "that keeps our partnership healthy for both of us."
        )
    else:
        lines.append("We want an agreement that works for both sides.")
    if statements:
        lines.append("")
        lines += list(statements)
    if claims:
        lines.append("")
        lines += [c["text"] for c in claims]
    lines.append("")
    if len(sheets) == 1:
        lines.append(f"On this basis we propose: {describe(case, sheets[0])}.")
    else:
        lines.append("On this basis we propose one of these packages:")
        lines += [f"- Option {chr(65 + i)}: {describe(case, s)}" for i, s in enumerate(sheets)]
    if first and not paragraph:
        lines += ["", ASK]
    lines += ["", "Kind regards,", "Hollerau Pumpenwerke, Purchasing"]
    return "\n".join(lines)


TRAITS = {
    "cash_need": "it is short of cash; when it gets paid matters a lot to it",
    "capacity_full": "it is fully booked; delivery time and a firm commitment matter to it",
    "spare_capacity": "it has free capacity and wants work for its machines",
    "price_frozen": "its management has frozen price cuts; other terms can move",
    "approval_2pct": "larger price steps need its pricing committee's approval",
    "deprioritising_us": "it focuses on customers with larger volumes",
    "hedged": "it bought its material forward at fixed prices",
    "open_book": "its owner once offered to walk us through its calculation",
    "stale_costing": "its costing has not followed the actual material prices",
    "partnership_2022": "it kept supplying at the old price during the 2022 crisis",
    "reference_customer": "it values having our company as a reference customer",
    "complains_late_pay": "it complained that our invoices were paid late",
}
OWNERS = {
    "family": "a family-owned company where the relationship matters",
    "group": "part of a larger group with formal approvals",
    "founder": "a small founder-run shop",
    "private": "a privately held company",
}


def brief(case, prof, last_body, facts, tone, question_allowed):
    """What the model needs for the paragraph: who the supplier is, what it wrote, what we may say."""
    who = OWNERS.get(prof.get("owner_type"), "a supplier")
    if prof.get("country") and prof.get("country") != "DE":
        who += f" based in {prof['country']}"
    traits = [TRAITS[s] for s in prof.get("signals", []) if s in TRAITS]
    out = [
        f"CASE: {case.get('title')} (we are the buyer; goal: {case['buyer'].get('category_goal')})",
        f"SUPPLIER: {who}." + (f" From our notes: {'; '.join(traits)}." if traits else ""),
        f"ITS LAST E-MAIL:\n{(last_body or '')[:1800]}",
        "WHAT WE CAN SAY:",
        *[f"- {f}" for f in facts],
        f"TONE: {tone}",
        f"QUESTION ALLOWED: {'yes' if question_allowed else 'no'}",
    ]
    return "\n".join(out)


def keepalive():
    return (
        "Dear Sir or Madam,\n\nthank you for your offer, which we are reviewing internally. Could you confirm "
        "how long it remains valid?\n\nKind regards,\nHollerau Pumpenwerke, Purchasing"
    )
