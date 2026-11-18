"""Quotations to the client (decision of 18 Nov 2026).

After the cost estimate and the route choice, the Aries Admin or Manager sends the client one price for the chosen method,
with the delivery time and validity. The client sees only the method, price, delivery days, validity and Aries' note;
never the cost breakdown, rates, margin, manpower or the other routes. The client accepts or rejects (with a reason).
A manufacturing order is released for production only after the client accepted the quotation for the chosen route.

Events in the request history: quotation_sent, quotation_withdrawn, quotation_accepted, quotation_rejected (the client
sees them; the message carries only the client-facing figures).
"""
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from apps.audit.service import record
from apps.core.exceptions import DomainError
from apps.tenancy.models import Role

from . import services as svc
from .models import ClientRequest, Quotation, RequestEvent

Q = Quotation.Status
CLIENT_DECIDERS = {Role.CLIENT_ADMIN, Role.CLIENT_ENGINEER, Role.PROCUREMENT}


def current(obj: ClientRequest) -> Quotation | None:
    """The quotation in force: the newest one that was not replaced."""
    return obj.quotations.exclude(status=Q.SUPERSEDED).select_related("sent_by", "decided_by").order_by("-number").first()


def accepted_for_route(obj: ClientRequest, route: str) -> bool:
    q = current(obj)
    return q is not None and q.status == Q.ACCEPTED and q.route == route


def _event(request, obj, event: str, side: str, message: str) -> None:
    RequestEvent.objects.create(tenant=obj.tenant, created_by=request.user, request=obj, event=event, from_status=obj.status,
                                to_status=obj.status, author=request.user, author_side=side, message=message[:2000])


def _money(q: Quotation) -> str:
    return f"{q.currency} {q.price:,.2f}"


def send(request, obj: ClientRequest, *, price, delivery_days, valid_until=None, note: str = "") -> Quotation:
    """Aries Admin or Manager: quote the route chosen in the cost estimate. Inside the client's tenant context."""
    from apps.intelligence.estimate import chosen_route

    if obj.status not in svc.OPEN or obj.status == svc.S.SUBMITTED:
        raise DomainError("transition_not_allowed", "Acknowledge the request first; a closed request cannot be quoted.", http_status=409)
    if obj.status in ("released", "in_production", "inspected"):
        raise DomainError("transition_not_allowed", "The order is already released; the quotation can no longer change.", http_status=409)
    route = chosen_route(obj)
    if route is None:
        raise DomainError("route_not_chosen", "Choose the route in the cost estimate before sending a quotation.", http_status=409)
    try:
        amount = Decimal(str(price)).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError, ValueError):
        raise DomainError("invalid_price", "Enter the price as a number.", http_status=400)
    if not Decimal("0") < amount < Decimal("100000000"):
        raise DomainError("invalid_price", "Enter a price above zero.", http_status=400)
    try:
        days = int(delivery_days)
    except (TypeError, ValueError):
        raise DomainError("invalid_days", "Enter the delivery time in days.", http_status=400)
    if not 1 <= days <= 730:
        raise DomainError("invalid_days", "Delivery time must be between 1 and 730 days.", http_status=400)
    if valid_until in (None, ""):
        until = date.today() + timedelta(days=14)
    else:
        try:
            until = valid_until if isinstance(valid_until, date) else date.fromisoformat(str(valid_until))
        except ValueError:
            raise DomainError("invalid_date", "Enter the validity date as YYYY-MM-DD.", http_status=400)
    if until < date.today():
        raise DomainError("invalid_date", "The validity date cannot be in the past.", http_status=400)
    with transaction.atomic():
        obj.quotations.filter(status__in=[Q.SENT, Q.ACCEPTED, Q.REJECTED, Q.WITHDRAWN]).update(status=Q.SUPERSEDED)
        n = (obj.quotations.aggregate(m=Max("number"))["m"] or 0) + 1
        q = Quotation.objects.create(tenant=obj.tenant, created_by=request.user, request=obj, number=n,
                                     estimate_id=None, route=route["route"], method=route["label"], price=amount,
                                     currency=route.get("currency") or "USD", delivery_days=days, valid_until=until,
                                     note=(note or "").strip()[:1000], sent_by=request.user)
        msg = (f"Quotation {n}: {q.method}, {_money(q)}, delivery in {days} days, valid until {until:%d %b %Y}."
               + (f" {q.note}" if q.note else ""))
        _event(request, obj, "quotation_sent", RequestEvent.Side.OPERATOR, msg)
    record(request, "quotation.sent", obj=q, tenant=obj.tenant, data={"request": obj.reference, "number": n, "route": q.route,
                                                                       "price": str(amount), "currency": q.currency, "days": days})
    svc.sync_envelope(obj)
    svc.notify_client(obj, "quotation_sent", body=msg[:300])
    return q


