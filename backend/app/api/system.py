from __future__ import annotations

import html
import json
import math
from xml.sax.saxutils import escape

import nh3
from fastapi import APIRouter, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse, PlainTextResponse, Response
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.models import (
    Author,
    Chapter,
    ContactRequest,
    Genre,
    Novel,
    NovelGenre,
    RightsRecord,
    Source,
    SourceItem,
    TakedownRequest,
)
from app.services.catalog import publication_filter

router = APIRouter(tags=["system"])


@router.get("/health")
def health(db: Session = Depends(get_db)) -> dict:
    db.execute(text("SELECT 1"))
    return {"status": "healthy", "service": "webnovel_backend"}


@router.get("/robots.txt", response_class=PlainTextResponse)
def robots() -> str:
    base = get_settings().public_base_url.rstrip("/")
    return f"User-agent: *\nAllow: /\nDisallow: /api/\nDisallow: /admin\nDisallow: /account\nSitemap: {base}/sitemap.xml\n"


@router.get("/ads.txt", response_class=PlainTextResponse)
def ads_txt() -> str:
    settings = get_settings()
    if not settings.adsense_publisher_id:
        return "# Ad inventory is disabled until a real publisher ID is configured.\n"
    return f"google.com, {settings.adsense_publisher_id}, DIRECT, f08c47fec0942fa0\n"


@router.get("/sitemap.xml")
def sitemap_index(db: Session = Depends(get_db)) -> Response:
    settings = get_settings()
    base = settings.public_base_url.rstrip("/")
    count = db.scalar(select(func.count(Novel.id)).where(*publication_filter())) or 0
    pages = max(1, math.ceil(count / 10_000))
    locations = [f"{base}/sitemaps/novels-{page}.xml" for page in range(1, pages + 1)]
    chapter_count = (
        db.scalar(
            select(func.count(Chapter.id))
            .join(Novel, Novel.id == Chapter.novel_id)
            .where(*publication_filter())
        )
        or 0
    )
    chapter_pages = max(1, math.ceil(chapter_count / 10_000))
    locations += [f"{base}/sitemaps/chapters-{page}.xml" for page in range(1, chapter_pages + 1)]
    locations += [f"{base}/sitemaps/authors.xml", f"{base}/sitemaps/genres.xml", f"{base}/sitemaps/pages.xml"]
    body = "".join(f"<sitemap><loc>{escape(url)}</loc></sitemap>" for url in locations)
    return Response(
        f'<?xml version="1.0" encoding="UTF-8"?><sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{body}</sitemapindex>',
        media_type="application/xml",
    )


@router.get("/sitemaps/novels-{page}.xml")
def novels_sitemap(page: int, db: Session = Depends(get_db)) -> Response:
    base = get_settings().public_base_url.rstrip("/")
    novels = db.scalars(
        select(Novel)
        .where(*publication_filter())
        .order_by(Novel.id)
        .offset((max(page, 1) - 1) * 10_000)
        .limit(10_000)
    ).all()
    body = "".join(
        f"<url><loc>{escape(base + '/novels/' + novel.slug)}</loc><lastmod>{novel.updated_at.date().isoformat()}</lastmod></url>"
        for novel in novels
    )
    return Response(
        f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{body}</urlset>',
        media_type="application/xml",
    )


@router.get("/sitemaps/chapters-{page}.xml")
def chapters_sitemap(page: int, db: Session = Depends(get_db)) -> Response:
    base = get_settings().public_base_url.rstrip("/")
    rows = db.execute(
        select(Chapter, Novel)
        .join(Novel, Novel.id == Chapter.novel_id)
        .where(*publication_filter())
        .order_by(Chapter.id)
        .offset((max(page, 1) - 1) * 10_000)
        .limit(10_000)
    ).all()
    body = "".join(
        f"<url><loc>{escape(base + '/novels/' + novel.slug + '/chapters/' + chapter.chapter_slug)}</loc>"
        f"<lastmod>{chapter.updated_at.date().isoformat()}</lastmod></url>"
        for chapter, novel in rows
    )
    return Response(
        f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{body}</urlset>',
        media_type="application/xml",
    )


