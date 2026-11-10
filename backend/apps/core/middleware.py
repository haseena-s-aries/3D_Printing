"""Request ID propagation for logs and error responses."""
import contextvars
import logging
import re
import uuid

_request_id = contextvars.ContextVar("request_id", default="-")
_VALID = re.compile(r"^[A-Za-z0-9\-]{8,64}$")


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
        try:
            response = self.get_response(request)
        finally:
            _request_id.reset(token)
        response["X-Request-ID"] = rid
        return response


class RequestIdLogFilter(logging.Filter):
    def filter(self, record):
        record.request_id = current_request_id()
        return True
