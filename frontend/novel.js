const novelPage = document.querySelector('[data-novel-page]');

if (novelPage) {
  const TOKEN_KEY = 'webnovel_session_token';
  const token = sessionStorage.getItem(TOKEN_KEY);
  const novelId = Number(novelPage.dataset.novelId);
  const action = document.querySelector('#novel-reading-action');
  const libraryButton = document.querySelector('#novel-library-action');
  const status = document.querySelector('#novel-action-status');

  async function request(path, options = {}) {
    const response = await fetch(path, {
      ...options,
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...(options.headers || {}),
      },
    });
    const data = response.status === 204 ? null : await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Request failed');
    return data;
  }

  if (token) {
    Promise.all([request('/api/me/continue-reading'), request('/api/me/library')]).then(([progress, library]) => {
      const savedProgress = progress.find((item) => item.novel.id === novelId);
      if (savedProgress?.chapter) {
        action.href = `/novels/${encodeURIComponent(savedProgress.novel.slug)}/chapters/${encodeURIComponent(savedProgress.chapter.slug)}`;
        action.textContent = `Continue reading · ${Math.round(Number(savedProgress.position_percent))}%`;
      }
      if (library.some((item) => item.novel.id === novelId)) {
        libraryButton.textContent = 'In your library';
        libraryButton.disabled = true;
      }
    }).catch(() => {});
  } else {
    libraryButton.textContent = 'Sign in to save';
  }

  libraryButton.addEventListener('click', async () => {
    if (!token) { window.location.assign('/account'); return; }
    try {
      await request(`/api/me/library/${novelId}`, {
        method: 'PUT',
        body: JSON.stringify({ status: 'SAVED', favourite: false }),
      });
      libraryButton.textContent = 'In your library';
      libraryButton.disabled = true;
      status.textContent = 'Saved to your library.';
    } catch (error) { status.textContent = error.message; }
  });
}

if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => navigator.serviceWorker.register('/service-worker.js').catch(() => {}));
}
