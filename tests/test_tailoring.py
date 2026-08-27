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
        self.assertIn("LangChain", res["skills_matched"])

        # Check DB record
        conn = get_connection(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM tailored_resumes WHERE job_id = ?", (anthropic_id,))
        row = cursor.fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["match_score"], res["match_score"])

        # Verify Cover Letter was generated (JobRight & ScaleJobs feature)
        cursor.execute("SELECT * FROM cover_letters WHERE job_id = ?", (anthropic_id,))
        cl_row = cursor.fetchone()
        self.assertIsNotNone(cl_row)
        self.assertIn("Anthropic", cl_row["cover_letter_text"])
        self.assertIn("Sarah Connor", cl_row["recipient_name"])
        conn.close()

    def test_jobright_match_breakdown_diagnostics(self):
        """Verifies JobRight-style structured match breakdown with why you match and gap mitigation."""
        scorer = MatchScorer()
        candidate_skills = ["Generative AI", "LangChain", "Python", "Product Leadership", "Fintech"]
        job = {
            "company": "Vanguard",
            "title": "AI/ML Product Manager",
            "salary_range": "$190,000 - $240,000",
            "remote_flag": 1,
            "location": "Remote"
        }
        job_reqs = {
            "required_skills": ["Generative AI", "LangChain", "Kubernetes"],
            "nice_to_have_skills": ["Python"],
            "min_years_experience": 8
        }

        breakdown = scorer.generate_match_breakdown(
            candidate_skills=candidate_skills,
            candidate_years=15,
            candidate_target_salary=180000,
            job=job,
            job_requirements=job_reqs
        )

        self.assertIn("overall_score", breakdown)
        self.assertIn("why_you_match", breakdown)
        self.assertGreaterEqual(len(breakdown["why_you_match"]), 2)
        self.assertIn("Kubernetes", breakdown["skills_gap"])
        self.assertIn("Remote Match", breakdown["remote_fit"])
        self.assertIn("190,000", breakdown["salary_fit"])

if __name__ == "__main__":
    unittest.main()
