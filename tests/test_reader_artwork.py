from app.api.system import _artwork_markup, _render_chapter_content
from app.models import ChapterImage


def artwork(*, approved: bool = True, animation_type: str = "drift") -> ChapterImage:
    return ChapterImage(
        chapter_id=1,
        image_type="interval",
        placement_order=1,
        paragraph_anchor=2,
        path="storage/chapter-images/example/chapter/interval-1.webp",
        fallback_path="storage/chapter-images/example/chapter/interval-1.webp",
        alt_text="Fog moving between period houses.",
        width=1400,
        height=875,
        mime_type="image/webp",
        file_size=100,
        animation_type=animation_type,
        content_hash="a" * 64,
        prompt_metadata={},
        approved=approved,
    )


def test_approved_interval_artwork_is_inserted_only_at_a_paragraph_boundary() -> None:
    rendered = _render_chapter_content(
        "<p>First complete paragraph.</p><p>Second complete paragraph.</p><p>Third paragraph.</p>",
        [artwork()],
    )

    assert rendered.index("Second complete paragraph") < rendered.index("chapter-artwork")
    assert rendered.index("chapter-artwork") < rendered.index("Third paragraph")
    assert 'loading="lazy"' in rendered
    assert 'width="1400"' in rendered


def test_artwork_animation_class_is_allowlisted() -> None:
    markup = _artwork_markup(artwork(animation_type="unsafe class"))

    assert "artwork-none" in markup
    assert "unsafe class" not in markup
