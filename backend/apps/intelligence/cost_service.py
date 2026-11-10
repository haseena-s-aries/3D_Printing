"""Cost and lead-time comparisons (CN-007 Phase 4): store, preview and explain.

preview(): calculate a scenario (e.g. a what-if quantity) without storing anything.
create():  validate, calculate and store a new immutable comparison version linked to the part's latest Phase 3
           feasibility version (required) and passport revision; unchanged inputs reuse the stored version. Optional
           Gemini assumption notes (explanations only) for synthetic scenarios of a company permitted to use external AI.

Technical status per alternative comes from the feasibility version, including an engineer's correction recorded in
its technical review. Additive and conventional routes are never "technically qualified" here: no formal engineering
approval exists (OQ-35/OQ-36). A lower cost never changes a technical status, passport, eligibility or release state,
and no alternative is recommended.

Sent to the AI (whitelist, `ai_payload`): technical status labels, quantities, MOQ, and per cost component its label,
basis, data source and share of the alternative's known cost (whole percent), lead-time days and sources, currency
codes. Never amounts, totals, rates, references, supplier names or notes.
"""
import hashlib
import json
import re
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from apps.audit.service import record
from apps.core.exceptions import DomainError
from apps.parts.models import SparePart
from apps.parts.submissions import display_name

from . import costing as C
from . import feasibility as F
from . import feasibility_service as FS
from . import consistency, gemini, service
from .models import AIUsageLog, CostComparison, FeasibilityAssessment

PROMPT_VERSION = "cost-prompt-2026-10-28.2"  # .2: status echo; statements contradicting the technical status removed
U = AIUsageLog.Outcome
A = CostComparison.AIStatus
RECOMMEND_RE = re.compile(r"[^.;\n]*\b(?:recommend\w*|should be (?:purchased|procured|bought|manufactured|printed|chosen)|"
                          r"best (?:option|choice|alternative)|preferred (?:option|alternative|route)|choose the)\b[^.;\n]*[.;]?", re.I)
NOT_QUALIFIED = "Not technically qualified"


# ------------------------------------------------------------------ technical status (Phase 3)

def latest_feasibility(part):
    return FeasibilityAssessment.objects.filter(tenant=part.tenant_id, part=part).order_by("-version").first()


def technical(fa: FeasibilityAssessment) -> dict:
    out = {}
    reviews = {}
    for r in fa.reviews.all().order_by("created_at"):
        reviews[r.alternative] = r
    for alt in ("oem", "additive", "conventional"):
        status = getattr(fa, f"{alt}_status")
        r = reviews.get(alt)
        corrected = r.corrected_status if r and r.decision == "corrected" else ""
        eff = corrected or status
        labels = F.OEM_STATUS if alt == "oem" else F.MF_STATUS
        if alt == "oem":
            qualified = eff == "identified_confirmation_required"
            label = "OEM part identified (availability still needs supplier confirmation)" if qualified else \
                "Not verified: OEM identity / availability"
        else:
            qualified = False  # no formal engineering approval exists in this platform yet
            label = ("Excluded: not suitable based on verified constraints" if eff == "not_suitable_verified"
                     else f"{NOT_QUALIFIED}: {labels.get(eff, eff).lower()}")
        out[alt] = {"status": eff, "status_label": labels.get(eff, eff), "screening_status": status,
                    "corrected_by_review": bool(corrected), "review_decision": r.get_decision_display() if r else "",
                    "qualified": qualified, "excluded": eff == "not_suitable_verified", "label": label,
                    "feasibility_version": fa.version}
    return out


# ------------------------------------------------------------------ calculate

def _validated(data) -> dict:
    try:
        return C.validate(data, timezone.localdate())
    except C.CostInputError as e:
        raise DomainError("invalid_cost_inputs", "Some inputs are invalid.", details={"errors": e.errors}, http_status=400)


def _require_feasibility(part):
    fa = latest_feasibility(part)
    if fa is None:
        raise DomainError("feasibility_required", "Run the manufacturing feasibility assessment (Phase 3) first.", http_status=409)
    return fa


def preview(request, part, data: dict) -> dict:
    """Calculate without storing (what-if quantities and draft scenarios)."""
    fa = _require_feasibility(part)
    sc = _validated(data)
    tech = technical(fa)
    return {"results": C.calculate(sc, tech, timezone.localdate()), "technical": tech, "feasibility_version": fa.version,
            "stored": False}


