# API

Public JSON routes include home groups, paginated novels, novel detail, per-novel chapter lists, one-chapter reader payloads, authors, genres, PostgreSQL search, recommendations, approved reviews, catalogue counts, consent-gated analytics events, and takedowns. HTML routes serve crawlable novel, chapter, author, genre, policy, and takedown pages.

Account routes provide registration/login JWTs, library and favourites, progress, bookmarks, history, continue reading, reader settings, ratings, and moderated reviews. Passwords use Argon2. Tokens expire and inactive accounts are rejected.

Admin routes require `X-Admin-Key` and expose dashboard, jobs, staged discovery, rights approval/rejection, cover/review/contact queues, quality, storage, SEO status, takedowns, and monetization readiness. Novel operations include fail-closed publish/unpublish, ad controls, chapter reprocessing, guarded cover regeneration, and non-destructive duplicate merging into a canonical work. Never place the admin key in client source or Git. The local admin page stores it in session storage only.

API docs are available at `/api/docs` in non-production environments. All public catalogue reads use the central publication filter; consumers must not query database tables directly.
