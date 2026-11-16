"""Manufacturing cost estimate for a requested spare part (decision of 16 Nov 2026).

For one client request, three routes side by side: OEM purchase, conventional manufacturing (machining) and 3D printing.
For each: feasible or not (the existing rule-based screening, apps.intelligence.feasibility), the work (material kg,
machine hours, manpower hours per role, days), the cost range, and the risks, so Aries can choose a route.

Who does what
- Rules (apps.intelligence.feasibility): which routes are possible. The AI may add caution, never make a route possible.
- Gemini, call 1 (structured output): the WORK per route: kg, machine hours, manpower hours per role, days, risks,
  assumptions, missing information, confidence. No money.
- Gemini, call 2 (Google Search grounding): indicative material prices per kg and a public OEM price, with the websites
  used. Price source "web_search" until Aries' own price website is configured (ESTIMATE_PRICE_SOURCE).
- This module: the MONEY, with a fixed formula from the work, the prices and Aries' rates (EstimateRates). A price the web
  search could not give falls back to the rate table, shown as such.
- The engineer corrects any figure (a new version); the Aries Admin or Manager records the chosen route.

External AI follows the existing gate (AI_PROVIDER, GEMINI_API_KEY, AI_ALLOWED_COMPANIES), limits, daily budget and
usage log (apps.intelligence.service). Without it an engineer fills in a manual estimate; the calculation is the same.
Sent to Gemini: the part's name and description, material, size, application, manufacturer and the passport's
manufacturing fields (process, standards, tolerances, heat treatment, NDT), the quantity and the days until the required
date. Never drawings, CAD, documents, photos, the client's name or its references.
"""
import json
import re
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from django.conf import settings
from django.db import transaction
from django.db.models import Max
from django.utils import timezone
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from apps.audit.service import record
from apps.core.exceptions import DomainError
from apps.tenancy.context import tenant_context
from apps.tenancy.models import Tenant

from . import gemini, service
from .models import AIUsageLog, EstimateRates, ManufacturingEstimate

PROMPT_VERSION = "estimate-2026-11-16.1"
ROUTES = ("oem", "conventional", "additive")
ROUTE_LABEL = {"oem": "OEM purchase", "conventional": "Conventional manufacturing", "additive": "3D printing"}
ROLES = {"design": "Design / CAD engineer", "machinist": "CNC machinist", "am_operator": "3D printer operator",
         "post_processing": "Post-processing technician", "qa": "QA inspector", "welder": "Welder / fitter"}
MACHINES = {"metal_am": "Metal 3D printer (powder bed)", "polymer_am": "Polymer 3D printer", "cnc": "CNC machine",
            "other": "Other machine"}
DAY_KEYS = ("preparation", "production", "post_processing", "inspection", "shipping")
U = AIUsageLog.Outcome

# Sample values until the Aries Admin enters the real ones (Estimate rates page). Every estimate stores its own copy.
DEFAULT_RATES = {
    "currency": "USD",
    "machine_rates": {"metal_am": 60, "polymer_am": 20, "cnc": 45, "other": 35},  # per hour
    "labour_rates": {"design": 40, "machinist": 30, "am_operator": 30, "post_processing": 25, "qa": 35, "welder": 30},  # per hour
    "material_prices": {  # per kg: fallback when the web search gives no price
        "stainless steel 316L powder": 55, "stainless steel bar": 6, "carbon steel bar": 2, "aluminium bar": 6,
        "bronze bar": 18, "titanium powder": 250, "nickel alloy (Inconel) powder": 110, "nylon PA12 powder": 70,
    },
    "default_material_price": 20,
    "heat_treatment_per_batch": 150,
    "ndt_per_part": 80,
    "shipping_per_order": 60,
    "oem_shipping_per_order": 80,
    "overhead_pct": 15,
    "margin_pct": 20,
    "uncertainty_pct": 20,  # the range shown: total - x % to total + x %
}


