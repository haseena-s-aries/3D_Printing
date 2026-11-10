from django.db import models

from apps.tenancy.owned import TenantOwnedModel


class Project(TenantOwnedModel):
    """Digitalisation project for a client (FR-03)."""

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        ON_HOLD = "on_hold", "On hold"
        CLOSED = "closed", "Closed"

    code = models.CharField(max_length=40)
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)

    class Meta:
        ordering = ["-created_at"]
        constraints = [models.UniqueConstraint(fields=["tenant", "code"], name="uniq_project_code_per_tenant")]

    def __str__(self):
        return f"{self.code} {self.name}"


class EngineerAccess(TenantOwnedModel):
    """Scope of an Aries staff assignment inside this client (CN-002 D4). No row means company-wide, which is how
    every assignment that existed before project scoping keeps exactly its previous access."""

    class Scope(models.TextChoices):
        COMPANY = "company", "All projects of the company"
        PROJECTS = "projects", "Assigned projects only"

    user = models.ForeignKey("accounts.User", on_delete=models.CASCADE, related_name="+")
    scope = models.CharField(max_length=16, choices=Scope.choices, default=Scope.COMPANY)
    updated_by = models.ForeignKey("accounts.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["tenant", "user"], name="uniq_engineer_access_per_tenant")]


class ProjectAssignment(TenantOwnedModel):
    """An Aries staff member assigned to one scanning/digitisation project (used when EngineerAccess.scope=projects)."""

    project = models.ForeignKey(Project, on_delete=models.PROTECT, related_name="assignments")
    user = models.ForeignKey("accounts.User", on_delete=models.CASCADE, related_name="+")
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["project", "user"], name="uniq_project_assignment")]
