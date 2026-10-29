"""Shared test setup: temp DB, mock LLM, and real resume PDFs rendered from text."""

import json
import tempfile
from pathlib import Path

from src.db import init_db, upsert_profile
from src.pdf import html_to_pdf
from src.orchestrator import DEFAULT_PROFILE

FORMS = Path(__file__).parent / "fixtures" / "forms"

RESUME_TEXT = {
    "general": "Manish Shukla. Forward Deployed Product Manager. Customer discovery, PRDs, LLMs, agentic workflows, "
               "REST APIs, SQL, Python, stakeholder management, roadmapping. Charles Schwab $10M+ modernization.",
    "fintech": "Manish Shukla. Forward Deployed Product Manager, Fintech. KYC, AML, payments, risk management, "
               "compliance, LLMs, customer discovery, SQL. Zelle automation reduced manual review 90%.",
}


class Env:
    def __init__(self, with_resumes=True):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.db_path = root / "test.db"
        self.data_dir = root / "data"
        init_db(self.db_path)
        if with_resumes:
            for variant, text in RESUME_TEXT.items():
                d = self.data_dir / "base_resumes"
                html_to_pdf(f"<p>{text}</p>", d / f"{variant}.pdf")
                (d / f"{variant}.txt").write_text(text)

    def profile(self, **answers):
        p = json.loads(json.dumps(DEFAULT_PROFILE))
        p["linkedin_url"] = "https://www.linkedin.com/in/example"
        p["salary_expectation"] = "$180,000 - $220,000"
        p["custom_field_answers"].update({"work_authorized": "Yes", "requires_sponsorship": "No",
                                          "willing_to_relocate": "No"})
        p["custom_field_answers"].update(answers)
        upsert_profile(p, self.db_path)
        return p

    def close(self):
        self.tmp.cleanup()
