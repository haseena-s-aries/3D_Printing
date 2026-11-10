"""Aries-confidential passport content (post-UAT D-18). R-L2 holds the Aries manufacturing specification (BR-026/BR-041),
the manufacturing process and the manufacturing solution: never shown to client roles, exactly as the client-facing report
already excludes them. Engineering notes keep their own capability rule (passports.view_engineering_notes)."""
from apps.tenancy.permissions import has_capability

ARIES_ONLY_RL2 = ("manufacturing_spec", "manufacturing_process", "manufacturing_solution")
ARIES_ONLY_FIELDS = tuple(f"rl2.{k}" for k in ARIES_ONLY_RL2)


def aries_reader(request) -> bool:
    """Aries engineering roles that may read the manufacturing specification."""
    return request is not None and (has_capability(request, "reports.view_internal") or has_capability(request, "passports.edit_draft"))


def is_aries_only(field: str) -> bool:
    return field in ARIES_ONLY_FIELDS or field.startswith(tuple(f + "." for f in ARIES_ONLY_FIELDS))


def client_content(content: dict) -> dict:
    """A copy of revision content without the Aries-only R-L2 entries."""
    out = dict(content or {})
    if isinstance(out.get("rl2"), dict):
        out["rl2"] = {k: v for k, v in out["rl2"].items() if k not in ARIES_ONLY_RL2}
    return out
