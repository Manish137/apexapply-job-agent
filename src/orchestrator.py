"""
Orchestrator for ApexApply Job Agent
====================================
Discover -> Filter (title, blacklist, daily cap) -> Extract requirements ->
Select resume & score -> Fill application (cover letter written on demand) -> Log.
"""

import os
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime, timezone

from src.db import get_connection, log_audit, get_profile, upsert_profile, get_preferences
from src.ingestion import IngestionService
from src.extraction import RequirementExtractionEngine
from src.tailoring import ResumeTailoringEngine
from src.executor import ApplicationExecutor
from src.scoring import MatchScorer
from src.llm import LLMInterface, LLMError
from src.sources import JobSources, title_matches, DEFAULT_TARGET_TITLES

DEFAULT_DATA_DIR = Path(__file__).parent.parent / "data"

DEFAULT_PROFILE = {
    "id": "default_profile",
    "full_name": "Manish Shukla",
    "email": "shukla.manish80@gmail.com",
    "phone": "(209) 319-8716",
    "address": "Tracy, CA",
    "linkedin_url": "",
    "portfolio_url": "",
    "work_authorization": "",
    "salary_expectation": "",
    "years_experience": 15,
    "custom_field_answers": {
        "location": "Tracy, CA",
        "current_company": "Persistent Systems",
        "current_title": "Product Manager, AI/ML",
        "how_did_you_hear": "Company careers page",
        # Must be confirmed by the candidate in the dashboard before applications auto-submit
        "work_authorized": "",
        "requires_sponsorship": "",
        "willing_to_relocate": "",
        "start_availability": "",
    },
}

# Values seeded by earlier versions that were never real candidate data
STALE_PROFILE_VALUES = {"portfolio_url": "https://manishshukla.dev"}


def _env_auto_submit() -> bool:
    return os.getenv("SUBMIT_MODE", "review").lower() == "auto"


