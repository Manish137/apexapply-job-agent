import unittest
import tempfile
import json
from pathlib import Path

from src.db import init_db, get_connection
from src.ingestion import IngestionService
from src.extraction import RequirementExtractionEngine
from src.tailoring import ResumeTailoringEngine
from src.scoring import MatchScorer
from src.llm import LLMInterface

class TestTailoringAndScoring(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_tailor.db"
        self.data_dir = Path(self.temp_dir.name) / "data"
        init_db(self.db_path)

        self.ingestion = IngestionService(db_path=self.db_path)
        self.fixture_path = Path(__file__).parent / "fixtures" / "sample_jobs.json"
        self.ingestion.ingest_file(self.fixture_path)

        self.extraction = RequirementExtractionEngine(db_path=self.db_path, llm=LLMInterface(provider="mock"))
        self.extraction.process_all_new_jobs()

        self.tailoring = ResumeTailoringEngine(
            db_path=self.db_path,
            data_dir=self.data_dir,
            llm=LLMInterface(provider="mock"),
            scorer=MatchScorer()
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_scoring_logic(self):
        scorer = MatchScorer()
        candidate = ["AI/ML", "LLMs", "LangChain", "Python", "SQL"]
        required = ["LangChain", "Python", "Rust"]
        nice = ["Docker"]
        keywords = ["LangChain", "Leadership"]

        score, matched, gap = scorer.calculate_match(candidate, required, nice, keywords)
        self.assertIn("LangChain", matched)
        self.assertIn("Python", matched)
        self.assertIn("Rust", gap)
        self.assertGreaterEqual(score, 50)
        self.assertLessEqual(score, 100)

    def test_tailoring_pipeline_no_fabrication(self):
        conn = get_connection(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM jobs WHERE company = 'Anthropic'")
        anthropic_id = cursor.fetchone()["id"]
        conn.close()

        res = self.tailoring.tailor_for_job(anthropic_id)
        self.assertIsNotNone(res)
        self.assertGreaterEqual(res["match_score"], 70)
        self.assertTrue(Path(res["file_path"]).exists())
        self.assertIn("Anthropic", res["tailored_summary"])

        # Check DB status
        conn = get_connection(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT status FROM jobs WHERE id = ?", (anthropic_id,))
        self.assertEqual(cursor.fetchone()["status"], "TAILORED")

        cursor.execute("SELECT * FROM tailored_resumes WHERE job_id = ?", (anthropic_id,))
        row = cursor.fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["match_score"], res["match_score"])
        conn.close()

if __name__ == "__main__":
    unittest.main()
