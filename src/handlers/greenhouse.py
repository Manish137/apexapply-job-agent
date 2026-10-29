"""
Greenhouse Platform Handler
===========================
Greenhouse hosted boards show the application form on the job page itself.
"""

import re

from src.handlers.form_handler import FormHandler


class GreenhouseHandler(FormHandler):
    submit_selectors = "#submit_app, button[type='submit'], input[type='submit']"
    form_ready_selector = "#application-form input, #application_form input, form input#first_name, form input[name='first_name']"

    def __init__(self, llm=None):
        super().__init__("greenhouse", llm)

    def application_url(self, posting_url: str) -> str:
        # boards.greenhouse.io/<co>/jobs/<id> and job-boards.greenhouse.io/<co>/jobs/<id> both carry the form
        m = re.search(r"greenhouse\.io/(?:embed/job_app\?for=)?([\w-]+)/jobs/(\d+)", posting_url)
        if m:
            return f"https://job-boards.greenhouse.io/{m.group(1)}/jobs/{m.group(2)}"
        return posting_url
