"""Quarterly inventory assessment runs and analytics (CN-007 Phase 6).

start():   create a run for the requester's scope (imported inventory parts they may access) with one item per part and
           enqueue it on the existing PostgreSQL job queue. Duplicate prevention: one active run per company and scope
           (database constraint), one scheduled run per company, quarter and scope, and an optional idempotency key.
process(): job handler. One part per job execution, so each part commits on its own and a crash resumes at the next
           pending part; the next job is enqueued in the same transaction. A failing part is retried within the run up
           to ASSESSMENT_ITEM_MAX_ATTEMPTS, then marked failed (the run completes "with errors"; retry() resumes it).
           Each part reuses the previous run's result when its inputs and the methodology are unchanged; otherwise it
           goes through Phase 3 feasibility and the Phase 5 recommendation (which reuse their own cached versions), with
           Gemini only within the existing gate, limits, budget, cache and total deadline.
dashboard()/compare(): aggregates and run-to-run changes, computed from the item results the viewer may see.

Savings: "estimated" = best positive difference to the OEM baseline among options with complete totals that are not
excluded by a verified constraint; "verified" only where the option meets every mandatory requirement and both its and
the baseline's cost evidence are verified-current quotations. A cheap but technically unqualified option is never a
verified saving. Nothing here approves, publishes or releases a passport or manufacturing job.
"""
import hashlib
import json
from datetime import date
from decimal import Decimal

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Max
from django.utils import timezone

from apps.audit.service import record
from apps.core.exceptions import DomainError
from apps.jobs.queue import JobFailure, enqueue, handler
from apps.parts.models import SparePart, lifecycle_parts
from apps.parts.submissions import display_name
from apps.projects.scoping import allowed_project_ids
from apps.tenancy.models import Membership

from . import costing as C
from . import cost_service as CS
from . import feasibility as F
from . import feasibility_service as FS
from . import recommendation as R
from . import recommendation_service as RS
from . import rules, service
from .models import AssessmentRun, AssessmentRunItem, CostComparison, PartAssessment, Recommendation

JOB_KIND = "intelligence.assessment_run"
RS_ = AssessmentRun.Status
IS = AssessmentRunItem.Status
SUITABLE = {"potentially_suitable", "potentially_suitable_redesign"}
OBSOLETE_WORDS = ("OBSOLETE", "DISCONTINUED", " OBS ", "SUPERSEDED")


def methodology() -> dict:
    return {"rules": rules.RULES_VERSION, "feasibility": F.METHODOLOGY_VERSION, "feasibility_prompt": FS.PROMPT_VERSION,
            "cost": C.METHOD_VERSION, "cost_prompt": CS.PROMPT_VERSION, "recommendation": R.METHOD_VERSION,
            "recommendation_prompt": RS.PROMPT_VERSION, "run": "run-method-2026-10-28.1"}


def quarter_of(d: date) -> str:
    return f"{d.year}-Q{(d.month - 1) // 3 + 1}"


class RunContext:
    """Request-like context for background processing: the run's company and the engineer who started it (audit actor)."""

    def __init__(self, tenant, user):
        self.tenant, self.user, self.META = tenant, user, {}
        self.membership = Membership.objects.filter(tenant=tenant, user=user).first() if user else None


# ------------------------------------------------------------------ start

def _scope(request) -> tuple[dict, str, list]:
    ids = allowed_project_ids(request)
    qs = lifecycle_parts(SparePart.objects.filter(tenant=request.tenant))
    if ids is not None:
        qs = qs.filter(project_id__in=ids)
    parts = list(qs.order_by("part_number"))
    scope = {"parts": "all parts in the engineering lifecycle", "projects": sorted(str(i) for i in ids) if ids is not None else None}
    key = hashlib.sha256(json.dumps(scope, sort_keys=True).encode()).hexdigest()
    return scope, key, parts


