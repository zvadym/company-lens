from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CURATED_IDENTITIES_PATH = Path("config/company_identity_aliases.yaml")


@dataclass(frozen=True)
class CuratedAlias:
    alias: str
    kind: str = "common"
    confidence: Decimal | None = None


@dataclass(frozen=True)
class CuratedIdentity:
    cik: str
    legal_name: str
    display_name: str
    tickers: tuple[str, ...] = ()
    aliases: tuple[CuratedAlias, ...] = ()
    source: str = "manual"


def load_curated_identities(
    path: Path = DEFAULT_CURATED_IDENTITIES_PATH,
) -> tuple[CuratedIdentity, ...]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    identities = payload.get("identities", ())
    if not isinstance(identities, list):
        raise ValueError("company identity aliases config must contain an identities list.")
    return tuple(_identity(item) for item in identities)


def _identity(value: object) -> CuratedIdentity:
    if not isinstance(value, dict):
        raise ValueError("curated company identity entries must be objects.")
    aliases = value.get("aliases", ())
    tickers = value.get("tickers", ())
    if not isinstance(aliases, list):
        raise ValueError("curated company identity aliases must be a list.")
    if not isinstance(tickers, list):
        raise ValueError("curated company identity tickers must be a list.")
    return CuratedIdentity(
        cik=_required_string(value, "cik").zfill(10),
        legal_name=_required_string(value, "legal_name"),
        display_name=_required_string(value, "display_name"),
        tickers=tuple(str(ticker).strip().upper() for ticker in tickers if str(ticker).strip()),
        aliases=tuple(_alias(alias) for alias in aliases),
        source=str(value.get("source") or "manual"),
    )


def _alias(value: object) -> CuratedAlias:
    if not isinstance(value, dict):
        raise ValueError("curated company identity alias entries must be objects.")
    confidence = value.get("confidence")
    return CuratedAlias(
        alias=_required_string(value, "alias"),
        kind=str(value.get("kind") or "common"),
        confidence=Decimal(str(confidence)) if confidence is not None else None,
    )


def _required_string(value: dict[str, Any], key: str) -> str:
    raw = value.get(key)
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError(f"curated company identity entry requires {key}.")
    return raw.strip()
