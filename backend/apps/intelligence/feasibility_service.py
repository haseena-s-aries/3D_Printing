"""Manufacturing feasibility assessments and engineering review (CN-007 Phase 3).

run():    deterministic screening (apps.intelligence.feasibility) of OEM procurement, additive and conventional
          manufacturing, optionally with a Gemini explanation. Stored as a new immutable version; unchanged inputs reuse
          the stored version (no new AI call). AI goes through the Phase 2 gate, limits, budget and usage log.
review(): an assigned Aries Engineer's technical review entry on one alternative (append-only). Technical review is not
          formal engineering approval: nothing here changes a passport, evidence level, manufacturing eligibility or
          release state (OQ-35, OQ-36), and there is no approval decision.

Sent to the AI (whitelist, `ai_payload`): the material description, the cleaned manufacturer name, the rule findings and
statuses, and for each evidence item only its state (verified, recorded, mentioned, missing) plus the value for material,
dimensions, wear/corrosion, criticality and the configured build envelope. Never file titles or contents, drawings, CAD,
passport text, manufacturing specifications, OEM part numbers, manufacturer references, locations, equipment tags or
the customer ABC indicator.
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
from apps.files.models import EngineeringFile
from apps.parts.models import SparePart
from apps.parts.submissions import display_name

from . import feasibility as F
from . import gemini, rules, service
from .models import AIUsageLog, FeasibilityAssessment, FeasibilityReview

PROMPT_VERSION = "mf-prompt-2026-10-27.1"
U = AIUsageLog.Outcome
A = FeasibilityAssessment.AIStatus
D = FeasibilityReview.Decision
VALUE_KEYS = {"material", "dimensions", "wear_corrosion", "criticality", "build_envelope", "function", "category"}
# Sentences claiming approval, certification or suitability are removed from AI text (AI never certifies a method).
CLAIM_RE = re.compile(
    r"[^.;\n]*(?:\b(?:is|are|has been|have been|was|were)\s+(?:approved|certified|qualified|released|authori[sz]ed)\b|"
    r"\b(?:approved|certified|released|authori[sz]ed)\s+for\s+(?:manufactur\w*|production|use|service|printing)\b|"
    r"\b(?:is|are)\s+(?:printable|manufacturable|suitable for (?:printing|manufactur\w*|production))\b|"
    r"\bguarantee[sd]?\b)[^.;\n]*[.;]?", re.I)
APPROVAL_WORDS = {"approve", "approved", "approval", "release", "released", "authorise", "authorised", "authorize",
                  "authorized", "eligible", "publish", "published"}


# ------------------------------------------------------------------ inputs

def snapshot(part, analysis: dict, docs: list[dict], pp: dict | None) -> dict:
    """Evidence / input snapshot stored with each version; a change gives a new version."""
    prov = part.field_provenance or {}
    pick = lambda lvl, keys: {k: (pp["content"].get(lvl) or {}).get(k) for k in keys if (pp["content"].get(lvl) or {}).get(k) not in (None, "", [], {})}  # noqa: E731
    return {
        "part": {k: getattr(part, k) for k in ("part_number", "name", "category", "criticality", "manufacturer", "manufacturer_reference",
                                              "oem_part_number", "original_material", "proposed_material", "material_change_reason",
                                              "dimensions", "status")},
        "verified_fields": sorted(k for k, v in prov.items() if isinstance(v, dict) and v.get("verified_by")),
        "imported": bool(part.import_record),
        "documents": docs,
        "passport": ({"passport_number": pp["passport_number"], "revision_number": pp["revision_number"],
                      "revision_status": pp["revision_status"],
                      "rl1": pick("rl1", ["original_material_grade", "proposed_material", "part_size", "application", "atmosphere", "motion", "rpm",
                                          "operating_environment", "ip_status", "cad_3d_available", "drawings_2d_available"]),
                      "rl2": pick("rl2", ["dimensional_tolerances", "applicable_standards", "mechanical_acceptance",
                                          "inspection_test_plan"])} if pp else None),
        "analysis": {"family": analysis["classification"]["family"], "category": analysis["classification"]["category"],
                     "assembly": analysis["classification"].get("assembly"), "mentions": analysis["mentions"],
                     "manufacturer": {k: analysis["manufacturer"][k] for k in ("cleaned", "placeholder", "possibly_truncated", "alias_candidates")},
                     "duplicates": analysis["duplicates"]},
        "configuration": {"am_build_envelope_mm": settings.AM_BUILD_ENVELOPE_MM},
    }


def ai_payload(part, analysis: dict, result: dict) -> dict:
    """The complete payload sent to the provider (whitelist; see the module docstring)."""
    ev = result["evidence"]
    return {
        "material_description": part.name,
        "manufacturer_name": analysis["manufacturer"]["cleaned"] or "not stated",
        "rule_findings": {
            "expanded_description": ", ".join(analysis["description"]["expanded"]),
            "part_family": analysis["classification"]["family"] or "not recognised",
            "assembly_by_description": bool(analysis["classification"].get("assembly")),
            "material_classes_mentioned": result["material_classes"],
        },
        "evidence": {k: {"state": e["state"], **({"value": e["value"]} if k in VALUE_KEYS and e["value"] else {})}
                     for k, e in ev.items()},
        "rule_screening": {"oem": result["oem"]["status"], "additive": result["additive"]["status"],
                           "conventional": result["conventional"]["status"]},
        "rule_constraints": [c["text"] for c in result["constraints"]],
    }


def _hash(blob) -> str:
    return hashlib.sha256(json.dumps(blob, sort_keys=True, default=str).encode()).hexdigest()


def _evaluate(part):
    analysis = service.analyse(part)
    docs, pp = F.documents(part), F.passport_info(part)
    return analysis, docs, pp, F.assess(part, analysis, docs, pp), snapshot(part, analysis, docs, pp)


def _own_inputs(snap: dict) -> dict:
    """The snapshot without company-wide context: a similar part appearing elsewhere in the company (for example a clone, listed
    under analysis.duplicates) is not a change of this part's own data and must not make its assessment outdated."""
    out = dict(snap or {})
    if isinstance(out.get("analysis"), dict):
        out["analysis"] = {k: v for k, v in out["analysis"].items() if k != "duplicates"}
    return out