def start(request, kind: str = "manual", ai_tier: str = "", idempotency_key: str = "", fault_injection=None) -> tuple[AssessmentRun, bool]:
    if ai_tier and ai_tier not in service.TIERS:
        raise DomainError("invalid_tier", "Choose no AI, lite, flash or pro.", http_status=400)
    if fault_injection and not getattr(settings, "ASSESSMENT_FAULT_INJECTION", False):
        raise DomainError("fault_injection_disabled", "Fault injection is available only in test environments.", http_status=400)
    idempotency_key = str(idempotency_key or "")[:80]
    if idempotency_key:
        existing = AssessmentRun.objects.filter(tenant=request.tenant, idempotency_key=idempotency_key).first()
        if existing:
            return existing, True
    scope, key, parts = _scope(request)
    if not parts:
        raise DomainError("nothing_to_assess", "No imported inventory parts in your scope.", http_status=400)
    today = timezone.localdate()
    previous = (AssessmentRun.objects.filter(tenant=request.tenant, scope_key=key,
                                             status__in=[RS_.COMPLETED, RS_.COMPLETED_WITH_ERRORS]).order_by("-number").first())
    try:
        with transaction.atomic():
            number = (AssessmentRun.objects.filter(tenant=request.tenant).aggregate(m=Max("number"))["m"] or 0) + 1
            run = AssessmentRun.objects.create(
                tenant=request.tenant, created_by=request.user, number=number, kind=kind, quarter=quarter_of(today),
                scope=scope, scope_key=key, ai_tier=ai_tier, methodology=methodology(), idempotency_key=idempotency_key,
                previous_run=previous, part_count=len(parts), fault_injection=fault_injection or {})
            AssessmentRunItem.objects.bulk_create([AssessmentRunItem(tenant=request.tenant, created_by=request.user, run=run, part=p,
                                                                     project_id=p.project_id) for p in parts])
            enqueue(request.tenant, JOB_KIND, {"run": str(run.pk)}, created_by=request.user)
    except IntegrityError:
        active = AssessmentRun.objects.filter(tenant=request.tenant, scope_key=key, status__in=AssessmentRun.ACTIVE).first()
        if active:
            raise DomainError("assessment_run_in_progress", f"Run {active.number} for this scope is still {active.get_status_display().lower()}.",
                              details={"run": str(active.pk), "number": active.number}, http_status=409)
        raise DomainError("assessment_run_exists", f"A scheduled run for {quarter_of(today)} already exists for this scope.", http_status=409)
    record(request, "assessment_run.started", obj=run, data={"number": run.number, "kind": kind, "quarter": run.quarter,
                                                              "parts": run.part_count, "ai_tier": ai_tier, "scope": scope,
                                                              "previous_run": previous.number if previous else None,
                                                              "fault_injection": bool(fault_injection)})
    return run, False


def retry(request, run: AssessmentRun) -> AssessmentRun:
    """Resume a run: failed parts are tried again; a stalled running run (worker stopped) is re-enqueued."""
    if run.status not in (RS_.COMPLETED_WITH_ERRORS, RS_.RUNNING, RS_.QUEUED):
        raise DomainError("not_retryable", f"Run {run.number} is {run.get_status_display().lower()}.", http_status=409)
    with transaction.atomic():
        failed = list(AssessmentRunItem.objects.filter(run=run, status=IS.FAILED))
        for it in failed:
            it.status, it.error_code, it.error_message = IS.PENDING, "", ""
            it.save(update_fields=["status", "error_code", "error_message", "updated_at"])
        try:
            run.status, run.finished_at, run.failed_count = RS_.RUNNING, None, 0
            run.save(update_fields=["status", "finished_at", "failed_count", "updated_at"])
        except IntegrityError:
            raise DomainError("assessment_run_in_progress", "Another run for this scope is active.", http_status=409)
        enqueue(request.tenant, JOB_KIND, {"run": str(run.pk), "resume": True}, created_by=request.user)
    record(request, "assessment_run.retried", obj=run, data={"number": run.number, "parts": len(failed)})
    return run


def cancel(request, run: AssessmentRun) -> AssessmentRun:
    if run.status not in AssessmentRun.ACTIVE + (RS_.COMPLETED_WITH_ERRORS,):
        raise DomainError("not_cancellable", f"Run {run.number} is {run.get_status_display().lower()}.", http_status=409)
    run.status, run.finished_at = RS_.CANCELLED, timezone.now()
    run.save(update_fields=["status", "finished_at", "updated_at"])
    record(request, "assessment_run.cancelled", obj=run, data={"number": run.number})
    return run


# ------------------------------------------------------------------ processing (job handler)

@handler(JOB_KIND)
def process(job):
    run = AssessmentRun.objects.select_for_update().filter(pk=job.payload.get("run")).first()
    if run is None or run.status not in AssessmentRun.ACTIVE:
        return  # finished or cancelled: nothing to do (idempotent)
    if run.status == RS_.QUEUED:
        run.status, run.started_at = RS_.RUNNING, timezone.now()
        run.save(update_fields=["status", "started_at", "updated_at"])
    ctx = RunContext(run.tenant, run.created_by)
    item = AssessmentRunItem.objects.filter(run=run, status=IS.PENDING).select_related("part").order_by("part__part_number").first()
    if item is not None:
        _process_item(ctx, run, item)
    if AssessmentRunItem.objects.filter(run=run, status=IS.PENDING).exists():
        enqueue(run.tenant, JOB_KIND, {"run": str(run.pk)}, created_by=run.created_by)  # one part per job
    else:
        finalise(ctx, run)


