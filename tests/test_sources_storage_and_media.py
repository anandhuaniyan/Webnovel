import os
from pathlib import Path
from types import SimpleNamespace

from app.core.enums import IllustrationMode
from app.services.covers import CoverBrief, CoverGenerationService
from app.services.illustrations import ChapterIllustrationService
from app.services.sources.base import SourceAdapter, SourceCandidate
from app.services.storage import StorageService
from PIL import Image


def candidate(subjects: tuple[str, ...]) -> SourceCandidate:
    return SourceCandidate(
        source_code="test",
        external_id="1",
        title="A title",
        authors=("An Author",),
        languages=("en",),
        subjects=subjects,
    )


def test_fiction_classifier_excludes_catalogue_inflation() -> None:
    assert SourceAdapter.is_fiction(candidate(("Detective fiction",)))
    assert not SourceAdapter.is_fiction(
        candidate(("Government handbooks", "Fiction bibliography"))
    )
    assert not SourceAdapter.is_fiction(candidate(("Scientific literature",)))
    assert not SourceAdapter.is_fiction(
        candidate(("Tragedies (Drama)", "Category: Plays/Films/Dramas"))
    )


def test_incomplete_multi_volume_titles_and_content_types_are_detected() -> None:
    partial = candidate(("Fairy tales", "Category: Romance"))
    partial = SourceCandidate(
        **{**partial.__dict__, "title": "Stories — Volume 01 (of 10)"}
    )
    assert not SourceAdapter.is_fiction(partial)
    stories = candidate(("Fiction", "Category: Short Stories"))
    assert SourceAdapter.classify_content_type(stories) == "SHORT_STORY_COLLECTION"


def test_temporary_cleanup_never_targets_other_categories(tmp_path: Path) -> None:
    service = StorageService()
    service.root = tmp_path
    temporary = tmp_path / "temporary"
    evidence = tmp_path / "rights-evidence"
    temporary.mkdir()
    evidence.mkdir()
    expired = temporary / "expired.part"
    protected = evidence / "proof.json"
    expired.write_text("temporary", encoding="utf-8")
    protected.write_text("never delete", encoding="utf-8")
    os.utime(expired, (1, 1))
    service.categories = {"temporary": temporary}

    result = service.cleanup_temporary_files(older_than_hours=1)

    assert result["removed"] == 1
    assert not expired.exists()
    assert protected.exists()


class SolidCoverProvider:
    def generate(self, brief: CoverBrief, output_path: Path) -> Path:
        Image.new("RGB", (600, 900), "#204b3b").save(output_path)
        return output_path


def test_cover_variants_are_original_local_optimized_assets(tmp_path: Path) -> None:
    service = CoverGenerationService(provider=SolidCoverProvider())
    service.settings = SimpleNamespace(storage_path=tmp_path, project_root=tmp_path)
    service.cover_root = tmp_path / "covers"
    brief = CoverBrief(
        "Title", "Author", "Gothic", "A house", "Victorian", "memory", "Overview"
    )

    variants = service.generate_variants(brief, "title")

    assert set(variants) == {"portrait", "thumbnail", "open_graph"}
    assert all((tmp_path / path).suffix == ".webp" for path in variants.values())
    assert all((tmp_path / path).exists() for path in variants.values())


def test_illustration_modes_are_conservative() -> None:
    should = ChapterIllustrationService.should_generate
    assert not should(IllustrationMode.NONE.value, 5)
    assert should(IllustrationMode.EVERY_5_CHAPTERS.value, 10)
    assert not should(IllustrationMode.EVERY_10_CHAPTERS.value, 5)
    assert should(IllustrationMode.AI_SELECTED.value, 3, ai_selected=True)
