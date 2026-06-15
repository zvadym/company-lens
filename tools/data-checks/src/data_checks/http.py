from __future__ import annotations

import httpx


DEFAULT_TIMEOUT = httpx.Timeout(20.0, connect=10.0)


def build_client(headers: dict[str, str] | None = None) -> httpx.Client:
    return httpx.Client(
        headers=headers or {},
        follow_redirects=True,
        timeout=DEFAULT_TIMEOUT,
    )
