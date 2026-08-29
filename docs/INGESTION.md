# Ingestion

The pipeline is discovery, metadata materialization, fiction classification, rights screening, download, immutable raw archive, parse, chapter extraction, completeness/quality review, deduplication, grounded metadata enrichment, cover generation, final review, and publication.

`ImportJob` stores status, checkpoint, attempt count, error, timestamps, retry time, and payload. Jobs lock their row and may be rerun safely. Automatic discovery queues newly created jobs, which stop at `RIGHTS_CHECK`; no source claim can advance itself. Transient failures use exponential retry with a ten-attempt ceiling.

After an approved manual rights record, workers download into `data/source-books/<source>/<external-id>/original.*`. The original is never edited. Parsed database chapters and future processed exports are derivatives. Hashes on sources, editions, and chapters support integrity and duplicate detection.

The operational checkpoints are 20 → 100 → 1,000 → 5,000 → 10,000+. Before advancing, audit false-positive fiction classification, duplicate rate, rights evidence, complete endings, chapter order, rendering, covers, search, performance, storage growth, and takedown readiness. Discovery count is not publication count.