def inputs_current(part, fa: FeasibilityAssessment) -> bool:
    """True when the part's own data, passport and documents still give the inputs this assessment was made from."""
    return _hash(_own_inputs(fa.inputs)) == _hash(_own_inputs(_evaluate(part)[4]))


def input_hash(snap: dict, model: str) -> str:
    return _hash({"methodology": F.METHODOLOGY_VERSION, "rules": rules.RULES_VERSION,
                  "prompt": PROMPT_VERSION if model else "", "model": model, "snapshot": snap})


# ------------------------------------------------------------------ AI view: cleaning and combination with the rules

def _clean(obj, removed: list):
    if isinstance(obj, str):
        for pattern, marker in ((service.PRICE_RE, "[price or cost statement removed]"),
                                (CLAIM_RE, "[unsupported approval or suitability claim removed]")):
            for m in pattern.findall(obj):
                if m.strip():
                    removed.append(m.strip())
            obj = pattern.sub(f" {marker} ", obj).strip()
        return obj
    if isinstance(obj, list):
        return [_clean(x, removed) for x in obj]
    if isinstance(obj, dict):
        return {k: _clean(v, removed) for k, v in obj.items()}
    return obj


def combine(result: dict, view: dict) -> list[dict]:
    """Apply the AI view to the rule statuses. The AI may make a favourable rule status more cautious; it never makes a
    status more favourable, and it cannot declare 'not suitable based on verified constraints' without a verified
    constraint. Returns the adjustments made (also when the rule status was kept)."""
    out = []
    for alt in ("additive", "conventional"):
        rs, ai_s = result[alt]["status"], view[alt]["suggested_status"]
        result[alt]["rule_status"] = rs
        if ai_s == rs:
            continue
        if F.FAVOURABILITY[rs] >= 3 and F.FAVOURABILITY[ai_s] < F.FAVOURABILITY[rs]:
            final = "specialist_assessment" if ai_s == "not_suitable_verified" else ai_s
            result[alt].update(status=final, status_label=F.MF_STATUS[final])
            out.append({"alternative": alt, "kind": "ai_more_cautious", "rule_status": rs, "ai_status": ai_s, "final_status": final,
                        "text": f"AI view is more cautious ({F.MF_STATUS[ai_s]}); the preliminary status was lowered to "
                                f"'{F.MF_STATUS[final]}'."})
        else:
            out.append({"alternative": alt, "kind": "rule_status_kept", "rule_status": rs, "ai_status": ai_s, "final_status": rs,
                        "text": f"AI suggested '{F.MF_STATUS[ai_s]}'. The rule-based status '{F.MF_STATUS[rs]}' stands: known "
                                "constraints and evidence gaps take precedence, and AI never makes a status more favourable."})
    return out


