"""Part intelligence service (CN-007 Phase 2): deterministic analysis always; external AI only where permitted.

External AI gate (all must hold, checked on every call, server-side):
- PART_INTELLIGENCE_ENABLED, AI_PROVIDER = "gemini" and GEMINI_API_KEY set (backend environment);
- the company's slug is in AI_ALLOWED_COMPANIES (real client companies stay off it until data-processing approval);
- the part is an imported inventory record (CN-007 Phase 1), i.e. it has an import record.
Only whitelisted fields are sent (`ai_inputs`): the material description, the cleaned manufacturer name and the
rule-based findings. Never plant, location, equipment tag, ABC indicator, manufacturer reference, remarks, files,
drawings, CAD, passport data, company or user names.

Limits: calls per minute (all companies), calls per day, a daily cost budget, a per-call timeout and bounded retries
for transient errors. An unchanged input (same hash) reuses the stored suggestion without calling again.
"""
import hashlib
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db import connection, transaction
from django.db.models import Q
from django.utils import timezone

from apps.audit.service import record
from apps.core.exceptions import DomainError
from apps.files.models import EngineeringFile
from apps.parts.models import SparePart, lifecycle_parts
from apps.parts.submissions import display_name
from apps.projects.scoping import restrict
from apps.tenancy import mssql
from apps.tenancy.context import tenant_context
from apps.tenancy.models import Tenant

from . import gemini, rules
from .models import AIUsageLog, PartAssessment

PROMPT_VERSION = "pi-prompt-2026-10-27.2"  # .2: no roles for unlabelled dimensions
TIERS = ("lite", "flash", "pro")
U = AIUsageLog.Outcome
# A sentence stating an amount of money is removed from suggestions (AI prices are never quotations).
PRICE_RE = re.compile(r"[^.;\n]*(?:[$€£]\s?\d|\b\d[\d,.]*\s?(?:USD|AED|EUR|GBP|dollars?|dirhams?|euros?)\b|"
                      r"\b(?:USD|AED|EUR|GBP)\s?\d)[^.;\n]*[.;]?", re.I)


# ------------------------------------------------------------------ deterministic analysis

def documents_count(part) -> int:
    return EngineeringFile.objects.filter(tenant=part.tenant_id, part=part).count()


def company_parts(tenant):
    return list(SparePart.objects.filter(tenant=tenant).only("id", "part_number", "name", "manufacturer"))


def analyse(part, peers=None) -> dict:
    return rules.analyse(part, peers if peers is not None else company_parts(part.tenant_id), documents_count(part))


# ------------------------------------------------------------------ external AI gate

def ai_status(tenant) -> dict:
    s = settings
    reason = ""
    if not s.PART_INTELLIGENCE_ENABLED:
        reason = "Part intelligence is switched off."
    elif s.AI_PROVIDER != "gemini":
        reason = "External AI is switched off (no provider configured). The rule-based analysis works without it."
    elif not s.GEMINI_API_KEY:
        reason = "External AI is not configured (no API key in the backend environment)."
    elif tenant is None or tenant.slug not in s.AI_ALLOWED_COMPANIES:
        reason = ("External AI is not permitted for this company. It stays off for client companies until data-processing "
                  "approval and suitable API terms are confirmed.")
    return {"enabled": not reason, "reason": reason, "provider": s.AI_PROVIDER or "", "models": dict(s.GEMINI_MODELS),
            "limits": {"calls_per_minute": s.AI_CALLS_PER_MINUTE, "calls_per_day": s.AI_CALLS_PER_DAY,
                       "daily_budget_usd": s.AI_DAILY_BUDGET_USD, "timeout_seconds": s.AI_TIMEOUT_SECONDS,
                       "max_retries": s.AI_MAX_RETRIES},
            "sent_fields": ["material description", "cleaned manufacturer name", "rule-based findings"]}