def _hash(blob) -> str:
    return hashlib.sha256(json.dumps(blob, sort_keys=True, default=str).encode()).hexdigest()


def ai_payload(results: dict, technical_: dict) -> dict:
    """The complete payload sent to the provider (whitelist; see the module docstring)."""
    out = {"required_quantity": results["quantity"], "alternatives": {}}
    for k, a in results["alternatives"].items():
        known = Decimal(a["known_costs_total"] or 0)
        comps = []
        for ln in a["lines"]:
            share = None
            if ln.get("reporting_amount") is not None and known > 0:
                share = int((Decimal(ln["reporting_amount"]) / known * 100).quantize(Decimal(1)))
            comps.append({"component": ln["label"], "basis": ln.get("basis", ""), "source": ln.get("source_label", ""),
                          "not_applicable": ln.get("not_applicable", False),
                          "missing": not ln.get("not_applicable") and ln.get("reporting_amount") is None,
                          "expired_quotation": bool(ln.get("expired")), "share_of_known_cost_percent": share})
        out["alternatives"][k] = {
            "technical_status": technical_[k]["label"], "technical_status_code": technical_[k]["status"], "ordered_quantity": a["ordered_quantity"], "moq": a["moq"],
            "order_multiple": a["order_multiple"], "qualification_units": a["qualification_units"],
            "total_complete": a["complete"], "data_confidence": a["confidence"], "cost_components": comps,
            "lead_time": [{"component": c["label"], "days": c.get("days"), "source": c.get("source_label", "")}
                          for c in a["lead_time"]["components"]],
            "currencies": sorted({ln.get("currency") for ln in a["lines"] if ln.get("currency")}),
        }
    return out


def _clean(obj, removed):
    obj = FS._clean(obj, removed)

    def rec(o):
        if isinstance(o, str):
            for m in RECOMMEND_RE.findall(o):
                if m.strip():
                    removed.append(m.strip())
            return RECOMMEND_RE.sub(" [recommendation removed: none is made in this phase] ", o).strip()
        if isinstance(o, list):
            return [rec(x) for x in o]
        if isinstance(o, dict):
            return {k: rec(v) for k, v in o.items()}
        return o
    return rec(obj)


INVALID_CODES = ("invalid_json", "schema_mismatch", "contradicts_technical_status")


def check_status_echo(result: dict, tech: dict):
    """The AI must repeat each alternative's recorded technical status; anything else contradicts the record."""
    wrong = [f"{k}: {result[k]['technical_status']} (recorded {tech[k]['status']})" for k in tech
             if result.get(k, {}).get("technical_status") != tech[k]["status"]]
    if wrong:
        raise gemini.AIError("contradicts_technical_status", "The response contradicts the recorded technical status: "
                             + "; ".join(wrong), True)


