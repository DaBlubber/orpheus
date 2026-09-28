"""Persistent, fault-tolerant cache for restic directory listings."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


class ListingCache:
    def __init__(self, directory: str):
        self.directory = Path(directory)
        self._memory: dict[str, list[dict]] = {}

    @staticmethod
    def _key(repo: str, snapshot_id: str, path: str) -> str:
        raw = "\0".join((repo, snapshot_id, path)).encode("utf-8", errors="surrogatepass")
        return hashlib.sha256(raw).hexdigest()

    def get(self, repo: str, snapshot_id: str, path: str) -> list[dict] | None:
        key = self._key(repo, snapshot_id, path)
        if key in self._memory:
            return self._memory[key]
        cache_file = self.directory / f"{key}.json"
        try:
            with cache_file.open("r", encoding="utf-8") as handle:
                value = json.load(handle)
            if not isinstance(value, list):
                return None
            self._memory[key] = value
            return value
        except (OSError, ValueError, json.JSONDecodeError):
            return None

    def put(self, repo: str, snapshot_id: str, path: str, entries: list[dict]):
        key = self._key(repo, snapshot_id, path)
        self._memory[key] = entries
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            cache_file = self.directory / f"{key}.json"
            temporary = cache_file.with_suffix(".tmp")
            with temporary.open("w", encoding="utf-8") as handle:
                json.dump(entries, handle, ensure_ascii=False)
            temporary.replace(cache_file)
        except OSError:
            # The cache is an optimisation; a write error must not disturb the view.
            return
