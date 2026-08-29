# Google AdSense

AdSense is disabled in development. `ADSENSE_ENABLED`, `ADSENSE_AUTO_ADS`, client ID, and publisher ID are environment settings; blank values are intentional and no ID is invented. `/ads.txt` contains only a comment until a real publisher ID is configured.

The frontend exposes one reusable `createAdSlot` function with slot, format, placement, and reserved-height classes. No ad slots are hard-coded into prose. The AdSense script loads only after advertising consent and valid configuration. Suitable placements may be selected conservatively from home feed, details, chapter top/end, genre feed, and author page.

Never cover prose, interrupt dialogue/paragraphs, block navigation, gate chapters, incentivize clicks, auto-refresh, or generate artificial impressions. Short chapters should have no ads. Account, login, admin, rights-uncertain, incomplete, broken, thin, or policy-ineligible pages are always excluded.

Before production enablement, pass the internal readiness report, use HTTPS and a real domain, configure a certified CMP where required, validate `ads.txt`, confirm meaningful original editorial value, audit Core Web Vitals, and obtain account approval.
