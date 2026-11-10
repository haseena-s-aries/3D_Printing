"""Write audit events. Must run inside the tenant's row-level security context."""
from apps.core.middleware import current_request_id

from .models import AuditEvent

SENSITIVE_KEYS = {"password", "token", "access", "refresh", "secret"}


def _clean(data):
    return {k: ("[redacted]" if k.lower() in SENSITIVE_KEYS else v) for k, v in (data or {}).items()}


def record(request, action, *, obj=None, obj_type="", obj_id="", data=None, actor=None, tenant=None):
    membership = getattr(request, "membership", None) if request is not None else None
    tenant = tenant or (membership.tenant if membership else None)
    if tenant is None:
        raise ValueError("audit event requires a tenant")
    actor = actor or (request.user if request is not None and getattr(request.user, "is_authenticated", False) else None)
    if obj is not None:
        obj_type = obj_type or obj._meta.model_name
        obj_id = obj_id or str(obj.pk)
    ip = None
    if request is not None:
        ip = (request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")[0].strip() or request.META.get("REMOTE_ADDR")) or None
    return AuditEvent.objects.create(
        tenant=tenant, actor=actor, actor_email=getattr(actor, "email", "") or "",
        actor_role=membership.role if membership else "", action=action,
        object_type=obj_type, object_id=str(obj_id or ""), request_id=current_request_id(),
        ip_address=ip, data=_clean(data),
    )