def ai_inputs(part, analysis: dict) -> dict:
    """The complete payload sent to the provider. Whitelist only; see the module docstring."""
    a = analysis
    return {
        "material_description": part.name,
        "manufacturer_name": a["manufacturer"]["cleaned"] or "not stated",
        "rule_based_findings": {
            "expanded_description": ", ".join(a["description"]["expanded"]),
            "unrecognised_abbreviations": a["description"]["unknown_tokens"],
            "part_family": a["classification"]["family"] or "not recognised",
            "category": a["classification"]["category"],
            "dimensions_mentioned": [f"{d['value']:g} {d['unit']}" for d in a["mentions"]["dimensions"]],
            "materials_mentioned": [m["reading"] for m in a["mentions"]["materials"]],
            "drawing_or_model_available": a["completeness"]["items"][-1]["met"],
        },
    }


def input_hash(provider: str, model: str, inputs: dict) -> str:
    blob = json.dumps({"provider": provider, "model": model, "prompt": PROMPT_VERSION, "inputs": inputs}, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()


def _prompt(inputs: dict) -> str:
    return ("Assess this spare-part inventory record. Data (JSON):\n" + json.dumps(inputs, ensure_ascii=False, indent=1))


def _strip_prices(result: dict) -> list[str]:
    removed = []

    def clean(s: str) -> str:
        for m in PRICE_RE.findall(s or ""):
            removed.append(m.strip())
        return PRICE_RE.sub(" [price or cost statement removed] ", s or "").strip()

    for k in ("expanded_description", "function", "rationale", "uncertainty", "part_family"):
        result[k] = clean(result[k])
    result["material"]["value"] = clean(result["material"]["value"])
    result["risks"] = [clean(x) for x in result["risks"]]
    result["information_needed"] = [clean(x) for x in result["information_needed"]]
    return removed


class Refused(DomainError):
    """A limit refused the call. The view answers without raising, so the refusal's usage log and audit are kept."""


def _adapter():
    return gemini.GeminiAdapter()


def _usage_rows(tenants, since) -> list[dict]:
    """Usage-log rows since a time, read company by company (the log is under tenant RLS like every tenant table)."""
    rows = []
    for t in tenants:
        with tenant_context(t):
            rows += [{**r, "company": t.name} for r in AIUsageLog.objects.filter(tenant=t, created_at__gte=since).values(
                "model", "outcome", "prompt_tokens", "output_tokens", "thinking_tokens", "cost_usd", "created_at")]
    return rows


def _limited_tenants(request) -> list:
    """Companies whose calls count towards the shared limits: those permitted to use external AI, plus this one."""
    return list(Tenant.objects.filter(Q(slug__in=settings.AI_ALLOWED_COMPANIES) | Q(pk=request.tenant.pk)))


def _reserve(request, model: str, part) -> AIUsageLog:
    """Check the shared limits and record the attempt atomically (an advisory lock serialises concurrent callers)."""
    now = timezone.now()
    with transaction.atomic():
        with connection.cursor() as c:
            if mssql.is_mssql(connection):
                c.execute("EXEC sp_getapplock @Resource = N'part_intelligence_ai', @LockMode = 'Exclusive', @LockOwner = 'Transaction'")
            else:
                c.execute("SELECT pg_advisory_xact_lock(hashtext('part_intelligence_ai'))")
        day = now.replace(hour=0, minute=0, second=0, microsecond=0)
        today = [r for r in _usage_rows(_limited_tenants(request), min(day, now - timedelta(minutes=1)))
                 if r["outcome"] not in (U.CACHE_HIT, U.REFUSED)]
        refusal = None
        if sum(1 for r in today if r["created_at"] >= now - timedelta(minutes=1)) >= settings.AI_CALLS_PER_MINUTE:
            refusal = ("ai_rate_limited", "Too many AI requests in the last minute. Try again shortly.")
        elif sum(1 for r in today if r["created_at"] >= day) >= settings.AI_CALLS_PER_DAY:
            refusal = ("ai_daily_limit", "The daily number of AI requests has been reached.")
        elif sum((r["cost_usd"] for r in today if r["created_at"] >= day), Decimal(0)) >= Decimal(str(settings.AI_DAILY_BUDGET_USD)):
            refusal = ("ai_budget_exhausted", "Today's AI cost budget has been used up.")
    log = AIUsageLog.objects.create(tenant=request.tenant, created_by=request.user, user=request.user, part_id=part.pk, provider="gemini", model=model,
                                        outcome=U.REFUSED if refusal else U.STARTED, error_code=refusal[0] if refusal else "")
    if refusal:
        record(request, "part_intelligence.ai_refused", obj=part, data={"reason": refusal[0], "model": model})
        raise Refused(refusal[0], refusal[1], http_status=429)
    return log


# AI calls run on a small bounded pool so a hung provider call can be abandoned at the deadline (the SDK's own HTTP timeout
# ends the abandoned thread later). At most this many calls are in flight per process.
_AI_POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix="ai-call")


