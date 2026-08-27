"""
LinkedIn Easy Apply Platform Handler
====================================
Automates LinkedIn Easy Apply steps in Mode A (human confirms submit).
"""

from pathlib import Path
from typing import Dict, List, Any, Optional

from src.handlers.base_handler import BaseHandler, FillResult
from src.mapper import ApplicationFieldMapper

class LinkedInEasyApplyHandler(BaseHandler):
    def __init__(self):
        super().__init__("linkedin")

    def discover_fields(self, url: str, html_content: Optional[str] = None) -> List[Dict[str, Any]]:
        return [
            {"field_name": "Full Name", "field_type": "text", "maps_to_profile_field": "full_name", "is_required": True},
            {"field_name": "Email", "field_type": "text", "maps_to_profile_field": "email", "is_required": True},
            {"field_name": "Phone Country Code", "field_type": "text", "maps_to_profile_field": "phone", "is_required": True},
            {"field_name": "Mobile Phone Number", "field_type": "text", "maps_to_profile_field": "phone", "is_required": True},
            {"field_name": "Resume Upload", "field_type": "file", "maps_to_profile_field": "resume_file", "is_required": True},
            {"field_name": "Years of Experience", "field_type": "text", "maps_to_profile_field": "years_experience", "is_required": True}
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
        # Decision 4: LinkedIn is permanently Mode A (manual confirm) to avoid account bans
        discovered = self.discover_fields(job.get("posting_url", ""))
        mapper = ApplicationFieldMapper(profile)
        mapping_result = mapper.map_fields(discovered, tailored_resume_path=tailored_resume_path)

        Path(screenshot_path).parent.mkdir(parents=True, exist_ok=True)
        if not Path(screenshot_path).exists():
            with open(screenshot_path, "w", encoding="utf-8") as f:
                f.write(f"[Screenshot Placeholder: LinkedIn Easy Apply for {job.get('company')}]")

        return FillResult(
            status="PENDING_REVIEW",
            platform_type=self.platform_name,
            fields_filled=mapping_result["mapped_fields"],
            screenshot_path=screenshot_path,
            submission_mode="manual_confirm"
        )
