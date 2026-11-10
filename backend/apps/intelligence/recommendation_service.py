"""Recommendations and engineering review (CN-007 Phase 5).

create(): combine the part's latest Phase 3 feasibility version (required), a Phase 4 cost comparison (the latest, or
          one chosen) and the latest Phase 2 AI suggestion (context only) with apps.intelligence.recommendation. Stored
          as a new immutable version that keeps the source revisions; unchanged inputs reuse the stored version. An
          optional Gemini explanation must repeat the deterministic outcome and every technical status; contradicting,
          priced, approving or recommending sentences are removed.
review(): engineering review queue decisions: approved for further study, information requested, corrected, rejected.
          The engineer who generated a version cannot approve it for further study or correct it (separation of
          duties). An option that fails a mandatory requirement cannot become the recommendation by correction, and an
          excluded option cannot be approved for further study. Nothing here changes a passport, evidence level,
          manufacturing eligibility or release state (OQ-35, OQ-36).

Sent to the AI (whitelist, `ai_payload`): the outcome, per option its technical status, requirement results, eligibility,
commercial completeness, evidence-strength label, relative cost index (total / lowest complete total), lead-time days,
cheapest/fastest flags and missing-input labels; the Phase 2 part family, category and completeness score. Never amounts,
references, file names, drawings, CAD, part numbers, supplier or customer names.
"""
import hashlib
import json
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from apps.audit.service import record
from apps.core.exceptions import DomainError
from apps.parts.models import SparePart
from apps.parts.submissions import display_name

from . import consistency, cost_service, gemini, service
from . import feasibility as F
from . import feasibility_service as FS
from . import recommendation as R
from .models import AIUsageLog, CostComparison, PartAssessment, Recommendation, RecommendationReview

PROMPT_VERSION = "rec-prompt-2026-10-28.2"  # .2: lists of needed information are not read as claims
U = AIUsageLog.Outcome
A = Recommendation.AIStatus
D = RecommendationReview.Decision
INVALID_CODES = ("invalid_json", "schema_mismatch", "contradicts_technical_status", "contradicts_outcome")
APPROVAL_WORDS = FS.APPROVAL_WORDS | {"approve_for_manufacture", "manufacturing_approval", "release_for_production"}


# ------------------------------------------------------------------ sources

def _sources(request, part, cost_comparison_id=None):
    fa = cost_service.latest_feasibility(part)
    if fa is None:
        raise DomainError("feasibility_required", "Run the manufacturing feasibility assessment (Phase 3) first.", http_status=409)
    qs = CostComparison.objects.filter(tenant=request.tenant, part=part)
    if cost_comparison_id:
        cc = qs.filter(pk=cost_comparison_id).first()
        if cc is None:
            raise DomainError("not_found", "Cost comparison not found for this part.", http_status=404)
    else:  # D-23: the latest comparison calculated on the current feasibility; otherwise the latest one (refused below)
        cc = qs.filter(feasibility=fa).order_by("-version").first() or qs.order_by("-version").first()
    pa = PartAssessment.objects.filter(tenant=request.tenant, part=part, status=PartAssessment.Status.OK).order_by("-created_at").first()
    return fa, cc, pa


def phase2_summary(part, analysis: dict, pa) -> dict:
    prov = (part.field_provenance or {}).get("category") or {}
    return {"family": analysis["classification"]["family"], "rules_category": analysis["classification"]["category"],
            "category": part.category, "category_verified": bool(prov.get("verified_by")),
            "completeness": analysis["completeness"]["score"], "missing": analysis["completeness"]["missing"],
            "duplicates": analysis["duplicates"]["same_description_and_manufacturer"],
            "manufacturer_possibly_truncated": analysis["manufacturer"]["possibly_truncated"],
            "ai_suggestion": ({"id": str(pa.pk), "model": pa.model_version or pa.model, "category": pa.result.get("category"),
                               "part_family": pa.result.get("part_family"), "am_screening": pa.result.get("am_screening"),
                               "confidence": pa.confidence, "created_at": pa.created_at.isoformat(),
                               "note": "Phase 2 AI suggestion: context only, never a decision input"} if pa else None)}


