from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from company_lens.observability.context import bind_context

CORRELATION_ID_HEADER = "X-Request-ID"
CORRELATION_ID_STATE_KEY = "correlation_id"
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        supplied = request.headers.get(CORRELATION_ID_HEADER)
        correlation_id = supplied if supplied and _SAFE_ID.fullmatch(supplied) else str(uuid4())
        setattr(request.state, CORRELATION_ID_STATE_KEY, correlation_id)
        with bind_context(correlation_id=correlation_id):
            response = await call_next(request)
        response.headers[CORRELATION_ID_HEADER] = correlation_id
        return response
