/**
 * ApexApply Dashboard Controller
 * ==============================
 * Comprehensive JobRight.ai & ScaleJobs inspired state management:
 * - Interactive Review Queue with real date badges & past-week filter
 * - JobRight-Style Multi-Dimensional Match Diagnostics
 * - Bespoke AI Tailored Cover Letter generation & copy
 * - Predefined Target Preferences & Company Blacklist Editor
 * - Full Applications Ledger & Status Tracking
 */

const API_BASE = window.location.origin;

let currentCoverLetterText = '';

const state = {
  stats: null,
  reviewQueue: [],
  applications: [],
  taxonomy: [],
  logs: [],
  profile: null,
  preferences: null,
  filterPlatform: 'all',
  filterStatus: 'all',
  search: '',
  reviewPeriod: 'all'
};

document.addEventListener('DOMContentLoaded', () => {
  setupNavigation();
  setupEventListeners();
  loadAll();
});

function setupNavigation() {
  const navLinks = document.querySelectorAll('.nav-link');
  const sections = document.querySelectorAll('.card-section');

  navLinks.forEach(link => {
    link.addEventListener('click', (e) => {
      e.preventDefault();
      navLinks.forEach(l => l.classList.remove('active'));
      link.classList.add('active');

      const targetId = 'view-' + link.id.replace('nav-', '');
      sections.forEach(sec => {
        sec.style.display = (sec.id === targetId) ? 'block' : 'none';
      });

      if (link.id === 'nav-profile') loadProfile();
      if (link.id === 'nav-preferences') loadPreferences();
      if (link.id === 'nav-taxonomy') loadTaxonomy();
      if (link.id === 'nav-review') loadReviewQueue();
      if (link.id === 'nav-tracker') loadStatsAndApps();
    });
  });
}

function setupEventListeners() {
  const searchInput = document.getElementById('filter-search');
  if (searchInput) {
    searchInput.addEventListener('input', (e) => {
      state.search = e.target.value.toLowerCase();
      renderReviewQueue();
      renderTracker();
    });
  }

  const filterPills = document.querySelectorAll('#view-review .pill');
  filterPills.forEach(pill => {
    pill.addEventListener('click', (e) => {
      filterPills.forEach(p => p.classList.remove('active'));
      e.target.classList.add('active');
      const filter = e.target.getAttribute('data-filter');
      if (filter === 'past_week') {
        state.reviewPeriod = 'past_week';
        state.filterPlatform = 'all';
      } else {
        state.reviewPeriod = 'all';
        state.filterPlatform = filter || 'all';
      }
      loadReviewQueue();
    });
  });

  const btnRunBatch = document.getElementById('btn-run-batch');
  if (btnRunBatch) btnRunBatch.addEventListener('click', runBatchPipeline);

  const btnSaveProfile = document.getElementById('btn-save-profile');
  if (btnSaveProfile) btnSaveProfile.addEventListener('click', saveProfile);

  const btnSavePref = document.getElementById('btn-save-preferences');
  if (btnSavePref) btnSavePref.addEventListener('click', savePreferences);

  // Resume Modal Close
  const modalResume = document.getElementById('modal-resume');
  const btnClose1 = document.getElementById('btn-close-resume');
  const btnClose2 = document.getElementById('btn-close-resume-2');
  if (btnClose1) btnClose1.addEventListener('click', () => modalResume.style.display = 'none');
  if (btnClose2) btnClose2.addEventListener('click', () => modalResume.style.display = 'none');
}

