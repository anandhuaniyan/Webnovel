# Architecture

Webnovel is an isolated, copyright-first publishing system. Nginx serves the existing static frontend and proxies public, account, admin, policy, reader, and SEO routes to FastAPI. PostgreSQL is authoritative for catalogue and reader state, Redis backs Celery and API rate limiting, and Celery workers execute resumable imports and scheduled reviews. Large binaries live under project storage, never in PostgreSQL.

The content boundary is `WORK → EDITION → SOURCE`. A work describes the intellectual work, an edition captures language/translator/publisher differences, and source items preserve provider identifiers and downloads. The public `Novel` selects one edition. False-negative duplicates can be linked to a canonical work and novel without deleting their provenance; future discovery follows that canonical link. This avoids treating two translations as interchangeable or a second repository copy as a new novel.

The public boundary is deliberately narrow. Every public query applies the same publication filter: `published=true`, no canonical merge target, `completeness_status=COMPLETE`, and an approved rights status. Final publication also requires current independent rights evidence, no blocking quality issues, readable chapters, and an approved original cover. Admin and worker operations are separate from reader APIs.

All persistent paths, Compose labels, ports, containers, volumes, and the database identity are guarded by the preflight and migration scripts. See `ISOLATION.md`.

## Scale path

Workers are horizontally scalable, source adapters are stateless, public lists use server-side pagination, search uses PostgreSQL GIN/trigram indexes, and sitemaps are split at 10,000 URLs. The validation gates are 20, 100, 1,000, 5,000, then 10,000+. Advancing a gate is an operational decision based on rights, content, reader, search, SEO, cover, and performance audits—not a change that weakens publication rules.
