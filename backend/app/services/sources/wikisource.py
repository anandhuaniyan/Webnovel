from __future__ import annotations

import httpx

from app.services.sources.base import SourceAdapter, SourceCandidate


class WikisourceAdapter(SourceAdapter):
    code = "wikisource"
    api_url = "https://en.wikisource.org/w/api.php"

    async def discover(self, *, page: int = 1, query: str | None = None) -> list[SourceCandidate]:
        search = query or "incategory:Novels"
        params = {
            "action": "query",
            "generator": "search",
            "gsrsearch": search,
            "gsrnamespace": 0,
            "gsrlimit": 50,
            "gsroffset": max(0, (page - 1) * 50),
            "prop": "info|categories",
            "inprop": "url",
            "cllimit": 50,
            "format": "json",
            "origin": "*",
        }
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            response = await client.get(self.api_url, params=params)
            response.raise_for_status()
        pages = (response.json().get("query") or {}).get("pages", {})
        return [self._candidate(page_data) for page_data in pages.values()]

    async def fetch_metadata(self, external_id: str) -> SourceCandidate:
        params = {
            "action": "query",
            "pageids": external_id,
            "prop": "info|categories",
            "inprop": "url",
            "cllimit": 100,
            "format": "json",
            "origin": "*",
        }
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            response = await client.get(self.api_url, params=params)
            response.raise_for_status()
        page = next(iter(response.json()["query"]["pages"].values()))
        return self._candidate(page)

    def _candidate(self, page: dict) -> SourceCandidate:
        categories = tuple(
            category["title"].removeprefix("Category:") for category in page.get("categories", [])
        )
        title = page.get("title") or "Untitled"
        page_id = str(page["pageid"])
        return SourceCandidate(
            source_code=self.code,
            external_id=page_id,
            title=title,
            authors=(),
            languages=("en",),
            subjects=categories,
            source_url=page.get("fullurl") or f"https://en.wikisource.org/?curid={page_id}",
            metadata_url=f"{self.api_url}?action=query&pageids={page_id}",
            licence_name="Licence varies by page: Public Domain, CC0, CC BY, or CC BY-SA; exact page review required",
            licence_url="https://foundation.wikimedia.org/wiki/Policy:Terms_of_Use",
            raw_metadata=page,
        )
