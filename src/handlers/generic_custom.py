"""
Generic Custom Form Platform Handler
====================================
Fallback for career sites without a dedicated handler: finds the form (clicking an
"Apply" button if needed) and fills it by reading each field's label.
"""

from src.handlers.ats_handler import LiveATSHandler


class GenericCustomHandler(LiveATSHandler):
    def __init__(self):
        super().__init__("custom")
