# ApexApply: Job Application Agent

Finds Forward Deployed PM roles on company job boards, picks the right resume, writes a cover letter,
fills the application form, and submits it when every required answer is known.

## How it works

1. **Discover**: reads the public Greenhouse, Lever and Ashby job-board APIs for the companies in
   `data/sources.json` (editable at `GET/PUT /api/sources`) and keeps titles matching the target titles in
   Preferences, in the US or remote.
2. **Extract**: the LLM (Gemini or Claude) pulls required skills from each job description.
3. **Resume**: uses one of *your own* reviewed PDFs, never generated text. Financial-services roles get the
   `fintech` resume; the rest get the `general` one. The match score is computed against the real resume text.
4. **Cover letter**: the LLM writes one per job from your resume only (no invented facts), saved as text and PDF.
5. **Apply**: Playwright opens the form, reads every field, answers standard questions from your profile
   (contact, links, work authorization, sponsorship, relocation, EEO "decline", consent), asks the LLM for
   the rest, uploads the resume and cover letter, and:
   - `SUBMIT_MODE=review`: stops before submit (status `PENDING_REVIEW`, screenshot saved)
   - `SUBMIT_MODE=auto`: submits Greenhouse/Lever/Ashby forms **only** when every required field was
     answered confidently and no captcha is showing, then checks for the confirmation page.

   Workday, LinkedIn and unknown career sites are never auto-submitted: they land in the review queue with
   the resume and cover letter ready.

Statuses: `SUBMITTED` (confirmation seen), `PENDING_REVIEW` (the error log says what's missing),
`CAPTCHA_BLOCKED`, `FAILED`.

## Deploy (VPS with Docker)

```bash
mkdir apexapply && cd apexapply
curl -O https://raw.githubusercontent.com/Manish137/apexapply-job-agent/main/docker-compose.yml
curl -o .env https://raw.githubusercontent.com/Manish137/apexapply-job-agent/main/.env.example
nano .env    # set GEMINI_API_KEY (or ANTHROPIC_API_KEY + LLM_PROVIDER=claude) and DASHBOARD_PASSWORD
docker compose up -d --build
```

Upload your two resume PDFs (user `apex`, your dashboard password):

```bash
curl -u apex:PASSWORD --data-binary @Manish_Shukla_Forward_Deployed_PM.pdf http://SERVER:8765/api/base-resume/general
curl -u apex:PASSWORD --data-binary @Manish_Shukla_Forward_Deployed_PM_Fintech.pdf http://SERVER:8765/api/base-resume/fintech
```

Then open `http://SERVER:8765`, fill in the Profile tab (work authorization, sponsorship, LinkedIn, salary),
and check `http://SERVER:8765/api/readiness` until `"ready": true`.

Update to the latest code: `docker compose up -d --build`.

## API

| Endpoint | Purpose |
|---|---|
| `GET /api/readiness` | LLM live check, resumes uploaded, profile answers still missing |
| `POST /api/discover` | Scan job boards, add matching roles (no applying) |
| `POST /api/run-batch` `{"max_jobs": 5}` | Discover, then apply to up to N jobs (uses `SUBMIT_MODE`) |
| `POST /api/jobs/{id}/apply?auto_submit=true` | Apply to one job |
| `GET /api/jobs` | Jobs found and their status |
| `GET /api/applications` | Application ledger with errors and screenshots |

## Development

```bash
pip install -r requirements.txt && python -m playwright install chromium
python -m pytest -q
```

Tests run the form agent against local Greenhouse-style and Lever-style forms, with the mock LLM.
