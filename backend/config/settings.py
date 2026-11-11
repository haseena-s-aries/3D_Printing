"""Django settings for the Digital Passport platform API.

All environment-specific values come from environment variables (see .env.example).
The same settings serve the shared multi-tenant deployment and dedicated deployments (HYB-001).
"""
import json
import os
import sys
from datetime import timedelta
from pathlib import Path
from urllib.parse import unquote, urlparse

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def env(name: str, default: str | None = None) -> str | None:
    return os.environ.get(name, default)


def env_bool(name: str, default: bool = False) -> bool:
    return str(env(name, str(default))).strip().lower() in {"1", "true", "yes", "on"}


def database_from_url(url: str) -> dict:
    u = urlparse(url)
    if u.scheme not in {"postgres", "postgresql"}:
        raise ValueError("DATABASE_URL must be a PostgreSQL URL; SQLite is not supported (row-level security).")
    return {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": unquote(u.path.lstrip("/")) or "postgres",
        "USER": unquote(u.username or ""),
        "PASSWORD": unquote(u.password or ""),
        "HOST": u.hostname or "",
        "PORT": str(u.port or ""),
        "ATOMIC_REQUESTS": True,  # required: tenant context is SET LOCAL inside the request transaction
        "CONN_MAX_AGE": int(env("DB_CONN_MAX_AGE", "60")),
        "OPTIONS": {"application_name": "passport-api"},
    }


def database_from_env() -> dict:
    """Microsoft SQL Server (mssql-django) from DB_* variables. Security controls: apps.tenancy.mssql.
    SESSION_CONTEXT belongs to the connection, so connections are not kept between requests unless DB_CONN_MAX_AGE is set
    (the context is reset at every request start and end either way)."""
    # LongAsMax: long strings (> 4000 characters, e.g. JSON) are sent as nvarchar(max), not legacy ntext, which the
    # supplementary-character (_SC) collation rejects
    extra = ["Encrypt=yes", "LongAsMax=yes"] + (["TrustServerCertificate=yes"] if env_bool("DB_TRUST_SERVER_CERTIFICATE") else [])
    return {
        "ENGINE": "apps.core.mssql_backend",  # mssql-django + filtered-index condition rewrite
        "NAME": env("DB_NAME"),
        "USER": env("DB_USER"),
        "PASSWORD": env("DB_PASSWORD"),
        "HOST": env("DB_HOST"),
        "PORT": env("DB_PORT", ""),
        "ATOMIC_REQUESTS": True,
        "CONN_MAX_AGE": int(env("DB_CONN_MAX_AGE", "0")),
        "OPTIONS": {"driver": env("DB_DRIVER", "ODBC Driver 18 for SQL Server"), "extra_params": ";".join(extra)},
        # tests run in an existing, separately created database (the test login cannot create databases)
        "TEST": {"NAME": env("DB_TEST_NAME", "")} if env("DB_TEST_NAME") else {},
    }


SECRET_KEY = env("DJANGO_SECRET_KEY")
if env("DB_ENGINE") == "mssql":
    # simplejwt's token_blacklist history alters a uniquely constrained column (0008), which SQL Server cannot do in
    # place. SQL Server databases are always created new, so they use one migration with the package's final models.
    MIGRATION_MODULES = {"token_blacklist": "apps.core.mssql_migrations.token_blacklist"}
DEBUG = env_bool("DJANGO_DEBUG", False)
if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = "insecure-development-key"
    else:
        raise RuntimeError("DJANGO_SECRET_KEY must be set when DEBUG is off")
ALLOWED_HOSTS = [h.strip() for h in (env("DJANGO_ALLOWED_HOSTS", "127.0.0.1,localhost") or "").split(",") if h.strip()]

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.staticfiles",
    "rest_framework",
    "rest_framework_simplejwt.token_blacklist",
    "drf_spectacular",
    "apps.core",
    "apps.tenancy",
    "apps.accounts",
    "apps.audit",
    "apps.policies",
    "apps.projects",
    "apps.parts",
    "apps.passports",
    "apps.files",
    "apps.jobs",
    "apps.servicerequests",
    "apps.registrations",
    "apps.jobsheets",
    "apps.reports",
    "apps.edits",
    "apps.imports",
    "apps.intelligence",
]

MIDDLEWARE = [
    "apps.core.middleware.RequestIdMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"
TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [],
    "APP_DIRS": True,
    "OPTIONS": {"context_processors": ["django.template.context_processors.request"]},
}]

DATABASES = {"default": database_from_env() if env("DB_ENGINE") == "mssql"
             else database_from_url(env("DATABASE_URL", "postgresql://app_user:app_user@127.0.0.1:5432/passport"))}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
