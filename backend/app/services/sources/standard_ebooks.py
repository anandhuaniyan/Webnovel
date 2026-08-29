from __future__ import annotations

from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from app.services.sources.base import SourceAdapter, SourceCandidate


class StandardEbooksAdapter(SourceAdapter):
    code = "standard_ebooks"
    opds_url = "https://standardebooks.org/opds/all"

    async def discover(self, *, page: int = 1, query: str | None = None) -> list[SourceCandidate]:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            response = await client.get(self.opds_url)
            response.raise_for_status()
        soup = BeautifulSoup(response.content, "xml")
        candidates: list[SourceCandidate] = []
        for entry in soup.find_all("entry"):
            title = entry.find("title")
            identifier = entry.find("id")
            if not title or not identifier:
                continue
            if query and query.lower() not in title.get_text(" ", strip=True).lower():
                continue
            links = entry.find_all("link")
            epub_link = next(
                (
                    link.get("href")
                    for link in links
                    if link.get("type") == "application/epub+zip"
                    and link.get("rel") == "http://opds-spec.org/acquisition"
                ),
                None,
            )
            page_link = next((link.get("href") for link in links if link.get("rel") == "alternate"), "")
            external_id = identifier.get_text(strip=True).rstrip("/").split("/")[-1]
            candidates.append(
                SourceCandidate(
                    source_code=self.code,
                    external_id=external_id,
                    title=title.get_text(" ", strip=True),
                    authors=tuple(author.get_text(" ", strip=True) for author in entry.find_all("author")),
                    languages=tuple(
                        category.get("term")
                        for category in entry.find_all("category")
                        if category.get("term") in {"en", "fr", "de"}
                    ),
                    subjects=tuple(
                        category.get("term")
                        for category in entry.find_all("category")
                        if category.get("term")
                    ),
                    source_url=urljoin("https://standardebooks.org", page_link or f"/ebooks/{external_id}"),
                    metadata_url=self.opds_url,
                    download_url=urljoin("https://standardebooks.org", epub_link) if epub_link else None,
                    media_type="application/epub+zip" if epub_link else None,
                    licence_name="Standard Ebooks uncopyright declaration; contributors and jurisdiction require review",
                    licence_url="https://standardebooks.org/about/uncopyright",
                    raw_metadata={"opds_id": identifier.get_text(strip=True)},
                )
            )
        start = max(0, (page - 1) * 50)
        return candidates[start : start + 50]

    async def fetch_metadata(self, external_id: str) -> SourceCandidate:
        candidates = await self.discover(query=external_id)
        match = next((item for item in candidates if item.external_id == external_id), None)
        if not match:
            raise LookupError(f"Standard Ebooks item not found: {external_id}")
        return match
