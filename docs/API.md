# API

Public JSON routes include home groups, paginated novels, novel detail, per-novel chapter lists, one-chapter reader payloads with approved artwork placements, authors, genres, PostgreSQL search, recommendations, approved reviews, catalogue counts, consent-gated analytics events, and takedowns. Catalogue filters cover genre, author, language, publication range, chapter range, maximum reading time, illustrated state, and scalable sort orders. HTML routes serve crawlable novel, chapter, author, genre, policy, and takedown pages.

Account routes provide registration/login JWTs, library and favourites, progress, bookmarks, history, continue reading, reader settings, ratings, and moderated reviews. Passwords use Argon2. Tokens expire and inactive accounts are rejected.

Admin routes require `X-Admin-Key` and expose dashboard, database/Redis/worker status, jobs, staged discovery (paged checkpoints or exact source identifiers), rights approval/rejection, cover/artwork/review/contact queues, quality, storage, SEO status, takedowns, and monetization readiness. Novel operations include fail-closed publish/unpublish, ad controls, chapter reprocessing, guarded cover/artwork generation, artwork moderation, and non-destructive duplicate merging into a canonical work. Never place the admin key in client source or Git. The local admin page stores it in session storage only.

API docs are available at `/api/docs` in non-production environments. All public catalogue reads use the central publication filter; consumers must not query database tables directly.
