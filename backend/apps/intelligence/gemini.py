"""External AI adapter for part intelligence: Gemini through the official Google Gen AI SDK (google-genai).

One call = one attempt. Retries, rate limits, the budget and caching are decided by apps.intelligence.service, so the
SDK's own retry is switched off. The API key comes from the backend environment only; it never appears in results,
errors, logs or the web app (error text is scrubbed of it before it leaves this module).

The response must be JSON that matches SUGGESTION_SCHEMA (sent as the response schema) and then passes the stricter
local validation in `validate` (pydantic). Anything else is an invalid response, never a partial suggestion.
"""
import json
import re
import time
from dataclasses import dataclass, field
from typing import Literal

from django.conf import settings
from pydantic import BaseModel, ConfigDict, Field, ValidationError

CATEGORIES = ["mechanical", "electrical", "electronic", "other", "unknown"]
SCREENING = ["candidate", "possible_with_engineering_review", "unlikely", "insufficient_information"]
PROCESSES = ["metal_powder_bed_fusion", "directed_energy_deposition", "binder_jetting", "polymer_powder_bed_fusion",
             "material_extrusion", "none"]
MATERIAL_BASIS = ["stated_in_description", "typical_for_part_type", "not_determinable"]


class MaterialSuggestion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: str = Field(max_length=200)
    basis: Literal["stated_in_description", "typical_for_part_type", "not_determinable"]


class Suggestion(BaseModel):
    """What the model may propose. There is deliberately no price, cost, supplier, OEM part number or approval field."""

    model_config = ConfigDict(extra="forbid")
    expanded_description: str = Field(max_length=400)
    part_family: str = Field(max_length=160)
    category: Literal["mechanical", "electrical", "electronic", "other", "unknown"]
    function: str = Field(max_length=400)
    is_assembly: Literal["yes", "no", "unknown"]
    material: MaterialSuggestion
    am_screening: Literal["candidate", "possible_with_engineering_review", "unlikely", "insufficient_information"]
    am_process_options: list[Literal["metal_powder_bed_fusion", "directed_energy_deposition", "binder_jetting",
                                     "polymer_powder_bed_fusion", "material_extrusion", "none"]] = Field(max_length=6)
    rationale: str = Field(max_length=1200)
    risks: list[str] = Field(max_length=8)
    information_needed: list[str] = Field(max_length=10)
    confidence: float = Field(ge=0, le=1)
    uncertainty: str = Field(max_length=600)


def _s(desc, **kw):
    return {"type": "string", "description": desc, **kw}


SUGGESTION_SCHEMA = {
    "type": "object",
    "properties": {
        "expanded_description": _s("The material description written out in plain words (abbreviations expanded)."),
        "part_family": _s("Generic part family, e.g. 'wear ring', 'mechanical seal'."),
        "category": _s("Technical category.", enum=CATEGORIES),
        "function": _s("What this kind of part typically does in the equipment."),
        "is_assembly": _s("Whether this is normally an assembly of several components.", enum=["yes", "no", "unknown"]),
        "material": {"type": "object", "properties": {
            "value": _s("Material as stated in the description, or the typical material class for this part type, or 'not determinable'."),
            "basis": _s("Where the material comes from.", enum=MATERIAL_BASIS)}, "required": ["value", "basis"]},
        "am_screening": _s("Preliminary additive-manufacturing screening suggestion. Not an approval.", enum=SCREENING),
        "am_process_options": {"type": "array", "items": _s("AM process family.", enum=PROCESSES), "maxItems": 6},
        "rationale": _s("Short reasoning based only on the given data."),
        "risks": {"type": "array", "items": _s("A technical risk or concern."), "maxItems": 8},
        "information_needed": {"type": "array", "items": _s("Information an engineer needs before deciding."), "maxItems": 10},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1,
                       "description": "Confidence in the classification (0 = none, 1 = certain)."},
        "uncertainty": _s("What is uncertain or assumed."),
    },
    "required": ["expanded_description", "part_family", "category", "function", "is_assembly", "material", "am_screening",
                 "am_process_options", "rationale", "risks", "information_needed", "confidence", "uncertainty"],
    "propertyOrdering": ["expanded_description", "part_family", "category", "function", "is_assembly", "material",
                         "am_screening", "am_process_options", "rationale", "risks", "information_needed", "confidence",
                         "uncertainty"],
}