# ------------------------------------------------------------------ run an assessment

def run(request, part, tier: str | None = None) -> tuple[FeasibilityAssessment, bool]:
    """Return (assessment, reused). tier None = rules only; lite/flash/pro adds a Gemini explanation."""
    if tier and tier not in service.TIERS:
        raise DomainError("invalid_tier", "Choose lite, flash or pro.", http_status=400)
    if tier:
        st = service.ai_status(request.tenant)
        if not st["enabled"]:
            raise DomainError("ai_not_permitted", st["reason"], http_status=403)
        if not part.import_record:
            raise DomainError("ai_not_permitted_for_part", "External AI is used only for imported synthetic inventory records; the rules-based assessment is available for every part.", http_status=403)
    analysis, docs, pp, result, snap = _evaluate(part)
    model = settings.GEMINI_MODELS[tier] if tier else ""
    h = input_hash(snap, model)
    existing = (FeasibilityAssessment.objects.filter(tenant=request.tenant, part=part, input_hash=h, ai_status__in=[A.NONE, A.OK])
                .order_by("-version").first())
    if existing:
        if tier:
            AIUsageLog.objects.create(tenant=request.tenant, created_by=request.user, user=request.user, part_id=part.pk,
                                      assessment_id=existing.pk, provider="gemini", model=model,
                                      model_version=existing.ai.get("model_version", ""), outcome=U.CACHE_HIT)
        record(request, "feasibility.reused", obj=part, data={"assessment": str(existing.pk), "version": existing.version, "model": model})
        return existing, True

    ai, ai_status = {}, A.NONE
    if tier:
        log = service._reserve(request, model, part)  # raises service.Refused at a limit (nothing else is stored)
        sent = ai_payload(part, analysis, result)
        prompt = "Screen this spare part for the three alternatives. Data (JSON):\n" + json.dumps(sent, ensure_ascii=False, indent=1)
        view, call, totals, attempts, err = service.call_ai(model, tier, prompt, gemini.FEASIBILITY_SCHEMA,
                                                            gemini.SYSTEM_FEASIBILITY, gemini.FeasibilityView)
        cost = gemini.cost_usd(model, call.model_version if call else "", totals["prompt"], totals["output"], totals["thinking"])
        removed, adjustments = [], []
        if view:
            view = _clean(view, removed)
            adjustments = combine(result, view)
            for alt in ("oem", "additive", "conventional"):
                result[alt]["ai"] = view[alt]
        ai_status = A.OK if view else (A.INVALID if err and err.code in ("invalid_json", "schema_mismatch") else A.FAILED)
        ai = {"provider": "gemini", "tier": tier, "model": model, "model_version": call.model_version if call else "",
              "prompt_version": PROMPT_VERSION, "sent": sent, "response": view or {}, "removed": removed,
              "adjustments": adjustments, "confidence": (view or {}).get("confidence"),
              "qualification_requirements": (view or {}).get("qualification_requirements", []),
              "uncertainty": (view or {}).get("uncertainty", ""),
              "usage": {"prompt_tokens": totals["prompt"], "output_tokens": totals["output"], "thinking_tokens": totals["thinking"],
                        "cost_usd": cost, "latency_ms": totals["latency"], "attempts": attempts,
                        "finish_reason": call.extra.get("finish_reason", "") if call else ""},
              "error_code": err.code if err else "", "error_message": gemini.scrub(err.message) if err else ""}

    with transaction.atomic():
        SparePart.objects.select_for_update().filter(pk=part.pk).first()  # one version number at a time per part
        version = (FeasibilityAssessment.objects.filter(tenant=request.tenant, part=part).aggregate(m=Max("version"))["m"] or 0) + 1
        a = FeasibilityAssessment.objects.create(
            tenant=request.tenant, created_by=request.user, part=part, project_id=part.project_id, version=version,
            methodology_version=F.METHODOLOGY_VERSION, rules_version=rules.RULES_VERSION,
            passport_number=pp["passport_number"] if pp else "",
            passport_revision_id=pp["revision_id"] if pp else None,
            passport_revision_number=pp["revision_number"] if pp else None,
            input_hash=h, inputs=snap, oem=result["oem"], additive=result["additive"], conventional=result["conventional"],
            oem_status=result["oem"]["status"], additive_status=result["additive"]["status"],
            conventional_status=result["conventional"]["status"], constraints=result["constraints"],
            missing_information=result["missing_information"], next_actions=result["next_actions"], ai_status=ai_status, ai=ai)
    if tier:
        AIUsageLog.objects.filter(pk=log.pk).update(
            assessment_id=a.pk, model_version=ai["model_version"],
            outcome={A.OK: U.OK, A.INVALID: U.INVALID}.get(ai_status, U.FAILED),
            prompt_tokens=totals["prompt"], output_tokens=totals["output"], thinking_tokens=totals["thinking"],
            cost_usd=Decimal(str(cost or 0)), latency_ms=totals["latency"], attempts=attempts, error_code=ai["error_code"],
            updated_at=timezone.now())
    record(request, "feasibility.assessed", obj=part, data={
        "assessment": str(a.pk), "version": version, "methodology": F.METHODOLOGY_VERSION, "input_hash": h,
        "oem": a.oem_status, "additive": a.additive_status, "conventional": a.conventional_status, "ai_status": ai_status,
        "model": model, "model_version": ai.get("model_version", ""),
        **({k: ai["usage"][k] for k in ("prompt_tokens", "output_tokens", "thinking_tokens", "cost_usd")} if tier else {}),
        "error": ai.get("error_code", "")})
    return a, False