AUTH_USER_MODEL = "accounts.User"
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 12}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

if env_bool("FAST_PASSWORD_HASHER_FOR_TESTS") and DEBUG:
    PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]  # tests only

LANGUAGE_CODE = "en-gb"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# Security headers (HTTPS is terminated by Azure; enforced outside DEBUG)
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
SECURE_REFERRER_POLICY = "same-origin"
if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = env_bool("DJANGO_SSL_REDIRECT", True)
    SECURE_HSTS_SECONDS = 31536000

# Uploads are streamed to temporary files, never held fully in memory
FILE_UPLOAD_MAX_MEMORY_SIZE = 2 * 1024 * 1024
DATA_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024
MAX_UPLOAD_BYTES = {
    "step": int(env("MAX_UPLOAD_MB_STEP", "200")) * 1024 * 1024,
    "dwg": int(env("MAX_UPLOAD_MB_DWG", "100")) * 1024 * 1024,
    "pdf": int(env("MAX_UPLOAD_MB_PDF", "100")) * 1024 * 1024,
    # Part photographs (BR-006 "original part image"); JPEG/PNG only. Provisional like the others (OQ-31).
    "image": int(env("MAX_UPLOAD_MB_IMAGE", "20")) * 1024 * 1024,
    "scan": int(env("MAX_UPLOAD_MB_SCAN", "500")) * 1024 * 1024,  # post-UAT D-09 (provisional, like OQ-31)
}
# Decoded size limit for photographs (width x height), checked before decoding. Provisional (OQ-31).
MAX_IMAGE_PIXELS = int(env("MAX_IMAGE_PIXELS", "60000000"))

FILE_STORAGE_BACKEND = env("FILE_STORAGE_BACKEND", "local")
LOCAL_STORAGE_ROOT = Path(env("LOCAL_STORAGE_ROOT", str(BASE_DIR / ".storage")))
if not LOCAL_STORAGE_ROOT.is_absolute():
    LOCAL_STORAGE_ROOT = BASE_DIR / LOCAL_STORAGE_ROOT
AZURE_STORAGE_CONNECTION_STRING = env("AZURE_STORAGE_CONNECTION_STRING", "")
# Download/preview links are single-use (files.LinkRedemption) and only need to survive the click that uses them.
DOWNLOAD_LINK_SECONDS = int(env("DOWNLOAD_LINK_SECONDS", "120"))
# Worker: role used to claim jobs across tenants. Empty when the worker process logs in as app_worker itself.
WORKER_DB_ROLE = env("WORKER_DB_ROLE", "")

# Invitations (apps.tenancy.invitations). The web address is used to build the emailed acceptance link.
WEB_BASE_URL = env("WEB_BASE_URL", "http://127.0.0.1:5173")
# Address browsers use to reach the API, for absolute links the API returns (file download and preview links), e.g.
# http://139.5.189.155:8031 when IIS on :8031 forwards /api/ to the backend on :8030. Empty: taken from each request.
PUBLIC_BASE_URL = env("PUBLIC_BASE_URL", "")
INVITATION_DAYS = int(env("INVITATION_DAYS", "7"))
# Development aid only: return the acceptance link to the inviting admin. Must be off wherever real email is
# configured, otherwise the inviter could act as the invitee. Never on without DEBUG, whatever the variable says
# (the serializer re-checks DEBUG at request time as well).
INVITATION_LINK_IN_RESPONSE = DEBUG and env_bool("INVITATION_LINK_IN_RESPONSE", DEBUG)
# Email is sent through Django's provider-independent mail API (apps.core.mail). Development uses the console or the
# file "outbox" backend (EMAIL_FILE_PATH); a production email provider is not provisioned yet (CN-002 D6).
EMAIL_BACKEND = env("EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend")
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", "no-reply@passport.local")
# SMTP server (EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend). The password comes only from the environment
# (backend/.env, never committed). Port 465 uses implicit SSL (EMAIL_USE_SSL=true); port 587 uses STARTTLS
# (EMAIL_USE_TLS=true); the two cannot both be on.
EMAIL_HOST = env("EMAIL_HOST", "localhost")
EMAIL_PORT = int(env("EMAIL_PORT", "25"))
EMAIL_HOST_USER = env("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", False)
EMAIL_USE_SSL = env_bool("EMAIL_USE_SSL", False)
EMAIL_TIMEOUT = int(env("EMAIL_TIMEOUT", "20"))
if EMAIL_USE_TLS and EMAIL_USE_SSL:
    raise RuntimeError("EMAIL_USE_TLS and EMAIL_USE_SSL cannot both be true (port 465: SSL; port 587: TLS).")
