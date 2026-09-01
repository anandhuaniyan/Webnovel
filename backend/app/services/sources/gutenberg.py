from __future__ import annotations

import httpx

from app.services.sources.base import SourceAdapter, SourceCandidate


class GutenbergAdapter(SourceAdapter):
    code = "gutenberg"
    # Gutendex redirects the non-canonical path to its trailing-slash URL. In
    # some container/network combinations that redirect can stall even though
    # the canonical endpoint is healthy, so call it directly.
    api_url = "https://gutendex.com/books/"

    async def discover(self, *, page: int = 1, query: str | None = None) -> list[SourceCandidate]:
        params: dict[str, str | int] = {"page": page}
        if query:
            params["search"] = query
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            response = await client.get(self.api_url, params=params)
            response.raise_for_status()
        return [self._candidate(item) for item in response.json().get("results", [])]

    async def fetch_metadata(self, external_id: str) -> SourceCandidate:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            response = await client.get(f"{self.api_url}{external_id}/")
            response.raise_for_status()
        return self._candidate(response.json())

    def _candidate(self, item: dict) -> SourceCandidate:
        formats = item.get("formats") or {}
        preferred = [
            "application/epub+zip",
            "application/x-mobipocket-ebook",
            "text/html; charset=utf-8",
            "text/html",
            "text/plain; charset=utf-8",
            "text/plain",
        ]
        download_type = next((media for media in preferred if formats.get(media)), None)
        external_id = str(item["id"])
        return SourceCandidate(
            source_code=self.code,
            external_id=external_id,
            title=item.get("title") or "Untitled",
            authors=tuple(author.get("name", "Unknown") for author in item.get("authors", [])),
            languages=tuple(item.get("languages", [])),
            subjects=tuple(item.get("subjects", [])),
            bookshelves=tuple(item.get("bookshelves", [])),
            source_url=f"https://www.gutenberg.org/ebooks/{external_id}",
            metadata_url=f"{self.api_url}{external_id}/",
            download_url=formats.get(download_type) if download_type else None,
            media_type=download_type,
            licence_name="Project Gutenberg licence; jurisdiction review required",
            licence_url="https://www.gutenberg.org/policy/license.html",
            raw_metadata=item,
        )
