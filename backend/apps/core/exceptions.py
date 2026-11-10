"""Consistent error envelope: {"error": {"code", "message", "details", "request_id"}}."""
import logging

from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.db import DatabaseError
from django.http import Http404
from rest_framework import exceptions, status
from rest_framework.response import Response
from rest_framework.views import exception_handler

from .middleware import current_request_id

log = logging.getLogger(__name__)


class DomainError(exceptions.APIException):
    """Business-rule refusal with a stable machine-readable code."""

    status_code = status.HTTP_409_CONFLICT
    default_code = "conflict"

    def __init__(self, code: str, message: str, details=None, http_status: int | None = None):
        super().__init__(detail=message, code=code)
        self.error_code = code
        self.details = details or {}
        if http_status:
            self.status_code = http_status


def error_response(code: str, message: str, http_status: int, details=None) -> Response:
    """Return the error envelope without raising, so work done in the request (such as an audit record of the
    refusal) is committed instead of rolled back."""
    return Response({"error": {"code": code, "message": message, "details": details or {}, "request_id": current_request_id()}},
                    status=http_status)


CODE_BY_CLASS = {
    exceptions.NotAuthenticated: "not_authenticated",
    exceptions.AuthenticationFailed: "authentication_failed",
    exceptions.PermissionDenied: "permission_denied",
    exceptions.NotFound: "not_found",
    exceptions.ValidationError: "validation_error",
    exceptions.MethodNotAllowed: "method_not_allowed",
    exceptions.Throttled: "throttled",
    exceptions.ParseError: "parse_error",
    exceptions.UnsupportedMediaType: "unsupported_media_type",
}


def api_exception_handler(exc, context):
    if isinstance(exc, Http404):
        exc = exceptions.NotFound()
    elif isinstance(exc, DjangoPermissionDenied):
        exc = exceptions.PermissionDenied()
    response = exception_handler(exc, context)
    if response is None:
        if isinstance(exc, DatabaseError):
            log.exception("database error")
        else:
            log.exception("unhandled error")
        return Response({"error": {"code": "server_error", "message": "An unexpected error occurred.",
                                   "details": {}, "request_id": current_request_id()}},
                        status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    if isinstance(exc, DomainError):
        code, message, details = exc.error_code, str(exc.detail), exc.details
    else:
        code = next((c for k, c in CODE_BY_CLASS.items() if isinstance(exc, k)), "error")
        data = response.data
        if isinstance(exc, exceptions.ValidationError):
            message, details = "The request is not valid.", data
        else:
            message = data.get("detail", "Request failed.") if isinstance(data, dict) else str(data)
            details = {}
    response.data = {"error": {"code": code, "message": str(message), "details": details, "request_id": current_request_id()}}
    return response