@router.get("/sitemaps/authors.xml")
def authors_sitemap(db: Session = Depends(get_db)) -> Response:
    base = get_settings().public_base_url.rstrip("/")
    authors = db.scalars(
        select(Author)
        .join(Novel, Novel.primary_author_id == Author.id)
        .where(*publication_filter())
        .distinct()
    ).all()
    body = "".join(f"<url><loc>{escape(base + '/authors/' + author.slug)}</loc></url>" for author in authors)
    return Response(
        f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{body}</urlset>',
        media_type="application/xml",
    )


@router.get("/sitemaps/genres.xml")
def genres_sitemap(db: Session = Depends(get_db)) -> Response:
    base = get_settings().public_base_url.rstrip("/")
    genres = db.scalars(
        select(Genre)
        .join(NovelGenre, NovelGenre.genre_id == Genre.id)
        .join(Novel, Novel.id == NovelGenre.novel_id)
        .where(*publication_filter())
        .distinct()
        .order_by(Genre.slug)
    ).all()
    body = "".join(f"<url><loc>{escape(base + '/genres/' + genre.slug)}</loc></url>" for genre in genres)
    return Response(
        f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{body}</urlset>',
        media_type="application/xml",
    )


@router.get("/sitemaps/pages.xml")
def pages_sitemap() -> Response:
    base = get_settings().public_base_url.rstrip("/")
    pages = ["", "about", "privacy", "terms", "cookies", "contact", "copyright", "takedown", "accessibility"]
    body = "".join(f"<url><loc>{escape(base + '/' + page)}</loc></url>" for page in pages)
    return Response(
        f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{body}</urlset>',
        media_type="application/xml",
    )


def _asset_url(path: str | None) -> str | None:
    if not path:
        return None
    normalized = path.replace("\\", "/").removeprefix("storage/")
    return f"/media/{normalized.lstrip('/')}"


