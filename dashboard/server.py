"""
Dashboard Server for ApexApply Job Agent
========================================
FastAPI backend powering the Tracker, Review Queue, Profile Editor, Field Taxonomy, and Scraper Ingestion.
"""

import os
import json
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta, timezone
import base64
import secrets
from fastapi import FastAPI, HTTPException, BackgroundTasks, Query, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse, Response
from pydantic import BaseModel

from src.db import get_connection, get_profile, upsert_profile, log_audit
from src.orchestrator import JobAgentOrchestrator
from src.field_taxonomy import FieldTaxonomyService

app = FastAPI(title="ApexApply Dashboard API", version="3.0.0")

DASHBOARD_USER = os.getenv("DASHBOARD_USER", "apex")
DASHBOARD_PASSWORD = os.getenv("DASHBOARD_PASSWORD", "")


@app.middleware("http")
async def basic_auth(request: Request, call_next):
    """The dashboard holds personal data and can submit applications, so it sits behind a password."""
    if not DASHBOARD_PASSWORD:
        return await call_next(request)
    header = request.headers.get("authorization", "")
    if header.startswith("Basic "):
        try:
            user, _, pw = base64.b64decode(header[6:]).decode().partition(":")
            if secrets.compare_digest(user, DASHBOARD_USER) and secrets.compare_digest(pw, DASHBOARD_PASSWORD):
                return await call_next(request)
        except Exception:
            pass
    return Response(status_code=401, headers={"WWW-Authenticate": 'Basic realm="ApexApply"'})

DASHBOARD_DIR = Path(__file__).parent
DATA_DIR = DASHBOARD_DIR.parent / "data"
DB_PATH = DATA_DIR / "job_agent.db"

orchestrator = JobAgentOrchestrator(db_path=DB_PATH, data_dir=DATA_DIR)
taxonomy_service = FieldTaxonomyService(db_path=DB_PATH)

# Request Models
class ResponseStatusUpdate(BaseModel):
    response_status: str  # No response, Rejected, Interview, Offer

class ApplicationStatusUpdate(BaseModel):
    status: str  # SUBMITTED, SKIPPED, FAILED
    notes: Optional[str] = ""

class CustomJobRequest(BaseModel):
    title: str
    company: str
    url: Optional[str] = ""
    description: Optional[str] = ""
    location: Optional[str] = "Remote"
    salary: Optional[str] = "Not listed"
    auto_submit: Optional[bool] = False

class BatchRunRequest(BaseModel):
    max_jobs: Optional[int] = 10
    auto_submit: Optional[bool] = None  # None = use SUBMIT_MODE

@app.on_event("startup")
def startup():
    from src.db import init_db
    init_db(DB_PATH)
    orchestrator.get_or_create_profile()
    taxonomy_service.seed_standard_taxonomy()
    if not DASHBOARD_PASSWORD:
        log_audit("SECURITY", "WARNING", "", "DASHBOARD_PASSWORD is not set: the dashboard is open to anyone who can reach it", DB_PATH)


@app.get("/api/readiness")
def readiness_endpoint():
    """LLM health, uploaded resumes, and profile answers still needed for auto-submit."""
    return orchestrator.readiness()


@app.post("/api/base-resume/{variant}")
async def upload_base_resume(variant: str, request: Request):
    """Upload a reviewed resume PDF as the raw request body: curl --data-binary @resume.pdf"""
    try:
        return orchestrator.tailoring.resumes.save_pdf(variant, await request.body())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/sources")
def get_sources_endpoint():
    return orchestrator.sources.load()


@app.put("/api/sources")
def put_sources_endpoint(sources: Dict[str, List[str]]):
    orchestrator.sources.save(sources)
    return orchestrator.sources.load()


@app.post("/api/discover")
def discover_endpoint():
    """Scans the configured job boards for target titles without applying."""
    from src.db import get_preferences
    return orchestrator.sources.discover(get_preferences(db_path=DB_PATH).get("target_titles"))


@app.post("/api/jobs/{job_id}/apply")
def apply_job_endpoint(job_id: str, auto_submit: Optional[bool] = None):
    return orchestrator.run_pipeline_for_job(job_id, auto_submit=auto_submit, enforce_titles=False)


@app.get("/api/jobs")
def list_jobs_endpoint(status: Optional[str] = None, limit: int = 100):
    conn = get_connection(DB_PATH)
    q = "SELECT id, title, company, location, posting_url, platform_type, salary_range, status, date_scraped FROM jobs"
    params: List[Any] = []
    if status:
        q += " WHERE status = ?"
        params.append(status)
    q += " ORDER BY date_scraped DESC LIMIT ?"
    params.append(limit)
    rows = [dict(r) for r in conn.execute(q, params).fetchall()]
    conn.close()
    return {"jobs": rows}

