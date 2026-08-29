# SEO

Published novels, chapters, authors, and non-thin genre pages have crawlable HTML, unique titles/descriptions, canonical URLs, OpenGraph metadata, breadcrumbs, and Book, Chapter, Person, CollectionPage, and BreadcrumbList structured data. The homepage includes WebSite and Organization data. No aggregate rating is emitted unless real approved data exists.

`/sitemap.xml` indexes paged novel and chapter sitemaps plus authors, populated genres, and policy/editorial pages. Pages cap at 10,000 URLs. Admin, accounts, APIs, and unpublished content are excluded; `robots.txt` explicitly disallows internal surfaces.

Production must set `WEBNOVEL_FRONTEND_URL` to the canonical HTTPS origin and build the static homepage canonical/structured data for that origin. Validate structured data, links, mobile rendering, redirects, media dimensions, and sitemap counts at each checkpoint. Do not publish thin genre/author pages or programmatic keyword pages.
