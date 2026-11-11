"""One start-up line for the API and the worker: which settings are in effect (never passwords or keys)."""
import logging

from django.conf import settings

log = logging.getLogger("passport.startup")


def describe() -> str:
    db = settings.DATABASES["default"]
    email = (f"{settings.EMAIL_HOST}:{settings.EMAIL_PORT}" + (" SSL" if settings.EMAIL_USE_SSL else " TLS" if settings.EMAIL_USE_TLS else "")
             if settings.EMAIL_BACKEND.endswith("smtp.EmailBackend") else settings.EMAIL_BACKEND.rsplit(".", 2)[-2])
    return (f"debug={settings.DEBUG} allowed_hosts={','.join(settings.ALLOWED_HOSTS)} web={settings.WEB_BASE_URL} "
            f"database={db['ENGINE'].rsplit('.', 1)[-1]}:{db.get('NAME')}@{db.get('HOST') or 'local'} email={email} "
            f"registration={'on' if settings.PUBLIC_REGISTRATION_ENABLED else 'off'} "
            f"log_file={settings.LOG_FILE or '(console only)'}")


def log_startup(what: str) -> None:
    log.info("%s started: %s", what, describe())