EMAIL_FILE_PATH = env("EMAIL_FILE_PATH", str(BASE_DIR / ".outbox"))
# Backends that do not deliver mail to the recipient's mailbox. Public registration and password reset need real
# delivery outside development, so they refuse to start with one of these unless DEBUG is on.
NON_DELIVERING_EMAIL_BACKENDS = {
    "django.core.mail.backends.console.EmailBackend", "django.core.mail.backends.filebased.EmailBackend",
    "django.core.mail.backends.locmem.EmailBackend", "django.core.mail.backends.dummy.EmailBackend",
}
# Development aid: an in-app page listing the file outbox (EMAIL_FILE_PATH). Never available without DEBUG.
DEV_OUTBOX_VIEW = DEBUG and env_bool("DEV_OUTBOX_VIEW", False)

# Company self-registration (CN-002). Off unless explicitly enabled; outside DEBUG it also needs a delivering email
# backend, so no account can be activated without real email verification.
PUBLIC_REGISTRATION_ENABLED = env_bool("PUBLIC_REGISTRATION_ENABLED", False)
if PUBLIC_REGISTRATION_ENABLED and not DEBUG and EMAIL_BACKEND in NON_DELIVERING_EMAIL_BACKENDS:
    raise RuntimeError("PUBLIC_REGISTRATION_ENABLED needs a real email backend outside DEBUG (EMAIL_BACKEND).")
REGISTRATION_TOKEN_HOURS = int(env("REGISTRATION_TOKEN_HOURS", "24"))
PASSWORD_RESET_TOKEN_MINUTES = int(env("PASSWORD_RESET_TOKEN_MINUTES", "60"))

# Client spare-part submissions held for Aries review (requirement update 2026-10). BRD v0.4 FR-04 names the Engineer
# as the registering actor, so this stays off until the change is approved; the access-test environment enables it.
CLIENT_PART_SUBMISSIONS_ENABLED = env_bool("CLIENT_PART_SUBMISSIONS_ENABLED", False)
# Controlled edit requests with reviewer decision (CN-006); access-test only until approved for wider use.
EDIT_REQUESTS_ENABLED = env_bool("EDIT_REQUESTS_ENABLED", False)
# CN-007 bulk inventory import (Excel/CSV) and data-quality assessment. Access-test only until approved elsewhere.
INVENTORY_IMPORT_ENABLED = env_bool("INVENTORY_IMPORT_ENABLED", False)
# CN-005 report builder: PDF page limits for uploads, for one report attachment and for an assembled report.
PDF_MAX_PAGES = int(env("PDF_MAX_PAGES", "300"))
REPORT_ATTACHMENT_MAX_PAGES = int(env("REPORT_ATTACHMENT_MAX_PAGES", "100"))
REPORT_MAX_PAGES = int(env("REPORT_MAX_PAGES", "400"))
REPORT_COMPANY_NAME = env("REPORT_COMPANY_NAME", "")  # manufacturing company printed on the MTS template (blank = not recorded)
REPORT_COMPANY_LOCATION = env("REPORT_COMPANY_LOCATION", "")
IMPORT_MAX_BYTES = int(env("IMPORT_MAX_BYTES", str(10 * 1024 * 1024)))
IMPORT_MAX_ROWS = int(env("IMPORT_MAX_ROWS", "20000"))

