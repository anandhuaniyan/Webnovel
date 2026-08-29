# Storage

Raw sources live in `data/source-books`, processed exports in `data/processed-books`, and rights evidence in `data/rights-evidence`. Covers and chapter images live under `storage`; temporary files are the only category eligible for automatic age-based deletion. PostgreSQL and Redis bind mounts, backups, and logs have dedicated project directories.

`StorageService` resolves every path and rejects paths outside the project root. It reports bytes and file counts by category plus total/free disk and configurable 70/80/90 percent warning levels. Image hashes support duplicate detection; Pillow applies EXIF orientation, resizing, and WebP compression. Do not store binaries in PostgreSQL.

Capacity planning targets at least 500 GB. Production may replace local media with S3-compatible storage such as Cloudflare R2 or AWS S3 while retaining object keys and hashes in PostgreSQL. Use versioning/lifecycle rules that never delete rights evidence, immutable raw sources, or approved assets without a reviewed retention policy.