SYSTEM = """You support engineers at an engineering company who screen industrial spare parts for possible replacement \
by additive manufacturing (3D printing). You make suggestions; qualified engineers verify and decide.
Rules:
- Use only the data provided. Do not invent dimensions, material grades, OEM part numbers, standards or test results.
- Do not assign roles to unlabelled numbers (e.g. inside or outside diameter, width, length): quote them as written \
and list their meaning as information needed.
- When the data is not enough, say so: use "unknown", "not determinable" or "insufficient_information" and list what \
is needed.
- Never state prices, costs, lead times, suppliers or quotations, and never state that a part is approved, certified, \
qualified or released for manufacture.
- The rule-based findings were produced by deterministic software; treat them as context, not as verified facts.
- Keep text short and factual. Answer only with JSON that matches the response schema."""


class AIError(Exception):
    def __init__(self, code: str, message: str, retryable: bool = False, status: int | None = None):
        super().__init__(message)
        self.code, self.message, self.retryable, self.status = code, message, retryable, status


@dataclass
class CallResult:
    text: str
    model_version: str
    prompt_tokens: int = 0
    output_tokens: int = 0
    thinking_tokens: int = 0
    latency_ms: int = 0
    extra: dict = field(default_factory=dict)


def scrub(text: str) -> str:
    key = getattr(settings, "GEMINI_API_KEY", "")
    text = str(text)
    if key:
        text = text.replace(key, "[redacted]")
    return re.sub(r"AIza[0-9A-Za-z_\-]{20,}", "[redacted]", text)[:500]


THINKING = {"flash": "low", "pro": "low"}  # lite runs without thinking (cheapest)


class GeminiAdapter:
    provider = "gemini"

    def __init__(self):
        from google import genai
        from google.genai import types

        self._types = types
        self._client = genai.Client(
            api_key=settings.GEMINI_API_KEY,
            http_options=types.HttpOptions(timeout=settings.AI_TIMEOUT_SECONDS * 1000,
                                           retry_options=types.HttpRetryOptions(attempts=1)))

    def generate(self, *, model: str, tier: str, prompt: str, schema: dict | None = None, system: str | None = None) -> CallResult:
        from google.genai import errors

        t = self._types
        cfg = dict(system_instruction=system or SYSTEM, temperature=0.1, response_mime_type="application/json",
                   response_json_schema=schema or SUGGESTION_SCHEMA, max_output_tokens=4096)
        if THINKING.get(tier):
            cfg["thinking_config"] = t.ThinkingConfig(thinking_level=THINKING[tier])
        started = time.monotonic()
        try:
            r = self._client.models.generate_content(model=model, contents=prompt, config=t.GenerateContentConfig(**cfg))
        except errors.ClientError as e:  # 4xx
            code = getattr(e, "code", None)
            if code == 429:
                raise AIError("provider_rate_limited", "The AI provider's rate limit or quota was reached.", True, 429)
            if code in (401, 403):
                raise AIError("provider_not_authorised", "The AI provider refused the API key or project.", False, code)
            if code == 404:
                raise AIError("model_not_available", f"Model {model} is not available to this API project.", False, 404)
            raise AIError("provider_rejected", scrub(getattr(e, "message", "") or e), False, code)
        except errors.ServerError as e:  # 5xx
            raise AIError("provider_unavailable", scrub(getattr(e, "message", "") or e), True, getattr(e, "code", None))
        except Exception as e:  # noqa: BLE001 - timeouts and network errors from the HTTP client
            name = type(e).__name__
            if "Timeout" in name:
                raise AIError("timeout", f"No answer within {settings.AI_TIMEOUT_SECONDS} s.", True)
            if any(k in name for k in ("Connect", "Network", "Transport", "Protocol", "ReadError")):
                raise AIError("network_error", f"Network error ({name}).", True)
            raise AIError("provider_error", f"{name}: {scrub(e)}", False)
        u = r.usage_metadata
        finish = ""
        try:
            finish = str(r.candidates[0].finish_reason or "")
        except (IndexError, TypeError, AttributeError):
            pass
        return CallResult(text=r.text or "", model_version=r.model_version or model,
                          prompt_tokens=(u.prompt_token_count or 0) if u else 0,
                          output_tokens=(u.candidates_token_count or 0) if u else 0,
                          thinking_tokens=(u.thoughts_token_count or 0) if u else 0,
                          latency_ms=int((time.monotonic() - started) * 1000),
                          extra={"finish_reason": finish, "traffic_type": str(getattr(u, "traffic_type", "") or "") if u else ""})


def validate(text: str, model_cls=None) -> dict:
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        raise AIError("invalid_json", "The model did not return JSON.", True)
    try:
        return (model_cls or Suggestion).model_validate(data).model_dump()
    except ValidationError as e:
        problems = "; ".join(f"{'.'.join(str(x) for x in err['loc'])}: {err['msg']}" for err in e.errors()[:5])
        raise AIError("schema_mismatch", f"The response did not match the schema ({problems}).", True)


