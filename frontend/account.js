const TOKEN_KEY = 'webnovel_session_token';
const authPanels = document.querySelector('#auth-panels');
const libraryPanel = document.querySelector('#library-panel');

async function request(path, options = {}) {
  const token = sessionStorage.getItem(TOKEN_KEY);
  const response = await fetch(path, {
    ...options,
    headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}), ...(options.headers || {}) },
  });
  const data = response.status === 204 ? null : await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Request failed');
  return data;
}

async function showLibrary() {
  try {
    const [user, library, progress, bookmarks, history] = await Promise.all([request('/api/me'), request('/api/me/library'), request('/api/me/continue-reading'), request('/api/me/bookmarks'), request('/api/me/history')]);
    authPanels.hidden = true;
    libraryPanel.hidden = false;
    document.querySelector('#account-name').textContent = `${user.display_name}'s saved worlds`;
    const list = document.querySelector('#library-list');
    list.replaceChildren(...library.map((item) => {
      const row = document.createElement('li');
      const link = document.createElement('a');
      link.href = `/novels/${encodeURIComponent(item.novel.slug)}`;
      link.textContent = item.novel.title;
      const badge = document.createElement('span');
      badge.className = 'badge';
      badge.textContent = item.favourite ? `${item.status} · Favourite` : item.status;
      row.append(link, badge);
      return row;
    }));
    document.querySelector('#library-empty').hidden = library.length > 0;
    document.querySelector('#continue-list').replaceChildren(...progress.map((item) => {
      const row = document.createElement('li'); const link = document.createElement('a');
      link.href = item.chapter ? `/novels/${encodeURIComponent(item.novel.slug)}/chapters/${encodeURIComponent(item.chapter.slug)}` : `/novels/${encodeURIComponent(item.novel.slug)}`;
      link.textContent = item.chapter ? `${item.novel.title} · ${item.chapter.title}` : item.novel.title;
      const badge = document.createElement('span'); badge.className = 'badge'; badge.textContent = `${Math.round(Number(item.position_percent))}%`;
      row.append(link, badge); return row;
    }));
    document.querySelector('#continue-empty').hidden = progress.length > 0;
    document.querySelector('#bookmark-list').replaceChildren(...bookmarks.map((item) => {
      const row = document.createElement('li'); const link = document.createElement('a');
      link.href = `/novels/${encodeURIComponent(item.novel.slug)}/chapters/${encodeURIComponent(item.chapter.slug)}`;
      link.textContent = `${item.novel.title} · ${item.chapter.title}`;
      const remove = document.createElement('button'); remove.type = 'button'; remove.className = 'button button-small button-ghost'; remove.textContent = 'Remove';
      remove.addEventListener('click', async () => { await request(`/api/me/bookmarks/${item.id}`, { method: 'DELETE' }); showLibrary(); });
      row.append(link, remove); return row;
    }));
    document.querySelector('#bookmark-empty').hidden = bookmarks.length > 0;
    document.querySelector('#history-list').replaceChildren(...history.map((item) => {
      const row = document.createElement('li'); const link = document.createElement('a');
      link.href = item.chapter ? `/novels/${encodeURIComponent(item.novel.slug)}/chapters/${encodeURIComponent(item.chapter.slug)}` : `/novels/${encodeURIComponent(item.novel.slug)}`;
      link.textContent = item.chapter ? `${item.novel.title} · ${item.chapter.title}` : item.novel.title;
      const timestamp = document.createElement('time'); timestamp.dateTime = item.read_at; timestamp.textContent = new Date(item.read_at).toLocaleDateString();
      row.append(link, timestamp); return row;
    }));
    document.querySelector('#history-empty').hidden = history.length > 0;
  } catch {
    sessionStorage.removeItem(TOKEN_KEY);
    authPanels.hidden = false;
    libraryPanel.hidden = true;
  }
}

document.querySelector('#login-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const notice = document.querySelector('#login-notice');
  try {
    const result = await request('/api/auth/login', { method: 'POST', body: JSON.stringify({ email: document.querySelector('#login-email').value, password: document.querySelector('#login-password').value }) });
    sessionStorage.setItem(TOKEN_KEY, result.access_token);
    notice.textContent = '';
    showLibrary();
  } catch (error) { notice.textContent = error.message; notice.className = 'notice error'; }
});

document.querySelector('#register-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const notice = document.querySelector('#register-notice');
  try {
    const result = await request('/api/auth/register', { method: 'POST', body: JSON.stringify({ display_name: document.querySelector('#register-name').value, email: document.querySelector('#register-email').value, password: document.querySelector('#register-password').value }) });
    sessionStorage.setItem(TOKEN_KEY, result.access_token);
    notice.textContent = '';
    showLibrary();
  } catch (error) { notice.textContent = error.message; notice.className = 'notice error'; }
});

document.querySelector('#sign-out').addEventListener('click', () => { sessionStorage.removeItem(TOKEN_KEY); showLibrary(); });
showLibrary();

if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => navigator.serviceWorker.register('/service-worker.js').catch(() => {}));
}
