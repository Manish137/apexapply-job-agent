"""
Application Executor for ApexApply Job Agent
============================================
Runs the platform handler for a job and records the honest outcome in the
applications ledger.
"""

import json
from pathlib import Path
from typing import Dict, Any, Optional, Callable
from datetime import datetime, timezone

from src.db import get_connection, log_audit
from src.llm import LLMInterface
from src.handlers.base_handler import BaseHandler, FillResult
from src.handlers.greenhouse import GreenhouseHandler
from src.handlers.lever import LeverHandler
from src.handlers.ashby import AshbyHandler
from src.handlers.workday import WorkdayHandler
from src.handlers.linkedin_easy_apply import LinkedInEasyApplyHandler
from src.handlers.generic_custom import GenericCustomHandler

DEFAULT_DATA_DIR = Path(__file__).parent.parent / "data"


class ApplicationExecutor:
    def __init__(self, db_path: Optional[Path] = None, data_dir: Optional[Path] = None, llm: Optional[LLMInterface] = None):
        self.db_path = db_path
        self.data_dir = data_dir or DEFAULT_DATA_DIR
        self.screenshots_dir = self.data_dir / "screenshots"
        self.screenshots_dir.mkdir(parents=True, exist_ok=True)
        self.handlers: Dict[str, BaseHandler] = {
            "greenhouse": GreenhouseHandler(llm),
            "lever": LeverHandler(llm),
            "ashby": AshbyHandler(llm),
            "workday": WorkdayHandler(),
            "linkedin": LinkedInEasyApplyHandler(),
            "custom": GenericCustomHandler(llm),
            "remoteok": GenericCustomHandler(llm),
        }

    def get_handler(self, platform_type: str) -> BaseHandler:
        return self.handlers.get((platform_type or "custom").lower(), self.handlers["custom"])

    def execute_application(
        self,
        job_id: str,
        profile: Dict[str, Any],
        auto_submit: bool = False,
        resume_text: str = "",
        cover_letter: Optional[Callable[[], Dict[str, Any]]] = None,
        html_fixture: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        conn = get_connection(self.db_path)
        cursor = conn.cursor()
        # Never apply twice
        cursor.execute("SELECT * FROM applications WHERE job_id = ? AND status = 'SUBMITTED'", (job_id,))
        existing = cursor.fetchone()
        cursor.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
        job_row = cursor.fetchone()
        cursor.execute("SELECT * FROM tailored_resumes WHERE job_id = ?", (job_id,))
        tailored_row = cursor.fetchone()
        conn.close()
        if existing:
            return dict(existing)
        if not job_row or not tailored_row:
            return None
        job, tailored = dict(job_row), dict(tailored_row)

        platform_type = job.get("platform_type") or "custom"
        handler = self.get_handler(platform_type)
        screenshot_path = str(self.screenshots_dir / f"screenshot_{job_id}.png")

        try:
            result: FillResult = handler.fill_form(
                job=job,
                resume_pdf=tailored["file_path"],
                resume_text=resume_text,
                profile=profile,
                cover_letter=cover_letter or (lambda: {}),
                screenshot_path=screenshot_path,
                auto_submit=auto_submit,
                html_fixture=html_fixture,
            )
        except Exception as e:
            result = FillResult("FAILED", platform_type, {}, error_message=f"{type(e).__name__}: {e}")

        app_id = f"app_{job_id}"
        applied_date = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        conn = get_connection(self.db_path)
        conn.execute(
            """INSERT OR REPLACE INTO applications (
                id, job_id, tailored_resume_id, status, applied_date,
                screenshot_before_submit_path, fields_filled_json, contact_person,
                contact_email, skills_targeted, match_score_at_apply,
                submission_mode, response_status, error_log, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (app_id, job_id, tailored["id"], result.status, applied_date, result.screenshot_path,
             json.dumps(result.fields_filled), job.get("contact_person") or "", job.get("contact_email") or "",
             tailored.get("skills_added_emphasis") or "[]", tailored.get("match_score"), result.submission_mode,
             "No response", result.error_message or "", f"{platform_type} handler"),
        )
        job_status = {"SUBMITTED": "APPLIED", "FAILED": "FAILED"}.get(result.status, "QUEUED")
        conn.execute("UPDATE jobs SET status = ? WHERE id = ?", (job_status, job_id))
        conn.commit()
        conn.close()

        level = {"SUBMITTED": "SUCCESS", "FAILED": "ERROR"}.get(result.status, "WARNING")
        log_audit("APPLICATION_EXECUTED", level, job_id,
                  f"{result.status} at {job['company']} ({platform_type}). {result.error_message or ''}".strip(),
                  self.db_path)
        return {
            "id": app_id,
            "job_id": job_id,
            "status": result.status,
            "applied_date": applied_date,
            "match_score": tailored.get("match_score"),
            "submission_mode": result.submission_mode,
            "fields_filled": result.fields_filled,
            "screenshot_path": result.screenshot_path,
            "error": result.error_message,
        }
