"""
Workday Handler
===============
Workday requires a per-company account and multi-page flows; it is left to the
candidate. The job is queued for review with the link to apply manually.
"""

from typing import Dict, Any, Optional, Callable

from src.handlers.base_handler import BaseHandler, FillResult


class WorkdayHandler(BaseHandler):
    def __init__(self, platform_name: str = "workday"):
        super().__init__(platform_name)

    def fill_form(self, job: Dict[str, Any], resume_pdf: str, resume_text: str, profile: Dict[str, Any],
                  cover_letter: Callable[[], Dict[str, Any]], screenshot_path: str, auto_submit: bool = False,
                  html_fixture: Optional[str] = None) -> FillResult:
        cover_letter()
        return FillResult("PENDING_REVIEW", self.platform_name, {"apply_manually": job.get("posting_url", "")},
                          submission_mode="manual_confirm",
                          error_message=f"{self.platform_name.title()} is applied manually (resume and cover letter are ready)")
