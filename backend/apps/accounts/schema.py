"""OpenAPI description of the tenant-aware bearer authentication."""
from drf_spectacular.contrib.rest_framework_simplejwt import SimpleJWTScheme


class TenantJWTScheme(SimpleJWTScheme):
    target_class = "apps.accounts.authentication.TenantJWTAuthentication"
    name = "tenantBearer"

    def get_security_definition(self, auto_schema):
        definition = super().get_security_definition(auto_schema)
        definition["description"] = ("Access token from POST /api/v1/auth/token/. Each token is bound to one "
                                     "membership and tenant; the tenant is never taken from request data.")
        return definition