def call_ai(model: str, tier: str, prompt: str, schema: dict | None = None, system: str | None = None, model_cls=None,
            check=None):
    """One AI request with bounded retries for transient errors and invalid responses. `check(result)` may raise a
    retryable AIError when a valid response contradicts deterministic results (the model is then asked again).

    True total deadline: every attempt, retry and back-off together end within AI_TOTAL_DEADLINE_SECONDS; a single
    attempt is abandoned after AI_TIMEOUT_SECONDS (or the time left, if less). A cold start therefore delays the caller
    by at most the deadline, never indefinitely.
    Returns (validated result or None, last CallResult or None, token/latency totals, attempts, last AIError or None)."""
    adapter = _adapter()
    extra = {k: v for k, v in (("schema", schema), ("system", system)) if v is not None}
    deadline = time.monotonic() + settings.AI_TOTAL_DEADLINE_SECONDS
    attempts, totals, err, result, call = 0, {"prompt": 0, "output": 0, "thinking": 0, "latency": 0}, None, None, None
    while attempts <= settings.AI_MAX_RETRIES:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            err = gemini.AIError("deadline_exceeded", f"No valid answer within the total deadline of {settings.AI_TOTAL_DEADLINE_SECONDS} s.")
            break
        attempts += 1
        wait = min(remaining, settings.AI_TIMEOUT_SECONDS)
        started = time.monotonic()
        try:
            future = _AI_POOL.submit(adapter.generate, model=model, tier=tier, prompt=prompt, **extra)
            try:
                call = future.result(timeout=wait)
            except FuturesTimeout:
                future.cancel()  # not started yet: dropped; running: abandoned, ended by the HTTP timeout
                totals["latency"] += int((time.monotonic() - started) * 1000)
                last = wait >= remaining
                raise gemini.AIError("deadline_exceeded" if last else "timeout",
                                     (f"No valid answer within the total deadline of {settings.AI_TOTAL_DEADLINE_SECONDS} s." if last
                                      else f"No answer within {wait:.0f} s."), retryable=not last)
            totals["prompt"] += call.prompt_tokens
            totals["output"] += call.output_tokens
            totals["thinking"] += call.thinking_tokens
            totals["latency"] += call.latency_ms
            candidate = gemini.validate(call.text, model_cls)
            if check:
                check(candidate)
            result, err = candidate, None  # only a response that passed every check counts
            break
        except gemini.AIError as e:
            err = e
            if not e.retryable or attempts > settings.AI_MAX_RETRIES:
                break
            time.sleep(max(0, min(2 ** (attempts - 1), 4, deadline - time.monotonic())))
    return result, call, totals, attempts, err


