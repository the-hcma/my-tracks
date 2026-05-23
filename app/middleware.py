"""Request/response logging middleware."""

import json
import logging

from django.http import HttpRequest, HttpResponse

logger = logging.getLogger(__name__)

# Health check requests are intentionally noisy — log them at TRACE so the
# existing HealthCheckFilter can further suppress them if desired.
TRACE = 5
_HEALTH_PREFIX = "/health/"
_JSON_CONTENT_TYPES = ("application/json", "text/json")


def _format_json(data: bytes) -> str:
    """Return a pretty-printed JSON string (2-space indent, keys sorted), or raw text if not valid JSON."""
    try:
        return json.dumps(json.loads(data), indent=2, sort_keys=True)
    except ValueError, UnicodeDecodeError:
        return data.decode("utf-8", errors="replace")


class RequestLoggingMiddleware:
    """Log each HTTP request, its response status, and JSON bodies at DEBUG level.

    Produces one line per request, with bodies pretty-printed:
        GET  /api/locations/ -> 200
        POST /api/owntracks/ -> 201 | req: {\n  "_type": "location"\n} | resp: [\n  {"id": 1}\n]

    Request bodies are captured only when Content-Type is application/json.
    Response bodies are captured only when the response Content-Type is
    application/json and the response is not streaming.
    Health-check paths are logged at TRACE instead of DEBUG.
    """

    def __init__(self, get_response: object) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        # Read request body before passing to the view. Django caches
        # request.body after the first read, so this is safe alongside DRF.
        req_body: str | None = None
        req_ct = request.content_type or ""
        if any(req_ct.startswith(ct) for ct in _JSON_CONTENT_TYPES) and request.body:
            req_body = _format_json(request.body)

        response: HttpResponse = self.get_response(request)  # type: ignore[assignment]

        resp_body: str | None = None
        resp_ct = response.get("Content-Type", "")
        if any(resp_ct.startswith(ct) for ct in _JSON_CONTENT_TYPES) and not getattr(response, "streaming", False):
            resp_body = _format_json(response.content)

        level = TRACE if request.path.startswith(_HEALTH_PREFIX) else logging.DEBUG

        if req_body is not None and resp_body is not None:
            logger.log(
                level,
                "%s %s -> %s | req: %s | resp: %s",
                request.method,
                request.path,
                response.status_code,
                req_body,
                resp_body,
            )
        elif req_body is not None:
            logger.log(level, "%s %s -> %s | req: %s", request.method, request.path, response.status_code, req_body)
        elif resp_body is not None:
            logger.log(level, "%s %s -> %s | resp: %s", request.method, request.path, response.status_code, resp_body)
        else:
            logger.log(level, "%s %s -> %s", request.method, request.path, response.status_code)

        return response