def _confidence(fa, res) -> dict:
    n = len(fa.missing_information)
    tech = ("High: evidence complete" if n == 0 else f"Medium: {n} evidence item(s) missing or unverified" if n <= 5
            else f"Low: {n} evidence items missing or unverified")
    order = ["incomplete", "no_comparison", "ai_estimates", "estimates", "includes_expired_quotation", "historical", "verified_current"]
    evs = [o["commercial"]["evidence"] for o in res["options"].values() if not o["excluded"]]
    weakest = min(evs, key=order.index) if evs else "no_comparison"
    return {"technical": tech, "commercial": R.EVIDENCE[weakest][0], "overall": "Low" if n > 5 or weakest in order[:4] else "Medium"}


def evaluate(request, part, raw_weights=None, cost_comparison_id=None):
    fa, cc, pa = _sources(request, part, cost_comparison_id)
    today = timezone.localdate()
    tech = cost_service.technical(fa)
    try:
        res = R.evaluate(tech, {"oem": fa.oem, "additive": fa.additive, "conventional": fa.conventional}, part.criticality,
                         cc.results if cc else None, raw_weights, today)
    except R.WeightError as e:
        raise DomainError("invalid_weights", str(e), http_status=400)
    analysis = service.analyse(part)
    p2 = phase2_summary(part, analysis, pa)
    risks = []
    for k in ("oem", "additive", "conventional"):
        risks += [f"{R.OPTIONS[k]}: {x}" for x in getattr(fa, k).get("risks", [])]
        risks += [f"{R.OPTIONS[k]}: {x}" for x in res["options"][k]["commercial"].get("expired_quotations", [])]
    if cc and cc.feasibility_id != fa.pk:
        risks.append(f"Cost comparison v{cc.version} was calculated with feasibility v{cc.feasibility_version}; technical status here "
                     f"uses the latest feasibility v{fa.version}.")
    if cc is None:
        risks.append("No cost comparison: commercial statuses cannot be determined.")
    missing = list(fa.missing_information)
    for k, o in res["options"].items():
        missing += [f"{R.OPTIONS[k]} cost: {m}" for m in o["commercial"].get("missing_inputs", [])]
    res.update(phase2=p2, risks=risks, missing_information=missing, confidence=_confidence(fa, res),
               sources={"feasibility": {"id": str(fa.pk), "version": fa.version, "methodology": fa.methodology_version},
                        "cost_comparison": ({"id": str(cc.pk), "version": cc.version, "name": cc.name, "synthetic": cc.synthetic,
                                             "quantity": cc.quantity, "currency": cc.reporting_currency, "method": cc.method_version,
                                             "as_of": cc.as_of.isoformat(), "feasibility_version": cc.feasibility_version} if cc else None),
                        "intelligence": ({"id": str(pa.pk), "model": pa.model_version or pa.model} if pa else None)})
    return fa, cc, pa, res, today


# ------------------------------------------------------------------ AI explanation

