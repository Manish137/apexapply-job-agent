"""
LinkedIn Easy Apply Handler
===========================
LinkedIn prohibits automated applications and bans accounts that use them, so ApexApply never
drives LinkedIn. The application is queued for the human with the tailored resume ready.
"""

from typing import Dict, List, Any, Optional

from src.handlers.base_handler import BaseHandler, FillResult


class LinkedInEasyApplyHandler(BaseHandler):
    def __init__(self):
        super().__init__("linkedin")

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
            error_message="LinkedIn is never automated (account-ban risk): apply manually with the tailored resume"
        )