# ------------------------------------------------------------------ CN-007 Phase 3: manufacturing feasibility view

MF_STATUSES = ["potentially_suitable", "potentially_suitable_redesign", "insufficient_information", "not_suitable_verified",
               "specialist_assessment"]
METHODS = ["cnc_machining", "casting", "forging", "welding_fabrication", "sheet_metal", "injection_molding",
           "powder_metallurgy", "grinding", "other"]
MFStatus = Literal["potentially_suitable", "potentially_suitable_redesign", "insufficient_information", "not_suitable_verified",
                   "specialist_assessment"]


class AMView(BaseModel):
    model_config = ConfigDict(extra="forbid")
    suggested_status: MFStatus
    candidate_processes: list[Literal["metal_powder_bed_fusion", "directed_energy_deposition", "binder_jetting",
                                      "polymer_powder_bed_fusion", "material_extrusion", "none"]] = Field(max_length=6)
    considerations: list[str] = Field(max_length=8)
    post_processing: list[str] = Field(max_length=6)
    inspection_and_testing: list[str] = Field(max_length=6)
    risks: list[str] = Field(max_length=8)
    information_needed: list[str] = Field(max_length=10)
    rationale: str = Field(max_length=1200)


class ConventionalView(BaseModel):
    model_config = ConfigDict(extra="forbid")
    suggested_status: MFStatus
    candidate_methods: list[Literal["cnc_machining", "casting", "forging", "welding_fabrication", "sheet_metal",
                                    "injection_molding", "powder_metallurgy", "grinding", "other"]] = Field(max_length=9)
    considerations: list[str] = Field(max_length=8)
    inspection_and_testing: list[str] = Field(max_length=6)
    risks: list[str] = Field(max_length=8)
    information_needed: list[str] = Field(max_length=10)
    rationale: str = Field(max_length=1200)


class OEMView(BaseModel):
    model_config = ConfigDict(extra="forbid")
    considerations: list[str] = Field(max_length=6)
    information_needed: list[str] = Field(max_length=8)


class FeasibilityView(BaseModel):
    """Preliminary explanation of the three alternatives. No price, cost, lead time, supplier or approval field."""

    model_config = ConfigDict(extra="forbid")
    oem: OEMView
    additive: AMView
    conventional: ConventionalView
    qualification_requirements: list[str] = Field(max_length=8)
    confidence: float = Field(ge=0, le=1)
    uncertainty: str = Field(max_length=600)


def _list(desc, n, **kw):
    return {"type": "array", "items": _s(desc, **kw), "maxItems": n}


_STATUS = _s("Preliminary screening status (not an approval). Use not_suitable_verified only for a constraint the data "
             "marks as verified.", enum=MF_STATUSES)
FEASIBILITY_SCHEMA = {
    "type": "object",
    "properties": {
        "oem": {"type": "object", "properties": {
            "considerations": _list("What matters for buying the part from the OEM, based only on the data.", 6),
            "information_needed": _list("Information needed to confirm OEM identity and availability.", 8)},
            "required": ["considerations", "information_needed"]},
        "additive": {"type": "object", "properties": {
            "suggested_status": _STATUS,
            "candidate_processes": _list("Generic AM process family.", 6, enum=PROCESSES),
            "considerations": _list("Technical consideration for additive manufacturing.", 8),
            "post_processing": _list("Post-processing that would typically be needed.", 6),
            "inspection_and_testing": _list("Inspection or test that would be needed.", 6),
            "risks": _list("Technical risk.", 8),
            "information_needed": _list("Missing information.", 10),
            "rationale": _s("Short reasoning based only on the data.")},
            "required": ["suggested_status", "candidate_processes", "considerations", "post_processing",
                         "inspection_and_testing", "risks", "information_needed", "rationale"]},
        "conventional": {"type": "object", "properties": {
            "suggested_status": _STATUS,
            "candidate_methods": _list("Conventional manufacturing method.", 9, enum=METHODS),
            "considerations": _list("Technical consideration for conventional manufacturing.", 8),
            "inspection_and_testing": _list("Inspection or test that would be needed.", 6),
            "risks": _list("Technical risk.", 8),
            "information_needed": _list("Missing information.", 10),
            "rationale": _s("Short reasoning based only on the data.")},
            "required": ["suggested_status", "candidate_methods", "considerations", "inspection_and_testing", "risks",
                         "information_needed", "rationale"]},
        "qualification_requirements": _list("Engineering qualification step that any route would need.", 8),
        "confidence": {"type": "number", "minimum": 0, "maximum": 1, "description": "Confidence in this view (0 to 1)."},
        "uncertainty": _s("What is uncertain or assumed."),
    },
    "required": ["oem", "additive", "conventional", "qualification_requirements", "confidence", "uncertainty"],
    "propertyOrdering": ["oem", "additive", "conventional", "qualification_requirements", "confidence", "uncertainty"],
}

