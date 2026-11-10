"""Aries Admin: read-only view of the platform configuration (feature switches, AI limits, access decisions).

Configuration is deployment-controlled, never changed from the application: in particular the objection-review authority
and the per-company file-access decisions must not be grantable by the person who benefits from them. Secrets (API keys,
database credentials) are never returned; only whether an AI provider is configured.
"""
from django.conf import settings
from drf_spectacular.utils import extend_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit.service import record

from . import admin_workspace
from .permissions import HasCapability

SWITCHES = [
    ("PUBLIC_REGISTRATION_ENABLED", "Public company registration"),
    ("CLIENT_PART_SUBMISSIONS_ENABLED", "Client spare-part submissions (CN-003)"),
    ("EDIT_REQUESTS_ENABLED", "Controlled edit requests (CN-006)"),
    ("INVENTORY_IMPORT_ENABLED", "Bulk inventory import (CN-007)"),
    ("PART_INTELLIGENCE_ENABLED", "Spare Parts Intelligence (CN-007)"),
    ("AI_CLIENT_ACCESS_ENABLED", "Client AI workspace and sharing (CN-007)"),
    ("ADMIN_THUMBNAIL_CONSENT_ENABLED", "Aries Admin thumbnails: client consent"),
    ("ADMIN_THUMBNAIL_PROVENANCE_ENABLED", "Aries Admin thumbnails: contract route"),
    ("ADMIN_WORKSPACE_ENABLED", "Aries Admin super-administrator workspaces (proposed OQ-37 revision)"),
    ("FOUR_ROLE_MODEL_ENABLED", "Four core roles with QA and feature permissions"),
]
OPEN_DECISIONS = [
    ("OQ-35", "Evidence levels and passport approval: approval and publication stay closed (409)."),
    ("OQ-36", "Manufacturing authorisation: manufacturing release stays closed (409)."),
    ("OQ-37", "Client consent, contract terms and notification for Aries access: revision proposed; confidential file content "
              "closed to the Aries Admin except where a documented decision is configured."),
    ("U9", "Contractual and privacy disclosure of Aries access to client companies before production."),
]


class PlatformSettingsView(APIView):
    permission_classes = [HasCapability]
    capabilities = {"get": "clients.manage"}

    @extend_schema(responses=dict)
    def get(self, request):
        s = settings
        body = {
            "switches": [{"key": k, "label": label, "on": bool(getattr(s, k, False))} for k, label in SWITCHES],
            "ai": {"provider": getattr(s, "AI_PROVIDER", "") or "off", "provider_configured": bool(getattr(s, "GEMINI_API_KEY", "")),
                   "allowed_companies": list(getattr(s, "AI_ALLOWED_COMPANIES", [])),
                   "client_sharing_companies": list(getattr(s, "AI_CLIENT_SHARING_COMPANIES", [])),
                   "calls_per_minute": getattr(s, "AI_CALLS_PER_MINUTE", 0), "calls_per_day": getattr(s, "AI_CALLS_PER_DAY", 0),
                   "daily_budget_usd": getattr(s, "AI_DAILY_BUDGET_USD", 0)},
            "access": {"file_access_decisions": [{"company": k, "decision": v} for k, v in admin_workspace.file_decisions().items()],
                       "objection_authority": getattr(s, "CONTRACT_OBJECTION_AUTHORITY", ""),
                       "objection_reviewers": list(getattr(s, "CONTRACT_OBJECTION_REVIEWERS", []))},
            "links": {"download_link_seconds": getattr(s, "DOWNLOAD_LINK_SECONDS", 0),
                      "admin_thumbnail_link_seconds": getattr(s, "ADMIN_THUMBNAIL_LINK_SECONDS", 0)},
            "open_decisions": [{"key": k, "text": t} for k, t in OPEN_DECISIONS],
            "managed_by": "Deployment configuration (not editable in the application).",
        }
        record(request, "platform.settings_viewed", obj_type="platform", obj_id="settings")
        return Response(body)
