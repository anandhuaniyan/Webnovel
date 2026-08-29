let adminKey = sessionStorage.getItem('webnovel_admin_key') || '';

async function adminRequest(path, options = {}) {
  const response = await fetch(path, { ...options, headers: { 'Content-Type': 'application/json', 'X-Admin-Key': adminKey, ...(options.headers || {}) } });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Administrative request failed');
  return data;
}

function metric(label, value) {
  const item = document.createElement('div');
  item.className = 'metric';
  const strong = document.createElement('strong'); strong.textContent = Number(value).toLocaleString();
  const span = document.createElement('span'); span.textContent = label;
  item.append(strong, span); return item;
}

async function loadDashboard() {
  const [dashboard, rights, contacts, jobs] = await Promise.all([adminRequest('/api/admin/dashboard'), adminRequest('/api/admin/rights-queue'), adminRequest('/api/admin/contact-requests'), adminRequest('/api/admin/import-jobs?limit=50')]);
  document.querySelector('#admin-auth').hidden = true;
  document.querySelector('#admin-dashboard').hidden = false;
  document.querySelector('#metrics').replaceChildren(metric('Published', dashboard.catalogue.published), metric('Rights review', dashboard.catalogue.rights_review), metric('Blocking issues', dashboard.quality.blocking), metric('Open takedowns', dashboard.takedowns.open), metric('Open contacts', dashboard.contacts.open));
  document.querySelector('#readiness').textContent = JSON.stringify(dashboard.adsense_readiness, null, 2);
  document.querySelector('#rights-list').replaceChildren(...rights.map((item) => { const li = document.createElement('li'); const title = document.createElement('span'); title.textContent = item.title; const badge = document.createElement('span'); badge.className = 'badge'; badge.textContent = item.status; li.append(title, badge); return li; }));
  document.querySelector('#contacts-list').replaceChildren(...contacts.map((item) => { const li = document.createElement('li'); const title = document.createElement('span'); title.textContent = `${item.category}: ${item.requester_name}`; const badge = document.createElement('span'); badge.className = 'badge'; badge.textContent = item.status; li.append(title, badge); return li; }));
  document.querySelector('#jobs-list').replaceChildren(...jobs.map((job) => { const li = document.createElement('li'); const title = document.createElement('span'); title.textContent = `Job #${job.id} · checkpoint ${job.checkpoint || 'pending'}`; const badge = document.createElement('span'); badge.className = 'badge'; badge.textContent = job.status; li.append(title, badge); return li; }));
}

document.querySelector('#admin-connect').addEventListener('click', async () => { adminKey = document.querySelector('#admin-key').value; try { await loadDashboard(); sessionStorage.setItem('webnovel_admin_key', adminKey); } catch (error) { const notice = document.querySelector('#admin-notice'); notice.textContent = error.message; notice.className = 'notice error'; } });
document.querySelector('#start-discovery').addEventListener('click', async () => { const source = document.querySelector('#source').value; const limit = document.querySelector('#stage-limit').value; const notice = document.querySelector('#discovery-notice'); try { const result = await adminRequest(`/api/admin/discovery/${source}?limit=${limit}`, { method: 'POST' }); notice.textContent = `Queued task ${result.task_id}. Candidates remain unpublished pending rights review.`; setTimeout(loadDashboard, 1500); } catch (error) { notice.textContent = error.message; notice.className = 'notice error'; } });
if (adminKey) loadDashboard().catch(() => sessionStorage.removeItem('webnovel_admin_key'));
