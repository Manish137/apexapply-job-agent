"""
Base Handler Interface for Platform-Specific Form Automation
============================================================
All ATS platform handlers (Greenhouse, Lever, Ashby, Workday, LinkedIn, Generic) implement this interface.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, Callable
from dataclasses import dataclass


@dataclass
class FillResult:
    status: str  # PENDING_REVIEW, SUBMITTED, FAILED, CAPTCHA_BLOCKED
    platform_type: str
    fields_filled: Dict[str, Any]
    screenshot_path: Optional[str] = None
    captcha_detected: bool = False
    submission_mode: str = "manual_confirm"
    error_message: Optional[str] = None


class BaseHandler(ABC):
    # Whether this platform may ever be submitted without a human click
    allows_auto_submit = False

    def __init__(self, platform_name: str):
        self.platform_name = platform_name

    def application_url(self, posting_url: str) -> str:
        """Maps a job posting URL to the page that holds the application form."""
        return posting_url

    @abstractmethod
    def fill_form(
        self,
        job: Dict[str, Any],
        resume_pdf: str,
        resume_text: str,
        profile: Dict[str, Any],
        cover_letter: Callable[[], Dict[str, Any]],
        screenshot_path: str,
        auto_submit: bool = False,
        html_fixture: Optional[str] = None,
    ) -> FillResult:
        """Fills the form, screenshots it, and submits only if auto_submit and the form is complete."""