# CN-007 Phase 2 part intelligence. The deterministic analysis (rules in Python) needs only PART_INTELLIGENCE_ENABLED.
# External AI (Gemini) is optional and additionally needs AI_PROVIDER=gemini, GEMINI_API_KEY (backend environment only,
# never sent to the web app or logged) and the company's slug in AI_ALLOWED_COMPANIES. Real client companies stay off
# that list until data-processing approval and suitable API terms are confirmed.
PART_INTELLIGENCE_ENABLED = env_bool("PART_INTELLIGENCE_ENABLED", False)
AI_PROVIDER = env("AI_PROVIDER", "")  # "" = external AI off; "gemini"
GEMINI_API_KEY = env("GEMINI_API_KEY", "")
GEMINI_MODELS = {  # tier -> model id; "lite" is the default, "flash" and "pro" are escalations an engineer chooses
    "lite": env("GEMINI_MODEL_LITE", "gemini-3.1-flash-lite"),
    "flash": env("GEMINI_MODEL_FLASH", "gemini-3.8-flash"),
    "pro": env("GEMINI_MODEL_PRO", "gemini-3.1-pro-preview"),
}
# Optional build envelope (x,y,z in mm) for the rule "dimension exceeds the build envelope"; unset = not checked.
AM_BUILD_ENVELOPE_MM = [float(x) for x in env("AM_BUILD_ENVELOPE_MM", "").split(",") if x.strip()] or None
AI_ALLOWED_COMPANIES = [s.strip() for s in env("AI_ALLOWED_COMPANIES", "").split(",") if s.strip()]
AI_TIMEOUT_SECONDS = int(env("AI_TIMEOUT_SECONDS", "45"))
AI_MAX_RETRIES = int(env("AI_MAX_RETRIES", "2"))  # retries after the first attempt, transient errors only
# True total deadline of one AI request (all attempts, retries and back-off); a single attempt gets at most AI_TIMEOUT_SECONDS.
AI_TOTAL_DEADLINE_SECONDS = int(env("AI_TOTAL_DEADLINE_SECONDS", "60"))
# CN-007 Phase 6 assessment runs: attempts per part within a run (transient failures), and test-only fault injection.
ASSESSMENT_ITEM_MAX_ATTEMPTS = int(env("ASSESSMENT_ITEM_MAX_ATTEMPTS", "2"))
ASSESSMENT_FAULT_INJECTION = env_bool("ASSESSMENT_FAULT_INJECTION", False)
# CN-007 role-based AI access: Aries Admin management dashboard, client "My Parts Intelligence" workspace, controlled
# disclosure of reviewed results and client assessment requests. Off by default (access-test only). A client company's
# workspace can be switched on only when its slug is listed here: real companies need a reviewed decision first.
AI_CLIENT_ACCESS_ENABLED = env_bool("AI_CLIENT_ACCESS_ENABLED", False)
AI_CLIENT_SHARING_COMPANIES = [s.strip() for s in env("AI_CLIENT_SHARING_COMPANIES", "").split(",") if s.strip()]
# Per-company consent for Aries Admin inventory thumbnails (Option A, approved 2026-10-29 for access-test). Off by default;
# with it off the consent endpoints and the thumbnail route refuse every request and the administrative summary carries no images.
ADMIN_THUMBNAIL_CONSENT_ENABLED = env_bool("ADMIN_THUMBNAIL_CONSENT_ENABLED", False)
# Lifetime of a thumbnail link issued to the Aries Admin (seconds). Consent is re-checked on every request regardless.
ADMIN_THUMBNAIL_LINK_SECONDS = int(env("ADMIN_THUMBNAIL_LINK_SECONDS", "600"))
# Provenance-aware contract route for those thumbnails (approved 2026-10-29 for access-test): QA-confirmed Aries scanning
# photos under an independently verified contract authorization. Off by default; needs ADMIN_THUMBNAIL_CONSENT_ENABLED too.
ADMIN_THUMBNAIL_PROVENANCE_ENABLED = env_bool("ADMIN_THUMBNAIL_PROVENANCE_ENABLED", False)
# Who may resolve a client's objection to that contract route, and under which documented authority (for example a
# delegation reference). Configured with the deployment, never granted in the application; contract verification gives
# no such right. Until both are set, every disputed contract route stays on hold.
CONTRACT_OBJECTION_REVIEWERS = [s.strip().lower() for s in env("CONTRACT_OBJECTION_REVIEWERS", "").split(",") if s.strip()]
CONTRACT_OBJECTION_AUTHORITY = env("CONTRACT_OBJECTION_AUTHORITY", "").strip()
# Aries Admin super-administrator workspaces in client companies (business decision 2026-10-29; proposed revision of OQ-37
# and CN-002 D3; access-test only). Off by default: Aries Admin then keeps administrative summaries only.
ADMIN_WORKSPACE_ENABLED = env_bool("ADMIN_WORKSPACE_ENABLED", False)
# Companies whose confidential file content (CAD, 3D, photos, documents, reports, request attachments) is open to the Aries
# Admin, each with its documented authorization decision: "slug=decision reference,...". Empty = closed everywhere.
ADMIN_FILE_ACCESS_DECISIONS = env("ADMIN_FILE_ACCESS_DECISIONS", "").strip()
# Four core roles (business decision 2026-10-30; supersedes CN-002 D5; access-test only): Aries Admin, Aries Engineer, Client
# Admin, Client User. QA, engineering review and contract review are permissions on Aries Engineers; Client Users get feature
# permissions. Off by default. Legacy roles keep their rights until mapped (manage.py four_role_mapping).
FOUR_ROLE_MODEL_ENABLED = env_bool("FOUR_ROLE_MODEL_ENABLED", False)
AI_CALLS_PER_MINUTE = int(env("AI_CALLS_PER_MINUTE", "10"))  # all companies together
AI_CALLS_PER_DAY = int(env("AI_CALLS_PER_DAY", "200"))
AI_DAILY_BUDGET_USD = float(env("AI_DAILY_BUDGET_USD", "1.00"))
# Standard (paid tier) list prices in USD per 1M tokens (input, output incl. thinking), ai.google.dev pricing page as
# read on 27 Oct 2026. Used for cost estimates only; override with AI_PRICES_JSON when prices change.
AI_PRICES = json.loads(env("AI_PRICES_JSON", "") or "null") or {
    "gemini-2.5-flash-lite": [0.10, 0.40], "gemini-3.1-flash-lite": [0.25, 1.50], "gemini-3.5-flash-lite": [0.30, 2.50],
    "gemini-2.5-flash": [0.30, 2.50], "gemini-3.8-flash": [0.75, 3.75], "gemini-3.1-pro-preview": [2.00, 12.00],
}

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["apps.accounts.authentication.TenantJWTAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_PAGINATION_CLASS": "apps.core.pagination.StandardPagination",
    "EXCEPTION_HANDLER": "apps.core.exceptions.api_exception_handler",
    "DEFAULT_THROTTLE_RATES": {
        "login": env("LOGIN_THROTTLE", "10/min"),
        # Public, unauthenticated flows (per client IP)
        "register": env("REGISTER_THROTTLE", "5/hour"),
        "verify": env("VERIFY_THROTTLE", "20/hour"),
        "password_reset": env("PASSWORD_RESET_THROTTLE", "5/hour"),
    },
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=int(env("JWT_ACCESS_MINUTES", "15"))),
    "REFRESH_TOKEN_LIFETIME": timedelta(minutes=int(env("JWT_REFRESH_MINUTES", "480"))),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "UPDATE_LAST_LOGIN": True,
    "SIGNING_KEY": SECRET_KEY,
    "AUTH_HEADER_TYPES": ("Bearer",),
}

