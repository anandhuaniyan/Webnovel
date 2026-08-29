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
    const [user, library] = await Promise.all([request('/api/me'), request('/api/me/library')]);
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
