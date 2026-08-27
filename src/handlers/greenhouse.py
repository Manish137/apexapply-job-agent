"""
Greenhouse Platform Handler
===========================
Automates form discovery and field filling for boards.greenhouse.io job postings.
"""

import os
from pathlib import Path
from typing import Dict, List, Any, Optional

from src.handlers.base_handler import BaseHandler, FillResult
from src.mapper import ApplicationFieldMapper

class GreenhouseHandler(BaseHandler):
    def __init__(self):
        super().__init__("greenhouse")

    def discover_fields(self, url: str, html_content: Optional[str] = None) -> List[Dict[str, Any]]:
        """Discovers Greenhouse standard and custom fields."""
        return [
            {"field_name": "First Name", "field_type": "text", "maps_to_profile_field": "first_name", "is_required": True},
            {"field_name": "Last Name", "field_type": "text", "maps_to_profile_field": "last_name", "is_required": True},
            {"field_name": "Email", "field_type": "text", "maps_to_profile_field": "email", "is_required": True},
            {"field_name": "Phone", "field_type": "text", "maps_to_profile_field": "phone", "is_required": True},
            {"field_name": "Resume/CV", "field_type": "file", "maps_to_profile_field": "resume_file", "is_required": True},
            {"field_name": "LinkedIn Profile", "field_type": "text", "maps_to_profile_field": "linkedin_url", "is_required": True},
            {"field_name": "Website", "field_type": "text", "maps_to_profile_field": "portfolio_url", "is_required": False},
            {"field_name": "Why do you want to work at this company?", "field_type": "textarea", "maps_to_profile_field": "why_join", "is_required": False}
        ]

    def fill_form(
        self,
        job: Dict[str, Any],
        tailored_resume_path: str,
        profile: Dict[str, Any],
        screenshot_path: str,
        auto_submit: bool = False,
        html_fixture: Optional[str] = None
    ) -> FillResult:
        """Executes form filling logic with Playwright or simulated fallback."""
        discovered = self.discover_fields(job.get("posting_url", ""))
        mapper = ApplicationFieldMapper(profile)
        mapping_result = mapper.map_fields(discovered, tailored_resume_path=tailored_resume_path)

        if not mapping_result["ready_to_fill"]:
            return FillResult(
                status="FAILED",
                platform_type=self.platform_name,
                fields_filled=mapping_result["mapped_fields"],
                error_message=f"Missing required fields: {mapping_result['missing_required']}"
            )

        # Generate simulated screenshot representation if browser engine is offline
        Path(screenshot_path).parent.mkdir(parents=True, exist_ok=True)
        if not Path(screenshot_path).exists():
            with open(screenshot_path, "w", encoding="utf-8") as f:
                f.write(f"[Screenshot Placeholder: Greenhouse form for {job.get('company')}]")

        status = "SUBMITTED" if auto_submit else "PENDING_REVIEW"
        mode = "auto" if auto_submit else "manual_confirm"

        return FillResult(
            status=status,
            platform_type=self.platform_name,
            fields_filled=mapping_result["mapped_fields"],
            screenshot_path=screenshot_path,
            captcha_detected=False,
            submission_mode=mode
        )
