"""Archive and restore single items (decision of 19 Nov 2026): spare parts (with their passport) and client requests.

Nothing is erased: the item is hidden from every list, count and dashboard (apps.core.archive), the audit trail keeps
everything, and the Aries Admin or Manager can restore it from the Archive screen. A part's number is free for a new part
while it is archived. Whole test companies are removed differently (apps.tenancy.purge).
"""
from django.utils import timezone

from apps.audit.service import record
from apps.core.exceptions import DomainError

from .context import tenant_context
from .models import Tenant

IN_PRODUCTION = ("released", "in_production", "inspected")


def _mirror_to_intake_queue(request_id, archived_at) -> None:
    """The request's summary lives in the Aries organisation (its own row-level security): hide or show it there too."""
    from apps.servicerequests.models import RequestEnvelope

    operator = Tenant.objects.filter(kind=Tenant.Kind.OPERATOR).order_by("created_at").first()
    if operator is not None:
        with tenant_context(operator):
            RequestEnvelope.all_objects.filter(request_id=request_id).update(archived_at=archived_at)


def archive_part(request, part) -> object:
    """Inside the part's company context. Refused while the part has open requests or a published passport."""
    from apps.passports.models import DigitalPassport
    from apps.servicerequests.models import ClientRequest
    from apps.servicerequests.services import OPEN

    if part.archived_at:
        raise DomainError("already_archived", "This spare part is already archived.", http_status=409)
    open_requests = ClientRequest.objects.filter(part=part, status__in=OPEN).count()
    if open_requests:
        raise DomainError("open_requests", f"This part has {open_requests} open request(s). Close or archive them first.", http_status=409)
    passport = DigitalPassport.all_objects.filter(part=part).first()
    if passport is not None and passport.publication_state == DigitalPassport.PublicationState.PUBLISHED:
        raise DomainError("published", "This part's passport is published. Unpublish it first.", http_status=409)
    part.archived_at, part.archived_by = timezone.now(), request.user
    part.save(update_fields=["archived_at", "archived_by", "updated_at"])
    record(request, "spare_part.archived", obj=part, tenant=part.tenant, data={"part_number": part.part_number, "name": part.name})
    return part


def archive_request(request, obj) -> object:
    """Inside the request's company context. Not while the order is released or in production."""
    if obj.archived_at:
        raise DomainError("already_archived", "This request is already archived.", http_status=409)
    if obj.status in IN_PRODUCTION:
        raise DomainError("in_production", "The order is released or in production. Finish or close it first.", http_status=409)
    now = timezone.now()
    obj.archived_at, obj.archived_by = now, request.user
    obj.save(update_fields=["archived_at", "archived_by", "updated_at"])
    _mirror_to_intake_queue(obj.pk, now)
    record(request, "request.archived", obj=obj, tenant=obj.tenant, data={"reference": obj.reference})
    return obj


def archived_items() -> list[dict]:
    """Every archived part and request of every company (Aries Admin or Manager)."""
    from apps.parts.models import SparePart
    from apps.servicerequests.models import ClientRequest

    rows = []
    for t in Tenant.objects.filter(kind=Tenant.Kind.CLIENT).order_by("name"):
        with tenant_context(t):
            for p in SparePart.all_objects.filter(archived_at__isnull=False).select_related("archived_by"):
                rows.append({"kind": "part", "id": str(p.pk), "client_id": str(t.pk), "client_name": t.name, "title": f"{p.part_number} · {p.name}",
                             "archived_at": p.archived_at, "archived_by": p.archived_by.email if p.archived_by_id else ""})
            for r in ClientRequest.all_objects.filter(archived_at__isnull=False).select_related("archived_by"):
                rows.append({"kind": "request", "id": str(r.pk), "client_id": str(t.pk), "client_name": t.name,
                             "title": f"{r.reference} · {r.part_number or r.part_name or r.get_kind_display()}",
                             "archived_at": r.archived_at, "archived_by": r.archived_by.email if r.archived_by_id else ""})
    return sorted(rows, key=lambda r: r["archived_at"], reverse=True)


def restore(request, kind: str, client: Tenant, item_id) -> None:
    from apps.parts.models import SparePart
    from apps.servicerequests.models import ClientRequest

    if client.kind != Tenant.Kind.CLIENT or client.status != Tenant.Status.ACTIVE:
        raise DomainError("not_found", "Company not found.", http_status=404)
    with tenant_context(client):
        if kind == "part":
            p = SparePart.all_objects.filter(pk=item_id, archived_at__isnull=False).first()
            if p is None:
                raise DomainError("not_found", "Archived part not found.", http_status=404)
            if SparePart.objects.filter(tenant=client, part_number=p.part_number).exists():
                raise DomainError("number_in_use", f"Part number {p.part_number} is used by another part now. Rename that one first.", http_status=409)
            p.archived_at, p.archived_by = None, None
            p.save(update_fields=["archived_at", "archived_by", "updated_at"])
            record(request, "spare_part.restored", obj=p, tenant=client, data={"part_number": p.part_number})
        elif kind == "request":
            r = ClientRequest.all_objects.filter(pk=item_id, archived_at__isnull=False).first()
            if r is None:
                raise DomainError("not_found", "Archived request not found.", http_status=404)
            r.archived_at, r.archived_by = None, None
            r.save(update_fields=["archived_at", "archived_by", "updated_at"])
            _mirror_to_intake_queue(r.pk, None)
            record(request, "request.restored", obj=r, tenant=client, data={"reference": r.reference})
        else:
            raise DomainError("invalid_kind", "Choose part or request.", http_status=400)