SPECTACULAR_SETTINGS = {
    "TITLE": "Digital Passport Platform API",
    "DESCRIPTION": "Versioned REST API (v1). All business endpoints are tenant-scoped; see docs/api.md.",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "COMPONENT_SPLIT_REQUEST": True,
    "ENUM_NAME_OVERRIDES": {
        "RequestKindEnum": "apps.servicerequests.models.ClientRequest.Kind",
        "RequestStatusEnum": "apps.servicerequests.models.ClientRequest.Status",
        "ReportVariantEnum": "apps.reports.models.PassportReport.Variant",
        "EditRequestStatusEnum": "apps.edits.models.EditRequest.Status",
    },
}

# Logging: console (captured by NSSM's I/O tab) and, when LOG_FILE is set, a rotating log file (10 MB x 5).
# The worker writes to its own file next to it (<name>-worker.log), so the two processes never rotate the same file.
# One line per API request (ACCESS_LOG, default on): method, path (one-time tokens masked), status, duration.
LOG_FILE = env("LOG_FILE", "")
if LOG_FILE and "run_worker" in sys.argv:
    LOG_FILE = str(Path(LOG_FILE).with_name(Path(LOG_FILE).stem + "-worker" + Path(LOG_FILE).suffix))
ACCESS_LOG = env_bool("ACCESS_LOG", True)
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {"request_id": {"()": "apps.core.middleware.RequestIdLogFilter"}},
    "formatters": {
        "plain": {"format": "%(asctime)s %(levelname)s %(name)s [req=%(request_id)s] %(message)s"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "plain", "filters": ["request_id"]},
        **({"file": {"class": "logging.handlers.RotatingFileHandler", "filename": LOG_FILE, "maxBytes": 10 * 1024 * 1024,
                     "backupCount": 5, "encoding": "utf-8", "delay": True, "formatter": "plain", "filters": ["request_id"]}}
           if LOG_FILE else {}),
    },
    "root": {"handlers": ["console", *(["file"] if LOG_FILE else [])], "level": env("LOG_LEVEL", "INFO")},
    # HTTP client libraries stay at WARNING so request details of external AI calls are never logged. django.request
    # stays quiet below ERROR: 4xx responses are already in the access log (passport.access).
    "loggers": {"django.db.backends": {"level": "WARNING"}, "httpx": {"level": "WARNING"}, "httpcore": {"level": "WARNING"},
                "google_genai": {"level": "WARNING"}, "django.request": {"level": "ERROR"}},
}
if LOG_FILE:
    Path(LOG_FILE).parent.mkdir(parents=True, exist_ok=True)