# ------------------------------------------------------------------ rates

def operator_tenant() -> Tenant:
    return Tenant.objects.filter(kind=Tenant.Kind.OPERATOR).order_by("created_at").first()


def get_rates() -> dict:
    op = operator_tenant()
    if op is None:
        return json.loads(json.dumps(DEFAULT_RATES))
    with tenant_context(op):
        row = EstimateRates.objects.filter(tenant=op).first()
    return _merge(DEFAULT_RATES, row.data if row else {})


def _merge(base: dict, over: dict) -> dict:
    out = json.loads(json.dumps(base))
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = {**out[k], **v}
        else:
            out[k] = v
    return out


def _num(v, field, lo=0, hi=1_000_000) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError):
        raise DomainError("invalid_rates", f"{field}: enter a number.", http_status=400)
    if not lo <= x <= hi:
        raise DomainError("invalid_rates", f"{field}: must be between {lo} and {hi}.", http_status=400)
    return x


def clean_rates(data: dict) -> dict:
    d = _merge(DEFAULT_RATES, data or {})
    cur = str(d.get("currency") or "").upper()
    if not re.fullmatch(r"[A-Z]{3}", cur):
        raise DomainError("invalid_rates", "Currency: use a 3-letter code such as USD, INR or AED.", http_status=400)
    out = {"currency": cur}
    for group in ("machine_rates", "labour_rates", "material_prices"):
        out[group] = {str(k)[:60]: _num(v, f"{group}.{k}") for k, v in (d.get(group) or {}).items() if str(k).strip()}
    for k in ("default_material_price", "heat_treatment_per_batch", "ndt_per_part", "shipping_per_order", "oem_shipping_per_order"):
        out[k] = _num(d.get(k), k)
    for k in ("overhead_pct", "margin_pct", "uncertainty_pct"):
        out[k] = _num(d.get(k), k, 0, 100)
    return out


def save_rates(request, data: dict) -> dict:
    clean = clean_rates(data)
    op = operator_tenant()
    with tenant_context(op):
        row = EstimateRates.objects.filter(tenant=op).first()
        if row is None:
            row = EstimateRates(tenant=op, created_by=request.user)
        row.data, row.updated_by = clean, request.user
        row.save()
        record(request, "estimate.rates_changed", obj=row, tenant=op, data={"currency": clean["currency"]})
    return clean


# ------------------------------------------------------------------ AI response shapes

