/**
 * ApexApply Dashboard Controller — Version 2.5
 */

const API_BASE = window.location.origin;

let state = {
  applications: [],
  reviewQueue: [],
  stats: {},
  profile: {},
  taxonomy: [],
  logs: [],
  search: '',
  filterStatus: 'all',
  reviewPeriod: 'all'
};

document.addEventListener('DOMContentLoaded', () => {
  setupNavigation();
  setupEventListeners();
  loadAll();

  // Polling intervals
  setInterval(loadStatsAndApps, 4000);
  setInterval(loadLogs, 2500);
});

function setupNavigation() {
  const links = document.querySelectorAll('.nav-link');
  const views = {
    'nav-review': document.getElementById('view-review'),
    'nav-tracker': document.getElementById('view-tracker'),
    'nav-profile': document.getElementById('view-profile'),
    'nav-taxonomy': document.getElementById('view-taxonomy'),
    'nav-logs': document.getElementById('view-logs')
  };

  links.forEach(link => {
    link.addEventListener('click', (e) => {
      e.preventDefault();
      links.forEach(l => l.classList.remove('active'));
      link.classList.add('active');

      Object.values(views).forEach(v => { if (v) v.style.display = 'none'; });
      const target = views[link.id];
      if (target) target.style.display = 'block';

      if (link.id === 'nav-profile') loadProfile();
      if (link.id === 'nav-taxonomy') loadTaxonomy();
      if (link.id === 'nav-review') loadReviewQueue();
      if (link.id === 'nav-tracker') loadStatsAndApps();
    });
  });
}

function setupEventListeners() {
  document.getElementById('tracker-search').addEventListener('input', (e) => {
    state.search = e.target.value.toLowerCase();
    renderTracker();
  });

  document.getElementById('tracker-status-filter').addEventListener('change', (e) => {
    state.filterStatus = e.target.value;
    renderTracker();
  });

  document.getElementById('filter-review-all').addEventListener('click', (e) => {
    document.querySelectorAll('.filter-pill').forEach(p => p.classList.remove('active'));
    e.target.classList.add('active');
    state.reviewPeriod = 'all';
    loadReviewQueue();
  });

  document.getElementById('filter-review-week').addEventListener('click', (e) => {
    document.querySelectorAll('.filter-pill').forEach(p => p.classList.remove('active'));
    e.target.classList.add('active');
    state.reviewPeriod = 'past_week';
    loadReviewQueue();
  });

  document.getElementById('btn-run-batch').addEventListener('click', runBatchPipeline);
  document.getElementById('btn-save-profile').addEventListener('click', saveProfile);

  // Custom Job Modal
  const modalCustom = document.getElementById('modal-custom');
  document.getElementById('btn-open-custom').addEventListener('click', () => modalCustom.style.display = 'flex');
  document.getElementById('btn-close-custom').addEventListener('click', () => modalCustom.style.display = 'none');
  document.getElementById('btn-cancel-custom').addEventListener('click', () => modalCustom.style.display = 'none');
  document.getElementById('btn-submit-custom').addEventListener('click', submitCustomJob);

  // Resume Modal
  const modalResume = document.getElementById('modal-resume');
  document.getElementById('btn-close-resume').addEventListener('click', () => modalResume.style.display = 'none');
  document.getElementById('btn-close-resume-2').addEventListener('click', () => modalResume.style.display = 'none');
}

async function loadAll() {
  await Promise.all([
    loadStatsAndApps(),
    loadReviewQueue(),
    loadLogs()
  ]);
}

async function loadStatsAndApps() {
  try {
    const [statsRes, appsRes] = await Promise.all([
      fetch(`${API_BASE}/api/stats`),
      fetch(`${API_BASE}/api/applications`)
    ]);

    if (statsRes.ok) {
      state.stats = await statsRes.json();
      renderStats(state.stats);
    }

    if (appsRes.ok) {
      const data = await appsRes.json();
      state.applications = data.applications || [];
      renderTracker();
    }
  } catch (err) {
    console.error('Error fetching data:', err);
  }
}

async function loadReviewQueue() {
  try {
    const res = await fetch(`${API_BASE}/api/review-queue?period=${state.reviewPeriod}`);
    if (res.ok) {
      const data = await res.json();
      state.reviewQueue = data.applications || [];
      document.getElementById('badge-review-count').textContent = state.reviewQueue.length;
      renderReviewQueue();
    }
  } catch (err) {
    console.error('Error fetching review queue:', err);
  }
}

