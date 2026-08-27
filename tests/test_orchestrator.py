import unittest
import tempfile
from pathlib import Path

from src.db import init_db, get_connection
from src.orchestrator import JobAgentOrchestrator
from src.llm import LLMInterface

class TestOrchestrator(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_orch.db"
        self.data_dir = Path(self.temp_dir.name) / "data"
        init_db(self.db_path)

        self.orchestrator = JobAgentOrchestrator(
            db_path=self.db_path,
            data_dir=self.data_dir,
            llm=LLMInterface(provider="mock"),
            match_threshold=70,
            borderline_threshold=50
        )
        self.fixture_dir = Path(__file__).parent / "fixtures"

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_full_pipeline_ingest_and_run(self):
        summary = self.orchestrator.ingest_and_run([self.fixture_dir], max_jobs=3)
        self.assertEqual(summary["new_jobs_ingested"], 3)
        self.assertEqual(summary["jobs_processed"], 3)

        conn = get_connection(self.db_path)
        cursor = conn.cursor()
        
        # High matching product jobs land in applications (Anthropic & Stripe)
        cursor.execute("SELECT COUNT(*) as c FROM applications")
        app_count = cursor.fetchone()["c"]
        self.assertEqual(app_count, 2)

        # Non-matching job (Workday Labs Architect) is skipped
        cursor.execute("SELECT status FROM jobs WHERE company = 'Workday Labs'")
        self.assertEqual(cursor.fetchone()["status"], "SKIPPED")

        # Check applications fields for high-match jobs
        cursor.execute("SELECT status, submission_mode, match_score_at_apply FROM applications")
        apps = cursor.fetchall()
        for a in apps:
            self.assertEqual(a["status"], "PENDING_REVIEW")
            self.assertEqual(a["submission_mode"], "manual_confirm")
            self.assertGreaterEqual(a["match_score_at_apply"], 70)
        conn.close()

if __name__ == "__main__":
    unittest.main()
