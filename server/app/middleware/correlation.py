"""WSGI middleware that injects X-Correlation-ID on every request/response."""

import uuid
import structlog


class CorrelationIdMiddleware:
    HEADER = "X-Correlation-ID"

    def __init__(self, app):
        self.app = app

    def __call__(self, environ, start_response):
        cid = environ.get(
            "HTTP_X_CORRELATION_ID", str(uuid.uuid4())
        )
        environ["HTTP_X_CORRELATION_ID"] = cid

        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(correlation_id=cid)

        def _start_response(status, headers, exc_info=None):
            headers.append((self.HEADER, cid))
            return start_response(status, headers, exc_info)

        return self.app(environ, _start_response)
