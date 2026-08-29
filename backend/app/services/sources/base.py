from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass(frozen=True)
class SourceCandidate:
    source_code: str
    external_id: str
    title: str
    authors: tuple[str, ...]
    languages: tuple[str, ...]
    subjects: tuple[str, ...] = ()
    bookshelves: tuple[str, ...] = ()
    source_url: str = ""
    metadata_url: str = ""
    download_url: str | None = None
    media_type: str | None = None
    licence_name: str | None = None
    licence_url: str | None = None
    raw_metadata: dict = field(default_factory=dict)


class SourceAdapter(ABC):
    code: str

    @abstractmethod
    async def discover(self, *, page: int = 1, query: str | None = None) -> list[SourceCandidate]:
        raise NotImplementedError

    @abstractmethod
    async def fetch_metadata(self, external_id: str) -> SourceCandidate:
        raise NotImplementedError

    @staticmethod
    def is_fiction(candidate: SourceCandidate) -> bool:
        haystack = " ".join((*candidate.subjects, *candidate.bookshelves)).lower()
        volume_match = re.search(r"\bvolume\s+(\d+)\s*\(of\s+(\d+)\)", candidate.title, re.IGNORECASE)
        if volume_match and int(volume_match.group(1)) < int(volume_match.group(2)):
            return False
        fiction_signals = (
            "fiction",
            "novel",
            "romance",
            "detective",
            "fantasy",
            "science fiction",
            "horror",
            "gothic",
            "adventure stories",
        )
        excluded = (
            "periodicals",
            "dictionaries",
            "bibliography",
            "cookery",
            "handbooks",
            "government",
            "scientific literature",
            " -- drama",
            "plays/films/dramas",
            "correspondence",
            "biographies",
            "essays, letters & speeches",
        )
        return any(signal in haystack for signal in fiction_signals) and not any(
            signal in haystack for signal in excluded
        )

    @staticmethod
    def classify_content_type(candidate: SourceCandidate) -> str:
        haystack = " ".join((*candidate.subjects, *candidate.bookshelves)).lower()
        if "short stories" in haystack:
            return "SHORT_STORY_COLLECTION"
        if "penny dreadful" in haystack or "serial fiction" in haystack:
            return "SERIAL_FICTION"
        if "novella" in haystack:
            return "NOVELLA"
        if "category: novels" in haystack or "novel" in haystack:
            return "NOVEL"
        return "FICTION"