def _process_item(ctx, run, item):
    item.attempts += 1
    try:
        with transaction.atomic():  # a failing part rolls back only its own work
            fails = int((run.fault_injection.get("fail_attempts") or {}).get(item.part.part_number, 0))
            if fails >= item.attempts:
                raise RuntimeError(f"Injected test failure (attempt {item.attempts} of {fails} configured to fail)")
            status, h, sources, result = assess_part(ctx, run, item.part)
            item.status, item.input_hash, item.sources, item.result = status, h, sources, result
            item.error_code, item.error_message, item.processed_at = "", "", timezone.now()
            item.save()
    except Exception as e:  # noqa: BLE001 - one part's failure must not stop the run
        item.error_code = getattr(e, "error_code", type(e).__name__)[:60]
        item.error_message = str(getattr(e, "detail", e))[:500]
        item.status = IS.FAILED if item.attempts >= settings.ASSESSMENT_ITEM_MAX_ATTEMPTS else IS.PENDING
        item.save(update_fields=["attempts", "status", "error_code", "error_message", "updated_at"])
        record(ctx, "assessment_run.part_failed", obj=run, tenant=run.tenant, data={"number": run.number, "part": item.part.part_number,
                                                                  "attempt": item.attempts, "error": item.error_code,
                                                                  "will_retry": item.status == IS.PENDING})


def latest_comparison(part):
    """The commercial source: the latest stored scenario that is not a saved what-if."""
    return (CostComparison.objects.filter(tenant=part.tenant_id, part=part, derived_from__isnull=True)
            .order_by("-version").first())


def _expired_refs(cc, today) -> list:
    if not cc:
        return []
    out = set()
    for a in cc.results.get("alternatives", {}).values():
        validity = C.quote_validity(a["lines"])
        out |= {ref for ref, d in validity.items() if d < today}
        for comp in a["lead_time"]["components"]:
            q = C.lead_quote_status(comp, validity, today)
            if q and (q["expired"] or q["unknown"]):
                out.add(f"lead:{comp.get('reference')}")
    return sorted(out)


def part_inputs(part, today) -> tuple[dict, CostComparison | None]:
    """Hash of everything a part's assessment depends on: the evidence snapshot, technical-review corrections, the
    commercial and Phase 2 sources, quotation validity on `today`, criticality and the methodology."""
    _a, _d, _p, _r, snap = FS._evaluate(part)
    fa = CS.latest_feasibility(part)
    # engineer corrections recorded in technical review of the current feasibility version (an input, unlike the
    # screening result itself, which the run produces)
    corrections = ({k: v["status"] for k, v in CS.technical(fa).items() if v["corrected_by_review"]}
                   if fa and FS._hash(fa.inputs) == FS._hash(snap) else {})
    cc = latest_comparison(part)
    pa = PartAssessment.objects.filter(tenant=part.tenant_id, part=part, status=PartAssessment.Status.OK).order_by("-created_at").first()
    deps = {"snapshot": FS._hash(snap), "corrections": corrections, "cost_comparison": str(cc.pk) if cc else None,
            "intelligence": str(pa.pk) if pa else None, "expired": _expired_refs(cc, today), "criticality": part.criticality}
    return deps, cc


def _misaligned(item) -> str | None:
    """D-23: why a previous run's result must not be reused: its recommendation combined a cost comparison with a different
    feasibility version (results produced before the alignment fix)."""
    rid = (item.sources.get("recommendation") or {}).get("id")
    rec = Recommendation.objects.filter(pk=rid).select_related("cost_comparison").first() if rid else None
    if rec is None:
        return "its recommendation is no longer available"
    if rec.cost_comparison_id and rec.cost_comparison.feasibility_id != rec.feasibility_id:
        return (f"its recommendation v{rec.version} used cost comparison v{rec.cost_comparison.version} (feasibility "
                f"v{rec.cost_comparison.feasibility_version}) with feasibility v{rec.feasibility_version}")
    return None