def assess(request, part, tier: str = "lite") -> tuple[PartAssessment, bool]:
    """Return (assessment, reused). Raises DomainError when AI is not permitted or a limit is reached."""
    if tier not in TIERS:
        raise DomainError("invalid_tier", "Choose lite, flash or pro.", http_status=400)
    status = ai_status(request.tenant)
    if not status["enabled"]:
        raise DomainError("ai_not_permitted", status["reason"], http_status=403)
    if not part.import_record:
        raise DomainError("ai_not_permitted_for_part", "External AI is used only for imported synthetic inventory records; the rules-based assessment is available for every part.", http_status=403)
    model = settings.GEMINI_MODELS[tier]
    analysis = analyse(part)
    inputs = ai_inputs(part, analysis)
    h = input_hash("gemini", model, inputs)
    existing = PartAssessment.objects.filter(tenant=request.tenant, part=part, status=PartAssessment.Status.OK, input_hash=h).first()
    if existing:
        AIUsageLog.objects.create(tenant=request.tenant, created_by=request.user, user=request.user, part_id=part.pk, assessment_id=existing.pk,
                                  provider="gemini", model=model, model_version=existing.model_version, outcome=U.CACHE_HIT)
        record(request, "part_intelligence.ai_reused", obj=part, data={"assessment": str(existing.pk), "model": model})
        return existing, True
    log = _reserve(request, model, part)
    result, call, totals, attempts, err = call_ai(model, tier, _prompt(inputs))
    cost = gemini.cost_usd(model, call.model_version if call else "", totals["prompt"], totals["output"], totals["thinking"])
    usage = {"prompt_tokens": totals["prompt"], "output_tokens": totals["output"], "thinking_tokens": totals["thinking"],
             "cost_usd": cost, "latency_ms": totals["latency"], "attempts": attempts,
             "finish_reason": call.extra.get("finish_reason", "") if call else "", "traffic_type": call.extra.get("traffic_type", "") if call else ""}
    removed = _strip_prices(result) if result else []
    st = PartAssessment.Status
    status_code = st.OK if result else (st.INVALID if err and err.code in ("invalid_json", "schema_mismatch") else st.FAILED)
    a = PartAssessment.objects.create(
        tenant=request.tenant, created_by=request.user, part=part, status=status_code, provider="gemini", tier=tier, model=model,
        model_version=call.model_version if call else "", prompt_version=PROMPT_VERSION, rules_version=rules.RULES_VERSION,
        input_hash=h, inputs=inputs, result=result or {}, confidence=(result or {}).get("confidence"), removed=removed,
        error_code=err.code if err else "", error_message=gemini.scrub(err.message) if err else "", usage=usage)
    AIUsageLog.objects.filter(pk=log.pk).update(
        assessment_id=a.pk, model_version=a.model_version, outcome={st.OK: U.OK, st.INVALID: U.INVALID}.get(status_code, U.FAILED),
        prompt_tokens=totals["prompt"], output_tokens=totals["output"], thinking_tokens=totals["thinking"],
        cost_usd=Decimal(str(cost or 0)), latency_ms=totals["latency"], attempts=attempts, error_code=a.error_code,
        updated_at=timezone.now())
    record(request, "part_intelligence.ai_assessed", obj=part, data={
        "assessment": str(a.pk), "status": status_code, "model": model, "model_version": a.model_version, "tier": tier,
        "input_hash": h, "prompt_tokens": totals["prompt"], "output_tokens": totals["output"],
        "thinking_tokens": totals["thinking"], "cost_usd": cost, "attempts": attempts, "error": a.error_code})
    return a, False


# ------------------------------------------------------------------ engineer classification (verified value)

def record_classification(request, part, category: str, note: str, assessment_id=None) -> SparePart:
    if category not in SparePart.Category.values:
        raise DomainError("invalid_category", "Choose a valid category.", http_status=400)
    basis = None
    if assessment_id:
        basis = PartAssessment.objects.filter(tenant=request.tenant, part=part, pk=assessment_id).first()
        if basis is None:
            raise DomainError("not_found", "Assessment not found for this part.", http_status=404)
    now = timezone.now()
    before = part.category
    prov = dict(part.field_provenance or {})
    prov["category"] = {"source": "aries", "entered_by": display_name(request.user), "entered_at": now.isoformat(),
                        "verified_by": display_name(request.user), "verified_at": now.isoformat(),
                        "basis": "engineer classification" + (f" (AI suggestion {basis.pk} considered)" if basis else ""),
                        "note": note[:500]}
    part.category, part.field_provenance = category, prov
    part.save(update_fields=["category", "field_provenance", "updated_at"])
    record(request, "part_intelligence.classification_recorded", obj=part, data={
        "from": before, "to": category, "assessment": str(basis.pk) if basis else "",
        "ai_category": (basis.result or {}).get("category", "") if basis else "", "note": note[:500]})
    return part


# ------------------------------------------------------------------ views over the company

def serialise(a: PartAssessment) -> dict:
    return {"id": str(a.pk), "status": a.status, "status_label": a.get_status_display(), "provider": a.provider, "tier": a.tier,
            "model": a.model, "model_version": a.model_version, "prompt_version": a.prompt_version,
            "rules_version": a.rules_version, "input_hash": a.input_hash, "inputs": a.inputs, "result": a.result,
            "confidence": a.confidence, "removed": a.removed, "error_code": a.error_code, "error_message": a.error_message,
            "usage": a.usage, "created_at": a.created_at, "created_by_name": display_name(a.created_by)}


