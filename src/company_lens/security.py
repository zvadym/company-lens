from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
from urllib.parse import urlparse


class UnsafeUrlError(ValueError):
    pass


@dataclass(frozen=True)
class OutboundUrlPolicy:
    allowed_hosts: frozenset[str]
    require_https: bool = True

    def validate(self, url: str) -> str:
        parsed = urlparse(url)
        if self.require_https and parsed.scheme != "https":
            raise UnsafeUrlError("Outbound URL must use HTTPS.")
        if parsed.username or parsed.password:
            raise UnsafeUrlError("Outbound URL must not contain credentials.")
        host = (parsed.hostname or "").rstrip(".").lower()
        if not host or not self._host_allowed(host):
            raise UnsafeUrlError("Outbound URL host is not allowlisted.")
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            address = None
        if address is not None and not address.is_global:
            raise UnsafeUrlError("Private or local network destinations are forbidden.")
        return url

    def _host_allowed(self, host: str) -> bool:
        return any(
            host == allowed or host.endswith(f".{allowed}") for allowed in self.allowed_hosts
        )


_CONTROL_CHARACTERS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_PROMPT_INJECTION_PATTERNS = (
    re.compile(r"ignore\s+(all\s+)?previous\s+instructions", re.IGNORECASE),
    re.compile(r"system\s+prompt", re.IGNORECASE),
    re.compile(r"developer\s+message", re.IGNORECASE),
    re.compile(r"you\s+are\s+now", re.IGNORECASE),
)


def sanitize_untrusted_text(value: str, *, maximum_chars: int = 100_000) -> str:
    cleaned = _CONTROL_CHARACTERS.sub("", value).replace("\r\n", "\n").replace("\r", "\n")
    return cleaned[:maximum_chars]


def prompt_injection_flags(value: str) -> tuple[str, ...]:
    return tuple(
        f"pattern_{index}"
        for index, pattern in enumerate(_PROMPT_INJECTION_PATTERNS, start=1)
        if pattern.search(value)
    )
