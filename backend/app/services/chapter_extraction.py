from __future__ import annotations

import hashlib
import html as html_stdlib
import re
import warnings
from dataclasses import dataclass
from pathlib import Path

import ebooklib
import nh3
from bs4 import BeautifulSoup, Tag, XMLParsedAsHTMLWarning
from ebooklib import epub
from slugify import slugify

CHAPTER_HEADING = re.compile(
    r"^\s*(?:(?:chapter|book|part|volume|letter|act)\s*"
    r"(?:\d+|[ivxlcdm]+|one|two|three|four|five|six|seven|eight|nine|ten|first|second|third)"
    r"(?:\s*[:.\-–—]\s*.*)?|prologue|epilogue|preface|introduction)\s*$",
    re.IGNORECASE,
)
TRAILING_CHAPTER_HEADING = re.compile(
    r"(?P<title>(?:(?:chapter|book|part|volume|letter|act)\s*"
    r"(?:\d+|[ivxlcdm]+|one|two|three|four|five|six|seven|eight|nine|ten|first|second|third)"
    r"(?:\s*[:.\-–—]\s*[^\n]{0,120})?|prologue|epilogue))\s*[.:]?\s*$",
    re.IGNORECASE,
)
NUMBERED_SECTION_HEADING = re.compile(r"^\s*(?:\d+|[ivxlcdm]+)[.:\-–—]\s+\S.{0,150}$", re.IGNORECASE)
NON_CONTENT_DOCUMENT = re.compile(r"(?:^|[/_.-])(?:cover|nav|toc|wrap\d*|colophon)(?:[/_.-]|$)", re.IGNORECASE)


@dataclass(frozen=True)
class ExtractedChapter:
    order: int
    number: int | None
    title: str
    slug: str
    content_html: str
    content_text: str
    word_count: int
    estimated_reading_minutes: int
    source_hash: str
    content_hash: str