def withdraw(request, obj: ClientRequest, reason: str = "") -> Quotation:
    q = current(obj)
    if q is None or q.status != Q.SENT:
        raise DomainError("no_open_quotation", "There is no quotation waiting for the client.", http_status=409)
    q.status = Q.WITHDRAWN
    q.save(update_fields=["status", "updated_at"])
    _event(request, obj, "quotation_withdrawn", RequestEvent.Side.OPERATOR,
           f"Quotation {q.number} withdrawn." + (f" {reason.strip()}" if reason.strip() else ""))
    record(request, "quotation.withdrawn", obj=q, tenant=obj.tenant, data={"request": obj.reference, "number": q.number})
    svc.notify_client(obj, "quotation_withdrawn", body=reason.strip()[:300])
    return q


def decide(request, obj: ClientRequest, decision: str, note: str = "") -> Quotation:
    """The client accepts or rejects the quotation in force (inside the client's own context)."""
    m = getattr(request, "membership", None)
    if m is None or (m.role not in CLIENT_DECIDERS and obj.requested_by_id != request.user.pk):
        raise DomainError("permission_denied", "Only the requester, a Client Administrator, Engineer or Procurement can decide.", http_status=403)
    if decision not in ("accept", "reject"):
        raise DomainError("invalid_decision", "Choose accept or reject.", http_status=400)
    q = current(obj)
    if q is None or q.status != Q.SENT:
        raise DomainError("no_open_quotation", "There is no quotation waiting for your decision.", http_status=409)
    if decision == "accept" and q.valid_until < date.today():
        raise DomainError("quotation_expired", "This quotation has expired. Please ask Aries for a new one.", http_status=409)
    if decision == "reject" and not (note or "").strip():
        raise DomainError("reason_required", "Please tell Aries why (for example price or delivery time).", http_status=400)
    q.status = Q.ACCEPTED if decision == "accept" else Q.REJECTED
    q.decided_by, q.decided_at, q.client_note = request.user, timezone.now(), (note or "").strip()[:1000]
    q.save(update_fields=["status", "decided_by", "decided_at", "client_note", "updated_at"])
    event = "quotation_accepted" if decision == "accept" else "quotation_rejected"
    _event(request, obj, event, RequestEvent.Side.CLIENT,
           f"Quotation {q.number} {'accepted' if decision == 'accept' else 'rejected'} ({q.method}, {_money(q)})."
           + (f" {q.client_note}" if q.client_note else ""))
    record(request, f"quotation.{decision}ed", obj=q, tenant=obj.tenant, data={"request": obj.reference, "number": q.number})
    svc.sync_envelope(obj)
    svc.notify_operators(obj, event, body=q.client_note[:300])
    return q


def client_view(q: Quotation | None) -> dict | None:
    """Only what the client may see."""
    if q is None:
        return None
    return {"number": q.number, "method": q.method, "price": str(q.price), "currency": q.currency, "delivery_days": q.delivery_days,
            "valid_until": q.valid_until, "note": q.note, "status": q.status, "status_label": q.get_status_display(),
            "expired": q.status == Q.SENT and q.valid_until < date.today(), "sent_at": q.created_at,
            "decided_at": q.decided_at, "client_note": q.client_note}


def operator_view(q: Quotation | None) -> dict | None:
    if q is None:
        return None
    return {**client_view(q), "route": q.route, "sent_by": q.sent_by.email if q.sent_by_id else "",
            "decided_by": q.decided_by.email if q.decided_by_id else ""}
