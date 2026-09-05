from __future__ import annotations

import hashlib
import html as html_stdlib
import re
import warnings
from dataclasses import dataclass
from pathlib import Path

import ebooklib
import nh3
from bs4 import BeautifulSoup, Comment, XMLParsedAsHTMLWarning
from ebooklib import epub
from slugify import slugify

CHAPTER_HEADING = re.compile(
    r"^\s*(?:(?:chapter|book|part|volume|letter|act|stave)\s*"
    r"(?:\d+|[ivxlcdm]+|one|two|three|four|five|six|seven|eight|nine|ten|first|second|third)"
    r"(?:\s*[:.\-–—]\s*.*)?|prologue|epilogue|preface|introduction)\s*$",
    re.IGNORECASE,
)
TRAILING_CHAPTER_HEADING = re.compile(
    r"(?P<title>(?:(?:chapter|book|part|volume|letter|act|stave)\s*"
    r"(?:\d+|[ivxlcdm]+|one|two|three|four|five|six|seven|eight|nine|ten|first|second|third)"
    r"(?:\s*[:.\-–—]\s*[^\n]{0,120})?|prologue|epilogue))\s*[.:]?\s*$",
    re.IGNORECASE,
)
NUMBERED_SECTION_HEADING = re.compile(r"^\s*(?:\d+|[ivxlcdm]+)[.:\-–—]\s+\S.{0,150}$", re.IGNORECASE)
BARE_ROMAN_HEADING = re.compile(r"^\s*[ivxlcdm]+\s*$", re.IGNORECASE)
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
            body_text = body.get_text(" ", strip=True)
            word_count = len(body_text.split())
            if word_count < 20 or "THE FULL PROJECT GUTENBERG" in body_text.upper():
                continue
            extracted = self.extract_html(str(body), require_chapter_heading=True)
            if not extracted and word_count >= 200:
                first_heading = body.find(["h1", "h2", "h3", "h4"])
                title = " ".join(first_heading.get_text(" ", strip=True).split()) if first_heading else ""
                lowered = title.casefold()
                if title and lowered not in {"contents", "table of contents"} and "project gutenberg" not in lowered:
                    extracted = [self._build(1, title, str(body), item.get_content())]
            chapters.extend(extracted)

        reordered = [
            ExtractedChapter(**{**chapter.__dict__, "order": order})
            for order, chapter in enumerate(chapters, start=1)
        ]
        return self._ensure_unique_slugs(reordered)

    @staticmethod
    def has_structural_ending(path: Path) -> bool:
        """Confirm a complete Gutenberg EPUB container without exposing its boilerplate.

        A Gutenberg licence document appearing after substantial narrative spine
        content is an edition-level end boundary. It supplements, but never
        replaces, chapter/content quality checks.
        """
        if path.suffix.lower() != ".epub":
            return False
        book = epub.read_epub(str(path))
        narrative_words = 0
        for idref, _linear in book.spine:
            item = book.get_item_with_id(idref)
            if not item or item.get_type() != ebooklib.ITEM_DOCUMENT:
                continue
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", XMLParsedAsHTMLWarning)
                text = BeautifulSoup(item.get_content(), "lxml").get_text(" ", strip=True)
            if "THE FULL PROJECT GUTENBERG" in text.upper():
                return narrative_words >= 500
            narrative_words += len(text.split())
        return False

    def extract_html(self, html: str, *, require_chapter_heading: bool = False) -> list[ExtractedChapter]:
        soup = BeautifulSoup(html, "lxml")
        body = soup.body or soup
        headings = []
        for heading in soup.find_all(["h1", "h2", "h3", "h4"]):
            title = self._chapter_title(heading.get_text(" ", strip=True))
            if title:
                headings.append((heading, title))
        if not headings:
            if require_chapter_heading:
                return []
            return [self._build(1, "Full Text", str(body), html.encode("utf-8"))]

        marker_prefix = "WEBNOVEL_CHAPTER_BOUNDARY_"
        for index, (heading, _title) in enumerate(headings):
            heading.insert_before(Comment(f"{marker_prefix}{index}"))
        chunks = re.split(rf"<!--{marker_prefix}(\d+)-->", str(body))
        content_by_index = {
            int(chunks[index]): chunks[index + 1]
            for index in range(1, len(chunks) - 1, 2)
        }
        result: list[ExtractedChapter] = []
        for order, (_heading, title) in enumerate(headings, start=1):
            content = content_by_index[order - 1]
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
        if (
            CHAPTER_HEADING.match(compact)
            or NUMBERED_SECTION_HEADING.match(compact)
            or BARE_ROMAN_HEADING.match(compact)
        ):
            candidate = compact
        else:
            trailing = TRAILING_CHAPTER_HEADING.search(compact)
            if not trailing:
                return None
            candidate = trailing.group("title")
        return re.sub(
            r"^(chapter|book|part|volume|letter|act|stave)(?=[\divxlcdm])",
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