@app.get("/api/stats")
def get_stats():
    conn = get_connection(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) as c FROM applications")
    total_apps = cursor.fetchone()["c"]

    cursor.execute("SELECT COUNT(*) as c FROM applications WHERE status = 'PENDING_REVIEW'")
    pending_review = cursor.fetchone()["c"]

    cursor.execute("SELECT COUNT(*) as c FROM applications WHERE status = 'SUBMITTED'")
    submitted = cursor.fetchone()["c"]

    cursor.execute("SELECT AVG(match_score_at_apply) as avg_s FROM applications")
    avg_row = cursor.fetchone()["avg_s"]
    avg_score = round(avg_row, 1) if avg_row else 0.0

    cursor.execute("SELECT COUNT(*) as c FROM jobs")
    total_jobs = cursor.fetchone()["c"]

    conn.close()
    return {
        "total_applications": total_apps,
        "pending_review": pending_review,
        "submitted": submitted,
        "average_match_score": avg_score,
        "total_jobs_scraped": total_jobs
    }

@app.get("/api/applications")
def list_applications(status: Optional[str] = None, period: Optional[str] = None):
    conn = get_connection(DB_PATH)
    cursor = conn.cursor()
    
    query = """
    SELECT 
        a.id, a.job_id, a.tailored_resume_id, a.status, a.applied_date,
        a.screenshot_before_submit_path, a.fields_filled_json, a.contact_person,
        a.contact_email, a.skills_targeted, a.match_score_at_apply,
        a.submission_mode, a.response_status, a.error_log, a.notes,
        j.title as job_title, j.company, j.posting_url, j.platform_type, j.location, j.salary_range,
        j.description_raw as job_description, j.date_scraped, j.date_posted, j.source_scraper_id,
        tr.file_path as resume_file_path, tr.skills_gap, tr.skills_added_emphasis
    FROM applications a
    JOIN jobs j ON a.job_id = j.id
    LEFT JOIN tailored_resumes tr ON a.tailored_resume_id = tr.id
    """
    clauses = []
    params = []
    if status and status != "all":
        clauses.append("a.status = ?")
        params.append(status)
    
    if period == "past_week":
        seven_days_ago = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
        clauses.append("(j.date_scraped >= ? OR j.date_posted >= ?)")
        params.extend([seven_days_ago, seven_days_ago])

    if clauses:
        query += " WHERE " + " AND ".join(clauses)

    query += " ORDER BY a.applied_date DESC, j.date_scraped DESC"

    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()

    results = []
    for r in rows:
        d = dict(r)
        try:
            d["fields_filled_json"] = json.loads(d.get("fields_filled_json") or "{}")
        except:
            d["fields_filled_json"] = {}
        try:
            d["skills_targeted"] = json.loads(d.get("skills_targeted") or "[]")
        except:
            d["skills_targeted"] = []
        try:
            d["skills_gap"] = json.loads(d.get("skills_gap") or "[]")
        except:
            d["skills_gap"] = []
        results.append(d)

    return {"applications": results}

@app.get("/api/review-queue")
def get_review_queue(period: Optional[str] = None):
    return list_applications(status="PENDING_REVIEW", period=period)

