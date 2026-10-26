"""
Workday Platform Handler
========================
Workday portals require a per-company candidate account and multi-step wizards, so ApexApply
does not automate them. The application is queued for the human with the tailored resume ready.
"""

from typing import Dict, List, Any, Optional

from src.handlers.base_handler import BaseHandler, FillResult


class WorkdayHandler(BaseHandler):
    def __init__(self):
        super().__init__("workday")

    def discover_fields(self, url: str, html_content: Optional[str] = None) -> List[Dict[str, Any]]:
        return []

    def fill_form(self, job: Dict[str, Any], tailored_resume_path: str, profile: Dict[str, Any],
                  screenshot_path: str, auto_submit: bool = False, html_fixture: Optional[str] = None,
                  **kwargs) -> FillResult:
        return FillResult(
            status="PENDING_REVIEW",
            platform_type=self.platform_name,
            fields_filled={},
            screenshot_path=None,
            submission_mode="manual_confirm",
            error_message="Workday needs a candidate account: apply manually with the tailored resume"
        )
