const reader = document.querySelector('[data-reader]');

if (reader) {
  const TOKEN_KEY = 'webnovel_session_token';
  const SETTINGS_KEY = 'webnovel_reader_settings';
  const chapterId = Number(reader.dataset.chapterId);
  const novelId = Number(reader.dataset.novelId);
  const readingMinutes = Number(reader.dataset.readingMinutes) || 1;
  const progressKey = `webnovel_progress_${novelId}_${chapterId}`;
  const bookmarkKey = `webnovel_bookmark_${chapterId}`;
  const defaults = { font_family: 'serif', font_scale: 100, line_height: 185, content_width: 760, theme: 'sepia' };
  let settings = { ...defaults };
  let saveTimer;

  function token() { return sessionStorage.getItem(TOKEN_KEY); }

  async function api(path, options = {}) {
    const response = await fetch(path, {
      ...options,
      headers: {
        'Content-Type': 'application/json',
        ...(token() ? { Authorization: `Bearer ${token()}` } : {}),
        ...(options.headers || {}),
      },
    });
    const data = response.status === 204 ? null : await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Request failed');
    return data;
  }

  function normalizeSettings(value = {}) {
    const merged = { ...defaults, ...value };
    if (merged.theme === 'paper') merged.theme = 'sepia';
    return merged;
  }

  function applySettings(value) {
    settings = normalizeSettings(value);
    const root = document.documentElement;
    root.dataset.readerTheme = settings.theme;
    root.dataset.readerFont = settings.font_family;
    root.style.setProperty('--reader-font-scale', `${settings.font_scale}%`);
    root.style.setProperty('--reader-font-size', `${1.18 * settings.font_scale / 100}rem`);
    root.style.setProperty('--reader-line-height', String(settings.line_height / 100));
    root.style.setProperty('--reader-width', `${settings.content_width}px`);
    document.querySelector('#reader-font').value = settings.font_family;
    document.querySelector('#reader-font-scale').value = settings.font_scale;
    document.querySelector('#reader-line-height').value = settings.line_height;
    document.querySelector('#reader-content-width').value = settings.content_width;
    document.querySelector('#reader-font-output').value = `${settings.font_scale}%`;
    document.querySelector('#reader-line-output').value = (settings.line_height / 100).toFixed(2);
    document.querySelector('#reader-width-output').value = `${settings.content_width}px`;
    document.querySelectorAll('[data-reader-theme]').forEach((button) => {
      button.setAttribute('aria-pressed', String(button.dataset.readerTheme === settings.theme));
    });
  }

  function persistSettings() {
    localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings));
    clearTimeout(saveTimer);
    if (token()) {
      saveTimer = setTimeout(() => {
        api('/api/me/reader-settings', { method: 'PUT', body: JSON.stringify(settings) }).catch(() => {});
      }, 500);
    }
  }

  function readLocalSettings() {
    try { return JSON.parse(localStorage.getItem(SETTINGS_KEY) || '{}'); } catch { return {}; }
  }

  applySettings(readLocalSettings());
  if (token()) {
    api('/api/me').then((user) => {
      applySettings({ ...readLocalSettings(), ...(user.reader_settings || {}) });
      localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings));
    }).catch(() => {});
    api('/api/me/history', { method: 'POST', body: JSON.stringify({ novel_id: novelId, chapter_id: chapterId }) }).catch(() => {});
  }

  const settingsPanel = document.querySelector('#reader-settings');
  const settingsToggle = document.querySelector('#reader-settings-toggle');
  function setSettingsOpen(open) {
    settingsPanel.hidden = !open;
    settingsToggle.setAttribute('aria-expanded', String(open));
    if (open) document.querySelector('#reader-font').focus();
  }
  settingsToggle.addEventListener('click', () => setSettingsOpen(settingsPanel.hidden));
  document.querySelector('#reader-settings-close').addEventListener('click', () => setSettingsOpen(false));

  document.querySelector('#reader-font').addEventListener('change', (event) => {
    applySettings({ ...settings, font_family: event.target.value }); persistSettings();
  });
  document.querySelector('#reader-font-scale').addEventListener('input', (event) => {
    applySettings({ ...settings, font_scale: Number(event.target.value) }); persistSettings();
  });
  document.querySelector('#reader-line-height').addEventListener('input', (event) => {
    applySettings({ ...settings, line_height: Number(event.target.value) }); persistSettings();
  });
  document.querySelector('#reader-content-width').addEventListener('input', (event) => {
    applySettings({ ...settings, content_width: Number(event.target.value) }); persistSettings();
  });
  document.querySelectorAll('[data-reader-theme]').forEach((button) => {
    button.addEventListener('click', () => {
      applySettings({ ...settings, theme: button.dataset.readerTheme }); persistSettings();
    });
  });

  function readingPercent() {
    const maximum = Math.max(document.documentElement.scrollHeight - window.innerHeight, 1);
    return Math.min(100, Math.max(0, window.scrollY / maximum * 100));
  }

  function updateProgress() {
    const percent = readingPercent();
    document.querySelector('#reading-progress').value = percent;
    document.querySelector('#reader-percent').textContent = `${Math.round(percent)}% complete`;
    const remaining = Math.max(0, Math.ceil(readingMinutes * (1 - percent / 100)));
    document.querySelector('#reader-time').textContent = remaining ? `About ${remaining} min left` : 'Chapter complete';
    localStorage.setItem(progressKey, JSON.stringify({ percent, scrollY: window.scrollY, updated_at: new Date().toISOString() }));
    clearTimeout(updateProgress.remoteTimer);
    if (token()) {
      updateProgress.remoteTimer = setTimeout(() => {
        api(`/api/me/progress/${novelId}`, {
          method: 'PUT',
          body: JSON.stringify({ chapter_id: chapterId, position_percent: percent, completed: percent >= 98 }),
        }).catch(() => {});
      }, 1200);
    }
  }
  updateProgress.remoteTimer = null;
  window.addEventListener('scroll', updateProgress, { passive: true });
  window.addEventListener('resize', updateProgress, { passive: true });
  let restoredLocalProgress = false;
  try {
    const saved = JSON.parse(localStorage.getItem(progressKey) || '{}');
    if (Number.isFinite(saved.scrollY) && Number(saved.percent) > 0) {
      restoredLocalProgress = true;
      setTimeout(() => window.scrollTo({ top: saved.scrollY }), 80);
    }
  } catch { /* Ignore corrupt local fallback state. */ }
  if (token() && !restoredLocalProgress) {
    api('/api/me/continue-reading').then((items) => {
      const saved = items.find((item) => item.novel.id === novelId && item.chapter?.id === chapterId);
      if (!saved || Number(saved.position_percent) <= 0) return;
      setTimeout(() => {
        const maximum = Math.max(document.documentElement.scrollHeight - window.innerHeight, 1);
        window.scrollTo({ top: maximum * Number(saved.position_percent) / 100 });
      }, 120);
    }).catch(() => {});
  }
  updateProgress();

  const bookmarkButton = document.querySelector('#reader-bookmark');
  if (localStorage.getItem(bookmarkKey)) bookmarkButton.classList.add('is-saved');
  bookmarkButton.addEventListener('click', async () => {
    const percent = Math.round(readingPercent());
    localStorage.setItem(bookmarkKey, JSON.stringify({ percent, saved_at: new Date().toISOString() }));
    bookmarkButton.classList.add('is-saved');
    bookmarkButton.querySelector('span').textContent = `Saved at ${percent}%`;
    if (token()) {
      try {
        await api('/api/me/bookmarks', {
          method: 'POST',
          body: JSON.stringify({ chapter_id: chapterId, position_key: 'chapter', note: `Saved at ${percent}%` }),
        });
      } catch { /* The local bookmark remains available offline. */ }
    }
  });

  const fullscreenButton = document.querySelector('#reader-fullscreen');
  fullscreenButton.addEventListener('click', async () => {
    try {
      if (!document.fullscreenElement) await document.documentElement.requestFullscreen();
      else await document.exitFullscreen();
    } catch { document.documentElement.classList.toggle('reader-focus'); }
  });
  document.addEventListener('fullscreenchange', () => {
    document.documentElement.classList.toggle('reader-focus', Boolean(document.fullscreenElement));
  });

  document.querySelector('#chapter-select').addEventListener('change', (event) => {
    window.location.assign(event.target.value);
  });
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && !settingsPanel.hidden) { setSettingsOpen(false); return; }
    if (event.defaultPrevented || event.ctrlKey || event.metaKey || event.altKey) return;
    const target = event.target;
    if (target.matches('input, select, textarea, button') || target.isContentEditable) return;
    if (event.key === 'ArrowLeft' && reader.dataset.previousUrl) window.location.assign(reader.dataset.previousUrl);
    if (event.key === 'ArrowRight' && reader.dataset.nextUrl) window.location.assign(reader.dataset.nextUrl);
  });

  let touchStart = null;
  reader.addEventListener('touchstart', (event) => {
    if (event.touches.length === 1) touchStart = { x: event.touches[0].clientX, y: event.touches[0].clientY };
  }, { passive: true });
  reader.addEventListener('touchend', (event) => {
    if (!touchStart || event.changedTouches.length !== 1) return;
    const deltaX = event.changedTouches[0].clientX - touchStart.x;
    const deltaY = event.changedTouches[0].clientY - touchStart.y;
    touchStart = null;
    if (Math.abs(deltaX) < 90 || Math.abs(deltaX) < Math.abs(deltaY) * 1.6) return;
    if (deltaX > 0 && reader.dataset.previousUrl) window.location.assign(reader.dataset.previousUrl);
    if (deltaX < 0 && reader.dataset.nextUrl) window.location.assign(reader.dataset.nextUrl);
  }, { passive: true });

  if ('IntersectionObserver' in window) {
    const observer = new IntersectionObserver((entries) => {
      entries.forEach((entry) => entry.target.classList.toggle('is-paused', !entry.isIntersecting));
    }, { rootMargin: '200px 0px' });
    document.querySelectorAll('.chapter-artwork').forEach((artwork) => observer.observe(artwork));
  }
}

if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => navigator.serviceWorker.register('/service-worker.js').catch(() => {}));
}