def assess_part(ctx, run, part):
    today = timezone.localdate()
    deps, cc = part_inputs(part, today)
    h = hashlib.sha256(json.dumps({"deps": deps, "methodology": run.methodology, "ai_tier": run.ai_tier}, sort_keys=True,
                                  default=str).encode()).hexdigest()
    notes = []
    if run.previous_run_id:
        prev = AssessmentRunItem.objects.filter(run_id=run.previous_run_id, part=part, input_hash=h,
                                                status__in=[IS.DONE, IS.REUSED]).first()
        mismatch = _misaligned(prev) if prev else None
        if prev and not mismatch:
            return IS.REUSED, h, {**prev.sources, "reused_from_run": run.previous_run.number}, prev.result
        if mismatch:
            notes.append(f"not reused from run #{run.previous_run.number}: {mismatch}")
    tier = run.ai_tier or None
    fa = _with_ai(lambda t: FS.run(ctx, part, t)[0], tier, notes, "feasibility")
    if cc is not None and cc.feasibility_id != fa.pk:
        # D-23: the stored scenario is recalculated on the feasibility this run produced (same inputs, deterministic, never AI),
        # so the recommendation never combines a cost comparison with a different feasibility version
        old = cc
        cc, reused = CS.create(ctx, part, dict(old.inputs))
        notes.append(f"cost: scenario of v{old.version} (feasibility v{old.feasibility_version}) recalculated on feasibility "
                     f"v{fa.version} as v{cc.version}" + (" (existing version reused)" if reused else ""))
    cc_id = str(cc.pk) if cc else None
    rec_tier = tier if (cc is None or cc.synthetic) else None
    if tier and not rec_tier:
        notes.append("recommendation: AI not used (cost scenario not marked synthetic)")
    rec = _with_ai(lambda t: RS.create(ctx, part, None, t, cc_id)[0], rec_tier, notes, "recommendation")
    sources = {"feasibility": {"id": str(fa.pk), "version": fa.version},
               "cost_comparison": {"id": cc_id, "version": cc.version, "name": cc.name, "synthetic": cc.synthetic,
                                   "feasibility_version": cc.feasibility_version} if cc else None,
               "recommendation": {"id": str(rec.pk), "version": rec.version},
               "intelligence": deps["intelligence"], "notes": notes}
    return IS.DONE, h, sources, summarise(part, fa, cc, rec)


def _with_ai(fn, tier, notes, what):
    """Run with the AI tier when permitted; otherwise (not permitted, limit or budget reached) the rules-only result."""
    if not tier:
        return fn(None)
    try:
        return fn(tier)
    except service.Refused as e:
        notes.append(f"{what}: AI refused ({e.error_code}); rules only")
    except DomainError as e:
        if not e.error_code.startswith("ai_not_permitted"):
            raise
        notes.append(f"{what}: AI not permitted ({e.error_code}); rules only")
    return fn(None)


