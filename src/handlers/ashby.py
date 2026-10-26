"""
Ashby Platform Handler
======================
Fills jobs.ashbyhq.com application forms (the posting's /application tab).
"""

from src.handlers.ats_handler import LiveATSHandler


class AshbyHandler(LiveATSHandler):
    submit_selector = "button:has-text('Submit Application'), button[type='submit']"

    def __init__(self):
        super().__init__("ashby")

    def application_url(self, url: str) -> str:
        url = url.split("?")[0].rstrip("/")
        if "jobs.ashbyhq.com" in url and not url.endswith("/application"):
            return url + "/application"
        return url
