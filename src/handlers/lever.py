"""
Lever Platform Handler
======================
Lever's form lives at jobs.lever.co/<company>/<posting-id>/apply.
"""

import re

from src.handlers.form_handler import FormHandler


class LeverHandler(FormHandler):
    submit_selectors = "#btn-submit, button[type='submit']"
    form_ready_selector = "form input[name='name'], form input[name='email']"

    def __init__(self, llm=None):
        super().__init__("lever", llm)

    def application_url(self, posting_url: str) -> str:
        m = re.search(r"(https://jobs\.lever\.co/[\w.-]+/[0-9a-f-]{36})", posting_url)
        return f"{m.group(1)}/apply" if m else posting_url
