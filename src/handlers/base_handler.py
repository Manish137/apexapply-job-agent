"""
Base Handler Interface for Platform-Specific Form Automation
============================================================
All ATS platform handlers (Greenhouse, Lever, Workday, LinkedIn, Generic) implement this interface.
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Any, Optional
from dataclasses import dataclass

@dataclass
class FillResult:
    status: str  # DRAFT, PENDING_REVIEW, SUBMITTED, FAILED, CAPTCHA_BLOCKED
    platform_type: str
    fields_filled: Dict[str, Any]
    screenshot_path: Optional[str] = None
    captcha_detected: bool = False
    submission_mode: str = "manual_confirm"
    error_message: Optional[str] = None

class BaseHandler(ABC):
    def __init__(self, platform_name: str):
        self.platform_name = platform_name

    @abstractmethod
    def discover_fields(self, url: str, html_content: Optional[str] = None) -> List[Dict[str, Any]]:
        """Scans page DOM to discover form fields without submitting."""
        pass

    @abstractmethod
    def fill_form(
        self,
        job: Dict[str, Any],
        tailored_resume_path: str,
        profile: Dict[str, Any],
        screenshot_path: str,
        auto_submit: bool = False,
        html_fixture: Optional[str] = None
    ) -> FillResult:
        """Fills form fields, captures screenshot before submit, and submits if auto_submit=True (Mode B)."""
        pass