def _document(title: str, description: str, canonical: str, body: str, structured_data: dict) -> str:
    base = get_settings().public_base_url.rstrip("/")
    structured = json.dumps(structured_data, ensure_ascii=False).replace("</", "<\\/")
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)} — Webnovel</title>
<meta name="description" content="{html.escape(description[:320], quote=True)}">
<meta property="og:title" content="{html.escape(title, quote=True)}"><meta property="og:description" content="{html.escape(description[:320], quote=True)}">
<meta property="og:type" content="book"><meta property="og:url" content="{html.escape(canonical, quote=True)}">
<link rel="canonical" href="{html.escape(canonical, quote=True)}"><link rel="stylesheet" href="/reader.css?v=20260829">
<script type="application/ld+json">{structured}</script></head>
<body><header class="site-header"><a class="brand" href="/" aria-label="Webnovel home">W <span>Webnovel</span></a><nav><a href="/">Discover</a><a href="/account">Account</a></nav></header>
{body}<footer><p>Complete fiction, independently reviewed for rights and integrity.</p><nav><a href="/about">About</a><a href="/copyright">Copyright &amp; sources</a><a href="/privacy">Privacy</a><a href="/takedown">Takedown</a></nav><small>© Webnovel · {html.escape(base)}</small></footer></body></html>"""


def _published_novel(db: Session, slug: str) -> Novel:
    novel = db.scalar(select(Novel).where(Novel.slug == slug, *publication_filter()))
    if not novel:
        raise HTTPException(status_code=404, detail="Novel not found")
    return novel


def _book_cards(novels: list[Novel], authors: dict[int, Author]) -> str:
    cards = []
    for novel in novels:
        author = authors.get(novel.primary_author_id) if novel.primary_author_id else None
        author_line = (
            f'<a href="/authors/{html.escape(author.slug)}">{html.escape(author.name)}</a>'
            if author
            else "Unknown author"
        )
        cover = _asset_url(novel.thumbnail_path or novel.cover_path)
        visual = (
            f'<img src="{html.escape(cover, quote=True)}" alt="Cover of {html.escape(novel.title, quote=True)}" loading="lazy">'
            if cover
            else '<span class="cover-placeholder" aria-hidden="true">W</span>'
        )
        cards.append(
            f'<article class="book-card"><a class="cover" href="/novels/{html.escape(novel.slug)}">{visual}</a>'
            f'<div><h2><a href="/novels/{html.escape(novel.slug)}">{html.escape(novel.title)}</a></h2>'
            f"<p>by {author_line}</p><small>{novel.chapter_count:,} chapters · {novel.total_words:,} words</small></div></article>"
        )
    return "".join(cards)


@router.get("/novels/{slug}", response_class=HTMLResponse)
def novel_page(slug: str, db: Session = Depends(get_db)) -> HTMLResponse:
    novel = _published_novel(db, slug)
    author = db.get(Author, novel.primary_author_id) if novel.primary_author_id else None
    genres = db.scalars(
        select(Genre)
        .join(NovelGenre, NovelGenre.genre_id == Genre.id)
        .where(NovelGenre.novel_id == novel.id)
        .order_by(NovelGenre.is_primary.desc(), Genre.name)
    ).all()
    chapters = db.scalars(
        select(Chapter).where(Chapter.novel_id == novel.id).order_by(Chapter.chapter_order)
    ).all()
    rights = db.scalar(
        select(RightsRecord)
        .where(RightsRecord.edition_id == novel.edition_id)
        .order_by(RightsRecord.updated_at.desc())
        .limit(1)
    )
    source_row = db.execute(
        select(SourceItem, Source)
        .join(Source, Source.id == SourceItem.source_id)
        .where(SourceItem.edition_id == novel.edition_id)
        .order_by(SourceItem.id)
        .limit(1)
    ).first()
    source_item, source = source_row if source_row else (None, None)
    base = get_settings().public_base_url.rstrip("/")
    canonical = f"{base}/novels/{novel.slug}"
    description = (
        novel.seo_description
        or novel.description
        or novel.ai_synopsis
        or f"Read the complete text of {novel.title}."
    )
    cover = _asset_url(novel.cover_path)
    cover_markup = (
        f'<img class="hero-cover" src="{html.escape(cover, quote=True)}" alt="Cover of {html.escape(novel.title, quote=True)}">'
        if cover
        else '<div class="hero-cover cover-placeholder" aria-hidden="true">W</div>'
    )
    author_markup = (
        f'<a href="/authors/{html.escape(author.slug)}">{html.escape(author.name)}</a>'
        if author
        else "Unknown author"
    )
    genre_markup = "".join(
        f'<a class="pill" href="/genres/{html.escape(genre.slug)}">{html.escape(genre.name)}</a>'
        for genre in genres
    )
    chapter_markup = "".join(
        f'<li><a href="/novels/{html.escape(novel.slug)}/chapters/{html.escape(chapter.chapter_slug)}">'
        f"<span>{html.escape(chapter.chapter_title)}</span><small>{chapter.estimated_reading_minutes} min</small></a></li>"
        for chapter in chapters
    )
    first_link = (
        f"/novels/{novel.slug}/chapters/{chapters[0].chapter_slug}" if chapters else f"/novels/{novel.slug}"
    )
    enhancements = "".join(
        f"<section><h2>{label}</h2><p>{html.escape(value)}</p></section>"
        for label, value in (
            ("Synopsis", novel.ai_synopsis),
            ("Themes", novel.themes),
            ("Setting", novel.setting),
            ("Character guide", novel.character_guide),
            ("Literary context", novel.literary_context),
        )
        if value
    )
    rights_status = html.escape(rights.status if rights else novel.rights_status)
    rights_details = []
    if rights and rights.licence_name:
        rights_details.append(f"Licence: {html.escape(rights.licence_name)}")
    if rights and rights.jurisdiction:
        rights_details.append(f"Jurisdiction reviewed: {html.escape(rights.jurisdiction)}")
    if source_item and source:
        rights_details.append(
            f'Source edition: <a rel="nofollow noopener" href="{html.escape(source_item.source_url, quote=True)}">{html.escape(source.name)}</a>'
        )
    rights_markup = " · ".join(rights_details) or "Rights evidence is retained in the publication record."
    body = f"""<main class="book-page"><nav class="breadcrumbs" aria-label="Breadcrumb"><a href="/">Home</a> / <span>{html.escape(novel.title)}</span></nav>
