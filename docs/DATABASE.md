# Database

The only accepted database name is `webnovel`, owned locally by `webnovel_app`. Both application configuration and Alembic reject another name. `scripts/verify-database.ps1 -RequireConnection` also checks the running container, Compose project label, current database, and current user before migrations.

The initial Alembic revision creates the requested catalogue, provenance, rights, import, quality, image, reader, community, recommendation, takedown, audit, analytics, and editorial collection tables. It enables `pg_trgm`, creates a weighted full-text vector and trigram title index, seeds normalized genres, and seeds initial sources.

Use migrations for every schema change. Back up before production upgrades, run `alembic upgrade head` in a single deployment step, and never point local tooling at a shared or unrelated PostgreSQL instance. Database records store object paths and hashes; book/image blobs remain in storage.