class Manpower(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["design", "machinist", "am_operator", "post_processing", "qa", "welder"]
    hours_per_part: float = Field(ge=0, le=500)
    hours_per_batch: float = Field(ge=0, le=500)


class Days(BaseModel):
    model_config = ConfigDict(extra="forbid")
    preparation: float = Field(ge=0, le=365)
    production: float = Field(ge=0, le=365)
    post_processing: float = Field(ge=0, le=365)
    inspection: float = Field(ge=0, le=365)
    shipping: float = Field(ge=0, le=365)


class MakeRoute(BaseModel):
    """Conventional or 3D printing: the work, never money."""

    model_config = ConfigDict(extra="forbid")
    feasible: Literal["yes", "with_review", "no", "unknown"]
    reason: str = Field(max_length=500)
    process: str = Field(max_length=120)
    material: str = Field(max_length=120)  # what is bought, e.g. "stainless steel 316L powder"
    kg_per_part: float = Field(ge=0, le=10000)  # including supports, machining allowance and waste
    machine: Literal["metal_am", "polymer_am", "cnc", "other"]
    machine_hours_per_part: float = Field(ge=0, le=2000)
    setup_hours: float = Field(ge=0, le=500)
    manpower: list[Manpower] = Field(max_length=8)
    heat_treatment: bool
    ndt: bool
    days: Days
    risks: list[str] = Field(max_length=8)
    assumptions: list[str] = Field(max_length=8)


class OemRoute(BaseModel):
    model_config = ConfigDict(extra="forbid")
    feasible: Literal["yes", "with_review", "no", "unknown"]
    reason: str = Field(max_length=500)
    lead_days: float = Field(ge=0, le=730)
    risks: list[str] = Field(max_length=8)


class WorkEstimate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    oem: OemRoute
    conventional: MakeRoute
    additive: MakeRoute
    missing_information: list[str] = Field(max_length=10)
    confidence: float = Field(ge=0, le=1)


def _s(desc, **kw):
    return {"type": "string", "description": desc, **kw}


_FEAS = _s("Is this route technically possible?", enum=["yes", "with_review", "no", "unknown"])
_DAYS = {"type": "object", "properties": {k: {"type": "number", "description": f"Working days for {k.replace('_', ' ')}."} for k in DAY_KEYS},
         "required": list(DAY_KEYS)}
_MAKE = {"type": "object", "properties": {
    "feasible": _FEAS, "reason": _s("One or two sentences why."),
    "process": _s("The process, e.g. 'laser powder bed fusion' or 'CNC turning and milling'."),
    "material": _s("The raw material bought, e.g. 'stainless steel 316L powder' or 'stainless steel bar'."),
    "kg_per_part": {"type": "number", "description": "Raw material per part in kg, including supports, machining allowance and waste."},
    "machine": _s("Machine type.", enum=list(MACHINES)),
    "machine_hours_per_part": {"type": "number", "description": "Machine hours per part (print or machining time)."},
    "setup_hours": {"type": "number", "description": "One-time machine set-up hours for the order."},
    "manpower": {"type": "array", "items": {"type": "object", "properties": {
        "role": _s("Role.", enum=list(ROLES)), "hours_per_part": {"type": "number"}, "hours_per_batch": {"type": "number"}},
        "required": ["role", "hours_per_part", "hours_per_batch"]}},
    "heat_treatment": {"type": "boolean"}, "ndt": {"type": "boolean", "description": "Non-destructive testing needed."},
    "days": _DAYS, "risks": {"type": "array", "items": {"type": "string"}}, "assumptions": {"type": "array", "items": {"type": "string"}}},
    "required": ["feasible", "reason", "process", "material", "kg_per_part", "machine", "machine_hours_per_part", "setup_hours",
                 "manpower", "heat_treatment", "ndt", "days", "risks", "assumptions"]}
WORK_SCHEMA = {"type": "object", "properties": {
    "oem": {"type": "object", "properties": {
        "feasible": _FEAS, "reason": _s("Is the part likely still available from the original manufacturer?"),
        "lead_days": {"type": "number", "description": "Typical OEM delivery time in days."},
        "risks": {"type": "array", "items": {"type": "string"}}},
        "required": ["feasible", "reason", "lead_days", "risks"]},
    "conventional": _MAKE, "additive": _MAKE,
    "missing_information": {"type": "array", "items": {"type": "string"}},
    "confidence": {"type": "number", "description": "0 to 1."}},
    "required": ["oem", "conventional", "additive", "missing_information", "confidence"]}

SYSTEM_WORK = (
    "You are a manufacturing engineer at a marine engineering company that repairs and remanufactures spare parts. "
    "For the spare part described, estimate the WORK of three routes: buying it from the original manufacturer (OEM), "
    "conventional manufacturing (machining, casting, fabrication) and 3D printing (additive manufacturing). Give realistic "
    "quantities for one part: raw material kg (with waste and supports), machine hours, set-up hours, manpower hours per role "
    "and working days per stage. Do NOT give any price, cost or currency. Mark a route 'no' only when it is clearly "
    "impossible, and 'unknown' when the data is insufficient. Be conservative; state assumptions and missing information.")
SYSTEM_PRICES = (
    "You look up current indicative market prices on public websites for a manufacturing cost estimate. Answer ONLY with "
    "one JSON object, no other text.")


# ------------------------------------------------------------------ inputs

def _days_until(d) -> int | None:
    return (d - date.today()).days if d else None


def collect_inputs(obj, part, revision) -> dict:
    c = (revision.content if revision else {}) or {}
    rl1, rl2 = c.get("rl1") or {}, c.get("rl2") or {}
    spec = rl2.get("manufacturing_spec") or {}
    pick = lambda d, keys: {k: d[k] for k in keys if d.get(k) not in (None, "", [], {})}  # noqa: E731
    return {
        "part": pick({"name": part.name, "description": part.description, "category": part.category, "original_material": part.original_material,
                      "dimensions": part.dimensions, "application": part.application, "manufacturer": part.manufacturer},
                     ["name", "description", "category", "original_material", "dimensions", "application", "manufacturer"]),
        "passport_rl1": pick(rl1, ["original_material_grade", "part_size", "application", "technical_description", "atmosphere", "motion",
                                   "rpm", "ip_status", "cad_3d_available", "drawings_2d_available"]),
        "passport_rl2": pick(rl2, ["manufacturing_solution", "manufacturing_process", "material_selection", "material_category",
                                   "criticality_amsl", "feedstock", "applicable_standards", "dimensional_tolerances", "ndt",
                                   "mtc_required", "test_coupons", "mechanical_acceptance"]),
        "manufacturing_spec": pick(spec, ["material", "feedstock", "machine", "layer_thickness", "heat_treatment", "post_processing",
                                          "machining", "printing_hours", "post_processing_hours"]),
        "quantity": obj.quantity or 1,
        "days_until_required": _days_until(obj.required_date),
        "material_option": obj.material_option, "proposed_material": obj.proposed_material,
    }


def feasibility_of(part) -> dict:
    """Rule-based screening per route (the existing Phase 3 rules; nothing stored)."""
    from . import feasibility_service as FS

    try:
        _analysis, _docs, _pp, result, _snap = FS._evaluate(part)
    except Exception:  # noqa: BLE001 - a screening problem must not block the estimate; the engineer judges
        return {}
    out = {}
    for route, key in (("oem", "oem"), ("additive", "additive"), ("conventional", "conventional")):
        r = result.get(key) or {}
        out[route] = {"status": r.get("status", ""), "label": r.get("status_label", ""),
                      "disqualified": r.get("status") == "not_suitable_verified"}
    return out


# ------------------------------------------------------------------ calculation (money)

def D(x) -> Decimal:
    return Decimal(str(x or 0))


def money(x: Decimal) -> float:
    return float(x.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _material_price(rates: dict, prices: dict, material: str) -> tuple[Decimal, dict]:
    found = (prices.get("materials") or {}).get(material)
    if found and found.get("price_per_kg") not in (None, ""):
        return D(found["price_per_kg"]), {"source": found.get("source", "web_search"), "url": found.get("url", ""),
                                          "title": found.get("title", ""), "note": found.get("note", "")}
    table = rates.get("material_prices") or {}
    key = next((k for k in table if k.lower() == (material or "").lower()), None)
    if key:
        return D(table[key]), {"source": "rate_table", "note": f"Aries rate table: {key}"}
    return D(rates.get("default_material_price")), {"source": "rate_table_default", "note": "Aries default material price (no price found)"}


def calculate(work: dict, prices: dict, rates: dict, quantity: int, feasibility: dict) -> dict:
    q = D(max(int(quantity or 1), 1))
    oh, mg, unc = D(rates["overhead_pct"]) / 100, D(rates["margin_pct"]) / 100, D(rates["uncertainty_pct"]) / 100
    out = {"currency": rates["currency"], "quantity": int(q), "routes": {}}
    for route in ("conventional", "additive"):
        w = work.get(route) or {}
        if not w:
            continue
        price, psrc = _material_price(rates, prices, w.get("material", ""))
        kg = D(w.get("kg_per_part")) * q
        material = kg * price
        mrate = D((rates.get("machine_rates") or {}).get(w.get("machine", "other"), 0))
        machine_hours = D(w.get("machine_hours_per_part")) * q + D(w.get("setup_hours"))
        machine = machine_hours * mrate
        labour, people = Decimal(0), []
        for m in w.get("manpower") or []:
            hours = D(m.get("hours_per_part")) * q + D(m.get("hours_per_batch"))
            rate = D((rates.get("labour_rates") or {}).get(m.get("role"), 0))
            labour += hours * rate
            people.append({"role": m.get("role"), "label": ROLES.get(m.get("role"), m.get("role")), "hours": float(hours),
                           "rate": float(rate), "cost": money(hours * rate)})
        extras = (D(rates["heat_treatment_per_batch"]) if w.get("heat_treatment") else 0) + \
                 (D(rates["ndt_per_part"]) * q if w.get("ndt") else 0) + D(rates["shipping_per_order"])
        direct = material + machine + labour + extras
        overhead = direct * oh
        margin = (direct + overhead) * mg
        total = direct + overhead + margin
        days = w.get("days") or {}
        f = feasibility.get(route) or {}
        feasible = "no" if f.get("disqualified") else w.get("feasible", "unknown")  # rules can veto, the AI cannot override
        out["routes"][route] = {
            "label": ROUTE_LABEL[route], "feasible": feasible, "reason": w.get("reason", ""), "rule_status": f.get("label", ""),
            "process": w.get("process", ""), "material": w.get("material", ""), "material_kg": float(kg),
            "material_price_per_kg": float(price), "material_price_source": psrc,
            "machine": MACHINES.get(w.get("machine"), w.get("machine", "")), "machine_hours": float(machine_hours),
            "manpower": people, "manpower_hours": float(sum(D(p["hours"]) for p in people)),
            "days": {k: float(D(days.get(k))) for k in DAY_KEYS}, "total_days": float(sum(D(days.get(k)) for k in DAY_KEYS)),
            "cost": {"material": money(material), "machine": money(machine), "manpower": money(labour), "extras": money(extras),
                     "overhead": money(overhead), "margin": money(margin), "total": money(total),
                     "low": money(total * (1 - unc)), "high": money(total * (1 + unc)), "per_part": money(total / q)},
            "risks": w.get("risks") or [], "assumptions": w.get("assumptions") or [],
        }
    o = work.get("oem") or {}
    if o:
        op = prices.get("oem") or {}
        f = feasibility.get("oem") or {}
        unit = D(op.get("price_per_part")) if op.get("price_per_part") not in (None, "") else None
        total = (unit * q + D(rates["oem_shipping_per_order"])) if unit is not None else None
        out["routes"]["oem"] = {
            "label": ROUTE_LABEL["oem"], "feasible": "no" if f.get("disqualified") else o.get("feasible", "unknown"),
            "reason": o.get("reason", ""), "rule_status": f.get("label", ""),
            "price_per_part": float(unit) if unit is not None else None, "price_source": op if unit is not None else {},
            "cost": ({"total": money(total), "low": money(total * (1 - unc)), "high": money(total * (1 + unc)),
                      "per_part": money(total / q), "shipping": money(D(rates["oem_shipping_per_order"]))} if total is not None else None),
            "total_days": float(D(o.get("lead_days"))), "days": {"shipping": float(D(o.get("lead_days")))},
            "manpower": [], "manpower_hours": 0.0, "risks": o.get("risks") or [],
            "note": "" if unit is not None else "No public price found: ask the OEM or a distributor for a quotation.",
        }
    priced = {r: v for r, v in out["routes"].items() if v.get("cost") and v["feasible"] != "no"}
    out["cheapest"] = min(priced, key=lambda r: priced[r]["cost"]["total"]) if priced else ""
    timed = {r: v for r, v in out["routes"].items() if v["feasible"] != "no" and v.get("total_days")}
    out["fastest"] = min(timed, key=lambda r: timed[r]["total_days"]) if timed else ""
    return out


# ------------------------------------------------------------------ AI calls

def _json_from_text(text: str) -> dict:
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        raise gemini.AIError("invalid_json", "The price search did not return JSON.", True)
    try:
        return json.loads(m.group(0))
    except ValueError:
        raise gemini.AIError("invalid_json", "The price search did not return valid JSON.", True)


def _price_lookup(adapter, model, tier, materials: list[str], inputs: dict, currency: str) -> tuple[dict, object]:
    """Gemini with Google Search: indicative prices and the websites used. Never raises; failures fall back to the rates."""
    part = inputs.get("part") or {}
    ask = {"currency": currency, "materials": materials,
           "oem_part": {k: part.get(k) for k in ("name", "manufacturer", "description") if part.get(k)}}
    prompt = ("Find current indicative prices on public websites. Data (JSON):\n" + json.dumps(ask, ensure_ascii=False) +
              "\nReturn JSON: {\"materials\": [{\"material\": str, \"price_per_kg\": number in " + currency + " or null, "
              "\"source_title\": str, \"source_url\": str, \"note\": str}], \"oem\": {\"price_per_part\": number in " + currency +
              " or null, \"source_title\": str, \"source_url\": str, \"note\": str}}. Convert to " + currency +
              " if needed and say so in the note. Use null when no reliable price is found; never guess.")
    try:
        call = adapter.generate(model=model, tier=tier, prompt=prompt, system=SYSTEM_PRICES, search=True)
        data = _json_from_text(call.text)
    except gemini.AIError as e:
        return {"error": e.code, "materials": {}, "oem": {}}, None
    sources = (call.extra or {}).get("sources") or []
    mats = {}
    for m in data.get("materials") or []:
        name = str(m.get("material") or "")[:120]
        try:
            price = float(m["price_per_kg"]) if m.get("price_per_kg") not in (None, "") else None
        except (TypeError, ValueError):
            price = None
        if name and price is not None and 0 < price < 100000:
            mats[name] = {"price_per_kg": price, "source": "web_search", "title": str(m.get("source_title") or "")[:200],
                          "url": str(m.get("source_url") or "")[:500], "note": str(m.get("note") or "")[:300]}
    o = data.get("oem") or {}
    try:
        oem_price = float(o["price_per_part"]) if o.get("price_per_part") not in (None, "") else None
    except (TypeError, ValueError):
        oem_price = None
    oem = ({"price_per_part": oem_price, "source": "web_search", "title": str(o.get("source_title") or "")[:200],
            "url": str(o.get("source_url") or "")[:500], "note": str(o.get("note") or "")[:300]}
           if oem_price is not None and 0 < oem_price < 10_000_000 else {})
    return {"materials": mats, "oem": oem, "sources": sources}, call


def _ai_estimate(request, client: Tenant, part, inputs: dict, currency: str, tier: str) -> tuple[dict, dict, dict]:
    model = settings.GEMINI_MODELS[tier]
    log = service._reserve(request, model, part, tenant=client)  # limits and daily budget; raises service.Refused
    prompt = "Estimate the work for this spare part. Data (JSON):\n" + json.dumps(inputs, ensure_ascii=False, indent=1)
    work, call, totals, attempts, err = service.call_ai(model, tier, prompt, WORK_SCHEMA, SYSTEM_WORK, WorkEstimate)
    prices, pcall = ({}, None)
    if work:
        mats = sorted({work[r]["material"] for r in ("conventional", "additive") if work[r]["feasible"] != "no" and work[r]["material"]})
        prices, pcall = _price_lookup(service._adapter(), model, tier, mats, inputs, currency)
        if pcall is not None:
            for k, v in (("prompt", pcall.prompt_tokens), ("output", pcall.output_tokens), ("thinking", pcall.thinking_tokens),
                         ("latency", pcall.latency_ms)):
                totals[k] += v
    cost = gemini.cost_usd(model, call.model_version if call else "", totals["prompt"], totals["output"], totals["thinking"])
    log.outcome = U.OK if work else U.FAILED
    log.model_version = call.model_version if call else ""
    log.prompt_tokens, log.output_tokens, log.thinking_tokens = totals["prompt"], totals["output"], totals["thinking"]
    log.cost_usd, log.latency_ms, log.attempts = Decimal(str(cost or 0)), totals["latency"], attempts
    log.error_code = err.code if err else ""
    log.save()
    if not work:
        raise DomainError("ai_failed", f"Gemini could not estimate this part ({gemini.scrub(err.message) if err else 'no answer'}). "
                          "You can fill in a manual estimate instead.", http_status=502)
    ai = {"provider": "gemini", "model": model, "model_version": call.model_version if call else "", "tier": tier,
          "prompt_version": PROMPT_VERSION, "confidence": work.get("confidence"), "missing_information": work.get("missing_information", []),
          "usage": {"cost_usd": cost, "attempts": attempts, "latency_ms": totals["latency"]},
          "price_search": {"ok": not prices.get("error"), "error": prices.get("error", ""), "sources": prices.get("sources", [])}}
    return {r: work[r] for r in ROUTES}, {"materials": prices.get("materials", {}), "oem": prices.get("oem", {})}, ai


def blank_work() -> dict:
    """A manual estimate starts empty: the engineer enters the work for each route."""
    make = lambda machine, material: {"feasible": "unknown", "reason": "", "process": "", "material": material, "kg_per_part": 0,  # noqa: E731
                                      "machine": machine, "machine_hours_per_part": 0, "setup_hours": 0, "manpower": [],
                                      "heat_treatment": False, "ndt": False, "days": {k: 0 for k in DAY_KEYS}, "risks": [], "assumptions": []}
    return {"oem": {"feasible": "unknown", "reason": "", "lead_days": 0, "risks": []},
            "conventional": make("cnc", "stainless steel bar"), "additive": make("metal_am", "stainless steel 316L powder")}


def validate_work(work: dict) -> dict:
    try:
        return {"oem": OemRoute.model_validate(work.get("oem") or {}).model_dump(),
                "conventional": MakeRoute.model_validate(work.get("conventional") or {}).model_dump(),
                "additive": MakeRoute.model_validate(work.get("additive") or {}).model_dump()}
    except ValidationError as e:
        problems = "; ".join(f"{'.'.join(str(x) for x in err['loc'])}: {err['msg']}" for err in e.errors()[:5])
        raise DomainError("invalid_estimate", f"Check the figures ({problems}).", http_status=400)


def validate_prices(prices: dict) -> dict:
    out = {"materials": {}, "oem": {}}
    for name, p in ((prices or {}).get("materials") or {}).items():
        if p and p.get("price_per_kg") not in (None, ""):
            out["materials"][str(name)[:120]] = {**{k: str(p.get(k) or "")[:500] for k in ("source", "title", "url", "note")},
                                                 "price_per_kg": _num(p["price_per_kg"], f"price of {name}", 0, 100000)}
    o = (prices or {}).get("oem") or {}
    if o.get("price_per_part") not in (None, ""):
        out["oem"] = {**{k: str(o.get(k) or "")[:500] for k in ("source", "title", "url", "note")},
                      "price_per_part": _num(o["price_per_part"], "OEM price", 0, 10_000_000)}
    return out


# ------------------------------------------------------------------ versions

def _store(request, obj, part, *, mode, work, prices, rates, inputs, feas, ai=None, note="") -> ManufacturingEstimate:
    with transaction.atomic():
        last = ManufacturingEstimate.objects.filter(request=obj).aggregate(m=Max("version"))["m"] or 0
        e = ManufacturingEstimate.objects.create(
            tenant=obj.tenant, created_by=request.user, request=obj, part=part, version=last + 1, mode=mode,
            quantity=obj.quantity or 1, inputs=inputs, feasibility=feas, work=work, prices=prices, rates=rates,
            result=calculate(work, prices, rates, obj.quantity or 1, feas), ai=ai or {}, note=note[:500])
    record(request, f"estimate.{mode}", obj=e, tenant=obj.tenant, data={"request": obj.reference, "version": e.version,
                                                                        "cheapest": e.result.get("cheapest", "")})
    return e


def run(request, obj, part, revision, *, use_ai: bool, tier: str = "lite") -> ManufacturingEstimate:
    """A new estimate: Gemini (use_ai) or an empty manual one. Inside the client's tenant context."""
    if tier not in service.TIERS:
        raise DomainError("invalid_tier", "Choose lite, flash or pro.", http_status=400)
    rates = get_rates()
    inputs = collect_inputs(obj, part, revision)
    feas = feasibility_of(part)
    if use_ai:
        st = service.ai_status(obj.tenant)
        if not st["enabled"]:
            raise DomainError("ai_not_permitted", st["reason"] + " You can fill in a manual estimate instead.", http_status=403)
        work, prices, ai = _ai_estimate(request, obj.tenant, part, inputs, rates["currency"], tier)
        return _store(request, obj, part, mode=ManufacturingEstimate.Mode.AI, work=work, prices=prices, rates=rates,
                      inputs=inputs, feas=feas, ai=ai)
    return _store(request, obj, part, mode=ManufacturingEstimate.Mode.MANUAL, work=blank_work(), prices={"materials": {}, "oem": {}},
                  rates=rates, inputs=inputs, feas=feas)


def adjust(request, obj, base: ManufacturingEstimate, work: dict, prices: dict, note: str) -> ManufacturingEstimate:
    """The engineer's corrections become a new version (the earlier one is kept); the AI details are carried over."""
    return _store(request, obj, base.part, mode=ManufacturingEstimate.Mode.ADJUSTED, work=validate_work(work),
                  prices=validate_prices(prices), rates=base.rates, inputs=base.inputs, feas=base.feasibility,
                  ai={**base.ai, "adjusted_from_version": base.version}, note=note)


def choose(request, e: ManufacturingEstimate, route: str, note: str) -> ManufacturingEstimate:
    if route not in ROUTES:
        raise DomainError("invalid_route", "Choose oem, conventional or additive.", http_status=400)
    r = (e.result.get("routes") or {}).get(route)
    if r is None or r.get("feasible") == "no":
        raise DomainError("route_not_feasible", "This route is not feasible in the estimate.", http_status=409)
    e.chosen_route, e.chosen_note, e.chosen_by, e.chosen_at = route, note[:500], request.user, timezone.now()
    e.save(update_fields=["chosen_route", "chosen_note", "chosen_by", "chosen_at", "updated_at"])
    record(request, "estimate.route_chosen", obj=e, tenant=e.tenant, data={"request": e.request.reference, "version": e.version,
                                                                          "route": route, "total": (r.get("cost") or {}).get("total")})
    return e


def serialise(e: ManufacturingEstimate) -> dict:
    return {"id": str(e.pk), "version": e.version, "mode": e.mode, "mode_label": e.get_mode_display(), "quantity": e.quantity,
            "work": e.work, "prices": e.prices, "result": e.result, "feasibility": e.feasibility, "rates": e.rates, "ai": e.ai,
            "note": e.note, "created_at": e.created_at, "created_by": e.created_by.email if e.created_by_id else "",
            "chosen_route": e.chosen_route, "chosen_note": e.chosen_note, "chosen_at": e.chosen_at,
            "chosen_by": e.chosen_by.email if e.chosen_by_id else ""}
