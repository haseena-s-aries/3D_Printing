"""Part intelligence records (CN-007 Phase 2).

PartAssessment: one AI suggestion for one part, kept apart from the part's own (engineer-verified) fields and never
changed after it is stored. It records the model, when it ran, the exact inputs sent, the validated proposed values,
the model's confidence and uncertainty, and token usage and estimated cost. Inputs are hashed so an unchanged part is
not sent again (the stored suggestion is reused).

AIUsageLog: every external AI attempt (including cache hits, refusals and failures) for rate limits, the daily budget
and the cost report. Operational metadata only: no part text, prompt or response. Under tenant row-level security like
every tenant table; shared limits and the Aries Admin totals read it company by company.
"""
from django.conf import settings
from django.db import models

from apps.tenancy.owned import TenantOwnedModel


class PartAssessment(TenantOwnedModel):
    class Status(models.TextChoices):
        OK = "ok", "Suggestion received"
        INVALID = "invalid_response", "Response failed validation"
        FAILED = "failed", "Call failed"

    part = models.ForeignKey("parts.SparePart", on_delete=models.CASCADE, related_name="ai_assessments")
    status = models.CharField(max_length=20, choices=Status.choices)
    provider = models.CharField(max_length=20)
    tier = models.CharField(max_length=10)  # lite, flash, pro
    model = models.CharField(max_length=80)  # model requested
    model_version = models.CharField(max_length=80, blank=True)  # model that answered, as reported by the provider
    prompt_version = models.CharField(max_length=40)
    rules_version = models.CharField(max_length=40)
    input_hash = models.CharField(max_length=64, db_index=True)
    inputs = models.JSONField(default=dict)  # exactly what was sent (whitelisted fields only)
    result = models.JSONField(default=dict)  # validated proposed values; empty unless status is ok
    confidence = models.FloatField(null=True, blank=True)
    removed = models.JSONField(default=list, blank=True)  # text the server removed from the suggestion (e.g. prices)
    error_code = models.CharField(max_length=40, blank=True)
    error_message = models.CharField(max_length=500, blank=True)
    usage = models.JSONField(default=dict)  # prompt/output/thinking tokens, cost_usd, latency_ms, attempts

    class Meta:
        ordering = ["-created_at"]


class AIUsageLog(TenantOwnedModel):
    class Outcome(models.TextChoices):
        STARTED = "started", "In progress"
        OK = "ok", "Suggestion received"
        CACHE_HIT = "cache_hit", "Reused stored suggestion (no call)"
        INVALID = "invalid_response", "Response failed validation"
        FAILED = "failed", "Call failed"
        REFUSED = "refused", "Refused before calling (limit, budget or not permitted)"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    part_id = models.UUIDField(null=True, blank=True)
    assessment_id = models.UUIDField(null=True, blank=True)
    provider = models.CharField(max_length=20)
    model = models.CharField(max_length=80)
    model_version = models.CharField(max_length=80, blank=True)
    outcome = models.CharField(max_length=20, choices=Outcome.choices, default=Outcome.STARTED)
    prompt_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)
    thinking_tokens = models.PositiveIntegerField(default=0)
    cost_usd = models.DecimalField(max_digits=12, decimal_places=8, default=0)
    latency_ms = models.PositiveIntegerField(default=0)
    attempts = models.PositiveSmallIntegerField(default=0)
    error_code = models.CharField(max_length=40, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["created_at"])]