def create(request, part, data: dict, tier: str | None = None, derived_from=None) -> tuple[CostComparison, bool]:
    if tier and tier not in service.TIERS:
        raise DomainError("invalid_tier", "Choose lite, flash or pro.", http_status=400)
    sc = _validated(data)
    base = None
    if derived_from:
        base = CostComparison.objects.filter(tenant=request.tenant, part=part, pk=derived_from).first()
        if base is None:
            raise DomainError("not_found", "The comparison to derive from was not found for this part.", http_status=404)
    if tier:
        st = service.ai_status(request.tenant)
        if not st["enabled"]:
            raise DomainError("ai_not_permitted", st["reason"], http_status=403)
        if not part.import_record:
            raise DomainError("ai_not_permitted_for_part", "External AI is used only for imported synthetic inventory records; the rules-based assessment is available for every part.", http_status=403)
        if not sc["synthetic"]:
            raise DomainError("ai_not_permitted_for_scenario", "External AI is used only for scenarios marked as synthetic test data.",
                              http_status=403)
    fa = _require_feasibility(part)
    today = timezone.localdate()
    tech = technical(fa)
    results = C.calculate(sc, tech, today)
    inputs = C.serialisable(sc)
    pp = F.passport_info(part)
    model = settings.GEMINI_MODELS[tier] if tier else ""
    h = _hash({"method": C.METHOD_VERSION, "inputs": inputs, "feasibility": str(fa.pk), "technical": tech, "as_of": today,
               "prompt": PROMPT_VERSION if tier else "", "model": model,
               "passport_revision": pp["revision_id"] if pp else None})
    existing = (CostComparison.objects.filter(tenant=request.tenant, part=part, input_hash=h, ai_status__in=[A.NONE, A.OK])
                .order_by("-version").first())
    if existing:
        if tier:
            AIUsageLog.objects.create(tenant=request.tenant, created_by=request.user, user=request.user, part_id=part.pk,
                                      assessment_id=existing.pk, provider="gemini", model=model,
                                      model_version=existing.ai.get("model_version", ""), outcome=U.CACHE_HIT)
        record(request, "cost_comparison.reused", obj=part, data={"comparison": str(existing.pk), "version": existing.version})
        return existing, True

    ai, ai_status = {}, A.NONE
    if tier:
        log = service._reserve(request, model, part)  # raises service.Refused at a limit
        sent = ai_payload(results, tech)
        prompt = "Explain the cost and lead-time assumptions of this comparison. Data (JSON):\n" + json.dumps(sent, ensure_ascii=False, indent=1)
        notes, call, totals, attempts, err = service.call_ai(model, tier, prompt, gemini.COST_SCHEMA, gemini.SYSTEM_COST,
                                                             gemini.CostNotes, check=lambda r: check_status_echo(r, tech))
        cost = gemini.cost_usd(model, call.model_version if call else "", totals["prompt"], totals["output"], totals["thinking"])
        removed, contra = [], []
        if notes:
            notes = _clean(notes, removed)
            notes, contra = consistency.scrub(notes, {k: tech[k]["status"] for k in tech})
            removed += [x["sentence"] for x in contra]
        ai_status = A.OK if notes else (A.INVALID if err and err.code in INVALID_CODES else A.FAILED)
        ai = {"provider": "gemini", "tier": tier, "model": model, "model_version": call.model_version if call else "",
              "prompt_version": PROMPT_VERSION, "sent": sent, "response": notes or {}, "removed": removed, "contradictions": contra,
              "usage": {"prompt_tokens": totals["prompt"], "output_tokens": totals["output"], "thinking_tokens": totals["thinking"],
                        "cost_usd": cost, "latency_ms": totals["latency"], "attempts": attempts},
              "error_code": err.code if err else "", "error_message": gemini.scrub(err.message) if err else ""}

    with transaction.atomic():
        SparePart.objects.select_for_update().filter(pk=part.pk).first()
        version = (CostComparison.objects.filter(tenant=request.tenant, part=part).aggregate(m=Max("version"))["m"] or 0) + 1
        c = CostComparison.objects.create(
            tenant=request.tenant, created_by=request.user, part=part, project_id=part.project_id, version=version,
            method_version=C.METHOD_VERSION, feasibility=fa, feasibility_version=fa.version,
            passport_number=pp["passport_number"] if pp else "", passport_revision_id=pp["revision_id"] if pp else None,
            passport_revision_number=pp["revision_number"] if pp else None, name=sc["name"], synthetic=sc["synthetic"],
            quantity=sc["quantity"], reporting_currency=sc["reporting_currency"], derived_from=base, input_hash=h,
            inputs=inputs, technical=tech, results=results, as_of=today, ai_status=ai_status, ai=ai)
    if tier:
        AIUsageLog.objects.filter(pk=log.pk).update(
            assessment_id=c.pk, model_version=ai["model_version"],
            outcome={A.OK: U.OK, A.INVALID: U.INVALID}.get(ai_status, U.FAILED),
            prompt_tokens=totals["prompt"], output_tokens=totals["output"], thinking_tokens=totals["thinking"],
            cost_usd=Decimal(str(cost or 0)), latency_ms=totals["latency"], attempts=attempts, error_code=ai["error_code"],
            updated_at=timezone.now())
    record(request, "cost_comparison.created", obj=part, data={
        "comparison": str(c.pk), "version": version, "method": C.METHOD_VERSION, "feasibility_version": fa.version,
        "quantity": c.quantity, "currency": c.reporting_currency, "synthetic": c.synthetic,
        "derived_from": str(base.pk) if base else "", "ai_status": ai_status, "model": model,
        **({k: ai["usage"][k] for k in ("prompt_tokens", "output_tokens", "cost_usd")} if tier else {})})
    return c, False


# ------------------------------------------------------------------ views