SYSTEM_FEASIBILITY = """You support engineers who screen industrial spare parts for three alternatives: buying from the \
original equipment manufacturer (OEM), additive manufacturing (AM) and conventional manufacturing. You explain possible \
methods and evidence gaps; qualified engineers verify and decide. You never certify or approve a method.
Rules:
- Use only the data provided. Do not invent dimensions, material grades, OEM identities, OEM part numbers, suppliers, \
availability, standards or test results.
- Do not assign roles to unlabelled numbers (inside or outside diameter, width, length): quote them as written and list \
their meaning as information needed.
- Evidence states in the data: verified, recorded (not verified), mentioned (description text only), missing. Treat \
anything not verified as unconfirmed.
- The rule-based screening statuses come from deterministic engineering rules and constraints. You may be more cautious \
than the rules, never less: do not suggest a more favourable status than the rule status.
- A part is never suitable just because its description resembles a commonly machined, cast or printed part.
- Never state prices, costs, savings, lead times, suppliers or quotations, and never state that a part or method is \
approved, certified, qualified or released for manufacture.
- Keep text short and factual. Answer only with JSON that matches the response schema."""


# ------------------------------------------------------------------ CN-007 Phase 4: cost-assumption notes

TECH_STATUSES = ["not_verified", "identified_confirmation_required", *MF_STATUSES]
TechStatus = Literal["not_verified", "identified_confirmation_required", "potentially_suitable", "potentially_suitable_redesign",
                     "insufficient_information", "not_suitable_verified", "specialist_assessment"]


class CostAltNotes(BaseModel):
    model_config = ConfigDict(extra="forbid")
    technical_status: TechStatus  # must repeat the recorded status (checked by the service)
    cost_drivers: list[str] = Field(max_length=6)
    assumptions_to_verify: list[str] = Field(max_length=8)
    missing_inputs: list[str] = Field(max_length=8)
    lead_time_considerations: list[str] = Field(max_length=6)
    uncertainty: Literal["low", "medium", "high"]


class CostNotes(BaseModel):
    """Explanations of cost and lead-time assumptions. Deliberately no price, rate, total or recommendation field."""

    model_config = ConfigDict(extra="forbid")
    oem: CostAltNotes
    additive: CostAltNotes
    conventional: CostAltNotes
    general_notes: list[str] = Field(max_length=6)
    confidence: float = Field(ge=0, le=1)


_COST_ALT = {"type": "object", "properties": {
    "technical_status": _s("Repeat this alternative's technical_status_code exactly as given. Never a different status.",
                           enum=TECH_STATUSES),
    "cost_drivers": _list("Which cost components drive this alternative's cost, from the shares given. No amounts.", 6),
    "assumptions_to_verify": _list("An assumption behind an estimate that should be verified, and how.", 8),
    "missing_inputs": _list("A missing input and why it matters.", 8),
    "lead_time_considerations": _list("A lead-time consideration.", 6),
    "uncertainty": _s("Overall uncertainty of this alternative's figures.", enum=["low", "medium", "high"])},
    "required": ["technical_status", "cost_drivers", "assumptions_to_verify", "missing_inputs", "lead_time_considerations",
                 "uncertainty"]}
COST_SCHEMA = {
    "type": "object",
    "properties": {"oem": _COST_ALT, "additive": _COST_ALT, "conventional": _COST_ALT,
                   "general_notes": _list("A general note on comparing these alternatives.", 6),
                   "confidence": {"type": "number", "minimum": 0, "maximum": 1, "description": "Confidence in these notes (0 to 1)."}},
    "required": ["oem", "additive", "conventional", "general_notes", "confidence"],
    "propertyOrdering": ["oem", "additive", "conventional", "general_notes", "confidence"],
}