async function loadLogs() {
  try {
    const res = await fetch(`${API_BASE}/api/logs`);
    if (res.ok) {
      const data = await res.json();
      state.logs = data.logs || [];
      renderLogs();
    }
  } catch (err) {
    console.error('Error fetching logs:', err);
  }
}

async function loadProfile() {
  try {
    const res = await fetch(`${API_BASE}/api/profile`);
    if (res.ok) {
      state.profile = await res.json();
      renderProfileEditor();
    }
  } catch (err) {
    console.error('Error fetching profile:', err);
  }
}

async function loadTaxonomy() {
  try {
    const res = await fetch(`${API_BASE}/api/taxonomy`);
    if (res.ok) {
      const data = await res.json();
      state.taxonomy = data.taxonomy || [];
      renderTaxonomy();
    }
  } catch (err) {
    console.error('Error fetching taxonomy:', err);
  }
}

function renderStats(stats) {
  document.getElementById('stat-pending').textContent = stats.pending_review || 0;
  document.getElementById('stat-submitted').textContent = stats.submitted || 0;
  document.getElementById('stat-avg-score').textContent = `${stats.average_match_score || 0}%`;
  document.getElementById('stat-total-jobs').textContent = stats.total_jobs_scraped || 0;
}

function formatScrapedDate(dateStr) {
  if (!dateStr) return 'Scraped recently';
  try {
    const d = new Date(dateStr.replace(' ', 'T'));
    const now = new Date();
    const diffHours = Math.round((now - d) / (1000 * 60 * 60));
    if (diffHours < 24) {
      return `Scraped today (${diffHours}h ago)`;
    }
    const diffDays = Math.round(diffHours / 24);
    if (diffDays === 1) return `Scraped yesterday (${d.toLocaleDateString()})`;
    return `Scraped ${diffDays} days ago (${d.toLocaleDateString()})`;
  } catch {
    return dateStr;
  }
}

function renderReviewQueue() {
  const container = document.getElementById('review-queue-cards');
  if (state.reviewQueue.length === 0) {
    container.innerHTML = `<div class="text-dim py-6" style="text-align:center;">No pending review applications found for this filter.</div>`;
    return;
  }

  container.innerHTML = state.reviewQueue.map(app => {
    const scrapedBadge = formatScrapedDate(app.date_scraped || app.applied_date);
    const fieldsList = Object.entries(app.fields_filled_json || {}).map(([k, v]) => `
      <div class="field-row">
        <span class="field-key">${escape(k)}</span>
        <span class="field-val" title="${escape(String(v))}">${escape(String(v))}</span>
      </div>
    `).join('');

    const targetedPills = (app.skills_targeted || []).slice(0, 4).map(s => `<span class="badge-tag">${escape(s)}</span>`).join('');
    const gapPills = (app.skills_gap || []).map(s => `<span class="badge-gap">${escape(s)}</span>`).join('') || '<span class="text-dim">None (Strong Match)</span>';

    return `
      <div class="review-item" id="card-${app.id}">
        <div class="review-header">
          <div class="review-title-box">
            <h4>${escape(app.job_title)}</h4>
            <div class="review-meta">
              <strong>${escape(app.company)}</strong>
              <span>&bull;</span>
              <span>${escape(app.location || 'Remote')}</span>
              <span>&bull;</span>
              <span class="date-badge">📅 ${scrapedBadge}</span>
              <span>&bull;</span>
              <span class="badge-tag">${escape(app.platform_type.toUpperCase())}</span>
            </div>
          </div>
          <span class="badge-score">🎯 ${app.match_score_at_apply}% Match</span>
        </div>

        <div class="review-grid-details">
          <div>
            <div style="font-size:12px;color:var(--text-muted);margin-bottom:6px;">
              <strong>Targeted Skills:</strong> ${targetedPills}
              <div style="margin-top:4px;"><strong>Honest Skills Gap:</strong> ${gapPills}</div>
            </div>
            <div class="jd-box">
              <strong>Job Description Summary:</strong><br>
              ${escape(app.job_description || 'Full JD available in portal.').substring(0, 420)}...
            </div>
          </div>

          <div class="fields-table-box">
            <h5>📋 Pre-Filled Form Values</h5>
            <div class="fields-list">
              ${fieldsList || '<div class="text-dim">Standard profile mappings active.</div>'}
            </div>
          </div>
        </div>

        <div class="review-footer">
          <div class="review-footer-left">
            <span style="font-size:12px;color:var(--text-dim);">Recruiter / Hiring Contact:</span>
            <strong style="font-size:12px;color:#cbd5e1;">${escape(app.contact_person || 'Hiring Team')} ${app.contact_email ? `(${escape(app.contact_email)})` : ''}</strong>
          </div>
          <div class="review-footer-right">
            <button class="btn btn-launch btn-sm" onclick="launchFill('${app.id}', '${app.posting_url}')">
              🚀 Launch Portal & Pre-Fill Form
            </button>
            <button class="btn btn-secondary btn-sm" onclick="viewResume('${app.job_id}', '${escape(app.company)}', ${app.match_score_at_apply})">
              📄 View Tailored Resume
            </button>
            <button class="btn btn-primary btn-sm" onclick="confirmSubmit('${app.id}')">
              ✅ Confirm Submitted
            </button>
            <button class="btn btn-secondary btn-sm" onclick="skipApplication('${app.id}')" style="color:var(--accent-rose);">
              Skip
            </button>
          </div>
        </div>
      </div>
    `;
  }).join('');
}