def ai_payload(res: dict) -> dict:
    """The complete payload sent to the provider (whitelist; see the module docstring)."""
    totals = [Decimal(o["commercial"]["total"]) for o in res["options"].values() if o["commercial"].get("complete") and not o["excluded"]]
    low = min(totals) if totals else None
    opts = {}
    for k, o in res["options"].items():
        c = o["commercial"]
        opts[k] = {"technical_status_code": o["technical"]["status"], "technical_status": o["technical"]["status_label"],
                   "meets_mandatory_requirements": o["eligible"],
                   "requirements": [{"requirement": r["label"], "met": r["met"]} for r in o["requirements"]],
                   "commercial_complete": c.get("complete", False), "commercial_evidence": c["evidence_label"],
                   "relative_cost_index": (str((Decimal(c["total"]) / low).quantize(Decimal("0.01"))) if c.get("complete") and low else None),
                   "lead_time_days": c.get("lead_days"), "commercially_cheapest": o["flags"]["commercially_cheapest"],
                   "cheapest_definitive": o["flags"]["cheapest_definitive"], "fastest": o["flags"]["fastest"],
                   "missing_cost_inputs": c.get("missing_inputs", []), "expired_quotation": bool(c.get("expired_quotations"))}
    p2 = res["phase2"]
    return {"outcome_code": res["outcome"]["code"], "outcome": res["outcome"]["label"], "options": opts,
            "part": {"family": p2["family"], "category": p2["category"], "category_verified": p2["category_verified"],
                     "record_completeness_percent": p2["completeness"]},
            "weights_applied": res["weights_applied"]}


def _check(result: dict, res: dict):
    if result.get("outcome_code") != res["outcome"]["code"]:
        raise gemini.AIError("contradicts_outcome", f"Outcome {result.get('outcome_code')} differs from {res['outcome']['code']}.", True)
    cost_service.check_status_echo(result, {k: o["technical"] for k, o in res["options"].items()})


# ------------------------------------------------------------------ create

def alignment_problems(part, fa, cc) -> list[str]:
    """Why these inputs may not produce a recommendation (D-23): the feasibility must match the part's current data and the cost
    comparison must have been calculated on that same feasibility version."""
    out = []
    if not FS.inputs_current(part, fa):
        out.append(f"The part, passport or documents changed after feasibility v{fa.version}: run the feasibility assessment again first.")
    if cc is not None and cc.feasibility_id != fa.pk:
        out.append(f"Cost comparison v{cc.version} was calculated with feasibility v{cc.feasibility_version}, not the current "
                   f"v{fa.version}: recalculate the cost comparison (save it as a new version) first.")
    return out


