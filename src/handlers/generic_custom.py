"""
Generic Custom Form Handler
===========================
Best-effort fill of unknown career sites. Never auto-submits: unknown sites
have unknown confirmation flows, so a human clicks submit after review.
"""

from src.handlers.form_handler import FormHandler


class GenericCustomHandler(FormHandler):
    allows_auto_submit = False

    def __init__(self, llm=None):
        super().__init__("custom", llm)
