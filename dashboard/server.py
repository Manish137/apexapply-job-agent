"""
Dashboard Server for ApexApply Job Agent
========================================
FastAPI backend powering the Tracker, Review Queue, Profile Editor, Field Taxonomy, and Scraper Ingestion.
"""

import os
import json
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta
from fastapi import FastAPI, HTTPException, BackgroundTasks, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from src.db import get_connection, get_profile, upsert_profile, log_audit
from src.orchestrator import JobAgentOrchestrator
from src.field_taxonomy import FieldTaxonomyService

app = FastAPI(title="ApexApply Dashboard API", version="2.5.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
    max_jobs: Optional[int] = 25
    auto_submit: Optional[bool] = False

@app.on_event("startup")
def startup():
    orchestrator.get_or_create_profile()
    taxonomy_service.seed_standard_taxonomy()
    # Ingest historical jobs on startup if empty
    search_dirs = [
        Path("/Users/manishshukla/job-hunter"),
        Path("/Users/manishshukla/.gemini/antigravity-ide/scratch/agent-command-center/output/jobs"),
        DATA_DIR / "jobs",
        DASHBOARD_DIR.parent / "tests" / "fixtures"
    ]
    orchestrator.ingestion.scan_scraper_directories(search_dirs)

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
        seven_days_ago = (datetime.utcnow() - timedelta(days=7)).strftime("%Y-%m-%d")
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
    SELECT a.*, j.posting_url, j.company, j.title, tr.file_path as resume_file_path
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

    # Open the browser window to the job URL
    if url and url.startswith("http"):
        import subprocess
        subprocess.Popen(["open", url])
        log_audit("LAUNCH_PORTAL", "INFO", app_id, f"Opened live ATS portal for {job_data['company']} in browser", DB_PATH)
        return {"status": "success", "message": f"Opened live portal for {job_data['company']} in browser"}
    else:
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
    search_dirs = [
        Path("/Users/manishshukla/job-hunter"),
        Path("/Users/manishshukla/.gemini/antigravity-ide/scratch/agent-command-center/output/jobs"),
        DATA_DIR / "jobs",
        DASHBOARD_DIR.parent / "tests" / "fixtures"
    ]
    def background_run():
        orchestrator.ingest_and_run(search_dirs, max_jobs=req.max_jobs or 25)
    bg.add_task(background_run)
    return {"status": "processing", "message": f"Autonomous pipeline triggered for up to {req.max_jobs} jobs"}

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

    res = orchestrator.run_pipeline_for_job(norm["id"], auto_submit=req.auto_submit)
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

    tailored_text = ""
    if d.get("file_path") and Path(d["file_path"]).exists():
        with open(d["file_path"], "r", encoding="utf-8") as f:
            tailored_text = f.read()

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

@app.get("/api/resume/preview/{job_id}")
def preview_resume_endpoint(job_id: str):
    conn = get_connection(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT file_path FROM tailored_resumes WHERE job_id = ? ORDER BY generated_at DESC LIMIT 1", (job_id,))
    row = cursor.fetchone()
    conn.close()
    if row and Path(row["file_path"]).exists():
        return FileResponse(str(row["file_path"]), media_type="text/html")
    raise HTTPException(status_code=404, detail="Tailored resume not found")

# Static Dashboard Files
if DASHBOARD_DIR.exists():
    app.mount("/", StaticFiles(directory=str(DASHBOARD_DIR), html=True), name="dashboard")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8765)
