"""
Ashby Platform Handler
======================
Ashby's form lives at jobs.ashbyhq.com/<company>/<posting-id>/application and renders client-side.
"""

import re

from src.handlers.form_handler import FormHandler


class AshbyHandler(FormHandler):
    submit_selectors = "button.ashby-application-form-submit-button, button[type='submit']"
    form_ready_selector = "input[type='email'], input[name='_systemfield_email'], input[type='file']"

    def __init__(self, llm=None):
        super().__init__("ashby", llm)

    def application_url(self, posting_url: str) -> str:
        m = re.search(r"(https://jobs\.ashbyhq\.com/[^/?#]+/[0-9a-f-]{36})", posting_url)
        return f"{m.group(1)}/application" if m else posting_url