<section class="book-hero">{cover_markup}<div><p class="eyebrow">Complete · Rights reviewed</p><h1>{html.escape(novel.title)}</h1><p class="byline">by {author_markup}</p><div class="pills">{genre_markup}</div><p>{html.escape(description)}</p><dl class="facts"><div><dt>Chapters</dt><dd>{novel.chapter_count:,}</dd></div><div><dt>Words</dt><dd>{novel.total_words:,}</dd></div><div><dt>Reading time</dt><dd>{novel.estimated_reading_minutes:,} min</dd></div></dl><a class="primary-action" href="{html.escape(first_link)}">Start reading</a></div></section>
<div class="book-columns"><div>{enhancements}<section class="rights"><h2>Copyright and source</h2><p><strong>{rights_status}</strong> · {rights_markup}</p><p>The selected edition passed manual, jurisdiction-specific review. Source availability alone is never treated as permission.</p></section></div>
<section><h2>Contents</h2><ol class="chapter-list">{chapter_markup}</ol></section></div></main>"""
    structured = {
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "Book",
                "@id": canonical,
                "name": novel.title,
                "url": canonical,
                "description": description,
                "inLanguage": novel.language,
                "author": {"@type": "Person", "name": author.name, "url": f"{base}/authors/{author.slug}"}
                if author
                else None,
                "genre": [genre.name for genre in genres],
                "image": f"{base}{cover}" if cover else None,
                "isAccessibleForFree": True,
                "license": rights.licence_url if rights else None,
            },
            {
                "@type": "BreadcrumbList",
                "itemListElement": [
                    {"@type": "ListItem", "position": 1, "name": "Home", "item": base},
                    {"@type": "ListItem", "position": 2, "name": novel.title, "item": canonical},
                ],
            },
        ],
    }
    return HTMLResponse(_document(novel.seo_title or novel.title, description, canonical, body, structured))


@router.get("/novels/{slug}/chapters/{chapter_slug}", response_class=HTMLResponse)
def chapter_page(slug: str, chapter_slug: str, db: Session = Depends(get_db)) -> HTMLResponse:
    novel = _published_novel(db, slug)
    chapter = db.scalar(
        select(Chapter).where(Chapter.novel_id == novel.id, Chapter.chapter_slug == chapter_slug)
    )
    if not chapter:
        raise HTTPException(status_code=404, detail="Chapter not found")
    previous = db.scalar(
        select(Chapter)
        .where(Chapter.novel_id == novel.id, Chapter.chapter_order < chapter.chapter_order)
        .order_by(Chapter.chapter_order.desc())
        .limit(1)
    )
    following = db.scalar(
        select(Chapter)
        .where(Chapter.novel_id == novel.id, Chapter.chapter_order > chapter.chapter_order)
        .order_by(Chapter.chapter_order)
        .limit(1)
    )
    base = get_settings().public_base_url.rstrip("/")
    canonical = f"{base}/novels/{novel.slug}/chapters/{chapter.chapter_slug}"
    prev_link = (
        f"/novels/{novel.slug}/chapters/{previous.chapter_slug}" if previous else f"/novels/{novel.slug}"
    )
    next_link = (
        f"/novels/{novel.slug}/chapters/{following.chapter_slug}" if following else f"/novels/{novel.slug}"
    )
    clean_content = nh3.clean(chapter.content_html)
    body = f"""<main class="reader-page"><nav class="breadcrumbs" aria-label="Breadcrumb"><a href="/">Home</a> / <a href="/novels/{html.escape(novel.slug)}">{html.escape(novel.title)}</a> / <span>{html.escape(chapter.chapter_title)}</span></nav>
