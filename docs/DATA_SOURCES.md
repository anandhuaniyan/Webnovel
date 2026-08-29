# Data sources

Adapters live in `backend/app/services/sources` and return the same `SourceCandidate` contract. Implemented adapters cover Project Gutenberg via Gutendex, Standard Ebooks via OPDS, Wikisource discovery, and an explicit HTTPS JSON-feed adapter for reviewed national/university archives.

Source priority is rights certainty, completeness, structural quality, chapter accuracy, cleanliness, metadata, then source reliability. EPUB is preferred over structured HTML and plain text. A downloadable file or provider-level rights statement is only a lead: the system archives that claim as `SOURCE_CLAIM_UNVERIFIED` and creates a jurisdiction-specific rights review.

Fiction classification uses subjects/bookshelves and excludes periodicals, dictionaries, bibliographies, cookery, handbooks, government material, and scientific literature. Operators must sample classifier decisions at every import checkpoint. New archives require an explicit source row, an adapter, terms review, test fixtures, and an independent per-edition rights workflow.

Wikisource content may be public domain, CC0, CC BY, or CC BY-SA. The exact page/version must be reviewed and exact attribution stored; the adapter never collapses these into “public domain.”