def summarise(part, fa, cc, rec) -> dict:
    analysis = service.analyse(part)
    res = rec.results
    opts = res["options"]
    oem = opts["oem"]["commercial"]
    signals = []
    if part.status == SparePart.Status.OBSOLETE:
        signals.append("Part record status is obsolete")
    if any(w in f" {part.name.upper()} " for w in OBSOLETE_WORDS):
        signals.append("Description mentions obsolescence")
    pp = F.passport_info(part)
    if pp and str((pp["content"].get("rl1") or {}).get("ip_status", "")).lower() == "obsolete":
        signals.append("Passport records the IP status as obsolete")
    avail = next((e for e in fa.oem.get("evidence", []) if e["key"] == "availability"), {"state": "missing"})
    estimated = verified = None
    base = opts["oem"]
    for k in ("additive", "conventional"):
        o, c = opts[k], opts[k]["commercial"]
        s = c.get("savings_vs_baseline")
        if o["excluded"] or not c.get("complete") or s is None or Decimal(s) <= 0 or c.get("baseline") != "oem":
            continue
        cand = {"option": k, "amount": s, "percent": c.get("savings_percent"), "currency": cc.reporting_currency if cc else "",
                "qualified": o["eligible"], "evidence": c["evidence"]}
        if estimated is None or Decimal(s) > Decimal(estimated["amount"]):
            estimated = cand
        if o["eligible"] and c["evidence"] == "verified_current" and base["commercial"].get("evidence") == "verified_current":
            if verified is None or Decimal(s) > Decimal(verified["amount"]):
                verified = cand
    return {
        "part_number": part.part_number, "name": part.name,
        "feasibility": {"version": fa.version, **{k: {"status": getattr(fa, f"{k}_status"),
                                                       "label": (F.OEM_STATUS if k == "oem" else F.MF_STATUS).get(getattr(fa, f"{k}_status"), "")}
                                                   for k in ("oem", "additive", "conventional")}},
        "insufficient_technical_data": any(c["code"] == "insufficient_data" for c in analysis["constraints"]),
        "completeness": analysis["completeness"]["score"], "evidence_gaps": list(fa.missing_information),
        "am_candidate": opts["additive"]["technical"]["status"] in SUITABLE,
        "am_specialist": opts["additive"]["technical"]["status"] == "specialist_assessment",
        "conventional_candidate": opts["conventional"]["technical"]["status"] in SUITABLE,
        "conventional_specialist": opts["conventional"]["technical"]["status"] == "specialist_assessment",
        "oem": {"identity": opts["oem"]["technical"]["status"], "identity_verified": opts["oem"]["eligible"],
                "cost_evidence": oem["evidence"], "lead_evidence": oem.get("lead_evidence", ""),
                "expired": list(oem.get("expired_quotations", [])) + list(oem.get("expired_lead_times", [])),
                "availability_documented": avail["state"] != "missing"},
        "obsolescence_signals": signals,
        "commercial": ({"comparison_version": cc.version, "name": cc.name, "synthetic": cc.synthetic, "quantity": cc.quantity,
                        "currency": cc.reporting_currency,
                        "options": {k: {"total": o["commercial"].get("total"), "complete": o["commercial"].get("complete", False),
                                        "lead_days": o["commercial"].get("lead_days"), "evidence": o["commercial"]["evidence"],
                                        "eligible": o["eligible"], "excluded": o["excluded"]} for k, o in opts.items()}} if cc else None),
        "savings": {"estimated": estimated, "verified": verified},
        "recommendation": {"id": str(rec.pk), "version": rec.version, "outcome": rec.outcome, "label": res["outcome"]["label"],
                           "option": rec.recommended_option},
    }


def finalise(ctx, run):
    items = list(AssessmentRunItem.objects.filter(run=run).select_related("part"))
    run.done_count = sum(1 for i in items if i.status == IS.DONE)
    run.reused_count = sum(1 for i in items if i.status == IS.REUSED)
    run.failed_count = sum(1 for i in items if i.status == IS.FAILED)
    run.summary = aggregate(run.tenant, items)
    prev = list(AssessmentRunItem.objects.filter(run_id=run.previous_run_id).select_related("part")) if run.previous_run_id else []
    run.comparison = compare(prev, items, run.previous_run.number if run.previous_run_id else None)
    run.status = RS_.COMPLETED_WITH_ERRORS if run.failed_count else RS_.COMPLETED
    run.finished_at = timezone.now()
    run.save()
    record(ctx, "assessment_run.completed", obj=run, tenant=run.tenant, data={"number": run.number, "status": run.status, "assessed": run.done_count,
                                                            "reused": run.reused_count, "failed": run.failed_count})


# ------------------------------------------------------------------ analytics

def _review_states(items) -> dict:
    """Live review state of each item's recommendation (reviews happen after the run)."""
    ids = [i.result.get("recommendation", {}).get("id") for i in items if i.result]
    recs = {str(r.pk): r for r in Recommendation.objects.filter(pk__in=[x for x in ids if x]).prefetch_related("reviews")}
    out = {}
    for i in items:
        r = recs.get((i.result or {}).get("recommendation", {}).get("id"))
        out[i.part_id] = RS.review_state(list(r.reviews.all().order_by("created_at"))) if r else None
    return out


