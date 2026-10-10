"""The model layer: it reads the supplier's prose into signals and words our e-mail. It never
sets a term or a figure. Every call has a hard timeout well inside the 60-second clock and
returns None on any failure, so the caller falls back to a deterministic move."""

import json
import logging
import os

log = logging.getLogger("negotiator")

DEFAULT_MODEL = "claude-opus-5-5"
READER_S, WRITER_S, OFFLINE_S = 14.0, 16.0, 60.0

READER_SYSTEM = """You read a supplier's e-mail in an industrial procurement negotiation, for the buyer.
Report only what the e-mail says or clearly implies, as JSON. Themes name the cost drivers the supplier
blames or cites (energy, labour, material, freight, quality, volume, capacity, currency, other).
`interested_in` lists the term fields the supplier shows interest in or asked for (faster payment -> payment_days,
longer commitment -> contract_months, more volume -> volume_per_year, a later or earlier start -> effective_date,
delivery dates -> lead_time_days, index pricing -> index_clause, tooling -> tooling_eur,
quality terms -> ppm_commitment).
`rejected_themes` are themes the supplier dismissed as irrelevant or "not our reality".
`needs_approval` is true when the supplier says a move needs its boss, head office or management."""

READER_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "stated_reasons": {"type": "array", "items": {"type": "string"}},
        "cost_driver_themes": {
            "type": "array",
            "items": {
                "type": "string",
                "enum": [
                    "energy",
                    "labour",
                    "material",
                    "freight",
                    "quality",
                    "volume",
                    "capacity",
                    "currency",
                    "other",
                ],
            },
        },
        "interested_in": {
            "type": "array",
            "items": {
                "type": "string",
                "enum": [
                    "unit_price",
                    "payment_days",
                    "volume_per_year",
                    "contract_months",
                    "effective_date",
                    "lead_time_days",
                    "index_clause",
                    "incoterm",
                    "tooling_eur",
                    "ppm_commitment",
                    "chargeback_eur_per_complaint",
                ],
            },
        },
        "rejected_themes": {"type": "array", "items": {"type": "string"}},
        "needs_approval": {"type": "boolean"},
        "mood": {"type": "string", "enum": ["warm", "neutral", "cool", "irritated"]},
        "walk_risk": {"type": "string", "enum": ["low", "medium", "high"]},
        "questions_to_us": {"type": "array", "items": {"type": "string"}},
        "offers_document": {"type": "string"},
        "cheaper_variant": {"type": "string"},
    },
    "required": [
        "summary",
        "stated_reasons",
        "cost_driver_themes",
        "interested_in",
        "rejected_themes",
        "needs_approval",
        "mood",
        "walk_risk",
        "questions_to_us",
        "offers_document",
        "cheaper_variant",
    ],
    "additionalProperties": False,
}

WRITER_SYSTEM = """You word the buyer's e-mail for Hollerau Pumpenwerke, a German pump maker, to one of its suppliers.
The buyer's analysts have fixed everything with a number: the term sheets, the figures and the data arguments.
You only write the prose around them.

Rules:
- A short business e-mail in plain English, at most 150 words: thanks, the arguments, the options in plain
  words, one question, a short close. No subject line, no placeholders.
- Include every DATA ARGUMENT sentence exactly as given, word for word, including the IDs in brackets.
- State the OPTIONS with exactly the figures given. Do not invent any price, percentage, date or ID.
- Never mention urgency, deadlines, budgets, targets, reservation prices, an alternative you lack, or that
  the supplier is the only source. Never threaten. Never promise what the options do not say.
- Match the TONE: warm means appreciative and personal; neutral means courteous and factual; firm means
  direct and factual, still polite. No sarcasm, no flattery.
- Sign off as "Hollerau Pumpenwerke, Purchasing"."""