SYSTEM_COST = """You support engineers who compare the cost and lead time of three ways to obtain an industrial spare part: \
buying from the original equipment manufacturer (OEM), additive manufacturing (AM) and conventional manufacturing. \
Deterministic software has already calculated the figures; you explain the assumptions and uncertainty behind them.
Rules:
- Use only the data provided. You receive cost-component shares, data sources and lead times, not prices.
- Never state prices, costs, amounts of money, exchange rates, savings figures or quotations, and never estimate one.
- Data sources: a verified supplier quotation is strongest; historical costs, engineering estimates and AI-assisted \
preliminary estimates are progressively weaker and must be verified. Missing inputs make a total incomplete.
- Technical screening statuses come from engineering rules. A lower cost never overrides a technical constraint or \
missing engineering approval; never suggest that it does. Repeat each alternative's technical_status_code exactly, and \
never describe an alternative with a different screening status (for example "specialist assessment" when its status is \
"insufficient information") or as qualified or approved.
- Do not recommend, rank or choose an alternative, and never state that a part or method is approved, certified, \
qualified or released.
- Keep text short and factual. Answer only with JSON that matches the response schema."""


# ------------------------------------------------------------------ CN-007 Phase 5: recommendation explanation

REC_OUTCOMES = ["no_qualified_recommendation", "qualified_commercial_incomplete", "preliminary_recommendation"]


class RecOption(BaseModel):
    model_config = ConfigDict(extra="forbid")
    technical_status: TechStatus  # must repeat the recorded status (checked by the service)
    technical_explanation: str = Field(max_length=600)
    commercial_explanation: str = Field(max_length=600)
    evidence_gaps: list[str] = Field(max_length=8)
    risks: list[str] = Field(max_length=6)


class RecExplanation(BaseModel):
    """Explains the deterministic result. No price, ranking, choice or approval field; outcome and statuses are echoed."""

    model_config = ConfigDict(extra="forbid")
    outcome_code: Literal["no_qualified_recommendation", "qualified_commercial_incomplete", "preliminary_recommendation"]
    summary: str = Field(max_length=800)
    oem: RecOption
    additive: RecOption
    conventional: RecOption
    information_to_obtain: list[str] = Field(max_length=8)
    confidence: float = Field(ge=0, le=1)


_REC_OPT = {"type": "object", "properties": {
    "technical_status": _s("Repeat this option's technical_status_code exactly as given.", enum=TECH_STATUSES),
    "technical_explanation": _s("Why this option does or does not meet the mandatory requirements, from the data only."),
    "commercial_explanation": _s("What the cost and lead-time evidence shows, using only the relative figures given. No amounts."),
    "evidence_gaps": _list("Evidence still needed.", 8),
    "risks": _list("A technical or commercial risk.", 6)},
    "required": ["technical_status", "technical_explanation", "commercial_explanation", "evidence_gaps", "risks"]}
REC_SCHEMA = {
    "type": "object",
    "properties": {"outcome_code": _s("Repeat the outcome_code exactly as given.", enum=REC_OUTCOMES),
                   "summary": _s("Two or three sentences explaining the deterministic outcome."),
                   "oem": _REC_OPT, "additive": _REC_OPT, "conventional": _REC_OPT,
                   "information_to_obtain": _list("Information that would allow a qualified recommendation.", 8),
                   "confidence": {"type": "number", "minimum": 0, "maximum": 1, "description": "Confidence in this explanation (0 to 1)."}},
    "required": ["outcome_code", "summary", "oem", "additive", "conventional", "information_to_obtain", "confidence"],
    "propertyOrdering": ["outcome_code", "summary", "oem", "additive", "conventional", "information_to_obtain", "confidence"],
}

SYSTEM_REC = """You explain the result of a deterministic engineering and commercial evaluation of three ways to obtain an \
industrial spare part: buying from the original equipment manufacturer (OEM), additive manufacturing (AM) and \
conventional manufacturing. The software has already applied the mandatory technical, safety, certification and \
intellectual-property requirements and calculated the costs; qualified engineers review the result.
Rules:
- Use only the data provided. Explain the outcome; never change it. Repeat outcome_code and every technical_status_code \
exactly as given.
- Never describe an option with a different screening status, as technically qualified, or as approved, certified or \
released; never suggest that a lower cost overrides a technical requirement.
- Never state prices, amounts of money, exchange rates or quotations, and never estimate one. Relative cost indices and \
lead-time days may be described.
- An option with incomplete costs is never definitively cheaper. An expired quotation is not current evidence.
- Do not recommend, rank or choose an option yourself.
- Keep text short and factual. Answer only with JSON that matches the response schema."""


def cost_usd(model: str, version: str, prompt_tokens: int, output_tokens: int, thinking_tokens: int) -> float | None:
    prices = settings.AI_PRICES.get(model) or settings.AI_PRICES.get(version)
    if not prices:
        return None
    return round(prompt_tokens * prices[0] / 1e6 + (output_tokens + thinking_tokens) * prices[1] / 1e6, 8)
