"""The model layer: it reads the supplier's prose into signals and words our e-mail. It never
sets a term or a figure. Every call has a hard timeout well inside the 60-second clock and
returns None on any failure, so the caller falls back to a deterministic move.

Provider from .env: LLM_PROVIDER=anthropic (default when ANTHROPIC_API_KEY is set; LLM_MODEL,
LLM_EFFORT) or openai (any OpenAI-compatible endpoint: LLM_BASE_URL, LLM_MODEL, LLM_API_KEY).
LLM_WRITER_MODEL lets a smaller model word the e-mails."""

import json
import logging
import os
import re

log = logging.getLogger("buyer")

DEFAULT_MODEL = "claude-opus-5-5"
READER_S, WRITER_S = 14.0, 16.0

READER_SYSTEM = """You read a supplier's e-mail in an industrial procurement negotiation, for the buyer.
Report only what the e-mail says or clearly implies, as JSON. Themes name the cost drivers the supplier
blames or cites (energy, labour, material, freight, quality, volume, capacity, currency, other).
`interested_in` lists the term fields the supplier shows interest in or asked for (faster payment -> payment_days,
longer commitment -> contract_months, more volume -> volume_per_year, a later or earlier start -> effective_date,
delivery dates -> lead_time_days, index pricing -> index_clause, tooling -> tooling_eur,
quality terms -> ppm_commitment).
`rejected_themes` are themes the supplier dismissed as irrelevant or "not our reality".
`needs_approval` is true when the supplier says a move needs its boss, head office or management.
`cheaper_variant` names a cheaper engineering or process variant the supplier mentions, else an empty string.
`offers_document` names a document it offers or attached (cost breakdown, 8D, schedule), else an empty string."""

READER_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
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
        "offers_document": {"type": "string"},
        "cheaper_variant": {"type": "string"},
    },
    "required": [
        "summary",
        "cost_driver_themes",
        "interested_in",
        "rejected_themes",
        "needs_approval",
        "mood",
        "walk_risk",
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
- Sign off as "Hollerau Pumpenwerke, Purchasing". Reply with the e-mail body only."""


class LLM:
    def __init__(self, provider=None, model=None, writer_model=None, effort=None):
        self.provider = (
            provider
            or os.environ.get("LLM_PROVIDER")
            or ("anthropic" if os.environ.get("ANTHROPIC_API_KEY") else "openai")
        )
        self.model = model or os.environ.get("LLM_MODEL") or DEFAULT_MODEL
        self.writer_model = writer_model or os.environ.get("LLM_WRITER_MODEL") or self.model
        self.effort = effort or os.environ.get("LLM_EFFORT") or "low"
        self.client = None
        if self.provider == "anthropic":
            import anthropic

            self.client = anthropic.Anthropic(max_retries=0)

    def _call(self, system, user, timeout, max_tokens, schema=None, model=None):
        """One request; any error is None (the caller has a deterministic fallback)."""
        try:
            if self.provider == "anthropic":
                text = self._anthropic(system, user, timeout, max_tokens, schema, model or self.model)
            else:
                text = self._openai(system, user, timeout, max_tokens, schema, model or self.model)
        except Exception as e:  # timeout, rate limit, network, refusal: all degrade to the template
            log.warning("LLM failed (%s: %s)", type(e).__name__, str(e)[:200])
            return None
        if not text:
            return None
        if not schema:
            return text.strip()
        match = re.search(r"\{.*\}", text, re.S)
        try:
            return json.loads(match.group(0)) if match else None
        except ValueError:
            log.warning("LLM returned no JSON")
            return None

    def _anthropic(self, system, user, timeout, max_tokens, schema, model):
        output_config = {"effort": self.effort}
        if schema:
            output_config["format"] = {"type": "json_schema", "schema": schema}
        r = self.client.with_options(timeout=timeout).beta.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
            output_config=output_config,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
        if r.stop_reason == "refusal":
            log.warning("LLM refused the request")
            return None
        return "".join(b.text for b in r.content if b.type == "text")

    def _openai(self, system, user, timeout, max_tokens, schema, model):
        import httpx

        base = os.environ.get("LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/")
        headers = {"Authorization": f"Bearer {os.environ.get('LLM_API_KEY', '')}"}
        if schema:
            system = f"{system}\n\nReply with one JSON object matching this schema:\n{json.dumps(schema)}"
        body = {
            "model": model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        }
        r = httpx.post(f"{base}/chat/completions", json=body, headers=headers, timeout=timeout)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]

    def read_reply(self, supplier_name, body, status, claim_results=None):
        user = (
            f"SUPPLIER: {supplier_name}\nSTATUS: {status}\nCLAIM CHECKS: {json.dumps(claim_results or [])}\n\n"
            f"E-MAIL:\n{body[:6000]}"
        )
        return self._call(READER_SYSTEM, user, READER_S, 4000, READER_SCHEMA)

    def write_email(self, brief):
        """`brief`: the plain-text brief built by the thread (tone, their mail, options, arguments, question)."""
        return self._call(WRITER_SYSTEM, brief, WRITER_S, 3000, model=self.writer_model)


def from_env():
    """An LLM when a key is configured, else None (template moves only)."""
    provider = os.environ.get("LLM_PROVIDER")
    if provider == "anthropic" or (not provider and os.environ.get("ANTHROPIC_API_KEY")):
        return LLM("anthropic")
    if provider == "openai" and os.environ.get("LLM_API_KEY"):
        return LLM("openai")
    return None
