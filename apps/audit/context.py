import contextvars
import re
import uuid

request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("request_id", default=None)

_SAFE_ID = re.compile(r"^[A-Za-z0-9._-]{1,100}$")


class RequestIdMiddleware:
    """Give every request an id (from X-Request-ID when well-formed) for logs and audit records."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        incoming = request.headers.get("X-Request-ID", "")
        request_id = incoming if _SAFE_ID.match(incoming) else uuid.uuid4().hex
        request.request_id = request_id
        token = request_id_var.set(request_id)
        try:
            response = self.get_response(request)
        finally:
            request_id_var.reset(token)
        response["X-Request-ID"] = request_id
        return response


class RequestIdLogFilter:
    """Adds request_id to every log record so log lines can be tied to audit events."""

    def filter(self, record):
        record.request_id = request_id_var.get() or "-"
        return True
