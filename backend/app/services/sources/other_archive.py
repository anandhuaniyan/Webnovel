from __future__ import annotations

import httpx

from app.services.sources.base import SourceAdapter, SourceCandidate


class OtherArchiveAdapter(SourceAdapter):
    """Adapter for an explicitly configured archive JSON feed.

    It never infers redistribution rights. Every item remains unverified and
    requires a separate rights record and independent evidence.
    """

    code = "other_archive"

    def __init__(self, feed_url: str):
        if not feed_url.startswith("https://"):
            raise ValueError("archive feed must use HTTPS")
        self.feed_url = feed_url

    async def discover(self, *, page: int = 1, query: str | None = None) -> list[SourceCandidate]:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            response = await client.get(self.feed_url, params={"page": page, "query": query or ""})
            response.raise_for_status()
        return [self._candidate(item) for item in response.json().get("items", [])]

    async def fetch_metadata(self, external_id: str) -> SourceCandidate:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            response = await client.get(self.feed_url, params={"id": external_id})
            response.raise_for_status()
        return self._candidate(response.json())

    def _candidate(self, item: dict) -> SourceCandidate:
        return SourceCandidate(
            source_code=self.code,
            external_id=str(item["id"]),
            title=item["title"],
            authors=tuple(item.get("authors", [])),
            languages=tuple(item.get("languages", [])),
            subjects=tuple(item.get("subjects", [])),
            source_url=item["source_url"],
            metadata_url=item.get("metadata_url", self.feed_url),
            download_url=item.get("download_url"),
            media_type=item.get("media_type"),
            licence_name=None,
            licence_url=None,
            raw_metadata=item,
        )
