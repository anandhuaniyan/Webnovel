const storyGrid = document.querySelector('#story-grid');
const emptyState = document.querySelector('#empty-state');
const searchInput = document.querySelector('#story-search');
const filters = [...document.querySelectorAll('.genre-filter')];
const CONSENT_KEY = 'webnovel_consent_v1';
let publicConfig = { adsense_enabled: false, ga_measurement_id: '' };
let searchTimer;

function coverClass(index) {
  return ['cover-winter', 'cover-silence', 'cover-letters', 'cover-moon'][index % 4];
}

function createStoryCard(story, index) {
  const article = document.createElement('article');
  article.className = 'story-card';
  const link = document.createElement('a');
  link.href = `/novels/${encodeURIComponent(story.slug)}`;
  link.setAttribute('aria-label', `Read ${story.title}`);
  const cover = document.createElement('div');
  cover.className = `story-cover ${coverClass(index)}`;
  if (story.thumbnail_url) {
    const image = document.createElement('img');
    image.src = story.thumbnail_url;
    image.alt = `Cover of ${story.title}`;
    image.loading = 'lazy';
    image.width = 400;
    image.height = 600;
    cover.append(image);
  } else {
    const symbol = document.createElement('span');
    symbol.textContent = '✦';
    cover.append(symbol);
  }
  const details = document.createElement('div');
  details.className = 'story-details';
  const genre = document.createElement('span');
  genre.className = 'story-genre';
  genre.textContent = story.genres?.[0]?.name || 'Fiction';
  const title = document.createElement('h3');
  title.textContent = story.title;
  const author = document.createElement('p');
  author.textContent = story.author?.name || 'Unknown author';
  const meta = document.createElement('div');
  meta.className = 'story-meta';
  const rating = document.createElement('span');
  rating.textContent = story.rating_count > 0 ? `★ ${story.average_rating}` : 'Not yet rated';
  const chapters = document.createElement('span');
  chapters.textContent = `${story.chapter_count} chapters`;
  meta.append(rating, chapters);
  details.append(genre, title, author, meta);
  link.append(cover, details);
  article.append(link);
  return article;
}

function renderStories(stories, emptyMessage = 'No published stories match this view.') {
  storyGrid.replaceChildren(...stories.map(createStoryCard));
  emptyState.hidden = stories.length > 0;
  emptyState.textContent = emptyMessage;
}

async function api(path, options) {
  const response = await fetch(path, { headers: { Accept: 'application/json' }, ...options });
  if (!response.ok) throw new Error(`Request failed (${response.status})`);
  return response.json();
}

async function loadHome() {
  try {
    const [home, stats, config] = await Promise.all([
      api('/api/home'),
      api('/api/catalogue/stats'),
      api('/api/config/public'),
    ]);
    publicConfig = config;
    const stories = home.trending.length ? home.trending : home.recently_added;
    renderStories(stories, 'The first catalogue checkpoint is undergoing independent rights review. No unverified work will appear here.');
    document.querySelector('#chapter-count').textContent = Number(stats.chapters).toLocaleString();
    document.querySelector('#novel-count').textContent = Number(stats.novels).toLocaleString();
    document.querySelector('#genre-count').textContent = Number(stats.genres).toLocaleString();
    applyConsentIntegrations();
  } catch {
    renderStories([], 'The catalogue service is temporarily unavailable. Please try again shortly.');
  }
}

async function runSearch() {
  const query = searchInput.value.trim();
  if (query.length < 2) return loadHome();
  try {
    const stories = await api(`/api/search?q=${encodeURIComponent(query)}`);
    renderStories(stories, `No rights-approved stories match “${query}”.`);
    track('search', { query, result_count: stories.length });
  } catch {
    renderStories([], 'Search is temporarily unavailable.');
  }
}

searchInput.addEventListener('input', () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(runSearch, 250);
});

filters.forEach((filter) => filter.addEventListener('click', async () => {
  filters.forEach((item) => item.classList.toggle('active', item === filter));
  searchInput.value = '';
  try {
    if (filter.dataset.genre === 'all') return loadHome();
    const genre = filter.dataset.genre.replaceAll(' ', '-');
    const result = await api(`/api/novels?genre=${encodeURIComponent(genre)}&page_size=24`);
    renderStories(result.items, `No rights-approved ${filter.textContent.toLowerCase()} stories are published yet.`);
  } catch {
    renderStories([], 'This genre is temporarily unavailable.');
  }
}));