function renderTracker() {
  const tbody = document.getElementById('tracker-tbody');
  const filtered = state.applications.filter(app => {
    const matchesFilter = state.filterStatus === 'all' || app.status === state.filterStatus;
    const q = state.search;
    const matchesSearch = !q ||
      (app.job_title && app.job_title.toLowerCase().includes(q)) ||
      (app.company && app.company.toLowerCase().includes(q)) ||
      (app.contact_person && app.contact_person.toLowerCase().includes(q)) ||
      (app.skills_targeted && app.skills_targeted.some(s => s.toLowerCase().includes(q)));
    return matchesFilter && matchesSearch;
  });

  if (filtered.length === 0) {
    tbody.innerHTML = `<tr><td colspan="11" class="text-center py-6 text-dim">No applications matching filter.</td></tr>`;
    return;
  }

  tbody.innerHTML = filtered.map(app => {
    const targetedPills = (app.skills_targeted || []).slice(0, 3).map(s => `<span class="badge-tag">${escape(s)}</span>`).join('');
    const gapPills = (app.skills_gap || []).slice(0, 2).map(s => `<span class="badge-gap">${escape(s)}</span>`).join('') || '<span class="text-dim">—</span>';
    const contactDisplay = app.contact_person ? `${escape(app.contact_person)} ${app.contact_email ? `<br><small style="color:var(--text-dim)">${escape(app.contact_email)}</small>` : ''}` : 'Hiring Team';
    const scrapedDateDisplay = formatScrapedDate(app.date_scraped || app.applied_date);

    return `
      <tr>
        <td>
          <strong>${escape(app.job_title)}</strong>
          <div style="font-size:11.5px;color:var(--text-muted);">${escape(app.company)} • ${escape(app.location || 'Remote')}</div>
        </td>
        <td><span class="badge-tag">${escape(app.platform_type.toUpperCase())}</span></td>
        <td><div style="font-size:11.5px;color:var(--accent-cyan);">${scrapedDateDisplay}</div></td>
        <td><span class="badge-score">🎯 ${app.match_score_at_apply}%</span></td>
        <td><div style="font-size:12px;">${contactDisplay}</div></td>
        <td>${targetedPills}</td>
        <td>${gapPills}</td>
        <td>
          <button class="btn btn-secondary btn-sm" onclick="viewResume('${app.job_id}', '${escape(app.company)}', ${app.match_score_at_apply})">
            📄 Preview
          </button>
        </td>
        <td><span class="badge-status ${app.status}">${app.status}</span></td>
        <td>
          <select class="select-response" onchange="updateResponse('${app.id}', this.value)">
            <option value="No response" ${app.response_status === 'No response' ? 'selected' : ''}>No response</option>
            <option value="Interview" ${app.response_status === 'Interview' ? 'selected' : ''}>Interview</option>
            <option value="Offer" ${app.response_status === 'Offer' ? 'selected' : ''}>Offer</option>
            <option value="Rejected" ${app.response_status === 'Rejected' ? 'selected' : ''}>Rejected</option>
          </select>
        </td>
        <td>
          <a href="${app.posting_url || '#'}" target="_blank" class="btn btn-secondary btn-sm" title="View Posting">↗</a>
        </td>
      </tr>
    `;
  }).join('');
}

