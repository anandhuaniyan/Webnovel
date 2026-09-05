from __future__ import annotations

import re
from dataclasses import dataclass

from app.services.chapter_extraction import ExtractedChapter


@dataclass(frozen=True)
class QualityFinding:
    code: str
    severity: str
    message: str
    blocking: bool = True


class CompletenessService:
    def inspect(
        self, chapters: list[ExtractedChapter], *, structural_end_confirmed: bool = False
    ) -> tuple[str, list[QualityFinding]]:
        findings: list[QualityFinding] = []
        if not chapters:
            return "INCOMPLETE", [QualityFinding("NO_CHAPTERS", "ERROR", "No chapters were extracted")]
        hashes = [chapter.content_hash for chapter in chapters]
        if len(hashes) != len(set(hashes)):
            findings.append(QualityFinding("DUPLICATE_CHAPTERS", "ERROR", "Duplicate chapter text detected"))
        if any(chapter.word_count < 20 for chapter in chapters):
            findings.append(
                QualityFinding("TINY_CHAPTER", "WARNING", "One or more chapters contain very little text")
            )
        combined = " ".join(chapter.content_text for chapter in chapters)
        replacement_ratio = combined.count("�") / max(1, len(combined))
        if replacement_ratio > 0.0005:
            findings.append(
                QualityFinding("BROKEN_ENCODING", "ERROR", "Text contains excessive replacement characters")
            )
        ocr_noise = len(re.findall(r"\b\w*[^\w\s'’.,;:!?-]\w*\b", combined)) / max(1, len(combined.split()))
        if ocr_noise > 0.02:
            findings.append(QualityFinding("OCR_CORRUPTION", "WARNING", "Text may contain OCR corruption"))
        ending = chapters[-1].content_text[-1000:].lower()
        ending_signal = bool(
            structural_end_confirmed
            or re.search(r"\b(?:the\s+end|finis)\b|end of the project gutenberg", ending)
        )
        if len(combined.split()) < 3_000:
            findings.append(QualityFinding("TOO_SHORT", "WARNING", "Work is unusually short for a novel"))
        blocking = [finding for finding in findings if finding.blocking and finding.severity == "ERROR"]
        if blocking:
            return "INCOMPLETE", findings
        if not ending_signal:
            findings.append(
                QualityFinding(
                    "ENDING_UNCONFIRMED", "WARNING", "No reliable end marker was detected", blocking=True
                )
            )
            return "POSSIBLY_INCOMPLETE", findings
        return "COMPLETE", findings