class JobAgentOrchestrator:
    def __init__(
        self,
        db_path: Optional[Path] = None,
        data_dir: Optional[Path] = None,
        llm: Optional[LLMInterface] = None,
        render_pdf: bool = True,
    ):
        self.db_path = db_path
        self.data_dir = data_dir or DEFAULT_DATA_DIR
        self.llm = llm or LLMInterface()
        self.scorer = MatchScorer()
        self.ingestion = IngestionService(db_path=self.db_path)
        self.extraction = RequirementExtractionEngine(db_path=self.db_path, llm=self.llm)
        self.tailoring = ResumeTailoringEngine(db_path=self.db_path, data_dir=self.data_dir, llm=self.llm,
                                               scorer=self.scorer, render_pdf=render_pdf)
        self.executor = ApplicationExecutor(db_path=self.db_path, data_dir=self.data_dir, llm=self.llm)
        self.sources = JobSources(db_path=self.db_path, data_dir=self.data_dir)

    def get_or_create_profile(self) -> Dict[str, Any]:
        profile = get_profile("default_profile", self.db_path)
        if not profile:
            upsert_profile(DEFAULT_PROFILE, self.db_path)
            return get_profile("default_profile", self.db_path)
        changed = False
        for key, stale in STALE_PROFILE_VALUES.items():
            if profile.get(key) == stale:
                profile[key] = ""
                changed = True
        answers = profile.get("custom_field_answers") or {}
        for key, val in DEFAULT_PROFILE["custom_field_answers"].items():
            if key not in answers:
                answers[key] = val
                changed = True
        profile["custom_field_answers"] = answers
        if changed:
            upsert_profile(profile, self.db_path)
        return profile

    def readiness(self) -> Dict[str, Any]:
        """What still blocks fully automatic applications."""
        profile = self.get_or_create_profile()
        answers = profile.get("custom_field_answers") or {}
        missing = [k for k in ("work_authorized", "requires_sponsorship") if not answers.get(k)]
        missing += [k for k in ("linkedin_url", "salary_expectation") if not profile.get(k)]
        resumes = self.tailoring.resumes.available()
        return {
            "llm": self.llm.status(),
            "resumes": resumes,
            "profile_missing": missing,
            "submit_mode": "auto" if _env_auto_submit() else "review",
            "ready": all(resumes.values()) and not missing,
        }

    def _applied_today(self) -> int:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        conn = get_connection(self.db_path)
        n = conn.execute("SELECT COUNT(*) AS c FROM applications WHERE status = 'SUBMITTED' AND applied_date LIKE ?",
                         (f"{today}%",)).fetchone()["c"]
        conn.close()
        return n

    def _set_job_status(self, job_id: str, status: str):
        conn = get_connection(self.db_path)
        conn.execute("UPDATE jobs SET status = ? WHERE id = ?", (status, job_id))
        conn.commit()
        conn.close()

    def run_pipeline_for_job(self, job_id: str, auto_submit: Optional[bool] = None, enforce_titles: bool = True) -> Dict[str, Any]:
        prefs = get_preferences(db_path=self.db_path)
        conn = get_connection(self.db_path)
        job_row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        conn.close()
        if not job_row:
            return {"job_id": job_id, "status": "FAILED", "error": "Job not found"}
        job = dict(job_row)

        company = (job.get("company") or "").lower()
        if any(b.lower() in company for b in prefs.get("blacklisted_companies", []) if b):
            self._set_job_status(job_id, "SKIPPED")
            log_audit("JOB_SKIPPED", "WARNING", job_id, f"Company '{job.get('company')}' is blacklisted", self.db_path)
            return {"job_id": job_id, "status": "SKIPPED", "reason": "Blacklisted company"}

        targets = prefs.get("target_titles") or DEFAULT_TARGET_TITLES
        if enforce_titles and not title_matches(job.get("title", ""), targets):
            self._set_job_status(job_id, "SKIPPED")
            return {"job_id": job_id, "status": "SKIPPED", "reason": "Title not in target titles"}

        if auto_submit is None:
            auto_submit = _env_auto_submit()
        if auto_submit and self._applied_today() >= int(prefs.get("max_daily_applications", 15)):
            return {"job_id": job_id, "status": "DEFERRED", "reason": "Daily application cap reached"}

        try:
            reqs = self.extraction.process_job(job_id)
        except LLMError as e:
            self._set_job_status(job_id, "FAILED")
            log_audit("EXTRACT_FAILED", "ERROR", job_id, str(e), self.db_path)
            return {"job_id": job_id, "status": "FAILED", "error": f"LLM: {e}"}
        if not reqs:
            return {"job_id": job_id, "status": "FAILED", "error": "Extraction failed"}

        tailored = self.tailoring.tailor_for_job(job_id)
        if not tailored:
            self._set_job_status(job_id, "FAILED")
            return {"job_id": job_id, "status": "FAILED", "error": "Resume PDF not uploaded (see /api/base-resume)"}

        score = tailored["match_score"]
        threshold = int(prefs.get("auto_tailor_threshold", 40))
        if score < threshold:
            self._set_job_status(job_id, "SKIPPED")
            log_audit("JOB_SKIPPED", "WARNING", job_id, f"Match {score}% below threshold {threshold}%", self.db_path)
            return {"job_id": job_id, "status": "SKIPPED", "match_score": score, "reason": "Low match score"}

        profile = self.get_or_create_profile()
        app_result = self.executor.execute_application(
            job_id, profile, auto_submit=auto_submit, resume_text=tailored["resume_text"],
            cover_letter=lambda: self.tailoring.generate_cover_letter(job_id, tailored["resume_text"], profile),
        )
        return {
            "job_id": job_id,
            "company": job.get("company"),
            "title": job.get("title"),
            "status": app_result["status"] if app_result else "FAILED",
            "match_score": score,
            "resume_variant": tailored["variant"],
            "application": app_result,
        }

    def run_batch_pipeline(self, max_jobs: int = 10, auto_submit: Optional[bool] = None) -> List[Dict[str, Any]]:
        conn = get_connection(self.db_path)
        rows = conn.execute(
            "SELECT id FROM jobs WHERE status IN ('NEW', 'ANALYZED', 'TAILORED') ORDER BY date_scraped DESC").fetchall()
        conn.close()
        results = []
        for r in rows:
            res = self.run_pipeline_for_job(r["id"], auto_submit=auto_submit)
            if res["status"] == "SKIPPED" and res.get("reason") == "Title not in target titles":
                continue
            results.append(res)
            if res["status"] == "DEFERRED" or len(results) >= max_jobs:
                break
        return results

    def discover_and_run(self, max_jobs: int = 10, auto_submit: Optional[bool] = None) -> Dict[str, Any]:
        prefs = get_preferences(db_path=self.db_path)
        discovered = self.sources.discover(prefs.get("target_titles") or DEFAULT_TARGET_TITLES)
        results = self.run_batch_pipeline(max_jobs=max_jobs, auto_submit=auto_submit)
        log_audit("BATCH_DONE", "INFO", "",
                  f"Processed {len(results)} jobs: " + ", ".join(f"{r.get('company')}={r['status']}" for r in results),
                  self.db_path)
        return {"discovered": discovered, "jobs_processed": len(results), "results": results}

    def ingest_and_run(self, search_dirs: List[Path], max_jobs: int = 10) -> Dict[str, Any]:
        """Legacy path: ingest scraper JSON files, then process."""
        new_c, dup_c = self.ingestion.scan_scraper_directories(search_dirs)
        results = self.run_batch_pipeline(max_jobs=max_jobs)
        return {"new_jobs_ingested": new_c, "duplicates_skipped": dup_c, "jobs_processed": len(results), "results": results}
