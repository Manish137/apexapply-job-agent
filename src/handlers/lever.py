"""
Lever Platform Handler
======================
Fills jobs.lever.co application forms (the posting's /apply page).
"""

from src.handlers.ats_handler import LiveATSHandler


class LeverHandler(LiveATSHandler):
    submit_selector = "#btn-submit, button[type='submit']"

    def __init__(self):
        super().__init__("lever")

    def application_url(self, url: str) -> str:
        url = url.split("?")[0].rstrip("/")
        if "jobs.lever.co" in url and not url.endswith("/apply"):
            return url + "/apply"
        return url
