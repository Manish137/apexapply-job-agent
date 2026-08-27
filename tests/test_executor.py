import unittest
import tempfile
import json
from pathlib import Path

from src.db import init_db, get_connection
from src.ingestion import IngestionService
from src.extraction import RequirementExtractionEngine
from src.tailoring import ResumeTailoringEngine
from src.executor import ApplicationExecutor
from src.llm import LLMInterface

class TestExecutor(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_exec.db"
        self.data_dir = Path(self.temp_dir.name) / "data"
        init_db(self.db_path)

        self.ingestion = IngestionService(db_path=self.db_path)
        self.fixture_path = Path(__file__).parent / "fixtures" / "sample_jobs.json"
        self.ingestion.ingest_file(self.fixture_path)

        self.extraction = RequirementExtractionEngine(db_path=self.db_path, llm=LLMInterface(provider="mock"))
        self.extraction.process_all_new_jobs()

        self.tailoring = ResumeTailoringEngine(db_path=self.db_path, data_dir=self.data_dir, llm=LLMInterface(provider="mock"))
        
        conn = get_connection(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM jobs")
        for r in cursor.fetchall():
            self.tailoring.tailor_for_job(r["id"])
        conn.close()

        self.executor = ApplicationExecutor(db_path=self.db_path, data_dir=self.data_dir)
        self.profile = {
            "full_name": "Manish Shukla",
            "first_name": "Manish",
            "last_name": "Shukla",
            "email": "shukla.manish80@gmail.com",
            "phone": "(209) 319-8716",
            "linkedin_url": "https://linkedin.com/in/mshukla1",
            "work_authorization": "Yes",
            "salary_expectation": "$180,000+"
        }

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_greenhouse_mode_a_execution(self):
        conn = get_connection(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM jobs WHERE company = 'Anthropic'")
        anthropic_id = cursor.fetchone()["id"]
        conn.close()

        res = self.executor.execute_application(anthropic_id, self.profile, auto_submit=False)
        self.assertIsNotNone(res)
        self.assertEqual(res["status"], "PENDING_REVIEW")
        self.assertEqual(res["submission_mode"], "manual_confirm")
        self.assertTrue(Path(res["screenshot_path"]).exists())

    def test_greenhouse_mode_b_unconfirmed_stays_pending_review(self):
        """Without a verifiable live confirmation page, auto_submit will NOT falsely claim SUBMITTED."""
        conn = get_connection(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM jobs WHERE company = 'Stripe'")
        stripe_id = cursor.fetchone()["id"]
        conn.close()

        res = self.executor.execute_application(stripe_id, self.profile, auto_submit=True)
        self.assertIsNotNone(res)
        self.assertEqual(res["status"], "PENDING_REVIEW")
        self.assertEqual(res["submission_mode"], "auto")

    def test_greenhouse_mode_b_confirmed_submission(self):
        """When confirmation indicator is detected in DOM, status is SUBMITTED."""
        from src.handlers.greenhouse import GreenhouseHandler
        handler = GreenhouseHandler()
        html_fixture = """
        <html>
          <body>
            <input id="first_name">
            <input id="last_name">
            <input id="email">
            <input id="phone">
            <button id="submit_app" type="submit">Submit Application</button>
            <div id="application_confirmation">Thank you! Your application has been received.</div>
          </body>
        </html>
        """
        screenshot_path = str(self.data_dir / "test_screenshot.png")
        fill_result = handler.fill_form(
            job={"id": "j_test", "posting_url": "http://localhost/greenhouse"},
            tailored_resume_path="",
            profile=self.profile,
            screenshot_path=screenshot_path,
            auto_submit=True,
            html_fixture=html_fixture
        )
        self.assertEqual(fill_result.status, "SUBMITTED")
        self.assertTrue(Path(screenshot_path).exists())

    def test_linkedin_enforces_mode_a(self):
        conn = get_connection(self.db_path)
        cursor = conn.cursor()
        # Insert a LinkedIn job
        cursor.execute("SELECT id FROM base_resumes LIMIT 1")
        base_id = cursor.fetchone()["id"]
        cursor.execute("""
        INSERT INTO jobs (id, title, company, platform_type, status)
        VALUES ('job_li_1', 'AI Lead', 'LinkedIn Co', 'linkedin', 'TAILORED')
        """)
        cursor.execute("""
        INSERT INTO tailored_resumes (id, job_id, base_resume_id, file_path, match_score)
        VALUES ('tr_li_1', 'job_li_1', ?, '/path/to/resume.html', 95)
        """, (base_id,))
        conn.commit()
        conn.close()

        # Even with auto_submit=True, LinkedIn MUST stay Mode A manual_confirm
        res = self.executor.execute_application('job_li_1', self.profile, auto_submit=True)
        self.assertEqual(res["status"], "PENDING_REVIEW")
        self.assertEqual(res["submission_mode"], "manual_confirm")

if __name__ == "__main__":
    unittest.main()
