from pathlib import Path

from app.services.chapter_extraction import ChapterExtractionService
from ebooklib import epub


def test_extracts_roman_named_and_numbered_chapters_in_order() -> None:
    source = """CHAPTER I

This is the opening paragraph with enough words to represent a small but useful chapter body for testing.

Chapter Two

This is the second paragraph with enough words to preserve ordering and produce a distinct content hash.

Epilogue

This is the final paragraph and THE END of the complete sample story used in the extraction test.
"""
    chapters = ChapterExtractionService().extract_text(source)

    assert [chapter.title for chapter in chapters] == [
        "CHAPTER I",
        "Chapter Two",
        "Epilogue",
    ]
    assert [chapter.order for chapter in chapters] == [1, 2, 3]
    assert len({chapter.slug for chapter in chapters}) == 3
    assert all(len(chapter.content_hash) == 64 for chapter in chapters)


def test_source_text_is_escaped_and_dangerous_markup_removed() -> None:
    chapters = ChapterExtractionService().extract_text(
        "Chapter 1\n\nA literal <script>alert('x')</script> marker and <b>source</b> characters."
    )

    assert "<script>" not in chapters[0].content_html
    assert "&lt;script&gt;" in chapters[0].content_html
    assert "A literal <script>" in chapters[0].content_text


def test_html_event_handlers_and_unsafe_urls_are_removed() -> None:
    chapters = ChapterExtractionService().extract_html(
        "<h1>Chapter 1</h1><p onclick='bad()'>Safe text <a href='javascript:bad()'>link</a></p>"
    )

    assert "onclick" not in chapters[0].content_html
    assert "javascript:" not in chapters[0].content_html
    assert "Safe text" in chapters[0].content_text
    assert "link" in chapters[0].content_text


def test_epub_splits_embedded_chapters_and_drops_gutenberg_boilerplate(tmp_path: Path) -> None:
    book = epub.EpubBook()
    book.set_identifier("test-book")
    book.set_title("Test Book")
    book.set_language("en")
    content = epub.EpubHtml(title="Story", file_name="story.xhtml", lang="en")
    content.content = """
    <header class="pg-boilerplate" id="pg-header"><p>Project Gutenberg header</p></header>
    <h2><span class="caption">An illustration caption.</span> CHAPTER I.</h2>
    <p>This is the opening chapter with enough useful words to be retained by the EPUB extractor.<span class="x-ebookmaker-pageno">{2}</span></p>
    <div class="figcenter"><p>Decorative plate caption and copyright notice.</p></div>
    <h2>CHAPTER II.</h2>
    <p>This is the second chapter with enough different words to verify that ordering is preserved.</p>
    <footer class="pg-boilerplate" id="pg-footer"><h2>THE FULL PROJECT GUTENBERG LICENSE</h2></footer>
    """
    book.add_item(content)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav", content]
    target = tmp_path / "book.epub"
    epub.write_epub(str(target), book)

    chapters = ChapterExtractionService().extract_epub(target)

    assert [chapter.title for chapter in chapters] == ["CHAPTER I.", "CHAPTER II."]
    assert [chapter.order for chapter in chapters] == [1, 2]
    assert all("Gutenberg" not in chapter.content_text for chapter in chapters)
    assert all("{2}" not in chapter.content_text for chapter in chapters)
    assert all("Decorative plate" not in chapter.content_text for chapter in chapters)


def test_epub_supports_staves_bare_roman_parts_and_spine_titled_chapters(tmp_path: Path) -> None:
    book = epub.EpubBook()
    book.set_identifier("period-fiction")
    book.set_title("Period Fiction")
    book.set_language("en")
    embedded = epub.EpubHtml(title="Embedded", file_name="embedded.xhtml", lang="en")
    embedded.content = "<h2>STAVE ONE.</h2><p>" + ("Winter words. " * 120) + "</p><h2>STAVE TWO.</h2><p>" + ("Morning words. " * 120) + "</p>"
    roman = epub.EpubHtml(title="Part", file_name="part.xhtml", lang="en")
    roman.content = "<h1>III</h1><p>" + ("River words. " * 120) + "</p>"
    titled = epub.EpubHtml(title="Door", file_name="door.xhtml", lang="en")
    titled.content = "<h1>STORY OF THE DOOR</h1><p>" + ("Street words. " * 120) + "</p>"
    licence = epub.EpubHtml(title="Licence", file_name="license.xhtml", lang="en")
    licence.content = "<h1>THE FULL PROJECT GUTENBERG LICENSE</h1><p>" + ("Licence words. " * 600) + "</p>"
    for item in (embedded, roman, titled, licence):
        book.add_item(item)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav", embedded, roman, titled, licence]
    target = tmp_path / "period-fiction.epub"
    epub.write_epub(str(target), book)

    chapters = ChapterExtractionService().extract_epub(target)

    assert [chapter.title for chapter in chapters] == [
        "STAVE ONE.", "STAVE TWO.", "III", "STORY OF THE DOOR"
    ]
    assert ChapterExtractionService.has_structural_ending(target)
    assert all("LICENSE" not in chapter.content_text for chapter in chapters)
