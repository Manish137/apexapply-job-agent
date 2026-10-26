"""
Orchestrator for ApexApply Job Agent
====================================
Coordinates the end-to-end pipeline:
Ingest -> Extract Requirements -> Tailor Resume -> Score -> Filter/Threshold -> Execute Application -> Log.
"""

import os
from pathlib import Path
from typing import Dict, List, Any, Optional

from src.db import get_connection, log_audit, get_profile, upsert_profile
from src.ingestion import IngestionService
from src.extraction import RequirementExtractionEngine
from src.tailoring import ResumeTailoringEngine
from src.executor import ApplicationExecutor
from src.scoring import MatchScorer
from src.llm import LLMInterface

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env")
except ImportError:
    pass

DEFAULT_DATA_DIR = Path(__file__).parent.parent / "data"

class JobAgentOrchestrator:
    def __init__(
        self,
        db_path: Optional[Path] = None,
        data_dir: Optional[Path] = None,
        llm: Optional[LLMInterface] = None,
        match_threshold: int = int(os.getenv("MATCH_SCORE_THRESHOLD", "70")),
        borderline_threshold: int = int(os.getenv("BORDERLINE_THRESHOLD", "50")),
        default_submission_mode: str = os.getenv("DEFAULT_SUBMISSION_MODE", "manual_confirm")
    ):
        self.db_path = db_path
        self.data_dir = data_dir or DEFAULT_DATA_DIR
        self.match_threshold = match_threshold
        self.borderline_threshold = borderline_threshold
        self.default_submission_mode = default_submission_mode

        self.llm = llm or LLMInterface()
        self.scorer = MatchScorer(match_threshold=match_threshold)
        self.ingestion = IngestionService(db_path=self.db_path)
        self.extraction = RequirementExtractionEngine(db_path=self.db_path, llm=self.llm)
        self.tailoring = ResumeTailoringEngine(db_path=self.db_path, data_dir=self.data_dir, llm=self.llm, scorer=self.scorer)
        self.executor = ApplicationExecutor(db_path=self.db_path, data_dir=self.data_dir, llm=self.llm)

    def get_or_create_profile(self) -> Dict[str, Any]:
        profile = get_profile("default_profile", self.db_path)
        if not profile:
            profile_data = {
                "id": "default_profile",
                "full_name": "Manish Shukla",
                "first_name": "Manish",
                "last_name": "Shukla",
                "email": "shukla.manish80@gmail.com",
                "phone": "(209) 319-8716",
                "address": "Tracy, CA",
                "linkedin_url": "https://linkedin.com/in/mshukla1",
                "portfolio_url": "https://manishshukla.dev",
                "work_authorization": "US Permanent Resident / Citizen",
                "salary_expectation": "$180,000 - $220,000",
                "years_experience": 15,
                "custom_field_answers": {
                    "why_join": "Passionate about building high-impact AI/ML platforms and workflow automations that bridge technical capabilities with tangible business ROI.",
                    "greatest_achievement": "Led a $10M+ risk workflow modernization at Charles Schwab replacing legacy systems with modern Appian architectures, and delivered an AI-powered OCR/LLM pipeline saving $900K annually at Baldwin Risk Partners."
                }
            }
            upsert_profile(profile_data, self.db_path)
            profile = profile_data
        return profile

    def run_pipeline_for_job(self, job_id: str, auto_submit: Optional[bool] = None,
                             min_score: Optional[int] = None, **apply_options) -> Dict[str, Any]:
        """Runs full pipeline for a single job with preference and blacklist checks."""
        from src.db import get_preferences
        prefs = get_preferences(db_path=self.db_path)

        conn = get_connection(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
        job_row = cursor.fetchone()
        conn.close()

        if not job_row:
            return {"job_id": job_id, "status": "FAILED", "error": "Job not found"}
        
        job = dict(job_row)
        company = job.get("company", "").lower()
        blacklisted = [b.lower() for b in prefs.get("blacklisted_companies", [])]

        # 0. Blacklist Check (ScaleJobs style)
        if any(b in company for b in blacklisted if b):
            conn = get_connection(self.db_path)
            cursor = conn.cursor()
            cursor.execute("UPDATE jobs SET status = 'SKIPPED' WHERE id = ?", (job_id,))
            conn.commit()
            conn.close()
            log_audit("JOB_SKIPPED", "WARNING", job_id, f"Company '{job.get('company')}' is in user blacklist", self.db_path)
            return {"job_id": job_id, "status": "SKIPPED", "reason": "Blacklisted company"}

        if auto_submit is None:
            auto_submit = self.default_submission_mode in ("auto", "auto_submit")

        # 1. Extraction
        reqs = self.extraction.process_job(job_id)
        if not reqs:
            return {"job_id": job_id, "status": "FAILED", "error": "Extraction failed"}

        # 2. Tailoring & Scoring & Cover Letter
        tailored = self.tailoring.tailor_for_job(job_id)
        if not tailored:
            return {"job_id": job_id, "status": "FAILED", "error": "Tailoring failed"}

        score = tailored["match_score"]
        threshold = min_score if min_score is not None else prefs.get("auto_tailor_threshold", self.borderline_threshold)

        # 3. Decision Threshold
        if score < threshold:
            conn = get_connection(self.db_path)
            cursor = conn.cursor()
            cursor.execute("UPDATE jobs SET status = 'SKIPPED' WHERE id = ?", (job_id,))
            conn.commit()
            conn.close()
            log_audit("JOB_SKIPPED", "WARNING", job_id, f"Match score ({score}%) below threshold ({threshold}%)", self.db_path)
            return {"job_id": job_id, "status": "SKIPPED", "match_score": score, "reason": "Low match score"}

        # 4. Execution
        profile = self.get_or_create_profile()
        app_result = self.executor.execute_application(job_id, profile, auto_submit=auto_submit, **apply_options)

        return {
            "job_id": job_id,
            "status": app_result["status"] if app_result else "FAILED",
            "match_score": score,
            "application": app_result,
            "cover_letter": tailored.get("cover_letter")
        }

    def run_batch_pipeline(self, max_jobs: int = 15, auto_submit: Optional[bool] = None) -> List[Dict[str, Any]]:
        """Processes unapplied jobs through the entire pipeline."""
        conn = get_connection(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM jobs WHERE status IN ('NEW', 'ANALYZED', 'TAILORED') LIMIT ?", (max_jobs,))
        rows = cursor.fetchall()
        conn.close()

        results = []
        for r in rows:
            res = self.run_pipeline_for_job(r["id"], auto_submit=auto_submit)
            results.append(res)
        return results

    def ingest_and_run(self, search_dirs: List[Path], max_jobs: int = 15) -> Dict[str, Any]:
        """Ingests scraper files and processes the batch."""
        new_c, dup_c = self.ingestion.scan_scraper_directories(search_dirs)
        results = self.run_batch_pipeline(max_jobs=max_jobs)
        return {
            "new_jobs_ingested": new_c,
            "duplicates_skipped": dup_c,
            "jobs_processed": len(results),
            "results": results
        }
