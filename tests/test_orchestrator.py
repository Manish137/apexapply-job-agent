import unittest
from pathlib import Path

from src.db import get_connection, get_cover_letter
from src.llm import LLMInterface
from src.orchestrator import JobAgentOrchestrator
from tests.helpers import Env


def add_job(env, job_id, title, company, desc, platform="workday", url="https://example.wd5.myworkdayjobs.com/x"):
    conn = get_connection(env.db_path)
    conn.execute("""INSERT INTO jobs (id, title, company, description_raw, posting_url, platform_type, status, date_scraped)
                    VALUES (?, ?, ?, ?, ?, ?, 'NEW', '2026-10-29')""", (job_id, title, company, desc, url, platform))
    conn.commit()
    conn.close()


class TestOrchestrator(unittest.TestCase):
    def setUp(self):
        self.env = Env()
        self.env.profile()
        self.orch = JobAgentOrchestrator(db_path=self.env.db_path, data_dir=self.env.data_dir, llm=LLMInterface("mock"))

    def tearDown(self):
        self.env.close()

    def test_fintech_job_uses_fintech_resume_and_writes_cover_letter(self):
        add_job(self.env, "j1", "Forward Deployed Product Manager, Financial Services", "Ode",
                "Banking clients: KYC, AML, payments, reconciliations. Customer discovery, LLMs, SQL.")
        res = self.orch.run_pipeline_for_job("j1", auto_submit=True)
        self.assertEqual(res["resume_variant"], "fintech")
        self.assertEqual(res["status"], "PENDING_REVIEW")  # Workday is always finished by hand
        self.assertTrue(get_cover_letter("j1", self.env.db_path))
        self.assertTrue(Path(self.env.data_dir / "cover_letters" / "cover_letter_j1.pdf").exists())

    def test_general_job_uses_general_resume(self):
        add_job(self.env, "j2", "Forward Deployed Product Manager", "Cresta",
                "Own AI agent deployments. Customer discovery, LLMs, REST APIs, Python, stakeholder management.")
        self.assertEqual(self.orch.run_pipeline_for_job("j2")["resume_variant"], "general")

    def test_off_target_titles_and_blacklist_are_skipped(self):
        add_job(self.env, "j3", "Hotel Manager", "Inua", "Front desk")
        add_job(self.env, "j4", "Forward Deployed PM", "Revature", "LLMs")
        self.assertEqual(self.orch.run_pipeline_for_job("j3")["reason"], "Title not in target titles")
        self.assertEqual(self.orch.run_pipeline_for_job("j4")["reason"], "Blacklisted company")

    def test_missing_resume_fails_clearly(self):
        for p in (self.env.data_dir / "base_resumes").iterdir():
            p.unlink()
        add_job(self.env, "j5", "Forward Deployed PM", "Exa", "LLMs, discovery")
        res = self.orch.run_pipeline_for_job("j5")
        self.assertEqual(res["status"], "FAILED")
        self.assertIn("Resume PDF not uploaded", res["error"])

    def test_greenhouse_job_end_to_end_with_local_form(self):
        add_job(self.env, "j6", "Forward Deployed Product Manager", "Acme", "LLMs, customer discovery, SQL",
                platform="greenhouse", url="https://job-boards.greenhouse.io/acme/jobs/1")
        self.orch.extraction.process_job("j6")
        tailored = self.orch.tailoring.tailor_for_job("j6")
        html = (Path(__file__).parent / "fixtures" / "forms" / "greenhouse_like.html").read_text()
        html = html.replace(" *</label><textarea id=\"q_why\" required>", "</label><textarea id=\"q_why\">")
        res = self.orch.executor.execute_application(
            "j6", self.orch.get_or_create_profile(), auto_submit=True, resume_text=tailored["resume_text"],
            cover_letter=lambda: self.orch.tailoring.generate_cover_letter("j6", tailored["resume_text"]),
            html_fixture=html.replace("required></textarea>", "></textarea>"))
        self.assertEqual(res["status"], "SUBMITTED", res["error"])
        conn = get_connection(self.env.db_path)
        self.assertEqual(conn.execute("SELECT status FROM jobs WHERE id='j6'").fetchone()["status"], "APPLIED")
        conn.close()

    def test_run_is_recorded_for_status_page(self):
        add_job(self.env, "j7", "Forward Deployed Product Manager", "Cresta", "LLMs, customer discovery")
        self.orch.sources.discover = lambda titles: {"postings_scanned": 40, "matched": 1, "new": 1}
        run = self.orch.discover_and_run(max_jobs=5, trigger="schedule")
        self.assertEqual(run["status"], "done")
        self.assertEqual(run["results"][0]["company"], "Cresta")
        self.assertEqual(self.orch.last_run()["discovered"]["postings_scanned"], 40)
        self.assertIn("finished", self.orch.last_run())

    def test_readiness_reports_missing_answers(self):
        self.env.profile(requires_sponsorship="")
        r = self.orch.readiness()
        self.assertIn("requires_sponsorship", r["profile_missing"])
        self.assertTrue(r["llm"]["ok"])


if __name__ == "__main__":
    unittest.main()
