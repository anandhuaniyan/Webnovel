from app.services.chapter_extraction import ChapterExtractionService
from app.services.deduplication import content_fingerprint, normalize_text
from app.services.quality import CompletenessService


def test_complete_text_requires_reliable_ending() -> None:
    text = "Chapter 1\n\n" + ("A complete narrative sentence. " * 700) + " THE END"
    status, findings = CompletenessService().inspect(
        ChapterExtractionService().extract_text(text)
    )

    assert status == "COMPLETE"
    assert not [finding for finding in findings if finding.severity == "ERROR"]


def test_missing_ending_fails_closed() -> None:
    text = "Chapter 1\n\n" + ("An unfinished narrative sentence. " * 700)
    status, findings = CompletenessService().inspect(
        ChapterExtractionService().extract_text(text)
    )

    assert status == "POSSIBLY_INCOMPLETE"
    assert any(
        finding.code == "ENDING_UNCONFIRMED" and finding.blocking
        for finding in findings
    )


def test_verified_source_container_can_confirm_natural_literary_ending() -> None:
    text = "Chapter 1\n\n" + ("A complete narrative sentence. " * 700)
    status, findings = CompletenessService().inspect(
        ChapterExtractionService().extract_text(text), structural_end_confirmed=True
    )

    assert status == "COMPLETE"
    assert not any(finding.code == "ENDING_UNCONFIRMED" for finding in findings)


def test_duplicate_and_normalization_fingerprints_are_stable() -> None:
    assert (
        normalize_text("  The Count\u2014of Mont\u00e9 Cristo! ")
        == "the count of monte cristo"
    )
    assert content_fingerprint("One\n two") == content_fingerprint(" one   two ")