# ------------------------------------------------------------------ engineering review (technical, not approval)

FAVOURABLE = {"potentially_suitable", "potentially_suitable_redesign", "identified_confirmation_required"}


def _allowed_statuses(alternative):
    return {"oem": F.OEM_STATUS, "additive": F.MF_STATUS, "conventional": F.MF_STATUS}.get(alternative, {})


def _favourability(alternative, status):
    if alternative == "oem":
        return {"not_verified": 0, "identified_confirmation_required": 1}[status]
    return F.FAVOURABILITY[status]


def review(request, part, assessment_id, data: dict) -> FeasibilityReview:
    a = FeasibilityAssessment.objects.filter(tenant=request.tenant, part=part, pk=assessment_id).first()
    if a is None:
        raise DomainError("not_found", "Assessment not found for this part.", http_status=404)
    decision = str(data.get("decision") or "").strip().lower()
    if decision in APPROVAL_WORDS:
        raise DomainError("formal_approval_not_available",
                          "Formal engineering approval, manufacturing authorisation and release are not available here "
                          "(OQ-35, OQ-36). Record a technical review decision instead.", http_status=403)
    if decision not in D.values:
        raise DomainError("invalid_decision", "Choose confirmed, corrected, rejected, more_information_required or finding.", http_status=400)
    alternative = str(data.get("alternative") or "")
    if alternative not in FeasibilityReview.Alternative.values:
        raise DomainError("invalid_alternative", "Choose oem, additive, conventional or overall.", http_status=400)
    latest = FeasibilityAssessment.objects.filter(tenant=request.tenant, part=part).aggregate(m=Max("version"))["m"]
    if a.version != latest:
        raise DomainError("assessment_superseded", f"Version {a.version} has been superseded by version {latest}; review the latest version.", http_status=409)
    findings, note = str(data.get("findings") or "").strip(), str(data.get("note") or "").strip()
    if len(findings) > 2000 or len(note) > 1000:
        raise DomainError("too_long", "Findings are limited to 2000 characters and notes to 1000.", http_status=400)
    corrected = str(data.get("corrected_status") or "")
    refs = _references(part, data.get("evidence_references") or [])
    independent = a.created_by_id != request.user.id
    current = getattr(a, alternative, {}).get("status") if alternative != "overall" else None
    if decision == D.CORRECTED:
        if alternative == "overall" or corrected not in _allowed_statuses(alternative):
            raise DomainError("invalid_corrected_status", "Choose the corrected status for this alternative.", http_status=400)
        if corrected == current:
            raise DomainError("invalid_corrected_status", "The corrected status is the same as the preliminary status.", http_status=400)
    elif corrected:
        raise DomainError("invalid_corrected_status", "A corrected status is given only with the decision 'corrected'.", http_status=400)
    if decision in (D.CORRECTED, D.REJECTED, D.MORE_INFO, D.FINDING) and not (findings or note):
        raise DomainError("findings_required", "Record the technical findings or a note for this decision.", http_status=400)
    # a correction towards suitability (or OEM identification) needs evidence and an independent reviewer; moving between
    # non-favourable outcomes (e.g. insufficient information -> specialist assessment) does not
    more_favourable = (decision == D.CORRECTED and corrected in FAVOURABLE
                       and _favourability(alternative, corrected) > _favourability(alternative, current))
    if more_favourable and not refs:
        raise DomainError("evidence_required", "A correction to a more favourable status needs at least one evidence reference.", http_status=400)
    # Separation of duties: the engineer who ran the assessment cannot confirm it or correct it to a more favourable status.
    if not independent and (decision == D.CONFIRMED or more_favourable):
        raise DomainError("self_confirmation", "You ran this assessment. Another assigned Aries Engineer must confirm it or "
                          "correct it to a more favourable status. You can record findings, a more cautious correction, a "
                          "rejection or a request for information.", http_status=403)
    r = FeasibilityReview.objects.create(
        tenant=request.tenant, created_by=request.user, assessment=a, part=part, alternative=alternative, decision=decision,
        corrected_status=corrected, findings=findings, note=note, evidence_references=refs, independent=independent,
        reviewer_name=display_name(request.user))
    record(request, "feasibility.reviewed", obj=part, data={
        "assessment": str(a.pk), "version": a.version, "alternative": alternative, "decision": decision,
        "corrected_status": corrected, "independent": independent, "evidence_references": len(refs)})
    return r