def create(request, part, raw_weights=None, tier=None, cost_comparison_id=None):
    if tier:
        if tier not in service.TIERS:
            raise DomainError("invalid_tier", "Choose lite, flash or pro.", http_status=400)
        st = service.ai_status(request.tenant)
        if not st["enabled"]:
            raise DomainError("ai_not_permitted", st["reason"], http_status=403)
        if not part.import_record:
            raise DomainError("ai_not_permitted_for_part", "External AI is used only for imported synthetic inventory records; the rules-based assessment is available for every part.", http_status=403)
    fa, cc, pa, res, today = evaluate(request, part, raw_weights, cost_comparison_id)
    problems = alignment_problems(part, fa, cc)
    if problems:  # D-23: stale or mismatched inputs never produce a recommendation version
        record(request, "recommendation.refused_inputs", obj=part, data={"problems": problems, "feasibility_version": fa.version,
                                                                         "cost_comparison_version": cc.version if cc else None})
        raise DomainError("inputs_not_aligned", problems[0], details={"problems": problems}, http_status=409)
    if tier and cc is not None and not cc.synthetic:
        raise DomainError("ai_not_permitted_for_scenario", "External AI is used only with cost scenarios marked as synthetic test data.",
                          http_status=403)
    pp = F.passport_info(part)
    model = settings.GEMINI_MODELS[tier] if tier else ""
    inputs = {"weights": res["weights"], "weights_requested": raw_weights or None, "feasibility": str(fa.pk),
              "cost_comparison": str(cc.pk) if cc else None, "intelligence": str(pa.pk) if pa else None,
              # D-23: the exact versions of the assessment chain this recommendation was generated from
              "versions": {"feasibility": fa.version, "cost_comparison": cc.version if cc else None,
                           "cost_comparison_feasibility": cc.feasibility_version if cc else None,
                           "passport_revision": pp["revision_number"] if pp else None}}
    h = hashlib.sha256(json.dumps({"method": R.METHOD_VERSION, "inputs": inputs, "tech": cost_service.technical(fa), "as_of": today,
                                   "criticality": part.criticality, "prompt": PROMPT_VERSION if tier else "", "model": model,
                                   "passport_revision": pp["revision_id"] if pp else None},
                                  sort_keys=True, default=str).encode()).hexdigest()
    existing = (Recommendation.objects.filter(tenant=request.tenant, part=part, input_hash=h, ai_status__in=[A.NONE, A.OK])
                .order_by("-version").first())
    if existing:
        if tier:
            AIUsageLog.objects.create(tenant=request.tenant, created_by=request.user, user=request.user, part_id=part.pk,
                                      assessment_id=existing.pk, provider="gemini", model=model,
                                      model_version=existing.ai.get("model_version", ""), outcome=U.CACHE_HIT)
        record(request, "recommendation.reused", obj=part, data={"recommendation": str(existing.pk), "version": existing.version})
        return existing, True
    ai, ai_status = {}, A.NONE
    if tier:
        log = service._reserve(request, model, part)
        sent = ai_payload(res)
        prompt = "Explain this deterministic evaluation. Data (JSON):\n" + json.dumps(sent, ensure_ascii=False, indent=1)
        expl, call, totals, attempts, err = service.call_ai(model, tier, prompt, gemini.REC_SCHEMA, gemini.SYSTEM_REC, gemini.RecExplanation,
                                                            check=lambda r: _check(r, res))
        cost = gemini.cost_usd(model, call.model_version if call else "", totals["prompt"], totals["output"], totals["thinking"])
        removed, contra = [], []
        if expl:
            expl = cost_service._clean(expl, removed)
            expl, contra = consistency.scrub(expl, {k: o["technical"]["status"] for k, o in res["options"].items()})
            removed += [x["sentence"] for x in contra]
        ai_status = A.OK if expl else (A.INVALID if err and err.code in INVALID_CODES else A.FAILED)
        ai = {"provider": "gemini", "tier": tier, "model": model, "model_version": call.model_version if call else "",
              "prompt_version": PROMPT_VERSION, "sent": sent, "response": expl or {}, "removed": removed, "contradictions": contra,
              "usage": {"prompt_tokens": totals["prompt"], "output_tokens": totals["output"], "thinking_tokens": totals["thinking"],
                        "cost_usd": cost, "latency_ms": totals["latency"], "attempts": attempts},
              "error_code": err.code if err else "", "error_message": gemini.scrub(err.message) if err else ""}
    with transaction.atomic():
        SparePart.objects.select_for_update().filter(pk=part.pk).first()
        version = (Recommendation.objects.filter(tenant=request.tenant, part=part).aggregate(m=Max("version"))["m"] or 0) + 1
        rec = Recommendation.objects.create(
            tenant=request.tenant, created_by=request.user, part=part, project_id=part.project_id, version=version,
            method_version=R.METHOD_VERSION, intelligence=pa, feasibility=fa, feasibility_version=fa.version, cost_comparison=cc,
            cost_comparison_version=cc.version if cc else None, passport_number=pp["passport_number"] if pp else "",
            passport_revision_id=pp["revision_id"] if pp else None, passport_revision_number=pp["revision_number"] if pp else None,
            input_hash=h, inputs=inputs, results=res, outcome=res["outcome"]["code"], recommended_option=res["outcome"]["option"] or "",
            as_of=today, ai_status=ai_status, ai=ai)
    if tier:
        AIUsageLog.objects.filter(pk=log.pk).update(
            assessment_id=rec.pk, model_version=ai["model_version"], outcome={A.OK: U.OK, A.INVALID: U.INVALID}.get(ai_status, U.FAILED),
            prompt_tokens=totals["prompt"], output_tokens=totals["output"], thinking_tokens=totals["thinking"],
            cost_usd=Decimal(str(cost or 0)), latency_ms=totals["latency"], attempts=attempts, error_code=ai["error_code"],
            updated_at=timezone.now())
    record(request, "recommendation.created", obj=part, data={
        "recommendation": str(rec.pk), "version": version, "outcome": rec.outcome, "option": rec.recommended_option,
        "feasibility_version": fa.version, "cost_comparison_version": rec.cost_comparison_version,
        "intelligence": str(pa.pk) if pa else "", "weights": res["weights"], "ai_status": ai_status, "model": model,
        **({k: ai["usage"][k] for k in ("prompt_tokens", "output_tokens", "cost_usd")} if tier else {})})
    return rec, False


