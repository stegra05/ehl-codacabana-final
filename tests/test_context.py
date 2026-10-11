"""Evidence must survive restart without treating a draft, claim or request as agreement."""

import copy
import json

from arena_kit.sim import load_cases

from buyer import analyst, context, writer


def test_delivered_evidence_preserves_conflicting_statements_and_exact_sheets():
    case = copy.deepcopy(load_cases()["case:S01"])
    events = [
        {
            "from": "supplier",
            "body": "We are hedged.",
            "term_sheets": [{"term_sheet_id": "old", "terms": {"unit_price": 12}}],
        },
        {
            "from": "buyer",
            "body": "Could you accept earlier payment?",
            "refs": ["doc:proof"],
            "term_sheets": [{"terms": {"unit_price": 10, "payment_days": 14}}],
        },
        {
            "from": "supplier",
            "body": "That is not our reality: material is covered at fixed prices.",
            "term_sheets": [{"term_sheet_id": "current", "terms": {"unit_price": 11, "payment_days": 30}}],
        },
    ]
    original = copy.deepcopy(events)
    state = context.snapshot(case, events)
    assert state == context.snapshot(case, json.loads(json.dumps(events)))
    assert state["standing_supplier_sheets"][0]["terms"]["payment_days"] == 30
    assert state["delivered_history"][1]["sheets"][0]["terms"]["payment_days"] == 14
    assert state["delivered_history"][1]["claim_feedback"] == []
    assert "covered at fixed prices" in state["delivered_history"][2]["text_excerpt"]
    state["delivered_history"][0]["sheets"][0]["terms"]["unit_price"] = 1
    assert events == original


def test_unrelated_events_and_pending_drafts_never_become_delivered_memory():
    case = load_cases()["case:S01"]
    events = [{"from": "supplier", "body": "x" * 900, "term_sheets": []}]
    state = context.snapshot(case, events)
    assert len(state["delivered_history"]) == 1
    assert state["delivered_history"][0]["text_truncated"]
    assert len(state["delivered_history"][0]["text_excerpt"]) == 800
    assert state["standing_supplier_sheets"] == []
    assert "draft_proposal" not in state


def test_existing_model_calls_receive_history_without_extra_call():
    case = load_cases()["case:S01"]
    state = context.snapshot(case, [{"from": "supplier", "body": "We refused the earlier payment request."}])
    calls = []

    def complete(system, user):
        calls.append(user)
        return json.dumps({"tactic": "steady", "notes": "Payment request was refused."})

    answer = analyst.read(complete, case, "Our offer stands.", [], [], evidence=state)
    assert answer["tactic"] == "steady" and len(calls) == 1
    assert "We refused the earlier payment request." in calls[0]
    brief = writer.brief(case, {}, "Our offer stands.", [], "warm", False, evidence=state)
    assert "We refused the earlier payment request." in brief
    assert "unverified" in brief and "not accepted" in brief