async function loadAll() {
  await Promise.all([
    loadStatsAndApps(),
    loadReviewQueue(),
    loadLogs(),
    loadPreferences()
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
    console.error('Error loading stats:', err);
  }
}

function renderStats(stats) {
  if (!stats) return;
  const setEl = (id, val) => {
    const el = document.getElementById(id);
    if (el) el.textContent = val;
  };
  setEl('stat-total-apps', stats.total_applications || 0);
  setEl('stat-pending-review', stats.pending_review || 0);
  setEl('stat-submitted', stats.submitted || 0);
  setEl('stat-avg-match', (stats.average_match_score || 0) + '%');
}

function formatScrapedDate(dateStr) {
  if (!dateStr) return 'Recently';
  try {
    const d = new Date(dateStr.replace(' ', 'T'));
    const now = new Date();
    const diffHours = Math.round((now - d) / (1000 * 60 * 60));
    if (diffHours < 24 && diffHours >= 0) return `Scraped today (${diffHours}h ago)`;
    const diffDays = Math.round(diffHours / 24);
    if (diffDays === 1) return `Scraped yesterday (${d.toLocaleDateString()})`;
    if (diffDays > 1) return `Scraped ${diffDays} days ago (${d.toLocaleDateString()})`;
    return d.toLocaleDateString();
  } catch {
    return dateStr;
  }
}

async function loadReviewQueue() {
  try {
    let url = `${API_BASE}/api/review-queue`;
    if (state.reviewPeriod === 'past_week') {
      url += '?period=past_week';
    }
    const res = await fetch(url);
    if (res.ok) {
      const data = await res.json();
      state.reviewQueue = data.review_queue || [];
      renderReviewQueue();
    }
  } catch (err) {
    console.error('Error loading review queue:', err);
  }
}

function renderReviewQueue() {
  const container = document.getElementById('review-queue-cards');
  if (!container) return;

  let filtered = state.reviewQueue;
  if (state.filterPlatform && state.filterPlatform !== 'all') {
    filtered = filtered.filter(a => (a.platform_type || '').toLowerCase() === state.filterPlatform.toLowerCase());
  }

  if (state.search) {
    filtered = filtered.filter(a => 
      (a.job_title || '').toLowerCase().includes(state.search) ||
      (a.company || '').toLowerCase().includes(state.search) ||
      (a.platform_type || '').toLowerCase().includes(state.search)
    );
  }

  if (filtered.length === 0) {
    container.innerHTML = `<div style="text-align:center;padding:40px;color:var(--text-muted);">No pending review applications found for this filter.</div>`;
    return;
  }

  container.innerHTML = filtered.map(app => {
    const scrapedBadge = formatScrapedDate(app.date_scraped || app.applied_date);
    const fieldsList = Object.entries(app.fields_filled_json || {}).slice(0, 6).map(([k, v]) => `
      <div class="field-row" style="display:flex;justify-content:space-between;padding:4px 0;border-bottom:1px solid rgba(255,255,255,0.04);font-size:11.5px;">
        <span style="color:var(--text-muted);font-weight:500;">${escapeHtml(k)}:</span>
        <span style="color:var(--text-main);font-family:monospace;">${escapeHtml(String(v))}</span>
      </div>
    `).join('');

    const targetedPills = (app.skills_targeted || []).slice(0, 4).map(s => `<span class="badge-tag" style="background:rgba(2,132,199,0.12);color:#38bdf8;padding:2px 6px;border-radius:4px;font-size:11px;margin-right:4px;">${escapeHtml(s)}</span>`).join('');
    const gapPills = (app.skills_gap || []).map(s => `<span style="background:rgba(239,68,68,0.1);color:#ef4444;padding:2px 6px;border-radius:4px;font-size:11px;margin-right:4px;">${escapeHtml(s)}</span>`).join('') || '<span style="color:var(--text-muted);font-size:11px;">None (Strong Alignment)</span>';

    return `
      <div class="review-item" id="card-${app.id}" style="background:var(--bg-card);border:1px solid var(--border-color);border-radius:10px;padding:18px;margin-bottom:16px;">
        <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:12px;">
          <div>
            <h4 style="margin:0 0 4px 0;font-size:16px;color:var(--text-main);">${escapeHtml(app.job_title)}</h4>
            <div style="font-size:12px;color:var(--text-muted);display:flex;gap:8px;align-items:center;flex-wrap:wrap;">
              <strong style="color:var(--primary);">${escapeHtml(app.company)}</strong>
              <span>&bull;</span>
              <span>${escapeHtml(app.location || 'Remote')}</span>
              <span>&bull;</span>
              <span style="background:var(--bg-secondary);padding:2px 8px;border-radius:4px;font-size:11px;">📅 ${scrapedBadge}</span>
              <span>&bull;</span>
              <span style="text-transform:uppercase;font-weight:700;font-size:10px;padding:2px 6px;background:rgba(255,255,255,0.06);border-radius:4px;">${escapeHtml(app.platform_type)}</span>
            </div>
          </div>
          <span class="badge-score" style="background:rgba(16,185,129,0.12);color:#10b981;font-weight:700;padding:4px 10px;border-radius:6px;font-size:13px;">
            🎯 ${app.match_score_at_apply}% Match
          </span>
        </div>

        <div style="display:grid;grid-template-columns:1.2fr 1fr;gap:16px;margin-bottom:14px;">
          <div style="background:var(--bg-secondary);padding:12px;border-radius:6px;font-size:12px;">
            <div style="margin-bottom:6px;"><strong>Targeted Core Competencies:</strong> ${targetedPills}</div>
            <div style="margin-bottom:8px;"><strong>Honest Skills Gap:</strong> ${gapPills}</div>
            <div style="color:var(--text-muted);font-size:11.5px;line-height:1.4;">
              <strong>Job Summary:</strong> ${(escapeHtml(app.job_description || '')).substring(0, 260)}...
            </div>
          </div>

          <div style="background:var(--bg-secondary);padding:12px;border-radius:6px;">
            <div style="font-size:11.5px;font-weight:600;color:var(--text-muted);margin-bottom:6px;">PRE-FILLED ATS VALUES</div>
            ${fieldsList}
          </div>
        </div>

        <div style="display:flex;justify-content:space-between;align-items:center;border-top:1px solid var(--border-color);padding-top:12px;">
          <div style="font-size:12px;color:var(--text-muted);">
            Recruiter: <strong style="color:var(--text-main);">${escapeHtml(app.contact_person || 'Hiring Team')}</strong>
            ${app.contact_email ? ` &bull; <a href="mailto:${escapeHtml(app.contact_email)}" style="color:var(--primary);text-decoration:none;">${escapeHtml(app.contact_email)}</a>` : ''}
          </div>
          <div style="display:flex;gap:8px;">
            <button class="btn btn-secondary btn-sm" onclick="viewResume('${app.job_id}', '${escapeHtml(app.company)}', ${app.match_score_at_apply})">
              📄 View Documents (Resume & Cover Letter)
            </button>
            <button class="btn btn-primary btn-sm" onclick="launchFillApplication('${app.id}')">
              🚀 Launch & Pre-Fill
            </button>
            <button class="btn btn-secondary btn-sm" style="color:#10b981;" onclick="confirmSubmission('${app.id}')">
              ✅ Confirm Submitted
            </button>
            <button class="btn btn-secondary btn-sm" style="color:#ef4444;" onclick="skipApplication('${app.id}')">
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
  if (!tbody) return;

  let filtered = state.applications;
  if (state.filterStatus && state.filterStatus !== 'all') {
    filtered = filtered.filter(a => a.status === state.filterStatus);
  }

  if (state.search) {
    filtered = filtered.filter(a =>
      (a.job_title || '').toLowerCase().includes(state.search) ||
      (a.company || '').toLowerCase().includes(state.search)
    );
  }

  tbody.innerHTML = filtered.map(app => `
    <tr>
      <td>
        <strong>${escapeHtml(app.job_title || '')}</strong><br>
        <span style="font-size:12px;color:var(--text-muted);">${escapeHtml(app.company || '')}</span>
      </td>
      <td><span class="badge-tag">${escapeHtml((app.platform_type || '').toUpperCase())}</span></td>
      <td><strong>${app.match_score_at_apply || 0}%</strong></td>
      <td style="font-size:12px;color:var(--text-muted);">${formatScrapedDate(app.applied_date)}</td>
      <td>
        <span style="padding:2px 8px;border-radius:4px;font-size:11px;font-weight:600;${app.status === 'SUBMITTED' ? 'background:rgba(16,185,129,0.15);color:#10b981;' : 'background:rgba(245,158,11,0.15);color:#f59e0b;'}">
          ${escapeHtml(app.status)}
        </span>
      </td>
      <td>
        <select class="input input-sm" style="font-size:12px;" onchange="updateResponse('${app.id}', this.value)">
          <option value="No response" ${app.response_status === 'No response' ? 'selected' : ''}>No response</option>
          <option value="Interview" ${app.response_status === 'Interview' ? 'selected' : ''}>🎉 Interview</option>
          <option value="Offer" ${app.response_status === 'Offer' ? 'selected' : ''}>🏆 Offer</option>
          <option value="Rejected" ${app.response_status === 'Rejected' ? 'selected' : ''}>Rejected</option>
        </select>
      </td>
      <td>
        <button class="btn btn-secondary btn-sm" onclick="viewResume('${app.job_id}', '${escapeHtml(app.company || '')}', ${app.match_score_at_apply || 70})">
          📄 Docs
        </button>
      </td>
    </tr>
  `).join('');
}

window.switchResumeTab = function(tab) {
  const singleView = document.getElementById('view-single-resume');
  const coverView = document.getElementById('view-cover-letter');
  const compareView = document.getElementById('view-compare-resume');

  const tabTailored = document.getElementById('tab-tailored');
  const tabCover = document.getElementById('tab-coverletter');
  const tabCompare = document.getElementById('tab-compare');

  [tabTailored, tabCover, tabCompare].forEach(t => t.classList.remove('active'));
  [singleView, coverView, compareView].forEach(v => v.style.display = 'none');

  if (tab === 'coverletter') {
    coverView.style.display = 'block';
    tabCover.classList.add('active');
  } else if (tab === 'compare') {
    compareView.style.display = 'block';
    tabCompare.classList.add('active');
  } else {
    singleView.style.display = 'block';
    tabTailored.classList.add('active');
  }
};

window.viewResume = async function(jobId, company, score) {
  const modal = document.getElementById('modal-resume');
  document.getElementById('modal-resume-title').textContent = `Application Documents for ${company}`;
  document.getElementById('modal-resume-score').textContent = `🎯 ${score}% ATS Match`;
  document.getElementById('resume-frame').src = `${API_BASE}/api/resume/preview/${jobId}`;
  
  switchResumeTab('tailored');
  modal.style.display = 'flex';

  // Load Cover Letter
  try {
    const clRes = await fetch(`${API_BASE}/api/cover-letter/${jobId}`);
    if (clRes.ok) {
      const clData = await clRes.json();
      currentCoverLetterText = clData.cover_letter_text || '';
      const clFrame = document.getElementById('cover-letter-frame');
      clFrame.srcdoc = clData.cover_letter_html || `<pre style="padding:20px;">${currentCoverLetterText}</pre>`;
    }
  } catch (err) {
    console.error('Cover letter load notice:', err);
  }

  // Load JobRight Match Breakdown & Comparison
  try {
    const [compRes, breakRes] = await Promise.all([
      fetch(`${API_BASE}/api/resume/compare/${jobId}`),
      fetch(`${API_BASE}/api/match-breakdown/${jobId}`)
    ]);

    if (compRes.ok) {
      const data = await compRes.json();
      document.getElementById('compare-original-text').value = data.original_text || 'Original master profile text';
      document.getElementById('compare-tailored-frame').src = `${API_BASE}/api/resume/preview/${jobId}`;
      document.getElementById('compare-score-badge').textContent = `🎯 ${data.match_score}% Score`;
      
      const targetedStr = (data.skills_matched || []).join(', ') || 'General AI Leadership';
      const gapStr = (data.skills_gap || []).join(', ') || 'None (Strong Alignment)';
      document.getElementById('compare-skills-summary').innerHTML = `
        <strong>Targeted:</strong> <span style="color:var(--primary);">${escapeHtml(targetedStr)}</span> &nbsp;|&nbsp;
        <strong>Honest Gaps:</strong> <span style="color:#ef4444;">${escapeHtml(gapStr)}</span>
      `;
    }

    if (breakRes.ok) {
      const bd = await breakRes.json();
      const badge = document.getElementById('breakdown-rating-badge');
      badge.textContent = bd.badge_label || 'Strong Fit';
      badge.style.background = `${bd.badge_color || '#10b981'}22`;
      badge.style.color = bd.badge_color || '#10b981';

      const whyList = document.getElementById('breakdown-why-list');
      whyList.innerHTML = (bd.why_you_match || []).map(w => `<li>${escapeHtml(w)}</li>`).join('');

      document.getElementById('breakdown-gap-advice').textContent = bd.gap_mitigation_advice || 'No critical gaps identified.';
      document.getElementById('breakdown-salary-fit').textContent = `💰 ${bd.salary_fit || 'Target: $180k+'}`;
      document.getElementById('breakdown-remote-fit').textContent = `🌐 ${bd.remote_fit || 'Remote Match'}`;
    }
  } catch (err) {
    console.error('Breakdown load notice:', err);
  }
};

window.copyCoverLetterText = function() {
  if (!currentCoverLetterText) return;
  navigator.clipboard.writeText(currentCoverLetterText).then(() => {
    alert('Cover letter text copied to clipboard!');
  }).catch(err => {
    alert('Failed to copy: ' + err.message);
  });
};

window.launchFillApplication = async function(appId) {
  try {
    const res = await fetch(`${API_BASE}/api/applications/${appId}/launch-fill`, { method: 'POST' });
    if (res.ok) {
      const data = await res.json();
      if (data.posting_url) {
        window.open(data.posting_url, '_blank', 'noopener');
      } else {
        alert(data.message || 'No application URL for this job');
      }
    }
  } catch (err) {
    alert('Launch error: ' + err.message);
  }
};

window.confirmSubmission = async function(appId) {
  try {
    await fetch(`${API_BASE}/api/applications/${appId}/status`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ status: 'SUBMITTED', notes: 'Manually verified and confirmed by user' })
    });
    loadAll();
  } catch (err) {
    alert('Failed to confirm: ' + err.message);
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
    alert('Failed to update response: ' + err.message);
  }
};

async function loadPreferences() {
  try {
    const res = await fetch(`${API_BASE}/api/preferences`);
    if (res.ok) {
      state.preferences = await res.json();
      const p = state.preferences;
      const setVal = (id, val) => {
        const el = document.getElementById(id);
        if (el) el.value = val;
      };
      setVal('pref-target-titles', (p.target_titles || []).join(', '));
      setVal('pref-min-salary', p.min_salary || 180000);
      setVal('pref-max-daily', p.max_daily_applications || 15);
      setVal('pref-threshold', p.auto_tailor_threshold || 70);
      setVal('pref-visa', p.visa_status || 'US Citizen');
      setVal('pref-locations', (p.location_preferences || []).join(', '));
      setVal('pref-blacklist', (p.blacklisted_companies || []).join(', '));
    }
  } catch (err) {
    console.error('Error loading preferences:', err);
  }
}

async function savePreferences() {
  const getVal = id => (document.getElementById(id) || {}).value || '';
  const prefData = {
    target_titles: getVal('pref-target-titles').split(',').map(s => s.trim()).filter(Boolean),
    min_salary: parseInt(getVal('pref-min-salary')) || 180000,
    max_daily_applications: parseInt(getVal('pref-max-daily')) || 15,
    auto_tailor_threshold: parseInt(getVal('pref-threshold')) || 70,
    visa_status: getVal('pref-visa'),
    location_preferences: getVal('pref-locations').split(',').map(s => s.trim()).filter(Boolean),
    blacklisted_companies: getVal('pref-blacklist').split(',').map(s => s.trim()).filter(Boolean),
    remote_only: true,
    pacing_mode: 'balanced'
  };

  try {
    const res = await fetch(`${API_BASE}/api/preferences`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(prefData)
    });
    if (res.ok) {
      alert('Preferences and blacklist criteria saved successfully!');
    }
  } catch (err) {
    alert('Failed to save preferences: ' + err.message);
  }
}

async function loadProfile() {
  try {
    const res = await fetch(`${API_BASE}/api/profile`);
    if (res.ok) {
      state.profile = await res.json();
      renderProfileEditor(state.profile);
    }
  } catch (err) {
    console.error('Error loading profile:', err);
  }
}

function renderProfileEditor(p) {
  const container = document.getElementById('profile-fields-container');
  if (!container || !p) return;

  container.innerHTML = `
    <div class="field-card">
      <label>Full Name</label>
      <input type="text" id="prof-full-name" class="input" value="${escapeHtml(p.full_name || '')}">
    </div>
    <div class="field-card">
      <label>Email Address</label>
      <input type="email" id="prof-email" class="input" value="${escapeHtml(p.email || '')}">
    </div>
    <div class="field-card">
      <label>Phone Number</label>
      <input type="text" id="prof-phone" class="input" value="${escapeHtml(p.phone || '')}">
    </div>
    <div class="field-card">
      <label>Location / Address</label>
      <input type="text" id="prof-address" class="input" value="${escapeHtml(p.address || '')}">
    </div>
    <div class="field-card">
      <label>LinkedIn URL</label>
      <input type="url" id="prof-linkedin" class="input" value="${escapeHtml(p.linkedin_url || '')}">
    </div>
    <div class="field-card">
      <label>Portfolio / Personal Website</label>
      <input type="url" id="prof-portfolio" class="input" value="${escapeHtml(p.portfolio_url || '')}">
    </div>
    <div class="field-card">
      <label>Work Authorization (free text, e.g. "US Citizen")</label>
      <input type="text" id="prof-auth" class="input" value="${escapeHtml(p.work_authorization || '')}">
    </div>
    <div class="field-card">
      <label>Years of Experience</label>
      <input type="number" id="prof-years" class="input" value="${p.years_experience || 15}">
    </div>
    <div class="field-card">
      <label>Salary Expectation (e.g. "$180,000 - $220,000")</label>
      <input type="text" id="prof-salary" class="input" value="${escapeHtml(p.salary_expectation || '')}">
    </div>
    ${ANSWER_FIELDS.map(([key, label, choices]) => {
      const v = (p.custom_field_answers || {})[key] || '';
      const input = choices
        ? `<select id="ans-${key}" class="input"><option value="">(not set)</option>${choices.map(c => `<option ${c === v ? 'selected' : ''}>${c}</option>`).join('')}</select>`
        : `<input type="text" id="ans-${key}" class="input" value="${escapeHtml(v)}">`;
      return `<div class="field-card"><label>${label}</label>${input}</div>`;
    }).join('')}
  `;
}

// Application questions answered automatically from these values
const ANSWER_FIELDS = [
  ['work_authorized', 'Legally authorized to work in the US?', ['Yes', 'No']],
  ['requires_sponsorship', 'Will you now or in future require visa sponsorship?', ['Yes', 'No']],
  ['willing_to_relocate', 'Willing to relocate?', ['Yes', 'No']],
  ['location', 'Current location (city, state)', null],
  ['current_company', 'Current company', null],
  ['current_title', 'Current title', null],
  ['start_availability', 'Notice period / earliest start', null],
  ['how_did_you_hear', 'How did you hear about us (default answer)', null],
  ['github_url', 'GitHub URL (optional)', null],
];

async function saveProfile() {
  const getVal = id => (document.getElementById(id) || {}).value || '';
  const answers = Object.assign({}, (state.profile || {}).custom_field_answers || {});
  ANSWER_FIELDS.forEach(([key]) => { answers[key] = getVal(`ans-${key}`); });
  const profileData = {
    full_name: getVal('prof-full-name'),
    email: getVal('prof-email'),
    phone: getVal('prof-phone'),
    address: getVal('prof-address'),
    linkedin_url: getVal('prof-linkedin'),
    portfolio_url: getVal('prof-portfolio'),
    work_authorization: getVal('prof-auth'),
    salary_expectation: getVal('prof-salary'),
    years_experience: parseInt(getVal('prof-years')) || 15,
    custom_field_answers: answers
  };

  try {
    const res = await fetch(`${API_BASE}/api/profile`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(profileData)
    });
    if (res.ok) {
      alert('Candidate master profile saved successfully!');
    }
  } catch (err) {
    alert('Failed to save profile: ' + err.message);
  }
}

async function loadTaxonomy() {
  try {
    const res = await fetch(`${API_BASE}/api/taxonomy`);
    if (res.ok) {
      state.taxonomy = await res.json();
      const tbody = document.getElementById('taxonomy-tbody');
      if (tbody) {
        tbody.innerHTML = state.taxonomy.map(t => `
          <tr>
            <td><span class="badge-tag">${escapeHtml(t.platform_type.toUpperCase())}</span></td>
            <td><strong>${escapeHtml(t.field_name)}</strong></td>
            <td>${escapeHtml(t.field_type)}</td>
            <td><code>${escapeHtml(t.maps_to_profile_field || 'N/A')}</code></td>
            <td>${t.is_required ? '<span style="color:#ef4444;">Yes</span>' : '<span style="color:var(--text-muted);">No</span>'}</td>
            <td style="font-size:12px;color:var(--text-muted);">${formatScrapedDate(t.last_seen_at)}</td>
          </tr>
        `).join('');
      }
    }
  } catch (err) {
    console.error('Error loading taxonomy:', err);
  }
}

async function loadLogs() {
  try {
    const res = await fetch(`${API_BASE}/api/logs`);
    if (res.ok) {
      state.logs = await res.json();
      const term = document.getElementById('audit-terminal');
      if (term) {
        term.innerHTML = state.logs.map(l => `
          <div style="font-family:monospace;font-size:12px;margin-bottom:4px;">
            <span style="color:#64748b;">[${l.timestamp}]</span>
            <span style="color:${l.level === 'SUCCESS' ? '#10b981' : (l.level === 'WARNING' ? '#f59e0b' : '#38bdf8')};font-weight:700;">[${l.action}]</span>
            <span style="color:var(--text-main);">${escapeHtml(l.details || '')}</span>
          </div>
        `).join('');
      }
    }
  } catch (err) {
    console.error('Error loading logs:', err);
  }
}

async function runBatchPipeline() {
  const btn = document.getElementById('btn-run-batch');
  if (btn) {
    btn.disabled = true;
    btn.textContent = 'Ingesting, Tailoring & Generating Cover Letters...';
  }

  try {
    const res = await fetch(`${API_BASE}/api/run-batch`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ max_jobs: 10 })
    });
    if (res.ok) {
      setTimeout(() => {
        loadAll();
        if (btn) {
          btn.disabled = false;
          btn.innerHTML = `
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"></polygon></svg>
            Ingest & Run Pipeline
          `;
        }
      }, 3000);
    }
  } catch (err) {
    alert('Batch run failed: ' + err.message);
    if (btn) btn.disabled = false;
  }
}

function escapeHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}
