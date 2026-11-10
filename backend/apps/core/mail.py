"""Provider-independent outgoing email (CN-002 D6).

All application email goes through `send()`, which uses Django's configured EMAIL_BACKEND. Development uses the console
or file backend; the file backend writes one file per message into EMAIL_FILE_PATH (the local "outbox"), which a
developer can read through the DEBUG-only outbox page. Nothing here marks an address as verified: verification only
happens when the recipient opens the emailed single-use link.
"""
import logging
import re
from email import message_from_bytes, policy
from pathlib import Path

from django.conf import settings
from django.core.mail import EmailMessage

log = logging.getLogger(__name__)


def send(to: str, subject: str, body: str) -> None:
    EmailMessage(subject=subject, body=body, from_email=settings.DEFAULT_FROM_EMAIL, to=[to]).send(fail_silently=False)
    log.info("email sent: %s", subject)


def outbox_messages(limit: int = 50) -> list[dict]:
    """Messages written by the file backend, newest first (development outbox page only)."""
    folder = Path(settings.EMAIL_FILE_PATH)
    if not folder.is_dir():
        return []
    out = []
    for path in sorted(folder.glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]:
        # One file can hold several messages, separated by a line of dashes.
        for chunk in re.split(rb"\r?\n-{20,}\r?\n", path.read_bytes()):
            if not chunk.strip():
                continue
            msg = message_from_bytes(chunk.strip(), policy=policy.default)
            body = msg.get_body(preferencelist=("plain",))
            out.append({"id": f"{path.stem}", "to": str(msg.get("To", "")), "subject": str(msg.get("Subject", "")),
                        "date": str(msg.get("Date", "")), "body": body.get_content() if body else ""})
    return out[:limit]
