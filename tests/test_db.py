import unittest
import json
import tempfile
from pathlib import Path

from src.db import init_db, get_connection, upsert_profile, get_profile, log_audit

class TestDatabase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_job_agent.db"
        init_db(self.db_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_schema_creation_and_insertion(self):
        conn = get_connection(self.db_path)
        cursor = conn.cursor()

        # 1. base_resumes
        cursor.execute(
            "INSERT INTO base_resumes (id, name, file_path, primary_skills, is_default) VALUES (?, ?, ?, ?, ?)",
            ("br_1", "Manish PM AI", "/data/base_resumes/manish.docx", json.dumps(["AI", "Python", "Product"]), 1)
        )

        # 2. jobs
        cursor.execute(
            "INSERT INTO jobs (id, source_scraper_id, title, company, description_raw, platform_type, status) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("job_1", "scraper_101", "Lead AI PM", "Anthropic", "Build LLM products", "greenhouse", "NEW")
        )

        # 3. job_requirements
        cursor.execute(
            "INSERT INTO job_requirements (id, job_id, required_skills, nice_to_have_skills, min_years_experience, raw_json) VALUES (?, ?, ?, ?, ?, ?)",
            ("req_1", "job_1", json.dumps(["LLM", "Python"]), json.dumps(["RAG"]), 5, "{}")
        )

        # 4. tailored_resumes
        cursor.execute(
            "INSERT INTO tailored_resumes (id, job_id, base_resume_id, file_path, match_score, skills_added_emphasis, skills_gap) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("tr_1", "job_1", "br_1", "/data/tailored_resumes/tr_1.docx", 92, json.dumps(["LLM"]), json.dumps(["Rust"]))
        )

        # 5. field_taxonomy
        cursor.execute(
            "INSERT INTO field_taxonomy (id, platform_type, field_name, field_type, maps_to_profile_field, is_required) VALUES (?, ?, ?, ?, ?, ?)",
            ("ft_1", "greenhouse", "first_name", "text", "first_name", 1)
        )

        # 6. applications
        cursor.execute(
            "INSERT INTO applications (id, job_id, tailored_resume_id, status, match_score_at_apply, submission_mode) VALUES (?, ?, ?, ?, ?, ?)",
            ("app_1", "job_1", "tr_1", "PENDING_REVIEW", 92, "manual_confirm")
        )

        conn.commit()

        # Read back
        cursor.execute("SELECT COUNT(*) as c FROM base_resumes")
        self.assertEqual(cursor.fetchone()["c"], 1)

        cursor.execute("SELECT COUNT(*) as c FROM jobs")
        self.assertEqual(cursor.fetchone()["c"], 1)

        cursor.execute("SELECT COUNT(*) as c FROM applications")
        self.assertEqual(cursor.fetchone()["c"], 1)

        conn.close()

    def test_profile_and_audit(self):
        profile_data = {
            "id": "default_profile",
            "full_name": "Manish Shukla",
            "email": "shukla.manish80@gmail.com",
            "phone": "(209) 319-8716",
            "work_authorization": "Yes",
            "salary_expectation": "$180,000+",
            "years_experience": 15,
            "custom_field_answers": {"why_join": "Passionate about AI platform scale."}
        }
        upsert_profile(profile_data, self.db_path)
        fetched = get_profile("default_profile", self.db_path)
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched["full_name"], "Manish Shukla")
        self.assertEqual(fetched["custom_field_answers"]["why_join"], "Passionate about AI platform scale.")

        log_audit("TEST_ACTION", "INFO", "job_1", "Audit details test", self.db_path)
        conn = get_connection(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM audit_logs")
        logs = cursor.fetchall()
        self.assertEqual(len(logs), 1)
        conn.close()

if __name__ == "__main__":
    unittest.main()