def serialise(c: CostComparison, latest_fa=None) -> dict:
    return {"id": str(c.pk), "version": c.version, "name": c.name, "synthetic": c.synthetic, "method_version": c.method_version,
            "quantity": c.quantity, "reporting_currency": c.reporting_currency, "as_of": c.as_of,
            "feasibility_id": str(c.feasibility_id), "feasibility_version": c.feasibility_version,
            "feasibility_superseded": bool(latest_fa and latest_fa.pk != c.feasibility_id),
            "project": c.project.code if c.project_id else "", "passport_number": c.passport_number,
            "passport_revision_number": c.passport_revision_number,
            "derived_from_version": c.derived_from.version if c.derived_from_id else None,
            "inputs": c.inputs, "technical": c.technical, "results": c.results, "ai_status": c.ai_status,
            "ai_status_label": c.get_ai_status_display(), "ai": c.ai, "input_hash": c.input_hash,
            # stored notes are immutable: notes written before the consistency check are flagged here, never changed
            "ai_consistency": consistency.check_stored(c.ai.get("response") or {}, {k: v["status"] for k, v in c.technical.items()}),
            "created_at": c.created_at, "created_by_name": display_name(c.created_by)}


def template(currency: str = "USD") -> dict:
    """A blank scenario: every figure missing until entered, nothing assumed."""
    def comp():
        return {"amount": None, "currency": currency, "source": "missing", "reference": "", "valid_until": None,
                "not_applicable": False, "note": ""}
    alt = lambda: {"moq": 1, "order_multiple": 1, "qualification_units": 0, "notes": "",  # noqa: E731
                   "costs": {**{k: comp() for k in C.COSTS}, "logistics": {**comp(), "basis": "per_order"},
                             "duties": {"percent": None, "source": "missing", "reference": "", "not_applicable": False, "note": ""}},
                   "lead_time": {"supplier_days": {"days": None, "source": "missing", "reference": "", "not_applicable": False},
                                 "engineering_days": {"days": None, "source": "missing", "reference": "", "not_applicable": False}}}
    return {"name": "", "synthetic": False, "quantity": 1, "reporting_currency": currency, "baseline": "oem", "notes": "",
            "exchange_rates": [], "alternatives": {k: alt() for k in C.ALTERNATIVES}}


def part_view(request, part) -> dict:
    fa = latest_feasibility(part)
    status = service.ai_status(request.tenant)
    if status["enabled"] and not part.import_record:
        status = {**status, "enabled": False, "reason": "External AI is used only for imported synthetic inventory records; the rules-based assessment is available for every part."}
    items = list(CostComparison.objects.filter(tenant=request.tenant, part=part)
                 .select_related("created_by", "project", "derived_from").order_by("-version")[:20])
    return {"ai": status, "feasibility": ({"id": str(fa.pk), "version": fa.version, "technical": technical(fa)} if fa else None),
            "comparisons": [serialise(c, fa) for c in items], "template": template(),
            "labels": {"sources": C.SOURCES, "alternatives": C.ALTERNATIVES, "costs": {k: v[0] for k, v in C.COSTS.items()},
                       "lead": C.LEAD, "categories": C.CATEGORIES},
            "statement": "Comparison only. No procurement recommendation, manufacturing authorisation or release is made."}


def overview(request, parts) -> dict:
    latest = {}
    for c in CostComparison.objects.filter(tenant=request.tenant, part__in=parts).order_by("part_id", "-version"):
        latest.setdefault(c.part_id, c)
    rows = []
    for p in parts:
        c = latest.get(p.pk)
        row = {"id": str(p.pk), "part_number": p.part_number, "name": p.name, "comparison": None}
        if c:
            row["comparison"] = {"id": str(c.pk), "version": c.version, "name": c.name, "synthetic": c.synthetic, "quantity": c.quantity,
                                 "currency": c.reporting_currency, "feasibility_version": c.feasibility_version,
                                 "alternatives": {k: {"total": a["total"], "effective_unit_cost": a["effective_unit_cost"],
                                                      "lead_days": a["lead_time"]["total_days"], "confidence": a["confidence"],
                                                      "technical": a["technical"]["label"], "savings": a["comparison"]["savings"],
                                                      "savings_percent": a["comparison"]["savings_percent"],
                                                      "missing": len(a["missing_inputs"])}
                                                  for k, a in c.results["alternatives"].items()}}
        rows.append(row)
    return {"parts": rows}
