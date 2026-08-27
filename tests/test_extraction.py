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

    def test_expanded_120_skill_catalog(self):
        """Verifies that modern cloud, DevOps, backend, and AI skills are accurately extracted."""
        sample_jd = """
        We are seeking a Platform Engineer proficient in Kubernetes, Docker, Terraform, Rust, and GraphQL.
        Must have experience deploying LLMs with PyTorch and integrating Snowflake or BigQuery data pipelines.
        """
        extracted = self.engine.llm.extract_requirements(sample_jd, title="Platform Engineer", company="InfraTech")
        skills = extracted.get("required_skills", [])
        
        self.assertIn("Kubernetes", skills)
        self.assertIn("Terraform", skills)
        self.assertIn("Rust", skills)
        self.assertIn("GraphQL", skills)
        self.assertIn("PyTorch", skills)
        self.assertIn("Snowflake", skills)
        self.assertIn("BigQuery", skills)

    def test_honest_skill_gap_scoring(self):
        """Verifies that non-matching technical skills are recognized as gaps and lower the score."""
        from src.scoring import MatchScorer
        scorer = MatchScorer()

        candidate_skills = ["Product Management", "AI/ML", "LangChain", "Python", "SQL", "Agile/Scrum"]
        devops_job_reqs = {
            "required_skills": ["Kubernetes", "Terraform", "Rust", "Ansible", "Helm"],
            "nice_to_have_skills": ["C++", "Linux"],
            "min_years_experience": 8,
            "education_requirement": "Bachelor"
        }

        result_score, matched, skills_gap = scorer.calculate_match(
            candidate_skills=candidate_skills,
            required_skills=devops_job_reqs["required_skills"],
            nice_to_have_skills=devops_job_reqs["nice_to_have_skills"]
        )
        self.assertLess(result_score, 40)
        self.assertIn("Kubernetes", skills_gap)
        self.assertIn("Terraform", skills_gap)
        self.assertIn("Rust", skills_gap)


if __name__ == "__main__":
    unittest.main()