class FeasibilityAssessment(TenantOwnedModel):
    """One version of the manufacturing feasibility screening of a part (CN-007 Phase 3): OEM procurement, additive and
    conventional manufacturing side by side. Never changed after it is stored; a changed input gives a new version.

    The rule results (apps.intelligence.feasibility) are authoritative for the statuses. An optional AI explanation is
    kept in `ai` with its full provenance; it can lower a status (more caution) but never raise one. Nothing here is an
    approval: no passport state, evidence level or manufacturing eligibility is derived from it."""

    class AIStatus(models.TextChoices):
        NONE = "none", "Rules only (no AI)"
        OK = "ok", "AI explanation received"
        INVALID = "invalid_response", "AI response failed validation"
        FAILED = "failed", "AI call failed"

    part = models.ForeignKey("parts.SparePart", on_delete=models.PROTECT, related_name="feasibility_assessments")
    project = models.ForeignKey("projects.Project", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    version = models.PositiveIntegerField()  # 1, 2, ... per part
    methodology_version = models.CharField(max_length=40)
    rules_version = models.CharField(max_length=40)
    # Passport and revision current when assessed (when the part has a passport).
    passport_number = models.CharField(max_length=60, blank=True)
    passport_revision = models.ForeignKey("passports.PassportRevision", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    passport_revision_number = models.PositiveIntegerField(null=True, blank=True)
    input_hash = models.CharField(max_length=64, db_index=True)
    inputs = models.JSONField(default=dict)  # evidence / input snapshot the rules used
    oem = models.JSONField(default=dict)
    additive = models.JSONField(default=dict)
    conventional = models.JSONField(default=dict)
    oem_status = models.CharField(max_length=40)
    additive_status = models.CharField(max_length=40)
    conventional_status = models.CharField(max_length=40)
    constraints = models.JSONField(default=list)  # constraints and disqualifying conditions
    missing_information = models.JSONField(default=list)
    next_actions = models.JSONField(default=list)
    ai_status = models.CharField(max_length=20, choices=AIStatus.choices, default=AIStatus.NONE)
    # provider, tier, model, model_version, prompt_version, sent (exact payload), response (validated), usage, removed,
    # adjustments (where the rules overrode or the AI lowered a status), error_code, error_message
    ai = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["part", "-version"]
        constraints = [models.UniqueConstraint(fields=["part", "version"], name="uniq_feasibility_version_per_part")]


class FeasibilityReview(TenantOwnedModel):
    """An engineer's technical review entry on one alternative of a feasibility assessment (append-only).
    Technical review only: it is not a formal engineering approval and changes no passport, eligibility or release state."""

    class Alternative(models.TextChoices):
        OEM = "oem", "OEM procurement"
        ADDITIVE = "additive", "Additive manufacturing"
        CONVENTIONAL = "conventional", "Conventional manufacturing"
        OVERALL = "overall", "Whole assessment"

    class Decision(models.TextChoices):
        CONFIRMED = "confirmed", "Preliminary result confirmed (technical review)"
        CORRECTED = "corrected", "Preliminary result corrected"
        REJECTED = "rejected", "Preliminary result rejected"
        MORE_INFO = "more_information_required", "Additional information required"
        FINDING = "finding", "Technical finding recorded"

    assessment = models.ForeignKey(FeasibilityAssessment, on_delete=models.PROTECT, related_name="reviews")
    part = models.ForeignKey("parts.SparePart", on_delete=models.PROTECT, related_name="+")
    alternative = models.CharField(max_length=16, choices=Alternative.choices)
    decision = models.CharField(max_length=32, choices=Decision.choices)
    corrected_status = models.CharField(max_length=40, blank=True)
    findings = models.TextField(blank=True)
    note = models.TextField(blank=True)
    evidence_references = models.JSONField(default=list, blank=True)  # [{file?, title?, reference}]
    independent = models.BooleanField(default=False)  # reviewer is not the engineer who ran the assessment
    reviewer_name = models.CharField(max_length=150, blank=True)

    class Meta:
        ordering = ["created_at"]


class CostComparison(TenantOwnedModel):
    """One version of the cost and lead-time comparison of a part (CN-007 Phase 4): OEM procurement, additive and
    conventional manufacturing for one required quantity in one reporting currency. Never changed after it is stored;
    a changed scenario or quantity gives a new version (derived_from links a what-if to the version it started from).

    Inputs keep every figure with its source (quotation, historical, engineering estimate, AI-assisted estimate or
    missing), evidence reference, currency and the explicitly entered, dated exchange rates. Results are the
    deterministic calculation (apps.intelligence.costing). Technical status comes from the linked Phase 3 feasibility
    version. Comparison only: no recommendation, approval, eligibility or release is derived from it."""

    class AIStatus(models.TextChoices):
        NONE = "none", "No AI notes"
        OK = "ok", "AI assumption notes received"
        INVALID = "invalid_response", "AI response failed validation"
        FAILED = "failed", "AI call failed"

    part = models.ForeignKey("parts.SparePart", on_delete=models.PROTECT, related_name="cost_comparisons")
    project = models.ForeignKey("projects.Project", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    version = models.PositiveIntegerField()
    method_version = models.CharField(max_length=40)
    feasibility = models.ForeignKey(FeasibilityAssessment, on_delete=models.PROTECT, related_name="cost_comparisons")
    feasibility_version = models.PositiveIntegerField()
    passport_number = models.CharField(max_length=60, blank=True)
    passport_revision = models.ForeignKey("passports.PassportRevision", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    passport_revision_number = models.PositiveIntegerField(null=True, blank=True)
    name = models.CharField(max_length=120)  # scenario name
    synthetic = models.BooleanField(default=False)  # synthetic test figures, not real prices
    quantity = models.PositiveIntegerField()
    reporting_currency = models.CharField(max_length=3)
    derived_from = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    input_hash = models.CharField(max_length=64, db_index=True)
    inputs = models.JSONField(default=dict)  # validated scenario: alternatives, cost and lead-time components, sources, rates
    technical = models.JSONField(default=dict)  # technical status per alternative from the feasibility version
    results = models.JSONField(default=dict)  # calculated breakdowns, totals, unit costs, lead times, savings, missing inputs
    as_of = models.DateField()  # date used for quotation validity
    ai_status = models.CharField(max_length=20, choices=AIStatus.choices, default=AIStatus.NONE)
    ai = models.JSONField(default=dict, blank=True)  # provenance as in Phase 3 (explanations only, never prices)

    class Meta:
        ordering = ["part", "-version"]
        constraints = [models.UniqueConstraint(fields=["part", "version"], name="uniq_cost_comparison_version_per_part")]


class Recommendation(TenantOwnedModel):
    """One version of the Phase 5 recommendation for a part (CN-007): Phase 2 part intelligence, Phase 3 feasibility
    and Phase 4 cost comparison combined by deterministic rules (apps.intelligence.recommendation). The source
    revisions it used are kept (never re-pointed); a changed source or weighting gives a new version. Preliminary until
    reviewed; never an engineering approval, manufacturing authorisation, publication or release (OQ-35, OQ-36)."""

    class AIStatus(models.TextChoices):
        NONE = "none", "No AI explanation"
        OK = "ok", "AI explanation received"
        INVALID = "invalid_response", "AI response failed validation"
        FAILED = "failed", "AI call failed"

    part = models.ForeignKey("parts.SparePart", on_delete=models.PROTECT, related_name="recommendations")
    project = models.ForeignKey("projects.Project", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    version = models.PositiveIntegerField()
    method_version = models.CharField(max_length=40)
    # source revisions (Phase 2 suggestion optional; Phase 4 comparison optional)
    intelligence = models.ForeignKey(PartAssessment, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    feasibility = models.ForeignKey(FeasibilityAssessment, on_delete=models.PROTECT, related_name="recommendations")
    feasibility_version = models.PositiveIntegerField()
    cost_comparison = models.ForeignKey(CostComparison, null=True, blank=True, on_delete=models.PROTECT, related_name="recommendations")
    cost_comparison_version = models.PositiveIntegerField(null=True, blank=True)
    passport_number = models.CharField(max_length=60, blank=True)
    passport_revision = models.ForeignKey("passports.PassportRevision", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    passport_revision_number = models.PositiveIntegerField(null=True, blank=True)
    input_hash = models.CharField(max_length=64, db_index=True)
    inputs = models.JSONField(default=dict)  # weights, source ids/versions and the Phase 2 summary used
    results = models.JSONField(default=dict)  # options, requirements, statuses, ranking, outcome
    outcome = models.CharField(max_length=40)
    recommended_option = models.CharField(max_length=16, blank=True)  # preliminary, for further study only
    as_of = models.DateField()
    ai_status = models.CharField(max_length=20, choices=AIStatus.choices, default=AIStatus.NONE)
    ai = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["part", "-version"]
        constraints = [models.UniqueConstraint(fields=["part", "version"], name="uniq_recommendation_version_per_part")]


class RecommendationReview(TenantOwnedModel):
    """An engineering review decision on a recommendation version (append-only). "Approved for further study" is not an
    engineering approval and authorises nothing; formal approval and release stay blocked (OQ-35, OQ-36)."""

    class Decision(models.TextChoices):
        FURTHER_STUDY = "approved_for_further_study", "Approved for further study"
        INFO = "information_requested", "Information requested"
        CORRECTED = "corrected", "Recommendation corrected"
        REJECTED = "rejected", "Recommendation rejected"

    recommendation = models.ForeignKey(Recommendation, on_delete=models.PROTECT, related_name="reviews")
    part = models.ForeignKey("parts.SparePart", on_delete=models.PROTECT, related_name="+")
    decision = models.CharField(max_length=32, choices=Decision.choices)
    option = models.CharField(max_length=16, blank=True)  # the option studied further / the corrected option ("none" allowed)
    findings = models.TextField()
    evidence_references = models.JSONField(default=list, blank=True)
    independent = models.BooleanField(default=False)  # reviewer did not generate the recommendation
    option_eligible = models.BooleanField(default=False)  # the option met every mandatory requirement at review time
    reviewer_name = models.CharField(max_length=150, blank=True)

    class Meta:
        ordering = ["created_at"]


class AssessmentRun(TenantOwnedModel):
    """A quarterly (or manual) assessment of a company's inventory (CN-007 Phase 6): every in-scope part is taken through
    Phase 2-5 (reusing unchanged results), processed in the background one part per job. Records its scope, methodology
    versions, counts, timestamps, the dashboard summary and the comparison with the previous run of the same scope.
    Never approves, publishes or releases anything. Immutable once completed, failed or cancelled."""

    class Kind(models.TextChoices):
        MANUAL = "manual", "Manual"
        SCHEDULED = "scheduled", "Scheduled (quarterly)"

    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"
        RUNNING = "running", "Running"
        COMPLETED = "completed", "Completed"
        COMPLETED_WITH_ERRORS = "completed_with_errors", "Completed with errors"
        FAILED = "failed", "Failed"
        CANCELLED = "cancelled", "Cancelled"

    ACTIVE = (Status.QUEUED, Status.RUNNING)

    number = models.PositiveIntegerField()  # 1, 2, ... per company
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.MANUAL)
    quarter = models.CharField(max_length=7)  # e.g. 2026-Q4
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.QUEUED)
    scope = models.JSONField(default=dict)  # {"parts": "imported", "projects": null | [ids], "project_codes": [...]}
    scope_key = models.CharField(max_length=64)
    ai_tier = models.CharField(max_length=10, blank=True)  # "" = rules only; lite/flash/pro within the AI limits
    methodology = models.JSONField(default=dict)  # rules, feasibility, cost, recommendation and prompt versions
    idempotency_key = models.CharField(max_length=80, blank=True)
    previous_run = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    part_count = models.PositiveIntegerField(default=0)
    done_count = models.PositiveIntegerField(default=0)
    reused_count = models.PositiveIntegerField(default=0)
    failed_count = models.PositiveIntegerField(default=0)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    summary = models.JSONField(default=dict, blank=True)  # dashboard aggregates at completion
    comparison = models.JSONField(default=dict, blank=True)  # changes against previous_run
    error = models.TextField(blank=True)
    fault_injection = models.JSONField(default=dict, blank=True)  # test environments only (ASSESSMENT_FAULT_INJECTION)

    class Meta:
        ordering = ["-number"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "number"], name="uniq_assessment_run_number"),
            models.UniqueConstraint(fields=["tenant", "scope_key"], condition=models.Q(status__in=["queued", "running"]),
                                    name="one_active_assessment_run_per_scope"),
            models.UniqueConstraint(fields=["tenant", "quarter", "scope_key"], condition=models.Q(kind="scheduled"),
                                    name="one_scheduled_assessment_run_per_quarter"),
            models.UniqueConstraint(fields=["tenant", "idempotency_key"], condition=~models.Q(idempotency_key=""),
                                    name="uniq_assessment_run_idempotency_key"),
        ]


class AssessmentRunItem(TenantOwnedModel):
    """One part in an assessment run, with the source revisions used and a summary of the result. Reused when the part's
    inputs and the methodology are unchanged since the previous run. Immutable once done or reused."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        DONE = "done", "Assessed"
        REUSED = "reused", "Unchanged: previous result reused"
        FAILED = "failed", "Failed"

    run = models.ForeignKey(AssessmentRun, on_delete=models.PROTECT, related_name="items")
    part = models.ForeignKey("parts.SparePart", on_delete=models.PROTECT, related_name="+")
    project = models.ForeignKey("projects.Project", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    attempts = models.PositiveSmallIntegerField(default=0)
    error_code = models.CharField(max_length=60, blank=True)
    error_message = models.CharField(max_length=500, blank=True)
    input_hash = models.CharField(max_length=64, blank=True)
    sources = models.JSONField(default=dict, blank=True)  # feasibility / cost comparison / recommendation / Phase 2 ids and versions
    result = models.JSONField(default=dict, blank=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["run", "part__part_number"]
        constraints = [models.UniqueConstraint(fields=["run", "part"], name="uniq_assessment_run_item")]


class AssessmentSchedule(TenantOwnedModel):
    """Quarterly schedule of a company's assessment run (one per company). `run_scheduled_assessments` starts a due run;
    at most one scheduled run per company and quarter."""

    enabled = models.BooleanField(default=False)
    months = models.JSONField(default=list)  # e.g. [1, 4, 7, 10]
    day_of_month = models.PositiveSmallIntegerField(default=1)
    ai_tier = models.CharField(max_length=10, blank=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["tenant"], name="uniq_assessment_schedule_per_company")]


# ------------------------------------------------------------------ CN-007 role-based AI access (AI_CLIENT_ACCESS_ENABLED)

class ClientAIWorkspace(TenantOwnedModel):
    """Whether a client company's "My Parts Intelligence" workspace is switched on (one row per client company). Set by
    the Aries Admin; switching on is refused unless the company is listed in AI_CLIENT_SHARING_COMPANIES."""

    enabled = models.BooleanField(default=False)
    changed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    note = models.CharField(max_length=300, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["tenant"], name="uniq_client_ai_workspace_per_company")]


class AIWorkspaceMember(TenantOwnedModel):
    """A Client Admin's decision on one member's access to the client workspace. Without a row the role default applies
    (Client Engineer allowed; Procurement, Client User and Auditor not allowed). Client Admins always have access."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    allowed = models.BooleanField(default=False)
    changed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["tenant", "user"], name="uniq_ai_workspace_member")]


class SharedAssessment(TenantOwnedModel):
    """A frozen, client-safe snapshot of one reviewed recommendation version of a part, approved by an Aries Engineer for
    disclosure to the client company (information sharing only: never an approval, publication, eligibility or release,
    OQ-35/OQ-36). The snapshot and its sources never change after creation (database trigger); only the status moves
    forward: approved -> shared -> withdrawn / superseded. Every change is a DisclosureEvent."""

    class Status(models.TextChoices):
        APPROVED = "approved", "Approved for client sharing"
        SHARED = "shared", "Shared with client"
        WITHDRAWN = "withdrawn", "Withdrawn"
        SUPERSEDED = "superseded", "Superseded by a newer shared result"

    part = models.ForeignKey("parts.SparePart", on_delete=models.PROTECT, related_name="+")
    project = models.ForeignKey("projects.Project", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    recommendation = models.ForeignKey(Recommendation, on_delete=models.PROTECT, related_name="+")
    recommendation_version = models.PositiveIntegerField()
    feasibility_version = models.PositiveIntegerField()
    cost_comparison_version = models.PositiveIntegerField(null=True, blank=True)
    snapshot = models.JSONField(default=dict)  # whitelisted client-safe content (apps.intelligence.disclosure.client_safe)
    released_prices = models.JSONField(default=list, blank=True)  # explicitly released client-facing quotes, never internal costs
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.APPROVED)
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    approved_by_name = models.CharField(max_length=150, blank=True)
    shared_at = models.DateTimeField(null=True, blank=True)
    shared_by_name = models.CharField(max_length=150, blank=True)
    withdrawn_at = models.DateTimeField(null=True, blank=True)
    withdrawn_reason = models.CharField(max_length=500, blank=True)

    class Meta:
        ordering = ["-created_at"]
        # one approval waiting to be shared and one shared result per part (sharing a newer one supersedes the older)
        constraints = [models.UniqueConstraint(fields=["part"], condition=models.Q(status="approved"), name="one_approved_disclosure_per_part"),
                       models.UniqueConstraint(fields=["part"], condition=models.Q(status="shared"), name="one_shared_disclosure_per_part")]


class DisclosureEvent(TenantOwnedModel):
    """Append-only history of a shared assessment (approved, shared, withdrawn, superseded)."""

    shared = models.ForeignKey(SharedAssessment, on_delete=models.PROTECT, related_name="events")
    part = models.ForeignKey("parts.SparePart", on_delete=models.PROTECT, related_name="+")
    event = models.CharField(max_length=20)
    note = models.CharField(max_length=500, blank=True)
    actor_name = models.CharField(max_length=150, blank=True)

    class Meta:
        ordering = ["created_at"]