function readConsent() {
  try { return JSON.parse(localStorage.getItem(CONSENT_KEY)) || null; } catch { return null; }
}

function saveConsent(analytics, advertising) {
  localStorage.setItem(CONSENT_KEY, JSON.stringify({ essential: true, analytics, advertising, updated_at: new Date().toISOString() }));
  document.querySelector('#consent').hidden = true;
  applyConsentIntegrations();
}

function openConsent(manage = false) {
  const panel = document.querySelector('#consent');
  const consent = readConsent();
  document.querySelector('#consent-analytics').checked = Boolean(consent?.analytics);
  document.querySelector('#consent-ads').checked = Boolean(consent?.advertising);
  document.querySelector('#consent-summary').hidden = manage;
  document.querySelector('#consent-choices').hidden = !manage;
  panel.hidden = false;
}

document.querySelector('#consent-accept').addEventListener('click', () => saveConsent(true, true));
document.querySelector('#consent-reject').addEventListener('click', () => saveConsent(false, false));
document.querySelector('#consent-manage').addEventListener('click', () => openConsent(true));
document.querySelector('#manage-consent').addEventListener('click', () => openConsent(true));
document.querySelector('#consent-save').addEventListener('click', () => saveConsent(document.querySelector('#consent-analytics').checked, document.querySelector('#consent-ads').checked));

function applyConsentIntegrations() {
  const consent = readConsent();
  if (consent?.analytics && publicConfig.ga_measurement_id && !document.querySelector('#ga-script')) {
    window.dataLayer = window.dataLayer || [];
    window.gtag = (...args) => window.dataLayer.push(args);
    window.gtag('js', new Date());
    window.gtag('config', publicConfig.ga_measurement_id, { anonymize_ip: true });
    const script = document.createElement('script');
    script.id = 'ga-script';
    script.async = true;
    script.src = `https://www.googletagmanager.com/gtag/js?id=${encodeURIComponent(publicConfig.ga_measurement_id)}`;
    document.head.append(script);
  }
  if (consent?.advertising && publicConfig.adsense_enabled && publicConfig.adsense_client_id && !document.querySelector('#adsense-script')) {
    const script = document.createElement('script');
    script.id = 'adsense-script';
    script.async = true;
    script.crossOrigin = 'anonymous';
    script.src = `https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=${encodeURIComponent(publicConfig.adsense_client_id)}`;
    document.head.append(script);
  }
}

function track(eventName, properties = {}) {
  const consent = readConsent();
  if (!consent?.analytics) return;
  fetch('/api/analytics/events', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ event_name: eventName, properties, consent_granted: true }),
    keepalive: true,
  }).catch(() => {});
}

function createAdSlot({ slot, format = 'auto', placement, minHeight = 120 }) {
  const container = document.createElement('aside');
  const reservedHeight = [90, 120, 250, 280].includes(Number(minHeight)) ? Number(minHeight) : 120;
  container.className = `ad-slot ad-slot-${reservedHeight}`;
  container.dataset.placement = placement;
  const consent = readConsent();
  if (!publicConfig.adsense_enabled || !consent?.advertising || !publicConfig.adsense_client_id || !slot) {
    container.hidden = true;
    return container;
  }
  const ad = document.createElement('ins');
  ad.className = 'adsbygoogle';
  ad.dataset.adClient = publicConfig.adsense_client_id;
  ad.dataset.adSlot = slot;
  ad.dataset.adFormat = format;
  ad.dataset.fullWidthResponsive = 'true';
  container.append(ad);
  window.adsbygoogle = window.adsbygoogle || [];
  window.adsbygoogle.push({});
  return container;
}

window.Webnovel = Object.freeze({ createAdSlot, track });
document.querySelector('#current-year').textContent = new Date().getFullYear();
if (!readConsent()) openConsent(false);
loadHome();

if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => navigator.serviceWorker.register('/service-worker.js').catch(() => {}));
}
