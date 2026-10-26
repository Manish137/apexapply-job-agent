"""
Application Executor for ApexApply Job Agent
============================================
Coordinates platform-specific handlers to execute form filling, screenshot logging,
and application recording in Mode A (manual review) or Mode B (auto-submit).
"""

import json
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime

from src.db import get_connection, log_audit
from src.handlers.base_handler import BaseHandler, FillResult
from src.handlers.greenhouse import GreenhouseHandler
from src.handlers.lever import LeverHandler
from src.handlers.workday import WorkdayHandler
from src.handlers.linkedin_easy_apply import LinkedInEasyApplyHandler
from src.handlers.generic_custom import GenericCustomHandler
from src.handlers.ashby import AshbyHandler
from src.llm import LLMInterface

DEFAULT_DATA_DIR = Path(__file__).parent.parent / "data"

class ApplicationExecutor:
    def __init__(self, db_path: Optional[Path] = None, data_dir: Optional[Path] = None,
                 llm: Optional[LLMInterface] = None):
        self.db_path = db_path
        self.llm = llm or LLMInterface()
        self.data_dir = data_dir or DEFAULT_DATA_DIR
        self.screenshots_dir = self.data_dir / "screenshots"
        self.screenshots_dir.mkdir(parents=True, exist_ok=True)

        self.handlers: Dict[str, BaseHandler] = {
            "greenhouse": GreenhouseHandler(),
            "lever": LeverHandler(),
            "workday": WorkdayHandler(),
            "linkedin": LinkedInEasyApplyHandler(),
            "custom": GenericCustomHandler(),
            "remoteok": GenericCustomHandler(),
            "ashby": AshbyHandler()
        }

    def get_handler(self, platform_type: str) -> BaseHandler:
        return self.handlers.get(platform_type.lower(), self.handlers["custom"])

    @staticmethod
    def upload_file_for(resume_path: str) -> str:
        """ATS forms want PDF/DOCX: use the PDF rendered next to the tailored HTML when present."""
        if not resume_path:
            return ""
        for ext in (".pdf", ".docx"):
            candidate = Path(resume_path).with_suffix(ext)
            if candidate.exists():
                return str(candidate)
        return resume_path

    def execute_application(
        self,
        job_id: str,
        profile: Dict[str, Any],
        auto_submit: bool = False,
        headless: Optional[bool] = None,
        wait_for_user_seconds: int = 0,
        retry_pending: bool = False
    ) -> Optional[Dict[str, Any]]:
        """Fills and records an application for a tailored job."""
        conn = get_connection(self.db_path)
        cursor = conn.cursor()

        # Idempotency check: never apply twice; PENDING_REVIEW is retried only when asked
        skip_statuses = ('SUBMITTED',) if retry_pending else ('SUBMITTED', 'PENDING_REVIEW')
        cursor.execute(f"SELECT * FROM applications WHERE job_id = ? AND status IN ({','.join('?' * len(skip_statuses))})",
                       (job_id, *skip_statuses))
        existing_app = cursor.fetchone()
        if existing_app:
            conn.close()
            return dict(existing_app)

        cursor.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
        job_row = cursor.fetchone()
        if not job_row:
            conn.close()
            return None
        job = dict(job_row)

        cursor.execute("SELECT * FROM tailored_resumes WHERE job_id = ?", (job_id,))
        tailored_row = cursor.fetchone()
        if not tailored_row:
            conn.close()
            return None
        tailored = dict(tailored_row)
        tailored_resume_path = tailored.get("file_path", "")
        match_score = tailored.get("match_score", 70)
        skills_targeted = json.loads(tailored.get("skills_added_emphasis") or "[]")

        platform_type = job.get("platform_type", "custom")
        handler = self.get_handler(platform_type)

        # Enforce Section 13 Decision 4: LinkedIn & Workday stay Mode A manual_confirm
        if platform_type in ["linkedin", "workday"]:
            auto_submit = False

        screenshot_path = str(self.screenshots_dir / f"screenshot_{job_id}.png")

        resume_text = ""
        txt_path = Path(tailored_resume_path).with_suffix(".txt") if tailored_resume_path else None
        if txt_path and txt_path.exists():
            resume_text = txt_path.read_text(encoding="utf-8")
        if hasattr(handler, "question_answerer"):
            handler.question_answerer = lambda qs: self.llm.answer_application_questions(
                qs, profile, resume_text, job.get("company", ""), job.get("title", ""), job.get("description_raw", ""))

        extra = {}
        if headless is not None:
            extra["headless"] = headless
        if wait_for_user_seconds:
            extra["wait_for_user_seconds"] = wait_for_user_seconds

        fill_result: FillResult = handler.fill_form(
            job=job,
            tailored_resume_path=self.upload_file_for(tailored_resume_path),
            profile=profile,
            screenshot_path=screenshot_path,
            auto_submit=auto_submit,
            **extra
        )

        app_id = f"app_{job_id}"
        applied_date = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

        cursor.execute("""
        INSERT OR REPLACE INTO applications (
            id, job_id, tailored_resume_id, status, applied_date,
            screenshot_before_submit_path, fields_filled_json, contact_person,
            contact_email, skills_targeted, match_score_at_apply,
            submission_mode, response_status, error_log, notes
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            app_id,
            job_id,
            tailored["id"],
            fill_result.status,
            applied_date,
            fill_result.screenshot_path,
            json.dumps(fill_result.fields_filled),
            job.get("contact_person", "Hiring Team"),
            job.get("contact_email", ""),
            json.dumps(skills_targeted),
            match_score,
            fill_result.submission_mode,
            "No response",
            fill_result.error_message or "",
            f"Filled via {platform_type.upper()} handler."
        ))

        # Update jobs status
        new_job_status = "APPLIED" if fill_result.status == "SUBMITTED" else "QUEUED"
        cursor.execute("UPDATE jobs SET status = ? WHERE id = ?", (new_job_status, job_id))

        conn.commit()
        conn.close()

        log_audit("APPLICATION_EXECUTED", "SUCCESS", job_id, 
                  f"Status: {fill_result.status} (Mode: {fill_result.submission_mode}) for {job['company']}", 
                  self.db_path)

        return {
            "id": app_id,
            "job_id": job_id,
            "status": fill_result.status,
            "applied_date": applied_date,
            "match_score": match_score,
            "submission_mode": fill_result.submission_mode,
            "fields_filled": fill_result.fields_filled,
            "screenshot_path": fill_result.screenshot_path,
            "error": fill_result.error_message
        }