def part_view(request, part) -> dict:
    analysis = analyse(part)
    status = ai_status(request.tenant)
    if status["enabled"] and not part.import_record:
        status = {**status, "enabled": False, "reason": "External AI is used only for imported synthetic inventory records; the rules-based assessment is available for every part."}
    current = {t: input_hash("gemini", m, ai_inputs(part, analysis)) for t, m in settings.GEMINI_MODELS.items()}
    items = [serialise(a) for a in PartAssessment.objects.filter(tenant=request.tenant, part=part).select_related("created_by")[:20]]
    for i in items:
        i["current"] = current.get(i["tier"]) == i["input_hash"]
    return {"analysis": analysis, "ai": status, "assessments": items,
            "classification": {"category": part.category, "provenance": (part.field_provenance or {}).get("category")}}


def overview(request) -> dict:
    parts = list(restrict(request, lifecycle_parts(SparePart.objects.filter(tenant=request.tenant)), "project")
                 .order_by("part_number"))
    peers = company_parts(request.tenant)
    latest = {}
    for a in PartAssessment.objects.filter(tenant=request.tenant, part__in=parts).order_by("-created_at"):
        latest.setdefault(a.part_id, a)
    rows = []
    for p in parts:
        an = analyse(p, peers)
        a = latest.get(p.pk)
        rows.append({"id": str(p.pk), "part_number": p.part_number, "name": p.name, "manufacturer": p.manufacturer,
                     "category": p.category, "rules": {"family": an["classification"]["family"], "category": an["classification"]["category"],
                                                       "screening": an["screening"], "completeness": an["completeness"]["score"],
                                                       "constraints": an["constraints"], "duplicates": an["duplicates"],
                                                       "manufacturer": an["manufacturer"]},
                     "ai": ({"id": str(a.pk), "status": a.status, "model": a.model, "model_version": a.model_version, "tier": a.tier,
                             "category": a.result.get("category"), "part_family": a.result.get("part_family"),
                             "am_screening": a.result.get("am_screening"), "confidence": a.confidence,
                             "cost_usd": a.usage.get("cost_usd"), "created_at": a.created_at, "error_code": a.error_code} if a else None)})
    return {"ai": ai_status(request.tenant), "parts": rows, "usage": usage_summary(tenant=request.tenant)}


def _totals(rows) -> dict:
    t = {"calls": 0, "cache_hits": 0, "refused": 0, "failed": 0, "prompt_tokens": 0, "output_tokens": 0, "thinking_tokens": 0,
         "cost_usd": 0.0}
    for r in rows:
        if r["outcome"] == U.CACHE_HIT:
            t["cache_hits"] += 1
        elif r["outcome"] == U.REFUSED:
            t["refused"] += 1
        else:
            t["calls"] += 1
        t["failed"] += r["outcome"] in (U.FAILED, U.INVALID)
        for k in ("prompt_tokens", "output_tokens", "thinking_tokens"):
            t[k] += r[k]
        t["cost_usd"] += float(r["cost_usd"] or 0)
    t["cost_usd"] = round(t["cost_usd"], 8)
    return t


def usage_summary(tenant=None, days: int = 30) -> dict:
    """AI calls, tokens and estimated cost for one company, or (tenant=None, Aries Admin) for every client company."""
    tenants = [tenant] if tenant is not None else list(Tenant.objects.filter(kind=Tenant.Kind.CLIENT).order_by("name"))
    rows = _usage_rows(tenants, timezone.now() - timedelta(days=days))
    group = lambda key: {k: [r for r in rows if r[key] == k] for k in sorted({r[key] for r in rows})}  # noqa: E731
    out = {"days": days, "total": _totals(rows), "by_model": [{"model": m, **_totals(rs)} for m, rs in group("model").items()],
           "note": "Estimated from list prices; the provider's bill is authoritative."}
    if tenant is None:
        out["by_company"] = [{"company": c, **_totals(rs)} for c, rs in group("company").items()]
    return out