LESSONS_SYSTEM = """You review a finished e-mail negotiation between a buyer (Hollerau Pumpenwerke) and a supplier.
Write at most three short lessons about THIS supplier for the next negotiation: what moved it, what did not,
what to do differently. Each lesson one sentence, concrete, no hedging. JSON only."""

DIGEST_SYSTEM = """You read a buyer's notes, letters and news about one supplier. Extract, as JSON: the supplier's
current situation in one sentence; what moves it in a negotiation (a short list); what it resists (a short list);
one sentence of tone advice for writing to it. Only what the notes support."""

DIGEST_SCHEMA = {
    "type": "object",
    "properties": {
        "situation": {"type": "string"},
        "what_moves_them": {"type": "array", "items": {"type": "string"}},
        "what_they_resist": {"type": "array", "items": {"type": "string"}},
        "tone_advice": {"type": "string"},
    },
    "required": ["situation", "what_moves_them", "what_they_resist", "tone_advice"],
    "additionalProperties": False,
}
LESSONS_SCHEMA = {
    "type": "object",
    "properties": {"lessons": {"type": "array", "items": {"type": "string"}}},
    "required": ["lessons"],
    "additionalProperties": False,
}


class LLM:
    def __init__(self, model=None, effort=None, client=None):
        import anthropic

        self.model = model or os.environ.get("LLM_MODEL") or DEFAULT_MODEL
        self.effort = effort or os.environ.get("LLM_EFFORT") or "low"
        self.client = client or anthropic.Anthropic(max_retries=0)

    def _call(self, system, user, timeout, max_tokens, schema=None):
        """One request; a refusal or any error is None (the caller has a deterministic fallback)."""
        import anthropic

        output_config = {"effort": self.effort}
        if schema:
            output_config["format"] = {"type": "json_schema", "schema": schema}
        try:
            r = self.client.with_options(timeout=timeout).beta.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
                output_config=output_config,
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
        except anthropic.APITimeoutError:
            log.warning("LLM timed out after %.0fs", timeout)
            return None
        except anthropic.APIStatusError as e:
            log.warning("LLM error %s: %s", e.status_code, getattr(e, "message", e))
            return None
        except anthropic.APIConnectionError as e:
            log.warning("LLM connection error: %s", e)
            return None
        if r.stop_reason == "refusal":
            log.warning("LLM refused the request")
            return None
        text = "".join(b.text for b in r.content if b.type == "text").strip()
        if not schema:
            return text or None
        try:
            return json.loads(text)
        except ValueError:
            log.warning("LLM returned no JSON")
            return None

    def read_reply(self, supplier_name, body, status, claim_results=None):
        user = (
            f"SUPPLIER: {supplier_name}\nSTATUS: {status}\nCLAIM CHECKS: {json.dumps(claim_results or [])}\n\n"
            f"E-MAIL:\n{body[:6000]}"
        )
        return self._call(READER_SYSTEM, user, READER_S, 1500, READER_SCHEMA)

    def write_email(self, brief):
        """`brief`: the plain-text brief built by the agent (tone, their mail, options, arguments, question)."""
        return self._call(WRITER_SYSTEM, brief, WRITER_S, 900)

    def lessons(self, transcript):
        out = self._call(LESSONS_SYSTEM, transcript[:30000], OFFLINE_S, 800, LESSONS_SCHEMA)
        return (out or {}).get("lessons") or None

    def digest_notes(self, name, notes, headlines):
        user = (
            f"SUPPLIER: {name}\n\nNEWS:\n"
            + "\n".join(f"- {h}" for h in headlines)
            + f"\n\nNOTES AND LETTERS:\n{notes[:20000]}"
        )
        return self._call(DIGEST_SYSTEM, user, OFFLINE_S, 1200, DIGEST_SCHEMA)


def from_env():
    """An LLM when a key or an `ant auth` profile is available, else None (template moves only)."""
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return None
    if not (
        os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN") or os.environ.get("LLM_FORCE")
    ):
        return None
    return LLM()
