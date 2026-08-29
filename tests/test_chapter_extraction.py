from app.services.chapter_extraction import ChapterExtractionService


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
