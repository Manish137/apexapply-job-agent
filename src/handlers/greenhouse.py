"""
Greenhouse Platform Handler
===========================
Fills boards.greenhouse.io / job-boards.greenhouse.io application forms, including forms
embedded on company career sites through the grnhse_iframe.
"""

from src.handlers.ats_handler import LiveATSHandler


class GreenhouseHandler(LiveATSHandler):
    submit_selector = "#submit_app, button[type='submit'], input[type='submit']"

    def __init__(self):
        super().__init__("greenhouse")
