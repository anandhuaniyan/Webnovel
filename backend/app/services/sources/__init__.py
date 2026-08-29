from app.services.sources.base import SourceAdapter, SourceCandidate
from app.services.sources.gutenberg import GutenbergAdapter
from app.services.sources.other_archive import OtherArchiveAdapter
from app.services.sources.standard_ebooks import StandardEbooksAdapter
from app.services.sources.wikisource import WikisourceAdapter

__all__ = [
    "SourceAdapter",
    "SourceCandidate",
    "GutenbergAdapter",
    "StandardEbooksAdapter",
    "WikisourceAdapter",
    "OtherArchiveAdapter",
]
