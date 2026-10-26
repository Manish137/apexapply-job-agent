"""
Live ATS Handler
================
Shared Playwright flow for public ATS application forms (Greenhouse, Lever, Ashby, generic):
open the posting, reach the application form, read its real fields, fill them via FormEngine,
screenshot, then either submit (Mode B) or hand the open browser to the human (Mode A, headed).
"""

import os
import re
import time
import base64
from pathlib import Path
from typing import Dict, List, Any, Optional, Callable

from src.handlers.base_handler import BaseHandler, FillResult
from src.form_engine import FormEngine

TINY_PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")
APPLY_BUTTON = "a:has-text('Apply for this job'), a:has-text('Apply now'), button:has-text('Apply for this job'), button:has-text('Apply now'), a:has-text('Apply'), button:has-text('Apply')"


class LiveATSHandler(BaseHandler):
    submit_selector = "button[type='submit'], input[type='submit']"

    def __init__(self, platform_name: str = "custom"):
        super().__init__(platform_name)
        self.question_answerer: Optional[Callable] = None
        self.cover_letter_path: str = ""

    def application_url(self, url: str) -> str:
        return url

    def discover_fields(self, url: str, html_content: Optional[str] = None) -> List[Dict[str, Any]]:
        # Fields are discovered live from the form DOM inside fill_form.
        return []

    @staticmethod
    def _fillable_count(frame) -> int:
        try:
            return frame.locator("input:not([type=hidden]):visible, textarea:visible, select:visible").count()
        except Exception:
            return 0

    def locate_form_frame(self, page):
        """Returns the frame holding the application form (handles embedded Greenhouse iframes)."""
        best, best_n = page.main_frame, self._fillable_count(page.main_frame)
        for fr in page.frames[1:]:
            n = self._fillable_count(fr)
            if n > best_n:
                best, best_n = fr, n
        if best_n < 2:
            btn = page.locator(APPLY_BUTTON)
            if btn.count() > 0:
                try:
                    btn.first.click(timeout=5000)
                    page.wait_for_timeout(2500)
                except Exception:
                    pass
                return self.locate_form_frame_no_click(page)
        return best

    def locate_form_frame_no_click(self, page):
        best, best_n = page.main_frame, -1
        for fr in page.frames:
            n = self._fillable_count(fr)
            if n > best_n:
                best, best_n = fr, n
        return best

    def fill_form(
        self,
        job: Dict[str, Any],
        tailored_resume_path: str,
        profile: Dict[str, Any],
        screenshot_path: str,
        auto_submit: bool = False,
        html_fixture: Optional[str] = None,
        headless: Optional[bool] = None,
        wait_for_user_seconds: int = 0
    ) -> FillResult:
        """
        auto_submit=True  -> submit only when every required field is answered and no CAPTCHA is shown;
                             SUBMITTED only on a confirmation that appears after the click.
        wait_for_user_seconds>0 (headed) -> leave the filled form open for the human to review and
                             click Submit; SUBMITTED if confirmation is seen before the timeout.
        """
        if headless is None:
            headless = os.getenv("HEADLESS", "true").lower() != "false"
        url = self.application_url(job.get("posting_url", "") or "")
        Path(screenshot_path).parent.mkdir(parents=True, exist_ok=True)
        engine = FormEngine(profile, resume_path=tailored_resume_path,
                            cover_letter_path=self.cover_letter_path,
                            question_answerer=self.question_answerer)
        mode = "auto" if auto_submit else "manual_confirm"
        status, error, captcha = "PENDING_REVIEW", None, False
        filled: Dict[str, Any] = {}

        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=headless)
                page = browser.new_page(viewport={"width": 1280, "height": 900})
                if html_fixture:
                    page.set_content(html_fixture)
                elif url.startswith("http"):
                    page.goto(url, timeout=45000, wait_until="domcontentloaded")
                    try:
                        page.wait_for_load_state("networkidle", timeout=10000)
                    except Exception:
                        pass
                else:
                    raise ValueError("Job has no application URL")

                frame = self.locate_form_frame(page)
                fields = engine.discover(frame)
                if not fields:
                    raise RuntimeError("No application form fields found on the page")
                answers = engine.resolve_answers(fields, job)
                run = engine.fill(frame, fields, answers)
                filled = dict(run.answers)
                captcha = engine.has_captcha(frame)
                page.screenshot(path=screenshot_path, full_page=True)

                problems = []
                if run.unanswered_required:
                    problems.append(f"Needs your answer: {run.unanswered_required}")
                if run.fill_errors:
                    problems.append(f"Fill issues: {run.fill_errors}")
                if captcha:
                    problems.append("CAPTCHA present")

                if auto_submit and not run.unanswered_required and not captcha:
                    res = engine.submit_and_verify(page, frame, self.submit_selector)
                    if res["submitted"]:
                        status = "SUBMITTED"
                    else:
                        captcha = captcha or bool(res.get("captcha"))
                        problems.append(res["error"])
                elif auto_submit:
                    problems.append("Not auto-submitted")

                if status != "SUBMITTED" and not headless and wait_for_user_seconds > 0:
                    # Mode A: the human reviews the filled form and clicks Submit themselves.
                    deadline = time.time() + wait_for_user_seconds
                    while time.time() < deadline:
                        try:
                            page.wait_for_timeout(1500)
                        except Exception:
                            break  # browser closed by the user
                        if engine.page_shows_confirmation(page):
                            status = "SUBMITTED"
                            problems = []
                            break

                error = "; ".join(problems) or None
                if captcha and status != "SUBMITTED":
                    status = "CAPTCHA_BLOCKED" if auto_submit else status
                try:
                    browser.close()
                except Exception:
                    pass
        except Exception as e:
            error = f"Automation error: {str(e).splitlines()[0][:300]}"
            if not Path(screenshot_path).exists():
                Path(screenshot_path).write_bytes(TINY_PNG)

        return FillResult(
            status=status,
            platform_type=self.platform_name,
            fields_filled=filled,
            screenshot_path=screenshot_path,
            captcha_detected=captcha,
            submission_mode=mode,
            error_message=error
        )