<header class="chapter-header"><p class="eyebrow">Chapter {chapter.chapter_order} of {novel.chapter_count}</p><h1>{html.escape(chapter.chapter_title)}</h1><p>{chapter.word_count:,} words · about {chapter.estimated_reading_minutes} minutes</p></header>
<article class="prose">{clean_content}</article><nav class="chapter-nav"><a rel="prev" href="{html.escape(prev_link)}">← Previous</a><a href="/novels/{html.escape(novel.slug)}">Contents</a><a rel="next" href="{html.escape(next_link)}">Next →</a></nav></main>"""
    structured = {
        "@context": "https://schema.org",
        "@type": "Chapter",
        "name": chapter.chapter_title,
        "position": chapter.chapter_order,
        "url": canonical,
        "isPartOf": {"@type": "Book", "name": novel.title, "url": f"{base}/novels/{novel.slug}"},
    }
    return HTMLResponse(
        _document(
            f"{chapter.chapter_title} — {novel.title}",
            f"Read {chapter.chapter_title} from {novel.title}.",
            canonical,
            body,
            structured,
        )
    )


@router.get("/authors/{slug}", response_class=HTMLResponse)
def author_page(slug: str, db: Session = Depends(get_db)) -> HTMLResponse:
    author = db.scalar(select(Author).where(Author.slug == slug))
    if not author:
        raise HTTPException(status_code=404, detail="Author not found")
    novels = list(
        db.scalars(
            select(Novel)
            .where(Novel.primary_author_id == author.id, *publication_filter())
            .order_by(Novel.title)
        ).all()
    )
    if not novels:
        raise HTTPException(status_code=404, detail="Author not found")
    authors = {author.id: author}
    base = get_settings().public_base_url.rstrip("/")
    canonical = f"{base}/authors/{author.slug}"
    description = author.biography or f"Browse complete, rights-reviewed editions by {author.name}."
    dates = " – ".join(
        value
        for value in (str(author.birth_date or ""), str(author.death_date or author.death_year or ""))
        if value
    )
    body = f'<main class="listing-page"><nav class="breadcrumbs"><a href="/">Home</a> / Authors / {html.escape(author.name)}</nav><header><p class="eyebrow">Author</p><h1>{html.escape(author.name)}</h1><p>{html.escape(dates)}</p><p>{html.escape(description)}</p></header><section class="book-grid">{_book_cards(novels, authors)}</section></main>'
    structured = {
        "@context": "https://schema.org",
        "@type": "Person",
        "name": author.name,
        "url": canonical,
        "description": author.biography,
    }
    return HTMLResponse(_document(author.name, description, canonical, body, structured))


@router.get("/genres/{slug}", response_class=HTMLResponse)
def genre_page(slug: str, db: Session = Depends(get_db)) -> HTMLResponse:
    genre = db.scalar(select(Genre).where(Genre.slug == slug))
    if not genre:
        raise HTTPException(status_code=404, detail="Genre not found")
    novels = list(
        db.scalars(
            select(Novel)
            .join(NovelGenre, NovelGenre.novel_id == Novel.id)
            .where(NovelGenre.genre_id == genre.id, *publication_filter())
            .order_by(Novel.published_at.desc())
            .limit(100)
        ).all()
    )
    author_ids = {novel.primary_author_id for novel in novels if novel.primary_author_id}
    authors = (
        {author.id: author for author in db.scalars(select(Author).where(Author.id.in_(author_ids))).all()}
        if author_ids
        else {}
    )
    base = get_settings().public_base_url.rstrip("/")
    canonical = f"{base}/genres/{genre.slug}"
    description = (
        genre.introduction or f"Explore complete, independently rights-reviewed {genre.name.lower()} novels."
    )
    body = f'<main class="listing-page"><nav class="breadcrumbs"><a href="/">Home</a> / Genres / {html.escape(genre.name)}</nav><header><p class="eyebrow">Genre</p><h1>{html.escape(genre.name)}</h1><p>{html.escape(description)}</p></header><section class="book-grid">{_book_cards(novels, authors) if novels else "<p>No reviewed editions are published in this genre yet.</p>"}</section></main>'
    structured = {
        "@context": "https://schema.org",
        "@type": "CollectionPage",
        "name": genre.name,
        "url": canonical,
        "description": description,
    }
    return HTMLResponse(_document(f"{genre.name} novels", description, canonical, body, structured))


POLICIES = {
    "privacy": (
        "Privacy",
        "We collect account details you provide, reading progress needed to operate your library, security logs, and consented analytics. Advertising and analytics remain disabled until you grant the relevant consent. We do not sell personal information. You may request access, correction, or deletion through the contact and takedown channels. Operational records may be retained where required for security, fraud prevention, legal compliance, or rights provenance.",
    ),
    "terms": (
        "Terms of use",
        "Webnovel provides access only to works whose selected edition has passed our rights and completeness review. Do not misuse the service, automate invalid advertising traffic, interfere with access controls, or upload unlawful material. Reader annotations and reviews remain your responsibility. Availability may change when rights require re-review or a takedown is received.",
    ),
    "cookies": (
        "Cookie choices",
        "Essential storage keeps the service secure and remembers your privacy selection. Optional analytics and advertising storage are off by default and activate only after consent. Rejecting optional storage does not prevent reading. You can reopen Manage choices from the footer at any time.",
    ),
    "about": (
        "About Webnovel",
        "Webnovel is a copyright-first reading platform for complete, carefully structured fiction. Each published edition keeps provenance, independent rights evidence, chapter integrity checks, and periodic rights review. Source text remains canonical and is never silently rewritten by AI.",
    ),
    "contact": (
        "Contact",
        "For general enquiries, accessibility feedback, privacy requests, or corrections, use the project contact channel configured by the site operator. Copyright claims should use the takedown form so they enter the tracked review workflow immediately.",
    ),
    "copyright": (
        "Copyright and sources",
        "Download availability is not treated as permission to republish. Every edition is reviewed separately for original work, translation, edition, contributor, licence, and jurisdiction considerations. Published novel pages identify their source and rights basis. If you believe a work is incorrectly available, submit a takedown request.",
    ),
    "accessibility": (
        "Accessibility",
        "Webnovel aims for keyboard navigation, semantic headings, readable contrast, reduced-motion support, scalable text, descriptive image alternatives, and uninterrupted prose. Report an access barrier through the contact channel and include the page and assistive technology used where comfortable.",
    ),
}


def policy_template(title: str, content: str) -> str:
    base = get_settings().public_base_url.rstrip("/")
    slug = title.lower().replace(" ", "-")
    body = f'<main class="listing-page policy-page"><nav class="breadcrumbs"><a href="/">Home</a> / {html.escape(title)}</nav><header><p class="eyebrow">Webnovel policy</p><h1>{html.escape(title)}</h1><p>{html.escape(content)}</p><p><a href="/">Return to Webnovel</a></p></header></main>'
    structured = {
        "@context": "https://schema.org",
        "@type": "WebPage",
        "name": title,
        "url": f"{base}/{slug}",
    }
    return _document(title, content, f"{base}/{slug}", body, structured)


@router.get("/{policy_name}", response_class=HTMLResponse)
def policy_page(policy_name: str) -> HTMLResponse:
    if policy_name == "takedown":
        base = get_settings().public_base_url.rstrip("/")
        body = """<main class="listing-page policy-page"><nav class="breadcrumbs"><a href="/">Home</a> / Copyright takedown</nav><header><p class="eyebrow">Rights protection</p><h1>Copyright takedown</h1><p>Submitting this form creates a tracked review request. Content can be disabled immediately while the claim is investigated.</p></header><form class="policy-form" method="post" action="/api/takedown-form"><label>Work slug (optional)<input name="novel_slug"></label><label>Your name<input name="requester_name" required></label><label>Email<input name="requester_email" type="email" required></label><label>Claim<textarea name="claim" minlength="30" required></textarea></label><label>Supporting evidence<textarea name="evidence"></textarea></label><button class="primary-action" type="submit">Submit request</button></form></main>"""
        structured = {
            "@context": "https://schema.org",
            "@type": "WebPage",
            "name": "Copyright takedown",
            "url": f"{base}/takedown",
        }
        return HTMLResponse(
            _document(
                "Copyright takedown",
                "Submit a tracked copyright or rights concern.",
                f"{base}/takedown",
                body,
                structured,
            )
        )
    if policy_name == "contact":
        base = get_settings().public_base_url.rstrip("/")
        body = """<main class="listing-page policy-page"><nav class="breadcrumbs"><a href="/">Home</a> / Contact</nav><header><p class="eyebrow">Contact Webnovel</p><h1>How can we help?</h1><p>Use this tracked form for general questions, accessibility feedback, privacy requests, or corrections. Copyright claims should use the dedicated takedown form.</p></header><form class="policy-form" method="post" action="/api/contact-form"><label>Your name<input name="requester_name" required minlength="2"></label><label>Email<input name="requester_email" type="email" required></label><label>Category<select name="category"><option value="GENERAL">General</option><option value="ACCESSIBILITY">Accessibility</option><option value="PRIVACY">Privacy</option><option value="CORRECTION">Correction</option></select></label><label>Message<textarea name="message" minlength="20" required></textarea></label><button class="primary-action" type="submit">Send message</button></form></main>"""
        structured = {
            "@context": "https://schema.org",
            "@type": "ContactPage",
            "name": "Contact Webnovel",
            "url": f"{base}/contact",
        }
        return HTMLResponse(
            _document(
                "Contact",
                "Contact Webnovel about general, accessibility, privacy, or correction requests.",
                f"{base}/contact",
                body,
                structured,
            )
        )
    if policy_name not in POLICIES:
        return HTMLResponse("Not found", status_code=404)
    title, content = POLICIES[policy_name]
    return HTMLResponse(policy_template(title, content))


@router.post("/api/takedown-form", response_class=HTMLResponse)
def takedown_form(
    requester_name: str = Form(),
    requester_email: str = Form(),
    claim: str = Form(min_length=30),
    evidence: str = Form(default=""),
    novel_slug: str = Form(default=""),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    novel_id = db.scalar(select(Novel.id).where(Novel.slug == novel_slug)) if novel_slug else None
    request = TakedownRequest(
        novel_id=novel_id,
        requester_name=requester_name[:255],
        requester_email=requester_email[:320],
        claim=claim[:20_000],
        evidence=evidence[:20_000] or None,
    )
    db.add(request)
    db.commit()
    return HTMLResponse(
        policy_template(
            "Request received", f"Your takedown request #{request.id} has been received for review."
        ),
        status_code=201,
    )


@router.post("/api/contact-form", response_class=HTMLResponse)
def contact_form(
    requester_name: str = Form(min_length=2),
    requester_email: str = Form(),
    category: str = Form(pattern="^(GENERAL|ACCESSIBILITY|PRIVACY|CORRECTION)$"),
    message: str = Form(min_length=20),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    request = ContactRequest(
        requester_name=requester_name[:255],
        requester_email=requester_email[:320],
        category=category,
        message=message[:20_000],
    )
    db.add(request)
    db.commit()
    return HTMLResponse(
        policy_template(
            "Message received",
            f"Your contact request #{request.id} has been received for review.",
        ),
        status_code=201,
    )
