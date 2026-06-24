"""Global public-company identity registry."""

from company_lens.identity.curated import CuratedAlias, CuratedIdentity, load_curated_identities
from company_lens.identity.registry import (
    CompanyIdentityCandidate,
    CompanyIdentityRegistry,
    CompanyIdentityResolution,
)

__all__ = [
    "CompanyIdentityCandidate",
    "CompanyIdentityRegistry",
    "CompanyIdentityResolution",
    "CuratedAlias",
    "CuratedIdentity",
    "load_curated_identities",
]