# ------------------------------------------------------------------ engineering review

def approval_blockers(part, rec: Recommendation) -> list[str]:
    """Why this recommendation version may not be approved for further study, corrected or shared (post-UAT D-07/D-13):
    outdated feasibility or cost inputs are never reused for an approval."""
    out = []
    fa = cost_service.latest_feasibility(part)
    if fa and fa.pk != rec.feasibility_id:
        out.append(f"A newer feasibility version (v{fa.version}) exists: generate a new recommendation version first.")
    cc = CostComparison.objects.filter(tenant=part.tenant, part=part).order_by("-version").first()
    if cc and cc.pk != rec.cost_comparison_id:
        out.append(f"A newer cost comparison (v{cc.version}) exists: generate a new recommendation version first.")
    if rec.cost_comparison_id and rec.cost_comparison.feasibility_id != rec.feasibility_id:
        out.append(f"The cost comparison (v{rec.cost_comparison.version}) was built on a different feasibility version: derive a new "
                   "cost comparison from the current feasibility, then generate a new recommendation version.")
    if not FS.inputs_current(part, rec.feasibility):
        out.append("The part, passport or documents changed after the feasibility assessment this version is based on (for example "
                   "material or dimensions): run a new feasibility assessment and generate a new recommendation version.")
    return out


def review(request, part, rec_id, data: dict) -> RecommendationReview:
    rec = Recommendation.objects.filter(tenant=request.tenant, part=part, pk=rec_id).first()
    if rec is None:
        raise DomainError("not_found", "Recommendation not found for this part.", http_status=404)
    decision = str(data.get("decision") or "").strip().lower()
    if decision in APPROVAL_WORDS:
        raise DomainError("formal_approval_not_available",
                          "Engineering approval, manufacturing authorisation, passport publication and production release are "
                          "not available (OQ-35, OQ-36). Use 'approved for further study' to continue the evaluation.", http_status=403)
    if decision not in D.values:
        raise DomainError("invalid_decision", "Choose approved_for_further_study, information_requested, corrected or rejected.", http_status=400)
    latest = Recommendation.objects.filter(tenant=request.tenant, part=part).aggregate(m=Max("version"))["m"]
    if rec.version != latest:
        raise DomainError("recommendation_superseded", f"Version {rec.version} has been superseded by version {latest}; review the latest version.",
                          http_status=409)
    findings = str(data.get("findings") or "").strip()
    if not findings:
        raise DomainError("findings_required", "Record the review findings.", http_status=400)
    if len(findings) > 2000:
        raise DomainError("too_long", "Findings are limited to 2000 characters.", http_status=400)
    option = str(data.get("option") or "").strip()
    opts = rec.results["options"]
    if decision in (D.FURTHER_STUDY, D.CORRECTED):
        allowed = list(R.OPTIONS) + (["none"] if decision == D.CORRECTED else [])
        if option not in allowed:
            raise DomainError("invalid_option", "Choose the option" + (" (or none)" if decision == D.CORRECTED else "") + ".", http_status=400)
    elif option:
        raise DomainError("invalid_option", "An option is given only when approving for further study or correcting.", http_status=400)
    independent = rec.created_by_id != request.user.id
    if decision in (D.FURTHER_STUDY, D.CORRECTED):
        last = rec.reviews.order_by("-created_at").first()
        if last is not None and last.decision in (D.INFO, D.REJECTED):
            raise DomainError("revision_required", f"Version {rec.version} was {last.get_decision_display().lower()}. Address it and "
                              "generate a revised recommendation version; the revised version is then reviewed independently.", http_status=409)
        blockers = approval_blockers(part, rec)
        if blockers:
            raise DomainError("recommendation_outdated", blockers[0], details={"blockers": blockers}, http_status=409)
    if decision in (D.FURTHER_STUDY, D.CORRECTED) and not independent:
        raise DomainError("self_review", "You generated this recommendation. Another assigned Aries Engineer must approve it for "
                          "further study or correct it. You can request information or reject it.", http_status=403)
    eligible = bool(option in opts and opts[option]["eligible"])
    if decision == D.FURTHER_STUDY and option in opts and opts[option]["excluded"]:
        raise DomainError("option_excluded", "This option is excluded by a verified technical constraint.", http_status=409)
    if decision == D.CORRECTED and option in opts and not eligible:
        raise DomainError("option_not_eligible", "A correction cannot make an option that fails a mandatory requirement the "
                          "recommendation. Record the findings, request information or correct to 'none'.", http_status=409)
    refs = FS._references(part, data.get("evidence_references") or [])
    r = RecommendationReview.objects.create(
        tenant=request.tenant, created_by=request.user, recommendation=rec, part=part, decision=decision, option=option,
        findings=findings, evidence_references=refs, independent=independent, option_eligible=eligible,
        reviewer_name=display_name(request.user))
    record(request, "recommendation.reviewed", obj=part, data={
        "recommendation": str(rec.pk), "version": rec.version, "decision": decision, "option": option, "independent": independent,
        "option_eligible": eligible, "evidence_references": len(refs)})
    return r


