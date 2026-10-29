"""
LinkedIn Easy Apply Handler
===========================
Automating LinkedIn risks account restriction, so LinkedIn jobs are queued for
manual application with the resume and cover letter prepared.
"""

from src.handlers.workday import WorkdayHandler


class LinkedInEasyApplyHandler(WorkdayHandler):
    def __init__(self):
        super().__init__("linkedin")
