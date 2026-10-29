"""
Shared Playwright-backed handler for ATS platforms whose forms the FormAgent can drive.
"""

from typing import Dict, Any, Optional, Callable

from src.handlers.base_handler import BaseHandler, FillResult
from src.form_agent import FormAgent
from src.llm import LLMInterface


class FormHandler(BaseHandler):
    allows_auto_submit = True
    submit_selectors = "button[type='submit'], input[type='submit']"
    form_ready_selector = "form input, form textarea"

    def __init__(self, platform_name: str, llm: Optional[LLMInterface] = None):
        super().__init__(platform_name)
        self.llm = llm

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
        agent = FormAgent(llm=self.llm or LLMInterface(), submit_selectors=self.submit_selectors,
                          form_ready_selector=self.form_ready_selector)
        url = self.application_url(job.get("posting_url", ""))
        if not url.startswith("http") and html_fixture is None:
            return FillResult("FAILED", self.platform_name, {}, error_message="Job has no application URL")
        return agent.run(self.platform_name, url, job, profile, resume_pdf, resume_text, cover_letter,
                         screenshot_path, auto_submit and self.allows_auto_submit, html_fixture=html_fixture)
