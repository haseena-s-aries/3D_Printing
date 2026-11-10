"""Client service requests (manufacturing enquiries and requests, 3D scanning / digitisation requests),
their history, attachments, the operator intake envelope and in-app notifications.

Tenant ownership and row-level security:
- ClientRequest, RequestEvent and RequestAttachment belong to the CLIENT tenant (forced RLS, tenant policy).
- RequestEnvelope belongs to the OPERATOR tenant (forced RLS): a minimal summary written when a client submits, so
  operator staff can see incoming work without any cross-tenant query. Opening the request itself requires an
  active operator-staff assignment (membership) to that client and runs inside the client's tenant context.
- Notification has no tenant column; a per-user RLS policy (app.user_id) lets each user read only their own rows.

Business gates: a request for a part that is not published AND manufacturing-eligible is always an ENQUIRY.
Manufacturing requests can be acknowledged but never reviewed, released or produced here (OQ-36 stays closed).
"""
from django.conf import settings
from django.db import models

from apps.core.models import TimeStampedModel
from apps.tenancy.owned import TenantOwnedModel


class ClientRequest(TenantOwnedModel):
    class Kind(models.TextChoices):
        ENQUIRY = "enquiry", "Manufacturing enquiry"
        MANUFACTURING = "manufacturing_request", "Manufacturing request"
        DIGITISATION = "digitisation", "3D scanning / digitisation request"
        # CN-007 (AI_CLIENT_ACCESS_ENABLED): a client asks Aries Engineering to assess or reassess a part.
        ASSESSMENT = "assessment", "AI assessment request"

    class Status(models.TextChoices):
        SUBMITTED = "submitted", "Submitted"
        ACKNOWLEDGED = "acknowledged", "Acknowledged"
        INFORMATION_REQUESTED = "information_requested", "Information requested"
        INFORMATION_PROVIDED = "information_provided", "Information provided"
        ANSWERED = "answered", "Answered"
        SCHEDULED = "scheduled", "Scheduled"
        IN_PROGRESS = "in_progress", "In progress"
        COMPLETED = "completed", "Completed"
        CLOSED = "closed", "Closed"
        DECLINED = "declined", "Declined"
        WITHDRAWN = "withdrawn", "Withdrawn"

    class Priority(models.TextChoices):
        ROUTINE = "routine", "Routine"
        URGENT = "urgent", "Urgent (breakdown)"

    class Reason(models.TextChoices):
        OBSOLETE = "obsolete", "Obsolete or no longer supplied"
        LEAD_TIME = "long_lead_time", "Long lead time"
        FAILURE = "failure", "Failure or breakdown"
        OTHER = "other", "Other"

    reference = models.CharField(max_length=30)
    kind = models.CharField(max_length=24, choices=Kind.choices)
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.SUBMITTED)
    priority = models.CharField(max_length=12, choices=Priority.choices, default=Priority.ROUTINE)
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")

    # Manufacturing enquiry / request: the part and the exact passport revision at submission
    part = models.ForeignKey("parts.SparePart", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    passport = models.ForeignKey("passports.DigitalPassport", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    passport_revision_number = models.PositiveIntegerField(null=True, blank=True)
    part_number = models.CharField(max_length=80, blank=True)
    part_name = models.CharField(max_length=200, blank=True)
    publication_state_at_submission = models.CharField(max_length=24, blank=True)
    eligibility_at_submission = models.CharField(max_length=40, blank=True)
    quantity = models.PositiveIntegerField(null=True, blank=True)
    required_date = models.DateField(null=True, blank=True)
    delivery_location = models.CharField(max_length=300, blank=True)
    services = models.JSONField(default=list, blank=True)
    remarks = models.TextField(blank=True)
    client_reference = models.CharField(max_length=80, blank=True)
    # Material change on a manufacturing enquiry (CN-003, BR-033). The original part and passport are never changed;
    # a proposed material is linked to a separate cloned part held for Aries review. Suitability is never assumed.
    material_option = models.CharField(max_length=10, blank=True, choices=[("original", "Original material"),
                                                                          ("proposed", "Different material proposed")])
    original_material = models.CharField(max_length=120, blank=True)
    proposed_material = models.CharField(max_length=120, blank=True)
    material_change_reason = models.TextField(blank=True)
    linked_part = models.ForeignKey("parts.SparePart", null=True, blank=True, on_delete=models.PROTECT, related_name="+",
                                    help_text="Clone of `part` carrying the proposed material")
    # Client-visible, non-confidential progress of Aries' internal job preparation (CN-004 J6). The job sheet itself is
    # internal to Aries and unreadable from the client portal.
    job_progress = models.CharField(max_length=16, blank=True, choices=[("preparing", "Manufacturing documentation in preparation"),
                                                                        ("cancelled", "Manufacturing preparation stopped")])

    # Digitisation (3D scanning) request
    site_location = models.CharField(max_length=300, blank=True)
    equipment = models.CharField(max_length=300, blank=True)
    part_description = models.TextField(blank=True)
    reason = models.CharField(max_length=24, choices=Reason.choices, blank=True)
    preferred_date = models.DateField(null=True, blank=True)
    contact_name = models.CharField(max_length=150, blank=True)
    contact_phone = models.CharField(max_length=60, blank=True)
    contact_email = models.EmailField(blank=True)
    quotation_reference = models.CharField(max_length=80, blank=True, help_text="Optional reference to an offline quotation")
    project = models.ForeignKey("projects.Project", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_part = models.ForeignKey("parts.SparePart", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    # Scanning-to-passport handover (post-UAT D-15): the responsible Aries Engineer, and when the scanned part was handed over
    # into the passport workflow (its passport then carries the engineering record; deliverables are listed in ScanDeliverable).
    assigned_to = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    assigned_at = models.DateTimeField(null=True, blank=True)
    handed_over_at = models.DateTimeField(null=True, blank=True)
    handed_over_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    handover_passport = models.ForeignKey("passports.DigitalPassport", null=True, blank=True, on_delete=models.PROTECT, related_name="+")

    acknowledged_at = models.DateTimeField(null=True, blank=True)
    acknowledged_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    closed_reason = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [models.UniqueConstraint(fields=["tenant", "reference"], name="uniq_request_reference_per_tenant")]

    def __str__(self):
        return self.reference


class RequestEvent(TenantOwnedModel):
    """Append-only history of a request; every entry is visible to the client (there are no internal notes)."""

    class Side(models.TextChoices):
        CLIENT = "client", "Client"
        OPERATOR = "operator", "Operator"

    request = models.ForeignKey(ClientRequest, on_delete=models.CASCADE, related_name="events")
    event = models.CharField(max_length=40)
    from_status = models.CharField(max_length=24, blank=True)
    to_status = models.CharField(max_length=24, blank=True)
    message = models.TextField(blank=True)
    author = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    author_side = models.CharField(max_length=10, choices=Side.choices)

    class Meta:
        ordering = ["created_at"]


class RequestAttachment(TenantOwnedModel):
    """Photograph or supporting document of a request, validated like engineering uploads; original kept unchanged."""

    request = models.ForeignKey(ClientRequest, on_delete=models.CASCADE, related_name="attachments")
    original_filename = models.CharField(max_length=255)
    kind = models.CharField(max_length=8)
    detected_format = models.CharField(max_length=60)
    content_type = models.CharField(max_length=80)
    size_bytes = models.BigIntegerField()
    sha256 = models.CharField(max_length=64)
    storage_key = models.CharField(max_length=400, unique=True)

    class Meta:
        ordering = ["created_at"]


class ScanDeliverable(TenantOwnedModel):
    """One deliverable of a scanning / digitisation request (append-only): scan source data, CAD model, drawing, report or
    photographs, optionally pinned to an engineering file version of the created part. Recording a deliverable states what was
    produced; it does not verify or approve it (scan meshes and point clouds are not production-ready CAD)."""

    class Kind(models.TextChoices):
        SCAN_DATA = "scan_data", "Scan source data (mesh / point cloud)"
        CAD_MODEL = "cad_model", "CAD model (STEP)"
        DRAWING = "drawing", "Engineering drawing"
        REPORT = "report", "Scan / inspection report"
        PHOTOS = "photos", "Photographs"
        OTHER = "other", "Other"

    request = models.ForeignKey(ClientRequest, on_delete=models.PROTECT, related_name="deliverables")
    kind = models.CharField(max_length=12, choices=Kind.choices)
    title = models.CharField(max_length=200)
    file = models.ForeignKey("files.EngineeringFile", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    file_version = models.PositiveIntegerField(null=True, blank=True)
    note = models.CharField(max_length=500, blank=True)

    class Meta:
        ordering = ["created_at"]


class RequestEnvelope(TenantOwnedModel):
    """Operator-tenant summary of a client request (operator intake queue). Holds no documents or remarks."""

    client_tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.PROTECT, related_name="+")
    client_name = models.CharField(max_length=200)
    request_id = models.UUIDField(unique=True)
    reference = models.CharField(max_length=30)
    kind = models.CharField(max_length=24)
    status = models.CharField(max_length=24)
    priority = models.CharField(max_length=12)
    part_number = models.CharField(max_length=80, blank=True)
    part_name = models.CharField(max_length=200, blank=True)
    quantity = models.PositiveIntegerField(null=True, blank=True)
    required_date = models.DateField(null=True, blank=True)
    submitted_at = models.DateTimeField()
    # Platform-wide intake number (post-UAT D-06): client references are numbered per company (MR-2026-00001 exists in many
    # companies), so the Aries intake identifies each request by this unique number; the client reference never changes.
    intake_number = models.CharField(max_length=20, blank=True)
    # D-05: the project and responsible engineer, so the intake list applies the same project rule as opening the request
    project_ref = models.UUIDField(null=True, blank=True)
    assigned_to = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        ordering = ["-submitted_at"]
        constraints = [models.UniqueConstraint(fields=["intake_number"], condition=~models.Q(intake_number=""),
                                               name="uniq_request_intake_number")]


class Notification(TimeStampedModel):
    """In-app notification for one user. Readable only by its recipient (per-user RLS on app.user_id)."""

    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    title = models.CharField(max_length=200)
    body = models.CharField(max_length=500, blank=True)
    link = models.CharField(max_length=300, blank=True)
    organisation_name = models.CharField(max_length=200, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["recipient", "read_at"])]
