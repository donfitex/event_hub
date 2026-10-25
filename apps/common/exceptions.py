import logging

from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.http import Http404
from rest_framework import exceptions, status
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

logger = logging.getLogger(__name__)


class DomainError(exceptions.APIException):
    """A business-rule failure with its own machine-readable code and HTTP status."""

    status_code = status.HTTP_400_BAD_REQUEST
    default_code = "domain_error"

    def __init__(self, code, message, status_code=status.HTTP_400_BAD_REQUEST):
        super().__init__(detail=message, code=code)
        self.code = code
        self.message = message
        self.status_code = status_code


def _contains_code(codes, target):
    if isinstance(codes, dict):
        return any(_contains_code(v, target) for v in codes.values())
    if isinstance(codes, (list, tuple)):
        return any(_contains_code(v, target) for v in codes)
    return codes == target


def _error_code(exc, status_code):
    if status_code == status.HTTP_429_TOO_MANY_REQUESTS:
        return "RATE_LIMITED"
    codes = exc.get_codes()
    return codes.upper() if isinstance(codes, str) else "ERROR"


def api_exception_handler(exc, context):
    if isinstance(exc, Http404):
        exc = exceptions.NotFound()
    elif isinstance(exc, DjangoPermissionDenied):
        exc = exceptions.PermissionDenied()

    response = drf_exception_handler(exc, context)

    if response is None:  # not an API exception: log it and hide the details
        logger.exception("Unhandled API exception", exc_info=exc)
        return Response(
            {"error": {"code": "INTERNAL_ERROR", "message": "An unexpected error occurred."}},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    if isinstance(exc, exceptions.ValidationError):
        error = {
            "code": "VALIDATION_ERROR",
            "message": "The request contains invalid data.",
            "details": response.data,
        }
        if _contains_code(exc.get_codes(), "business_rule"):
            response.status_code = 422
            error["code"] = "BUSINESS_RULE_VIOLATION"
            error["message"] = "The data violates a business rule."
    else:
        error = {"code": _error_code(exc, response.status_code), "message": str(exc.detail)}
        if isinstance(exc, exceptions.Throttled) and exc.wait is not None:
            error["retry_after"] = int(exc.wait)

    response.data = {"error": error}
    return response