def _references(part, raw) -> list[dict]:
    if not isinstance(raw, list) or len(raw) > 10:
        raise DomainError("invalid_references", "Give up to 10 evidence references.", http_status=400)
    out = []
    for item in raw:
        item = item if isinstance(item, dict) else {"reference": str(item)}
        ref = str(item.get("reference") or "").strip()[:300]
        fid = item.get("file")
        entry = {"reference": ref}
        if fid:
            f = EngineeringFile.objects.filter(tenant=part.tenant_id, part=part, pk=fid).first()
            if f is None:
                raise DomainError("invalid_references", "An evidence file does not belong to this part.", http_status=400)
            entry.update(file=str(f.pk), title=f.title, category=f.category)
        if not (ref or fid):
            continue
        out.append(entry)
    return out


# ------------------------------------------------------------------ views

def serialise_review(r: FeasibilityReview) -> dict:
    return {"id": str(r.pk), "assessment": str(r.assessment_id), "alternative": r.alternative,
            "alternative_label": r.get_alternative_display(), "decision": r.decision, "decision_label": r.get_decision_display(),
            "corrected_status": r.corrected_status,
            "corrected_status_label": _allowed_statuses(r.alternative).get(r.corrected_status, ""),
            "findings": r.findings, "note": r.note, "evidence_references": r.evidence_references, "independent": r.independent,
            "reviewer": r.reviewer_name, "reviewer_id": str(r.created_by_id) if r.created_by_id else None, "created_at": r.created_at}


