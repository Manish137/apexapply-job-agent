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
│   ├── mapper.py              # Candidate profile -> form field mapper
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
│   └── llm.py                 # Multi-provider LLM interface (Mock, Gemini Free, Ollama)
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

## 🚀 Getting Started

### 1. Install Dependencies
```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Run Test Suite (100% Pass Rate)
```bash
python -m unittest discover -s tests
```

### 3. Launch Dashboard & API Server
```bash
python -m uvicorn dashboard.server:app --host 0.0.0.0 --port 8765
```
Open **`http://localhost:8765`** in your browser.

---

## 🎯 Reviewer Notes
- **Resume Honesty Guarantee**: Never hallucinates or fabricates unheld skills. Calculates honest `skills_gap[]` and surfaces them directly on the dashboard.
- **Safety Policy**: Mode A (Human Confirms Submit) is enabled by default. LinkedIn and Workday permanently enforce Mode A to prevent account bans or malformed submissions.
- **Deterministic & Cloud-Ready**: Provider-agnostic LLM interface supports Gemini Free Tier, local Ollama models, and offline deterministic Mock mode for CI/CD.
