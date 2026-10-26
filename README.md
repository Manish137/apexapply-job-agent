# ApexApply — Autonomous Job Application Agent & Command Center

**ApexApply** is a production-grade autonomous agent and dashboard that consumes listings from scraper feeds, extracts structured requirements, dynamically tailors high-impact resumes using the STAR framework, calculates honest ATS match scores, maps form fields across major ATS platforms (Greenhouse, Lever, Workday, LinkedIn, Custom), and manages Mode A (Human Confirms Submit) pre-fill review and execution.

---

## 🏗️ Architecture & Component Map

```
job-agent/
├── data/
│   ├── base_resumes/          # Source candidate profiles
│   ├── tailored_resumes/      # Dynamically generated HTML/MD/TXT tailored resumes
│   ├── screenshots/           # Pre-submit audit screenshots
│   └── job_agent.db           # SQLite database backing all 8 tables
├── src/
│   ├── ingestion.py           # Ingests scraper JSON feeds, normalizes, & deduplicates
│   ├── extraction.py          # LLM & regex requirement + recruiter contact extraction
│   ├── tailoring.py           # Deep dynamic STAR resume tailoring engine
│   ├── scoring.py             # Weighted 75/15/10 ATS match scoring (honest gap surfacing)
│   ├── field_taxonomy.py      # Discovered ATS field registry & mapping store
│   ├── form_engine.py         # Reads live form fields, answers & fills them, verifies submission
│   ├── resume_render.py       # Plain-text resume -> HTML / PDF / DOCX
│   ├── apply_cli.py           # Command line: apply to a job list
│   ├── handlers/
│   │   ├── base_handler.py    # Standard interface implemented by all handlers
│   │   ├── greenhouse.py      # Greenhouse ATS form automation
│   │   ├── lever.py           # Lever ATS form automation
│   │   ├── workday.py         # Workday multi-step portal handler (Mode A enforced)
│   │   ├── linkedin_easy_apply.py # LinkedIn Easy Apply handler (Mode A enforced)
│   │   └── generic_custom.py  # Generic form label-matching fallback
│   ├── executor.py            # Platform handler & screenshot coordinator
│   ├── orchestrator.py        # End-to-end pipeline coordinator with thresholding
│   ├── db.py                  # Full SQLite schema & CRUD operations
│   └── llm.py                 # LLM interface (Claude / Haiku 5.5 default, Mock, Gemini, Ollama)
├── dashboard/
│   ├── index.html             # Command Center UI (Review Queue, Ledger, Profile Editor)
│   ├── styles.css             # Dark-theme design system
│   ├── app.js                 # Reactive frontend controller & live polling
│   └── server.py              # FastAPI server hosting REST API & dashboard UI
├── tests/
│   ├── fixtures/sample_jobs.json # Test job fixtures
│   └── test_*.py               # 7 test suites (13 unit & integration tests)
├── .env.example
├── requirements.txt
└── README.md
```

---

## 💾 Database Schema (8 Tables)

1. **`base_resumes`**: Candidate master resumes and core skills.
2. **`jobs`**: Normalized job listings from scraper feeds (with `date_scraped`, `date_posted`, `status`, `platform_type`).
3. **`job_requirements`**: Extracted required skills, nice-to-haves, ATS keywords, contact person/email, and education.
4. **`tailored_resumes`**: Generated tailored HTML/MD resumes, match scores, added emphases, and honest `skills_gap[]`.
5. **`field_taxonomy`**: Catalog of discovered form fields across ATS platforms.
6. **`applications`**: Application ledger records, submission modes (`manual_confirm` vs `auto`), pre-submit screenshots, and editable response statuses (`No response`, `Interview`, `Offer`, `Rejected`).
7. **`profile`**: Master candidate profile values used by the Form Mapper.
8. **`audit_logs`**: Chronological event logs tracking every step of the ingestion, extraction, tailoring, and execution lifecycle.

---

## 🚀 Applying to Jobs (run on your own computer)

Job sites must be reachable and you need to see the browser, so run this on your laptop, not a server.

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium
cp .env.example .env        # then paste your ANTHROPIC_API_KEY into .env
```

**Your resume.** Every application uses `data/base_resumes/manish_shukla_fdpm_resume.txt`
(override with `BASE_RESUME_PATH`). Per job, only the summary may be rewritten by Claude, and any
rewrite that introduces a number not in your resume is rejected. Titles, dates, employers and
metrics are always copied verbatim. A PDF is generated per job and uploaded.

**Apply to the target list** (`data/jobs/*.json`, fields: title, company, url, description, location):

```bash
# Review mode (recommended): a browser opens per job with the whole form filled and your resume
# attached. Check it, click Submit yourself; it records SUBMITTED when the confirmation page shows.
python -m src.apply_cli --jobs data/jobs/fdpm_targets_2026-10-26.json --min-score 0

# Auto mode: submits on its own only when every required question is answered and there is no
# CAPTCHA; anything else stays in the dashboard Review Queue with the reason.
python -m src.apply_cli --jobs data/jobs/fdpm_targets_2026-10-26.json --min-score 0 --auto
```

Supported: Greenhouse (including embedded career-site iframes), Lever, Ashby, and generic forms.
Workday (needs an account) and LinkedIn (bans automation) are never automated; they are queued
for you to apply manually with the generated resume. EEO questions are always answered with
"decline to self-identify". Questions the profile and resume cannot answer are left for you.

**Dashboard:** `python -m uvicorn dashboard.server:app --port 8765` then open http://localhost:8765.
"Launch fill" on a Review Queue item opens the filled form in a browser for you to submit.

**Tests:** `python -m pytest -q`

---

## 🎯 Reviewer Notes
- **Resume Honesty Guarantee**: Never hallucinates or fabricates unheld skills. Calculates honest `skills_gap[]` and surfaces them directly on the dashboard.
- **Safety Policy**: Mode A (Human Confirms Submit) is enabled by default. LinkedIn and Workday permanently enforce Mode A to prevent account bans or malformed submissions.
- **Deterministic & Cloud-Ready**: Provider-agnostic LLM interface supports Gemini Free Tier, local Ollama models, and offline deterministic Mock mode for CI/CD.