function renderProfileEditor() {
  const container = document.getElementById('profile-fields-container');
  const p = state.profile;
  const custom = p.custom_field_answers || {};

  container.innerHTML = `
    <div class="field-box">
      <label>Full Name</label>
      <input type="text" id="prof-full-name" class="input" value="${escape(p.full_name || '')}">
    </div>
    <div class="field-box">
      <label>Email Address</label>
      <input type="email" id="prof-email" class="input" value="${escape(p.email || '')}">
    </div>
    <div class="field-box">
      <label>Phone Number</label>
      <input type="text" id="prof-phone" class="input" value="${escape(p.phone || '')}">
    </div>
    <div class="field-box">
      <label>Location / Address</label>
      <input type="text" id="prof-address" class="input" value="${escape(p.address || '')}">
    </div>
    <div class="field-box">
      <label>LinkedIn URL</label>
      <input type="url" id="prof-linkedin" class="input" value="${escape(p.linkedin_url || '')}">
    </div>
    <div class="field-box">
      <label>Portfolio / GitHub URL</label>
      <input type="url" id="prof-portfolio" class="input" value="${escape(p.portfolio_url || '')}">
    </div>
    <div class="field-box">
      <label>Work Authorization</label>
      <input type="text" id="prof-work-auth" class="input" value="${escape(p.work_authorization || '')}">
    </div>
    <div class="field-box">
      <label>Salary Expectation</label>
      <input type="text" id="prof-salary" class="input" value="${escape(p.salary_expectation || '')}">
    </div>
    <div class="field-box" style="grid-column: 1/-1;">
      <label>Why do you want to work here? (Template answer)</label>
      <textarea id="prof-why-join" class="textarea" rows="3">${escape(custom.why_join || '')}</textarea>
    </div>
    <div class="field-box" style="grid-column: 1/-1;">
      <label>Highlight your greatest professional achievement (Template answer)</label>
      <textarea id="prof-achievement" class="textarea" rows="3">${escape(custom.greatest_achievement || '')}</textarea>
    </div>
  `;
}

async function saveProfile() {
  const updated = {
    id: "default_profile",
    full_name: document.getElementById('prof-full-name').value.trim(),
    email: document.getElementById('prof-email').value.trim(),
    phone: document.getElementById('prof-phone').value.trim(),
    address: document.getElementById('prof-address').value.trim(),
    linkedin_url: document.getElementById('prof-linkedin').value.trim(),
    portfolio_url: document.getElementById('prof-portfolio').value.trim(),
    work_authorization: document.getElementById('prof-work-auth').value.trim(),
    salary_expectation: document.getElementById('prof-salary').value.trim(),
    years_experience: 15,
    custom_field_answers: {
      why_join: document.getElementById('prof-why-join').value.trim(),
      greatest_achievement: document.getElementById('prof-achievement').value.trim()
    }
  };

  try {
    const res = await fetch(`${API_BASE}/api/profile`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(updated)
    });
    if (res.ok) {
      alert('✅ Candidate profile updated successfully!');
      loadProfile();
    }
  } catch (err) {
    alert('Failed to save profile: ' + err.message);
  }
}

function renderTaxonomy() {
  const tbody = document.getElementById('taxonomy-tbody');
  if (state.taxonomy.length === 0) {
    tbody.innerHTML = `<tr><td colspan="6" class="text-center py-6 text-dim">No fields registered yet.</td></tr>`;
    return;
  }
  tbody.innerHTML = state.taxonomy.map(t => `
    <tr>
      <td><span class="badge-tag">${escape(t.platform_type.toUpperCase())}</span></td>
      <td><strong>${escape(t.field_name)}</strong></td>
      <td><code>${escape(t.field_type)}</code></td>
      <td>${escape(t.maps_to_profile_field || '—')}</td>
      <td>${t.is_required ? '<span style="color:var(--accent-rose)">Yes</span>' : 'No'}</td>
      <td><small style="color:var(--text-dim)">${escape(t.last_seen_at)}</small></td>
    </tr>
  `).join('');
}

function renderLogs() {
  const term = document.getElementById('audit-terminal');
  term.innerHTML = state.logs.slice().reverse().map(l => `
    <div class="term-line">
      <span class="term-time">[${new Date(l.timestamp).toLocaleTimeString()}]</span>
      <span class="term-${l.level}">[${l.level}]</span>
      <strong>${escape(l.action)}</strong>: 
      <span>${escape(l.details)}</span>
    </div>
  `).join('');
}

// Actions
window.launchFill = async function(appId, url) {
  try {
    const res = await fetch(`${API_BASE}/api/applications/${appId}/launch-fill`, { method: 'POST' });
    if (res.ok) {
      loadLogs();
    }
  } catch (err) {
    window.open(url, '_blank');
  }
};

window.confirmSubmit = async function(appId) {
  try {
    await fetch(`${API_BASE}/api/applications/${appId}/status`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ status: 'SUBMITTED', notes: 'Confirmed and submitted by candidate' })
    });
    loadAll();
  } catch (err) {
    alert('Failed to confirm submit: ' + err.message);
  }
};

