from rest_framework import serializers

from apps.core.exceptions import DomainError
from apps.tenancy.viewsets import TenantModelViewSet

from .models import Project
from .scoping import allowed_project_ids, restrict


class ProjectSerializer(serializers.ModelSerializer):
    class Meta:
        model = Project
        fields = ["id", "code", "name", "description", "status", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]

    def validate_code(self, value):
        tenant = self.context.get("tenant")
        qs = Project.objects.filter(tenant=tenant, code__iexact=value)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("A project with this code already exists.")
        return value


class ProjectViewSet(TenantModelViewSet):
    model = Project
    serializer_class = ProjectSerializer
    audit_type = "project"
    capabilities = {"list": "projects.view", "retrieve": "projects.view", "create": "projects.manage",
                    "update": "projects.manage", "partial_update": "projects.manage"}

    def get_queryset(self):
        # Project-limited Aries staff see only their assigned projects (CN-002 D4).
        return restrict(self.request, super().get_queryset(), "id")

    def perform_create(self, serializer):
        if allowed_project_ids(self.request) is not None:
            raise DomainError("project_scope", "Your assignment is limited to specific projects; ask an Aries Admin to "
                              "create the project and assign it to you.", http_status=403)
        super().perform_create(serializer)