# ------------------------------------------------------------------ views

def review_state(reviews: list) -> dict:
    if not reviews:
        return {"code": "preliminary", "label": "Preliminary: not reviewed", "reviewed": False}
    r = reviews[-1]
    opt = f" ({R.OPTIONS.get(r.option, 'none')})" if r.option else ""
    return {"code": r.decision, "label": f"Reviewed: {r.get_decision_display()}{opt}, {r.reviewer_name}"
            + (" (independent)" if r.independent else " (by the engineer who generated it)"), "reviewed": True,
            "decision": r.decision, "option": r.option}


def serialise_review(r: RecommendationReview) -> dict:
    return {"id": str(r.pk), "decision": r.decision, "decision_label": r.get_decision_display(), "option": r.option,
            "option_label": R.OPTIONS.get(r.option, "None" if r.option == "none" else ""), "findings": r.findings,
            "evidence_references": r.evidence_references, "independent": r.independent, "option_eligible": r.option_eligible,
            "reviewer": r.reviewer_name, "created_at": r.created_at}


def serialise(rec: Recommendation, latest: dict | None = None) -> dict:
    reviews = list(rec.reviews.all().order_by("created_at"))
    statuses = {k: o["technical"]["status"] for k, o in rec.results.get("options", {}).items()}
    stale = []
    if latest:
        if latest.get("feasibility") and latest["feasibility"] != str(rec.feasibility_id):
            stale.append("A newer feasibility version exists.")
        if latest.get("cost") and latest["cost"] != str(rec.cost_comparison_id or ""):
            stale.append("A newer cost comparison exists.")
        if latest.get("snapshot") and FS._hash(rec.feasibility.inputs) != latest["snapshot"]:
            stale.append("The part, passport or documents changed after the feasibility this version is based on.")
    if rec.cost_comparison_id and rec.cost_comparison.feasibility_id != rec.feasibility_id:
        stale.append(f"Its cost comparison v{rec.cost_comparison.version} was calculated with feasibility "
                     f"v{rec.cost_comparison.feasibility_version}, not v{rec.feasibility_version}.")
    return {"id": str(rec.pk), "version": rec.version, "method_version": rec.method_version, "as_of": rec.as_of,
            "outcome": rec.outcome, "recommended_option": rec.recommended_option, "results": rec.results, "inputs": rec.inputs,
            "feasibility_version": rec.feasibility_version, "cost_comparison_version": rec.cost_comparison_version,
            "passport_number": rec.passport_number, "passport_revision_number": rec.passport_revision_number,
            "project": rec.project.code if rec.project_id else "", "ai_status": rec.ai_status, "ai_status_label": rec.get_ai_status_display(),
            "ai": rec.ai, "ai_consistency": consistency.check_stored(rec.ai.get("response") or {}, statuses),
            "created_at": rec.created_at, "created_by_name": display_name(rec.created_by),
            "created_by_id": str(rec.created_by_id) if rec.created_by_id else None,
            "reviews": [serialise_review(r) for r in reviews], "review_state": review_state(reviews), "stale": stale,
            "requires_reassessment": bool(stale),
            "engineering_approved": False, "authorisation": R.APPROVAL_NOTE}