REVIEW_NOTE = ("Technical review only: not a formal engineering approval. Passport approval, publication, manufacturing "
               "eligibility and production release are unchanged (OQ-35, OQ-36).")


def serialise(a: FeasibilityAssessment, current_snapshot_hash: str | None = None) -> dict:
    reviews = [serialise_review(r) for r in a.reviews.all().order_by("created_at")]
    status = {}
    for alt in ("oem", "additive", "conventional", "overall"):
        mine = [r for r in reviews if r["alternative"] == alt]
        status[alt] = mine[-1] if mine else None
    panels = {}
    for alt in ("oem", "additive", "conventional"):
        panels[alt] = {**getattr(a, alt), "review": status[alt]}
    return {"id": str(a.pk), "version": a.version, "methodology_version": a.methodology_version, "rules_version": a.rules_version,
            "project": a.project.code if a.project_id else "", "passport_number": a.passport_number,
            "passport_revision_number": a.passport_revision_number, "input_hash": a.input_hash, "inputs": a.inputs,
            "created_at": a.created_at, "created_by_name": display_name(a.created_by),
            "created_by_id": str(a.created_by_id) if a.created_by_id else None,
            **panels, "constraints": a.constraints, "missing_information": a.missing_information, "next_actions": a.next_actions,
            "ai_status": a.ai_status, "ai_status_label": a.get_ai_status_display(), "ai": a.ai,
            "reviews": reviews, "overall_review": status["overall"], "review_note": REVIEW_NOTE,
            "inputs_current": (_hash(a.inputs) == current_snapshot_hash) if current_snapshot_hash else None,
            "authorisation": {"manufacturing_authorised": False,
                              "text": "Screening only. No manufacturing authorisation, passport approval, publication or "
                                      "manufacturing eligibility is given or changed (OQ-35, OQ-36)."}}


def part_view(request, part) -> dict:
    _a, _d, _p, preview, snap = _evaluate(part)
    snap_hash = _hash(snap)
    status = service.ai_status(request.tenant)
    if status["enabled"] and not part.import_record:
        status = {**status, "enabled": False, "reason": "External AI is used only for imported synthetic inventory records; the rules-based assessment is available for every part."}
    items = list(FeasibilityAssessment.objects.filter(tenant=request.tenant, part=part)
                 .select_related("created_by", "project").prefetch_related("reviews").order_by("-version")[:20])
    return {"ai": status, "statuses": {"oem": F.OEM_STATUS, "manufacturing": F.MF_STATUS},
            "assessments": [serialise(a, snap_hash) for a in items], "inputs_changed": bool(items) and _hash(items[0].inputs) != snap_hash,
            "review_note": REVIEW_NOTE}


def overview(request, parts) -> dict:
    latest = {}
    for a in (FeasibilityAssessment.objects.filter(tenant=request.tenant, part__in=parts)
              .prefetch_related("reviews").order_by("part_id", "-version")):
        latest.setdefault(a.part_id, a)
    rows = []
    for p in parts:
        a = latest.get(p.pk)
        if a is None:
            rows.append({"id": str(p.pk), "part_number": p.part_number, "name": p.name, "assessment": None})
            continue
        reviews = list(a.reviews.all())
        last = {}
        for r in sorted(reviews, key=lambda r: r.created_at):
            last[r.alternative] = r.get_decision_display()
        rows.append({"id": str(p.pk), "part_number": p.part_number, "name": p.name, "assessment": {
            "id": str(a.pk), "version": a.version, "created_at": a.created_at, "ai_status": a.ai_status,
            "model": a.ai.get("model", ""), "oem": {"status": a.oem_status, "label": F.OEM_STATUS.get(a.oem_status, "")},
            "additive": {"status": a.additive_status, "label": F.MF_STATUS.get(a.additive_status, "")},
            "conventional": {"status": a.conventional_status, "label": F.MF_STATUS.get(a.conventional_status, "")},
            "missing_count": len(a.missing_information), "reviews": last}})
    return {"parts": rows}