def aggregate(tenant, items, total_parts=None) -> dict:
    ok = [i for i in items if i.status in (IS.DONE, IS.REUSED)]
    res = [i.result for i in ok]
    states = _review_states(ok)
    backlog = {"preliminary": 0, "information_requested": 0}
    for st in states.values():
        if st and st["code"] in backlog:
            backlog[st["code"]] += 1
    est, ver = {}, {}
    for r in res:
        for kind, bucket in (("estimated", est), ("verified", ver)):
            s = r["savings"][kind]
            if s:
                bucket[s["currency"]] = str(Decimal(bucket.get(s["currency"], "0")) + Decimal(s["amount"]))
    ev = {}
    for r in res:
        ev[r["oem"]["cost_evidence"]] = ev.get(r["oem"]["cost_evidence"], 0) + 1
    total = total_parts if total_parts is not None else SparePart.objects.filter(tenant=tenant).count()
    outcomes = {}
    for r in res:
        outcomes[r["recommendation"]["outcome"]] = outcomes.get(r["recommendation"]["outcome"], 0) + 1
    return {
        "total_parts": total, "in_scope": len(items), "outside_scope": max(total - len(items), 0),
        "assessed": len(ok), "unassessed": len(items) - len(ok),
        "insufficient_technical_data": sum(1 for r in res if r["insufficient_technical_data"]),
        "am_candidates": sum(1 for r in res if r["am_candidate"]), "am_specialist": sum(1 for r in res if r["am_specialist"]),
        "conventional_candidates": sum(1 for r in res if r["conventional_candidate"]),
        "conventional_specialist": sum(1 for r in res if r["conventional_specialist"]),
        "oem": {"identity_verified": sum(1 for r in res if r["oem"]["identity_verified"]),
                "identity_not_verified": sum(1 for r in res if not r["oem"]["identity_verified"]),
                "cost_evidence": {k: {"count": v, "label": R.EVIDENCE[k][0]} for k, v in sorted(ev.items())},
                "with_expired_evidence": sum(1 for r in res if r["oem"]["expired"]),
                "availability_not_documented": sum(1 for r in res if not r["oem"]["availability_documented"])},
        "potentially_obsolete": sum(1 for r in res if r["obsolescence_signals"]),
        "review_backlog": {**backlog, "total": sum(backlog.values()), "reviewed": len(ok) - sum(backlog.values())},
        "savings": {"estimated": est, "verified": ver, "estimated_parts": sum(1 for r in res if r["savings"]["estimated"]),
                    "verified_parts": sum(1 for r in res if r["savings"]["verified"]),
                    "note": "Estimated: complete totals against the OEM baseline, including options that are not technically "
                            "qualified (provisional). Verified: only qualified options with verified-current quotations on both sides."},
        "outcomes": outcomes,
        "evidence_gaps_total": sum(len(r["evidence_gaps"]) for r in res),
    }


def compare(prev_items, items, prev_number) -> dict:
    """Changes since the preceding run of the same scope, part by part."""
    if prev_number is None:
        return {"previous_run": None, "note": "First run for this scope: nothing to compare."}
    before = {i.part.part_number: i.result for i in prev_items if i.status in (IS.DONE, IS.REUSED)}
    after = {i.part.part_number: i.result for i in items if i.status in (IS.DONE, IS.REUSED)}
    out = {"previous_run": prev_number, "added_parts": sorted(set(after) - set(before)), "removed_parts": sorted(set(before) - set(after)),
           "new_am_candidates": [], "new_conventional_candidates": [], "evidence_gaps": [], "oem_changes": [], "cost_changes": [],
           "lead_time_changes": [], "outcome_changes": [], "technical_changes": [], "unchanged": []}
    for n in sorted(set(before) & set(after)):
        b, a = before[n], after[n]
        changed = False
        if a["am_candidate"] and not b["am_candidate"]:
            out["new_am_candidates"].append(n)
            changed = True
        if a["conventional_candidate"] and not b["conventional_candidate"]:
            out["new_conventional_candidates"].append(n)
            changed = True
        for k in ("oem", "additive", "conventional"):
            if a["feasibility"][k]["status"] != b["feasibility"][k]["status"]:
                out["technical_changes"].append({"part": n, "option": k, "before": b["feasibility"][k]["label"], "after": a["feasibility"][k]["label"]})
                changed = True
        added, closed = sorted(set(a["evidence_gaps"]) - set(b["evidence_gaps"])), sorted(set(b["evidence_gaps"]) - set(a["evidence_gaps"]))
        if added or closed:
            out["evidence_gaps"].append({"part": n, "before": len(b["evidence_gaps"]), "after": len(a["evidence_gaps"]),
                                         "new": added, "closed": closed})
            changed = True
        for key, label in (("identity", "OEM identity"), ("cost_evidence", "OEM cost evidence"), ("lead_evidence", "OEM lead-time evidence")):
            if a["oem"].get(key) != b["oem"].get(key):
                out["oem_changes"].append({"part": n, "what": label, "before": b["oem"].get(key), "after": a["oem"].get(key)})
                changed = True
        if bool(a["obsolescence_signals"]) != bool(b["obsolescence_signals"]):
            out["oem_changes"].append({"part": n, "what": "Obsolescence signals", "before": b["obsolescence_signals"], "after": a["obsolescence_signals"]})
            changed = True
        ca, cb = a.get("commercial") or {}, b.get("commercial") or {}
        for k in ("oem", "additive", "conventional"):
            oa, ob = (ca.get("options") or {}).get(k, {}), (cb.get("options") or {}).get(k, {})
            if oa.get("total") != ob.get("total"):
                delta = (str(Decimal(oa["total"]) - Decimal(ob["total"])) if oa.get("total") and ob.get("total") else None)
                out["cost_changes"].append({"part": n, "option": k, "before": ob.get("total"), "after": oa.get("total"), "delta": delta,
                                            "currency": ca.get("currency") or cb.get("currency"),
                                            "scenario": f"v{cb.get('comparison_version')} → v{ca.get('comparison_version')}"})
                changed = True
            if oa.get("lead_days") != ob.get("lead_days"):
                out["lead_time_changes"].append({"part": n, "option": k, "before": ob.get("lead_days"), "after": oa.get("lead_days")})
                changed = True
        if a["recommendation"]["outcome"] != b["recommendation"]["outcome"]:
            out["outcome_changes"].append({"part": n, "before": b["recommendation"]["label"], "after": a["recommendation"]["label"]})
            changed = True
        if not changed:
            out["unchanged"].append(n)
    return out