window.skipApplication = async function(appId) {
  try {
    await fetch(`${API_BASE}/api/applications/${appId}/status`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ status: 'FAILED', notes: 'Skipped by user in review queue' })
    });
    loadAll();
  } catch (err) {
    alert('Failed to skip: ' + err.message);
  }
};

window.updateResponse = async function(appId, responseStatus) {
  try {
    await fetch(`${API_BASE}/api/applications/${appId}/response-status`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ response_status: responseStatus })
    });
    loadStatsAndApps();
  } catch (err) {
    alert('Failed to update response status: ' + err.message);
  }
};

window.switchResumeTab = function(tab) {
  const singleView = document.getElementById('view-single-resume');
  const compareView = document.getElementById('view-compare-resume');
  const tabTailored = document.getElementById('tab-tailored');
  const tabCompare = document.getElementById('tab-compare');

  if (tab === 'compare') {
    singleView.style.display = 'none';
    compareView.style.display = 'block';
    tabTailored.classList.remove('active');
    tabCompare.classList.add('active');
  } else {
    singleView.style.display = 'block';
    compareView.style.display = 'none';
    tabTailored.classList.add('active');
    tabCompare.classList.remove('active');
  }
};

window.viewResume = async function(jobId, company, score) {
  const modal = document.getElementById('modal-resume');
  document.getElementById('modal-resume-title').textContent = `Resume Tailoring for ${company}`;
  document.getElementById('modal-resume-score').textContent = `🎯 ${score}% ATS Match`;
  document.getElementById('resume-frame').src = `${API_BASE}/api/resume/preview/${jobId}`;
  
  // Default to single view tab
  switchResumeTab('tailored');
  modal.style.display = 'flex';

  // Load comparison data asynchronously
  try {
    const res = await fetch(`${API_BASE}/api/resume/compare/${jobId}`);
    if (res.ok) {
      const data = await res.json();
      document.getElementById('compare-original-text').value = data.original_text || 'Original master profile text';
      document.getElementById('compare-tailored-frame').src = `${API_BASE}/api/resume/preview/${jobId}`;
      document.getElementById('compare-score-badge').textContent = `🎯 ${data.match_score}% Score`;
      
      const targetedStr = (data.skills_matched || []).join(', ') || 'General AI Leadership';
      const gapStr = (data.skills_gap || []).join(', ') || 'None (Strong Match)';
      document.getElementById('compare-skills-summary').innerHTML = `
        <strong>Targeted:</strong> <span style="color:var(--primary);">${escape(targetedStr)}</span> &nbsp;|&nbsp;
        <strong>Honest Gaps:</strong> <span style="color:#ef4444;">${escape(gapStr)}</span>
      `;
    }
  } catch (err) {
    console.error('Error fetching resume comparison:', err);
  }
};

async function runBatchPipeline() {
  const btn = document.getElementById('btn-run-batch');
  btn.disabled = true;
  btn.textContent = 'Ingesting & Tailoring...';

  try {
    const res = await fetch(`${API_BASE}/api/run-batch`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ max_jobs: 25, auto_submit: false })
    });
    if (res.ok) {
      setTimeout(() => {
        loadAll();
        btn.disabled = false;
        btn.innerHTML = `
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"></polygon></svg>
          Ingest & Run Pipeline
        `;
      }, 3500);
    }
  } catch (err) {
    alert('Batch run failed: ' + err.message);
    btn.disabled = false;
  }
}

async function submitCustomJob(e) {
  e.preventDefault();
  const title = document.getElementById('cust-title').value.trim();
  const company = document.getElementById('cust-company').value.trim();
  const url = document.getElementById('cust-url').value.trim();
  const location = document.getElementById('cust-location').value.trim();
  const description = document.getElementById('cust-desc').value.trim();
  const auto_submit = document.getElementById('cust-auto').checked;

  if (!title || !company) {
    alert('Please provide Job Title and Company.');
    return;
  }

  const btn = document.getElementById('btn-submit-custom');
  btn.disabled = true;
  btn.textContent = 'Processing & Tailoring...';

  try {
    const res = await fetch(`${API_BASE}/api/apply-custom`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title, company, url, location, description, auto_submit })
    });
    if (res.ok) {
      document.getElementById('modal-custom').style.display = 'none';
      document.getElementById('custom-form').reset();
      loadAll();
    }
  } catch (err) {
    alert('Error submitting custom job: ' + err.message);
  } finally {
    btn.disabled = false;
    btn.textContent = 'Process & Tailor';
  }
}

function escape(s) {
  if (!s) return '';
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}
