"""API contract: the OpenAPI schema generates, validates against the OpenAPI spec, and documents the v1 surface."""
from drf_spectacular.generators import SchemaGenerator
from drf_spectacular.validation import validate_schema

EXPECTED_PATHS = {
    "/api/v1/auth/token/": {"post"},
    "/api/v1/auth/refresh/": {"post"},
    "/api/v1/auth/me/": {"get"},
    "/api/v1/clients/": {"get", "post"},
    "/api/v1/clients/{id}/members/": {"get", "post"},
    "/api/v1/users/": {"get", "post"},
    "/api/v1/projects/": {"get", "post"},
    "/api/v1/parts/": {"get", "post"},
    "/api/v1/parts/{id}/": {"get", "patch", "put"},
    "/api/v1/passports/": {"get", "post"},
    "/api/v1/passports/{id}/revisions/": {"get", "post"},
    "/api/v1/passports/{id}/revisions/{rev}/": {"get", "patch"},
    "/api/v1/passports/{id}/revisions/{rev}/approve/": {"post"},
    "/api/v1/files/": {"get", "post"},
    "/api/v1/files/{id}/versions/": {"get", "post"},
    "/api/v1/files/{id}/versions/{number}/download-link/": {"post"},
    "/api/v1/downloads/{token}/": {"get"},
    "/api/v1/audit-events/": {"get"},
}


def test_openapi_schema_valid_and_complete(db):
    schema = SchemaGenerator().get_schema(request=None, public=True)
    validate_schema(schema)
    paths = schema["paths"]
    for path, methods in EXPECTED_PATHS.items():
        assert path in paths, f"missing {path}"
        assert methods <= set(paths[path]), f"{path}: {methods - set(paths[path])} missing"
    # no DELETE on business records (retired by status, never removed)
    for path, ops in paths.items():
        if path.startswith(("/api/v1/parts", "/api/v1/passports", "/api/v1/files", "/api/v1/audit")):
            assert "delete" not in ops, path
    assert schema["components"]["securitySchemes"], "bearer auth must be documented"