# ------------------------------------------------------------------ views

def visible_items(request, run):
    qs = AssessmentRunItem.objects.filter(run=run).select_related("part", "project")
    ids = allowed_project_ids(request)
    return list(qs if ids is None else qs.filter(project_id__in=ids))


def serialise_run(r: AssessmentRun) -> dict:
    return {"id": str(r.pk), "number": r.number, "kind": r.kind, "kind_label": r.get_kind_display(), "quarter": r.quarter,
            "status": r.status, "status_label": r.get_status_display(), "scope": r.scope, "ai_tier": r.ai_tier,
            "methodology": r.methodology, "part_count": r.part_count, "done_count": r.done_count, "reused_count": r.reused_count,
            "failed_count": r.failed_count, "started_at": r.started_at, "finished_at": r.finished_at, "created_at": r.created_at,
            "previous_run": r.previous_run.number if r.previous_run_id else None, "error": r.error,
            "fault_injection": bool(r.fault_injection), "requested_by": display_name(r.created_by)}


def serialise_item(i: AssessmentRunItem, review_state=None) -> dict:
    return {"id": str(i.pk), "part_id": str(i.part_id), "part_number": i.part.part_number, "name": i.part.name,
            "project": i.project.code if i.project_id else "", "status": i.status, "status_label": i.get_status_display(),
            "attempts": i.attempts, "error_code": i.error_code, "error_message": i.error_message, "sources": i.sources,
            "result": i.result, "processed_at": i.processed_at, "review_state": review_state}


def run_detail(request, run) -> dict:
    items = visible_items(request, run)
    states = _review_states([i for i in items if i.result])
    prev = visible_items(request, run.previous_run) if run.previous_run_id else []
    progress = {s: sum(1 for i in items if i.status == s) for s in IS.values}
    return {"run": serialise_run(run), "items": [serialise_item(i, states.get(i.part_id)) for i in items], "progress": progress,
            "summary": aggregate(request.tenant, items, _total_parts(request)) if run.status not in AssessmentRun.ACTIVE else None,
            "comparison": compare(prev, items, run.previous_run.number if run.previous_run_id else None)
            if run.status not in AssessmentRun.ACTIVE else None}


def _total_parts(request) -> int:
    qs = SparePart.objects.filter(tenant=request.tenant)
    ids = allowed_project_ids(request)
    return (qs if ids is None else qs.filter(project_id__in=ids)).count()


def dashboard(request) -> dict:
    runs = list(AssessmentRun.objects.filter(tenant=request.tenant).select_related("created_by", "previous_run").order_by("-number")[:20])
    latest = next((r for r in runs if r.status in (RS_.COMPLETED, RS_.COMPLETED_WITH_ERRORS)), None)
    active = next((r for r in runs if r.status in AssessmentRun.ACTIVE), None)
    detail = run_detail(request, latest) if latest else None
    return {"runs": [serialise_run(r) for r in runs], "latest": detail, "active": serialise_run(active) if active else None,
            "total_parts": _total_parts(request), "ai": service.ai_status(request.tenant),
            "schedule": schedule_view(request),
            "statement": "Analytics only. Nothing here approves, publishes or releases a passport or manufacturing job; "
                         "estimated savings include options that are not technically qualified and are never validated savings."}


# ------------------------------------------------------------------ schedule