def part_view(request, part) -> dict:
    fa = cost_service.latest_feasibility(part)
    cc = CostComparison.objects.filter(tenant=request.tenant, part=part).order_by("-version")
    latest = {"feasibility": str(fa.pk) if fa else None, "cost": str(cc[0].pk) if cc else None,
              "snapshot": FS._hash(FS._evaluate(part)[4])}
    status = service.ai_status(request.tenant)
    if status["enabled"] and not part.import_record:
        status = {**status, "enabled": False, "reason": "External AI is used only for imported synthetic inventory records; the rules-based assessment is available for every part."}
    items = list(Recommendation.objects.filter(tenant=request.tenant, part=part).select_related("created_by", "project", "feasibility",
                                                                                                    "cost_comparison")
                 .prefetch_related("reviews").order_by("-version")[:20])
    return {"ai": status, "feasibility": {"id": str(fa.pk), "version": fa.version} if fa else None,
            "cost_comparisons": [{"id": str(c.pk), "version": c.version, "name": c.name, "quantity": c.quantity,
                                  "currency": c.reporting_currency, "synthetic": c.synthetic} for c in cc[:20]],
            "default_weights": {k: str(v) for k, v in R.DEFAULT_WEIGHTS.items()},
            "recommendations": [serialise(r, latest) for r in items], "decisions": dict(D.choices), "outcomes": R.OUTCOMES,
            "approval_blockers": approval_blockers(part, items[0]) if items else [],
            "statement": "Preliminary until reviewed. Not an engineering approval, manufacturing authorisation, passport "
                         "publication or production release (OQ-35, OQ-36)."}


def queue(request, parts, state: str | None = None) -> dict:
    latest = {}
    for rec in (Recommendation.objects.filter(tenant=request.tenant, part__in=parts).prefetch_related("reviews")
                .order_by("part_id", "-version")):
        latest.setdefault(rec.part_id, rec)
    rows, counts = [], {}
    for p in parts:
        rec = latest.get(p.pk)
        rs = review_state(list(rec.reviews.all().order_by("created_at"))) if rec else {"code": "not_generated", "label": "Not generated", "reviewed": False}
        counts[rs["code"]] = counts.get(rs["code"], 0) + 1
        if state and rs["code"] != state:
            continue
        rows.append({"id": str(p.pk), "part_number": p.part_number, "name": p.name, "review_state": rs,
                     "recommendation": ({"id": str(rec.pk), "version": rec.version, "outcome": rec.outcome,
                                         "outcome_label": rec.results["outcome"]["label"], "option": rec.recommended_option,
                                         "cheapest": rec.results["statuses"]["commercially_cheapest"]["text"],
                                         "fastest": rec.results["statuses"]["fastest"]["text"],
                                         "potentially_suitable": rec.results["statuses"]["potentially_suitable"]["text"],
                                         "created_at": rec.created_at, "created_by_name": display_name(rec.created_by),
                                         "ai_status": rec.ai_status} if rec else None)})
    return {"parts": rows, "counts": counts}
