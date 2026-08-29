# Chapter extraction

`ChapterExtractionService` prefers EPUB document order, then structured HTML headings, then text headings and patterns. It recognizes numbered, Roman, named-number, chapter/book/part/volume/letter/act headings, prologues, epilogues, prefaces, and introductions. Duplicate slugs receive deterministic order suffixes.

Canonical content text, source bytes, and hashes remain separate from supplementary AI fields. Scripts, frames, objects, event handlers, and unsafe URL schemes are stripped from rendered HTML; this is security sanitation, not literary rewriting. Original raw files remain immutable for comparison.

Quality inspection checks absent/duplicate/tiny chapters, replacement characters, likely OCR noise, unusually short works, and reliable ending markers. A missing ending is `POSSIBLY_INCOMPLETE`; blocking errors are `INCOMPLETE`. Only `COMPLETE` can publish. AI-assisted fallback must be added only as structure detection and may never invent, modernize, summarize, or alter prose.
