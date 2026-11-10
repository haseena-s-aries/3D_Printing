"""Base view set for tenant-owned resources.

Three layers of isolation apply to every request:
1. TenantJWTAuthentication resolves the tenant from the verified membership and sets the RLS context.
2. Querysets are always filtered by request.tenant (application layer).
3. PostgreSQL forced row-level security (database layer), so a missed filter still leaks nothing.
Objects of other tenants therefore return 404, never 403, to avoid revealing that they exist.
"""
from rest_framework import mixins, viewsets

from apps.audit.service import record

from .permissions import HasCapability


class TenantModelViewSet(mixins.CreateModelMixin, mixins.RetrieveModelMixin, mixins.UpdateModelMixin,
                         mixins.ListModelMixin, viewsets.GenericViewSet):
    """No DELETE by default: business records are retired by status, not removed."""

    permission_classes = [HasCapability]
    capabilities: dict[str, str] = {}
    model = None
    audit_type = ""

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):  # OpenAPI schema generation
            return self.model.objects.none()
        return self.model.objects.filter(tenant=self.request.tenant)

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx["tenant"] = getattr(self.request, "tenant", None)
        return ctx

    def perform_create(self, serializer):
        obj = serializer.save(tenant=self.request.tenant, created_by=self.request.user)
        record(self.request, f"{self.audit_type}.created", obj=obj)

    def perform_update(self, serializer):
        changed = sorted(serializer.validated_data.keys())
        obj = serializer.save()
        record(self.request, f"{self.audit_type}.updated", obj=obj, data={"fields": changed})


class TenantScopedRelatedField:
    """Serializer mixin helper: restrict related-object choices to the request tenant."""

    @staticmethod
    def limit(serializer, field_name, model):
        tenant = serializer.context.get("tenant")
        field = serializer.fields.get(field_name)
        if field is not None and hasattr(field, "queryset"):
            field.queryset = model.objects.filter(tenant=tenant) if tenant else model.objects.none()
