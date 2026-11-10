import uuid

from django.db.models import Q
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import mixins, serializers, viewsets

from apps.tenancy.models import Tenant
from apps.tenancy.permissions import HasCapability

from .models import AuditEvent


class AuditEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = AuditEvent
        fields = ["id", "created_at", "actor_email", "actor_role", "action", "object_type", "object_id", "request_id", "data"]


def _is_uuid(value: str) -> bool:
    try:
        uuid.UUID(str(value))
        return True
    except ValueError:
        return False


@extend_schema_view(list=extend_schema(parameters=[
    OpenApiParameter("action", str), OpenApiParameter("object_type", str), OpenApiParameter("object_id", str),
    OpenApiParameter("client", str, description="Only events about this client company (id)."),
    OpenApiParameter("exclude_views", bool, description="Leave out record-view events (actions ending in _viewed)."),
]))
class AuditEventViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    """Read-only, tenant-scoped audit trail."""

    serializer_class = AuditEventSerializer
    permission_classes = [HasCapability]
    capabilities = {"list": "audit.view"}

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return AuditEvent.objects.none()
        qs = AuditEvent.objects.filter(tenant=self.request.tenant)
        p = self.request.query_params
        for field in ("action", "object_type", "object_id"):
            value = p.get(field)
            if value:
                qs = qs.filter(**{field: value})
        if p.get("client"):
            # Events in this organisation's own trail about one client company (operator side: the company record
            # itself, plus membership, assignment and invitation events tagged with the company). Same tenant scope.
            client = Tenant.objects.filter(pk=p["client"], kind=Tenant.Kind.CLIENT).first() if _is_uuid(p["client"]) else None
            if client is None:
                return qs.none()
            qs = qs.filter(Q(object_type="tenant", object_id=str(client.pk)) | Q(data__client=client.slug))
        if p.get("exclude_views") in ("1", "true"):
            qs = qs.exclude(action__endswith="_viewed")
        return qs
