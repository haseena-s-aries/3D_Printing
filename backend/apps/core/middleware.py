"""Request ID propagation for logs and error responses, and a one-line access log per API request."""
import contextvars
import logging
import re
import time
import uuid

from django.conf import settings

_request_id = contextvars.ContextVar("request_id", default="-")
_VALID = re.compile(r"^[A-Za-z0-9\-]{8,64}$")
_UUID = re.compile(r"^[0-9a-fA-F]{8}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{12}$")
access_log = logging.getLogger("passport.access")


def mask_path(path: str) -> str:
    """The request path for the log, with one-time tokens (download, verification, password-reset and invitation links)
    replaced: any path segment of 20+ characters that is not a record id (UUID). Query strings are never logged."""
    return "/".join("<token>" if len(seg) >= 20 and not _UUID.match(seg) else seg for seg in path.split("/"))


def current_request_id() -> str:
    return _request_id.get()


class RequestIdMiddleware:
    header = "HTTP_X_REQUEST_ID"

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        incoming = request.META.get(self.header, "")
        rid = incoming if _VALID.match(incoming or "") else uuid.uuid4().hex
        token = _request_id.set(rid)
        request.request_id = rid
        started = time.monotonic()
        try:
            response = self.get_response(request)
            if getattr(settings, "ACCESS_LOG", True):
                ms = round((time.monotonic() - started) * 1000)
                level = logging.ERROR if response.status_code >= 500 else logging.WARNING if response.status_code >= 400 else logging.INFO
                access_log.log(level, "%s %s -> %s (%s ms)", request.method, mask_path(request.path), response.status_code, ms)
        finally:
            _request_id.reset(token)
        response["X-Request-ID"] = rid
        return response


class RequestIdLogFilter(logging.Filter):
    def filter(self, record):
        record.request_id = current_request_id()
        return True