@app.post("/api/applications/{app_id}/launch-fill")
def launch_fill(app_id: str):
    """Launches Playwright or browser to the live job URL and fills the form."""
    conn = get_connection(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
    SELECT a.*, j.posting_url, j.platform_type, j.company, j.title, tr.file_path as resume_file_path
    FROM applications a
    JOIN jobs j ON a.job_id = j.id
    LEFT JOIN tailored_resumes tr ON a.tailored_resume_id = tr.id
    WHERE a.id = ?
    """, (app_id,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        raise HTTPException(status_code=404, detail="Application not found")

    job_data = dict(row)
    url = job_data.get("posting_url")

    # The server is headless; the dashboard opens this URL in the user's own browser
    if url and url.startswith("http"):
        log_audit("LAUNCH_PORTAL", "INFO", app_id, f"Opened {job_data['company']} application for manual finish", DB_PATH)
        return {"status": "success", "posting_url": url, "platform_type": job_data.get("platform_type") or "custom"}
    return {"status": "warning", "message": "No valid URL to open"}

@app.patch("/api/applications/{app_id}/response-status")
def update_response_status(app_id: str, req: ResponseStatusUpdate):
    conn = get_connection(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("UPDATE applications SET response_status = ? WHERE id = ?", (req.response_status, app_id))
    conn.commit()
    conn.close()
    log_audit("UPDATE_RESPONSE_STATUS", "INFO", app_id, f"Updated response status to {req.response_status}", DB_PATH)
    return {"status": "success", "response_status": req.response_status}

@app.patch("/api/applications/{app_id}/status")
def update_application_status(app_id: str, req: ApplicationStatusUpdate):
    conn = get_connection(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("UPDATE applications SET status = ?, notes = ? WHERE id = ?", (req.status, req.notes or "Confirmed by user in Review Queue", app_id))
    conn.commit()
    conn.close()
    log_audit("UPDATE_APP_STATUS", "SUCCESS", app_id, f"Transitioned application to {req.status}", DB_PATH)
    return {"status": "success", "new_status": req.status}

@app.get("/api/profile")
def get_profile_endpoint():
    profile = orchestrator.get_or_create_profile()
    return profile

@app.post("/api/profile")
def update_profile_endpoint(profile_data: Dict[str, Any]):
    upsert_profile(profile_data, DB_PATH)
    log_audit("UPDATE_PROFILE", "INFO", "", "Updated master candidate profile", DB_PATH)
    return {"status": "success", "profile": profile_data}

@app.get("/api/taxonomy")
def get_taxonomy_endpoint():
    return {"taxonomy": taxonomy_service.get_all_taxonomy()}

@app.get("/api/logs")
def get_logs_endpoint(limit: int = 50):
    conn = get_connection(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM audit_logs ORDER BY id DESC LIMIT ?", (limit,))
    rows = cursor.fetchall()
    conn.close()
    return {"logs": [dict(r) for r in rows]}

@app.post("/api/run-batch")
def run_batch_endpoint(req: BatchRunRequest, bg: BackgroundTasks):
    def background_run():
        orchestrator.discover_and_run(max_jobs=req.max_jobs or 10, auto_submit=req.auto_submit)
    bg.add_task(background_run)
    return {"status": "processing", "message": f"Searching job boards and applying to up to {req.max_jobs} jobs"}

@app.post("/api/apply-custom")
def apply_custom_endpoint(req: CustomJobRequest):
    import hashlib
    job_id = f"job_manual_{hashlib.md5(f'{req.company}_{req.title}'.encode()).hexdigest()[:10]}"
    norm = orchestrator.ingestion.normalize_job_dict({
        "id": job_id,
        "title": req.title,
        "company": req.company,
        "url": req.url,
        "description": req.description,
        "location": req.location,
        "salary": req.salary
    }, source_id="manual_dashboard_entry")

    conn = get_connection(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
    INSERT OR REPLACE INTO jobs (
        id, source_scraper_id, title, company, description_raw,
        posting_url, platform_type, location, remote_flag, salary_range,
        contact_person, contact_email, date_scraped, date_posted, status
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        norm["id"], norm["source_scraper_id"], norm["title"], norm["company"],
        norm["description_raw"], norm["posting_url"], norm["platform_type"],
        norm["location"], norm["remote_flag"], norm["salary_range"],
        norm["contact_person"], norm["contact_email"], norm["date_scraped"],
        norm["date_posted"], norm["status"]
    ))
    conn.commit()
    conn.close()

    res = orchestrator.run_pipeline_for_job(norm["id"], auto_submit=req.auto_submit, enforce_titles=False)
    return {"status": "success", "result": res}

@app.get("/api/resume/compare/{job_id}")
def compare_resume_endpoint(job_id: str):
    conn = get_connection(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
    SELECT tr.*, br.file_path as original_file_path, br.name as original_name, j.company, j.title
    FROM tailored_resumes tr
    JOIN base_resumes br ON tr.base_resume_id = br.id
    JOIN jobs j ON tr.job_id = j.id
    WHERE tr.job_id = ?
    ORDER BY tr.generated_at DESC LIMIT 1
    """, (job_id,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        raise HTTPException(status_code=404, detail="Tailored resume comparison not found")

    d = dict(row)
    original_text = ""
    if d.get("original_file_path") and Path(d["original_file_path"]).exists():
        with open(d["original_file_path"], "r", encoding="utf-8") as f:
            original_text = f.read()

    # The resume sent is the candidate's own PDF; show where it is served from
    tailored_text = f'<p>Resume sent: <a href="/api/resume/preview/{job_id}" target="_blank">{Path(d.get("file_path") or "").name}</a> (unchanged PDF)</p>'

    return {
        "job_id": job_id,
        "company": d.get("company"),
        "title": d.get("title"),
        "match_score": d.get("match_score"),
        "original_name": d.get("original_name"),
        "original_text": original_text,
        "tailored_html": tailored_text,
        "skills_matched": json.loads(d.get("skills_added_emphasis") or "[]"),
        "skills_gap": json.loads(d.get("skills_gap") or "[]")
    }

@app.get("/api/screenshot/{job_id}")
def get_screenshot_endpoint(job_id: str):
    conn = get_connection(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT screenshot_before_submit_path FROM applications WHERE job_id = ?", (job_id,))
    row = cursor.fetchone()
    conn.close()

    if row and row["screenshot_before_submit_path"] and Path(row["screenshot_before_submit_path"]).exists():
        return FileResponse(row["screenshot_before_submit_path"], media_type="image/png")
    
    # Fallback to default screenshot placeholder
    default_ss = DATA_DIR / "screenshots" / f"screenshot_{job_id}.png"
    if default_ss.exists():
        return FileResponse(str(default_ss), media_type="image/png")
    raise HTTPException(status_code=404, detail="Screenshot not found")

@app.get("/api/cover-letter/{job_id}")
def get_cover_letter_endpoint(job_id: str):
    from src.db import get_cover_letter
    cl = get_cover_letter(job_id, DB_PATH)
    if not cl:
        raise HTTPException(status_code=404, detail="Cover letter not found for this job")
    return cl

@app.get("/api/match-breakdown/{job_id}")
def get_match_breakdown_endpoint(job_id: str):
    from src.scoring import MatchScorer
    from src.db import get_profile, get_preferences
    
    conn = get_connection(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
    job_row = cursor.fetchone()
    if not job_row:
        conn.close()
        raise HTTPException(status_code=404, detail="Job not found")
    
    cursor.execute("SELECT * FROM job_requirements WHERE job_id = ?", (job_id,))
    req_row = cursor.fetchone()
    conn.close()

    job = dict(job_row)
    reqs = dict(req_row) if req_row else {}
    if reqs and isinstance(reqs.get("required_skills"), str):
        try:
            reqs["required_skills"] = json.loads(reqs["required_skills"])
            reqs["nice_to_have_skills"] = json.loads(reqs.get("nice_to_have_skills") or "[]")
            reqs["keywords_for_ats"] = json.loads(reqs.get("keywords_for_ats") or "[]")
        except:
            pass

    profile = get_profile(db_path=DB_PATH) or {}
    prefs = get_preferences(db_path=DB_PATH)

    # Skills actually found in the resume used for this job
    conn = get_connection(DB_PATH)
    tr = conn.execute("SELECT skills_added_emphasis FROM tailored_resumes WHERE job_id = ?", (job_id,)).fetchone()
    conn.close()
    candidate_skills = json.loads(tr["skills_added_emphasis"] or "[]") if tr else []

    scorer = MatchScorer()
    breakdown = scorer.generate_match_breakdown(
        candidate_skills=candidate_skills,
        candidate_years=profile.get("years_experience", 15),
        candidate_target_salary=prefs.get("min_salary", 180000),
        job=job,
        job_requirements=reqs
    )
    breakdown["job_id"] = job_id
    breakdown["company"] = job.get("company")
    breakdown["title"] = job.get("title")
    return breakdown

@app.get("/api/preferences")
def get_preferences_endpoint():
    from src.db import get_preferences
    return get_preferences(db_path=DB_PATH)

@app.patch("/api/preferences")
def update_preferences_endpoint(pref_data: Dict[str, Any]):
    from src.db import upsert_preferences, get_preferences
    upsert_preferences(pref_data, db_path=DB_PATH)
    return {"status": "success", "preferences": get_preferences(db_path=DB_PATH)}

@app.get("/api/resume/preview/{job_id}")
def preview_resume_endpoint(job_id: str):
    conn = get_connection(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT file_path FROM tailored_resumes WHERE job_id = ? ORDER BY generated_at DESC LIMIT 1", (job_id,))
    row = cursor.fetchone()
    conn.close()
    if row and Path(row["file_path"]).exists():
        return FileResponse(str(row["file_path"]), media_type="application/pdf")
    raise HTTPException(status_code=404, detail="Tailored resume not found")

# Static Dashboard Files
if DASHBOARD_DIR.exists():
    app.mount("/", StaticFiles(directory=str(DASHBOARD_DIR), html=True), name="dashboard")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8765)
