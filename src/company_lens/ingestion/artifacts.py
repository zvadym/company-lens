from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class StoredArtifact:
    path: Path
    content_hash: str
    size_bytes: int
    mime_type: str | None


class ArtifactStore:
    def __init__(self, root: Path) -> None:
        self._root = root

    def store_bytes(
        self,
        *,
        relative_path: Path,
        content: bytes,
        mime_type: str | None = None,
    ) -> StoredArtifact:
        absolute_path = self._root / relative_path
        absolute_path.parent.mkdir(parents=True, exist_ok=True)
        content_hash = hashlib.sha256(content).hexdigest()
        if not absolute_path.exists() or absolute_path.read_bytes() != content:
            absolute_path.write_bytes(content)
        return StoredArtifact(
            path=absolute_path,
            content_hash=content_hash,
            size_bytes=len(content),
            mime_type=mime_type,
        )

    def store_json(self, *, relative_path: Path, payload: dict[str, Any]) -> StoredArtifact:
        content = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")
        return self.store_bytes(
            relative_path=relative_path,
            content=content,
            mime_type="application/json",
        )