def schedule_view(request) -> dict:
    from .models import AssessmentSchedule
    s = AssessmentSchedule.objects.filter(tenant=request.tenant).first()
    return ({"enabled": s.enabled, "months": s.months, "day_of_month": s.day_of_month, "ai_tier": s.ai_tier,
             "updated_at": s.updated_at, "updated_by": display_name(s.updated_by)} if s else
            {"enabled": False, "months": [1, 4, 7, 10], "day_of_month": 1, "ai_tier": "", "updated_at": None, "updated_by": ""})


def save_schedule(request, data: dict) -> dict:
    from .models import AssessmentSchedule
    if allowed_project_ids(request) is not None:
        raise DomainError("company_access_required", "Only an engineer with company-wide access can schedule company runs.", http_status=403)
    months = data.get("months") or [1, 4, 7, 10]
    if not isinstance(months, list) or not months or any(not isinstance(m, int) or not 1 <= m <= 12 for m in months):
        raise DomainError("invalid_schedule", "Months must be 1 to 12.", http_status=400)
    day = data.get("day_of_month") or 1
    if not isinstance(day, int) or not 1 <= day <= 28:
        raise DomainError("invalid_schedule", "Day of month must be 1 to 28.", http_status=400)
    tier = data.get("ai_tier") or ""
    if tier and tier not in service.TIERS:
        raise DomainError("invalid_tier", "Choose no AI, lite, flash or pro.", http_status=400)
    s, _ = AssessmentSchedule.objects.get_or_create(tenant=request.tenant, defaults={"created_by": request.user})
    s.enabled, s.months, s.day_of_month, s.ai_tier, s.updated_by = bool(data.get("enabled")), sorted(set(months)), day, tier, request.user
    s.save()
    record(request, "assessment_schedule.saved", obj=s, data={"enabled": s.enabled, "months": s.months, "day": day, "ai_tier": tier})
    return schedule_view(request)


def run_due_schedules(today: date | None = None) -> list[str]:
    """Start the scheduled run of every company whose schedule is due (management command / scheduler). Idempotent:
    one scheduled run per company, quarter and scope."""
    from apps.tenancy.context import tenant_context
    from apps.tenancy.models import Tenant

    from .models import AssessmentSchedule
    today = today or timezone.localdate()
    started = []
    for t in Tenant.objects.filter(kind=Tenant.Kind.CLIENT):
        with tenant_context(t):
            s = AssessmentSchedule.objects.filter(tenant=t, enabled=True).select_related("updated_by", "created_by").first()
            if not s or today.month not in s.months or today.day < s.day_of_month:
                continue
            user = s.updated_by or s.created_by
            ctx = RunContext(t, user)
            if ctx.membership is None:
                continue
            if AssessmentRun.objects.filter(tenant=t, kind=AssessmentRun.Kind.SCHEDULED, quarter=quarter_of(today)).exists():
                continue
            try:
                with transaction.atomic():
                    run, _ = start(ctx, kind=AssessmentRun.Kind.SCHEDULED, ai_tier=s.ai_tier,
                                   idempotency_key=f"scheduled:{quarter_of(today)}")
                started.append(f"{t.slug}: run {run.number}")
            except DomainError as e:
                started.append(f"{t.slug}: skipped ({e.error_code})")
    return started


# ------------------------------------------------------------------ Aries Admin aggregate (no engineering records)

def admin_summary() -> dict:
    from apps.tenancy.context import tenant_context
    from apps.tenancy.models import Tenant
    rows = []
    for t in Tenant.objects.filter(kind=Tenant.Kind.CLIENT).order_by("name"):
        with tenant_context(t):
            r = (AssessmentRun.objects.filter(tenant=t, status__in=[RS_.COMPLETED, RS_.COMPLETED_WITH_ERRORS]).order_by("-number").first())
            active = AssessmentRun.objects.filter(tenant=t, status__in=AssessmentRun.ACTIVE).exists()
            if r is None and not active:
                continue
            s = r.summary if r else {}
            rows.append({"company": t.name, "latest_run": r.number if r else None, "quarter": r.quarter if r else "",
                         "status": r.get_status_display() if r else "", "finished_at": r.finished_at if r else None, "active_run": active,
                         "counts": {k: s.get(k) for k in ("total_parts", "assessed", "unassessed", "insufficient_technical_data",
                                                          "am_candidates", "conventional_candidates", "potentially_obsolete")},
                         "review_backlog": (s.get("review_backlog") or {}).get("total"),
                         "savings": {"estimated": (s.get("savings") or {}).get("estimated", {}),
                                     "verified": (s.get("savings") or {}).get("verified", {})}})
    return {"companies": rows, "note": "Aggregate counts only: no part numbers, descriptions, drawings, prices per part or engineering records."}