class ChapterExtractionService:
    def extract(self, path: Path) -> list[ExtractedChapter]:
        suffix = path.suffix.lower()
        if suffix == ".epub":
            return self.extract_epub(path)
        if suffix in {".html", ".htm", ".xhtml"}:
            return self.extract_html(path.read_text(encoding="utf-8", errors="replace"))
        return self.extract_text(path.read_text(encoding="utf-8", errors="replace"))

    def extract_epub(self, path: Path) -> list[ExtractedChapter]:
        book = epub.read_epub(str(path))
        chapters: list[ExtractedChapter] = []
        items = []
        for idref, _linear in book.spine:
            item = book.get_item_with_id(idref)
            if item and item.get_type() == ebooklib.ITEM_DOCUMENT:
                items.append(item)
        if not items:
            items = list(book.get_items_of_type(ebooklib.ITEM_DOCUMENT))

        for item in items:
            if NON_CONTENT_DOCUMENT.search(item.get_name()):
                continue
            html = item.get_content().decode("utf-8", errors="replace")
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", XMLParsedAsHTMLWarning)
                soup = BeautifulSoup(html, "lxml")
            for boilerplate in soup.select(
                "header.pg-boilerplate, footer.pg-boilerplate, #pg-header, #pg-footer, #pg-machine-header, "
                ".x-ebookmaker-pageno, .figcenter, .figleft, .figright, .caption, .fint"
            ):
                boilerplate.decompose()
            body = soup.body or soup
            if len(body.get_text(" ", strip=True).split()) < 20:
                continue
            chapters.extend(self.extract_html(str(body), require_chapter_heading=True))

        reordered = [
            ExtractedChapter(**{**chapter.__dict__, "order": order})
            for order, chapter in enumerate(chapters, start=1)
        ]
        return self._ensure_unique_slugs(reordered)

    def extract_html(self, html: str, *, require_chapter_heading: bool = False) -> list[ExtractedChapter]:
        soup = BeautifulSoup(html, "lxml")
        body = soup.body or soup
        headings = []
        for heading in soup.find_all(["h1", "h2", "h3", "h4"]):
            title = self._chapter_title(heading.get_text(" ", strip=True))
            if title:
                boundary = heading
                while isinstance(boundary.parent, Tag) and boundary.parent is not body:
                    boundary = boundary.parent
                headings.append((boundary, title))
        if not headings:
            if require_chapter_heading:
                return []
            return [self._build(1, "Full Text", str(body), html.encode("utf-8"))]

        result: list[ExtractedChapter] = []
        boundary_tags = {id(boundary) for boundary, _title in headings}
        for order, (boundary, title) in enumerate(headings, start=1):
            parts: list[str] = [str(boundary)]
            for sibling in boundary.next_siblings:
                if isinstance(sibling, Tag) and id(sibling) in boundary_tags:
                    break
                if (
                    isinstance(sibling, Tag)
                    and sibling.find(["h1", "h2", "h3", "h4"])
                    and any(
                        self._chapter_title(candidate.get_text(" ", strip=True))
                        for candidate in sibling.find_all(["h1", "h2", "h3", "h4"])
                    )
                ):
                    break
                parts.append(str(sibling))
            content = "".join(parts)
            result.append(self._build(order, title, content, content.encode()))
        return self._ensure_unique_slugs(result)

    def extract_text(self, text: str) -> list[ExtractedChapter]:
        lines = text.splitlines()
        boundaries = [index for index, line in enumerate(lines) if self._looks_like_chapter(line)]
        if not boundaries:
            return [self._build(1, "Full Text", self._text_to_html(text), text.encode())]
        boundaries.append(len(lines))
        chapters = []
        for order, (start, end) in enumerate(zip(boundaries, boundaries[1:], strict=False), start=1):
            title = lines[start].strip()
            content = "\n".join(lines[start:end]).strip()
            chapters.append(self._build(order, title, self._text_to_html(content), content.encode()))
        return self._ensure_unique_slugs(chapters)

    @staticmethod
    def _looks_like_chapter(title: str) -> bool:
        return ChapterExtractionService._chapter_title(title) is not None

    @staticmethod
    def _chapter_title(title: str) -> str | None:
        compact = " ".join(title.split())
        if not compact or len(compact) > 320:
            return None
        if CHAPTER_HEADING.match(compact) or NUMBERED_SECTION_HEADING.match(compact):
            candidate = compact
        else:
            trailing = TRAILING_CHAPTER_HEADING.search(compact)
            if not trailing:
                return None
            candidate = trailing.group("title")
        return re.sub(
            r"^(chapter|book|part|volume|letter|act)(?=[\divxlcdm])",
            r"\1 ",
            candidate,
            flags=re.IGNORECASE,
        )

    @staticmethod
    def _text_to_html(text: str) -> str:
        paragraphs = [paragraph.strip() for paragraph in re.split(r"\n\s*\n", text) if paragraph.strip()]
        return "".join(f"<p>{html_stdlib.escape(p)}</p>" for p in paragraphs)

    @staticmethod
    def _build(order: int, title: str, html: str, source_bytes: bytes) -> ExtractedChapter:
        soup = BeautifulSoup(html, "lxml")
        for element in soup(["script", "style", "iframe", "object"]):
            element.decompose()
        text = soup.get_text("\n", strip=True)
        clean_html = nh3.clean(
            str(soup.body or soup),
            tags={
                "a",
                "abbr",
                "blockquote",
                "br",
                "cite",
                "code",
                "dd",
                "div",
                "dl",
                "dt",
                "em",
                "figcaption",
                "figure",
                "h1",
                "h2",
                "h3",
                "h4",
                "h5",
                "h6",
                "hr",
                "i",
                "li",
                "ol",
                "p",
                "pre",
                "q",
                "small",
                "span",
                "strong",
                "sub",
                "sup",
                "table",
                "tbody",
                "td",
                "tfoot",
                "th",
                "thead",
                "tr",
                "u",
                "ul",
            },
            attributes={"a": {"href", "title"}, "*": {"lang"}},
            url_schemes={"http", "https", "mailto"},
            link_rel="noopener noreferrer",
        )
        words = len(re.findall(r"\b[\w’'-]+\b", text))
        number_match = re.search(r"\b(\d+)\b", title)
        return ExtractedChapter(
            order=order,
            number=int(number_match.group(1)) if number_match else None,
            title=title[:500],
            slug=slugify(title)[:220] or f"chapter-{order}",
            content_html=clean_html,
            content_text=text,
            word_count=words,
            estimated_reading_minutes=max(1, round(words / 225)),
            source_hash=hashlib.sha256(source_bytes).hexdigest(),
            content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        )

    @staticmethod
    def _ensure_unique_slugs(chapters: list[ExtractedChapter]) -> list[ExtractedChapter]:
        seen: set[str] = set()
        result: list[ExtractedChapter] = []
        for chapter in chapters:
            slug = chapter.slug
            if slug in seen:
                slug = f"{slug}-{chapter.order}"
            seen.add(slug)
            result.append(ExtractedChapter(**{**chapter.__dict__, "slug": slug}))
        return result
