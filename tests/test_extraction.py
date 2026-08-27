import unittest
import tempfile
import json
from pathlib import Path

from src.db import init_db, get_connection
from src.ingestion import IngestionService
from src.extraction import RequirementExtractionEngine
from src.llm import LLMInterface

class TestExtraction(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_extraction.db"
        init_db(self.db_path)
        self.ingestion = IngestionService(db_path=self.db_path)
        self.fixture_path = Path(__file__).parent / "fixtures" / "sample_jobs.json"
        self.ingestion.ingest_file(self.fixture_path)
        self.engine = RequirementExtractionEngine(db_path=self.db_path, llm=LLMInterface(provider="mock"))

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_extraction_pipeline(self):
        conn = get_connection(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM jobs WHERE company = 'Anthropic'")
        anthropic_id = cursor.fetchone()["id"]
        conn.close()

        # Process Anthropic job
        reqs = self.engine.process_job(anthropic_id)
        self.assertIsNotNone(reqs)
        self.assertIn("LangChain", reqs["required_skills"])
        self.assertIn("Python", reqs["required_skills"])
        self.assertEqual(reqs["contact_person"], "Sarah Connor")
        self.assertEqual(reqs["contact_email"], "sarah@anthropic.com")

        # Verify DB status updated to ANALYZED
        conn = get_connection(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT status, contact_person FROM jobs WHERE id = ?", (anthropic_id,))
        row = cursor.fetchone()
        self.assertEqual(row["status"], "ANALYZED")
        self.assertEqual(row["contact_person"], "Sarah Connor")

        cursor.execute("SELECT * FROM job_requirements WHERE job_id = ?", (anthropic_id,))
        req_row = cursor.fetchone()
        self.assertIsNotNone(req_row)
        self.assertIn("LangChain", json.loads(req_row["required_skills"]))
        conn.close()

    def test_process_all_new(self):
        results = self.engine.process_all_new_jobs()
        self.assertEqual(len(results), 3)

        conn = get_connection(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) as c FROM jobs WHERE status = 'ANALYZED'")
        self.assertEqual(cursor.fetchone()["c"], 3)
        conn.close()

if __name__ == "__main__":
    unittest.main()
