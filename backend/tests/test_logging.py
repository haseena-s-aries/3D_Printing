"""Server logs: one access line per API request (tokens masked), and a start-up line without secrets."""
import logging

from apps.core.middleware import mask_path
from apps.core.startup import describe


def test_mask_path_hides_one_time_tokens_but_keeps_record_ids():
    rid = "0f8fad5b-d9cb-469f-a165-70867728950e"
    assert mask_path(f"/api/v1/parts/{rid}/") == f"/api/v1/parts/{rid}/"
    assert mask_path("/api/v1/downloads/AbCdEfGhIjKlMnOpQrStUvWxYz0123456789abc/") == "/api/v1/downloads/<token>/"
    assert mask_path("/api/v1/public/registrations/verify/Zz9_-Yy8Xx7Ww6Vv5Uu4Tt3/") == "/api/v1/public/registrations/verify/<token>/"
    assert mask_path("/api/health/") == "/api/health/"


def test_every_api_request_gets_an_access_line(db, client, caplog):
    with caplog.at_level(logging.INFO, logger="passport.access"):
        client.get("/api/health/")
        client.get("/api/v1/auth/me/")
        client.get("/api/v1/public/password-reset/AbCdEfGhIjKlMnOpQrStUvWxYz0123456789abc/?secret=1")
    lines = [r for r in caplog.records if r.name == "passport.access"]
    msgs = [r.getMessage() for r in lines]
    assert msgs[0].startswith("GET /api/health/ -> 200 (") and lines[0].levelno == logging.INFO
    assert msgs[1].startswith("GET /api/v1/auth/me/ -> 401 (") and lines[1].levelno == logging.WARNING
    assert msgs[2].startswith("GET /api/v1/public/password-reset/<token>/ -> ")
    assert "AbCdEf" not in " ".join(msgs) and "secret" not in " ".join(msgs)


def test_startup_line_names_settings_but_never_secrets(settings):
    settings.EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
    settings.EMAIL_HOST, settings.EMAIL_PORT, settings.EMAIL_USE_SSL = "mail.example.test", 465, True
    settings.EMAIL_HOST_PASSWORD = "Mail-Secret-Value-1"
    line = describe()
    assert "email=mail.example.test:465 SSL" in line and "database=" in line and "allowed_hosts=" in line
    assert "Mail-Secret-Value-1" not in line and settings.SECRET_KEY not in line
    assert settings.DATABASES["default"].get("PASSWORD", "x") not in line
