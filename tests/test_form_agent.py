import unittest
from pathlib import Path

from src.form_agent import FormAgent
from src.llm import LLMInterface
from tests.helpers import Env, FORMS

JOB = {"title": "Forward Deployed Product Manager", "company": "Acme", "description_raw": "FDPM role"}


class StubLLM(LLMInterface):
    """Mock provider that answers free-text questions, like a real model would."""

    def __init__(self):
        super().__init__("mock")

    def answer_question(self, question, field_type, options, profile, resume_text, job):
        if "interested" in question.lower():
            return {"answer": "The role pairs customer discovery with shipping AI systems.", "confident": True}
        return super().answer_question(question, field_type, options, profile, resume_text, job)


class TestFormAgent(unittest.TestCase):
    def setUp(self):
        self.env = Env()
        self.resume = str(self.env.data_dir / "base_resumes" / "general.pdf")
        self.shot = str(self.env.data_dir / "shots" / "s.png")
        self.letter_calls = 0

    def tearDown(self):
        self.env.close()

    def letter(self):
        self.letter_calls += 1
        return {"body": "Dear Acme Hiring Team, ...", "file_path": self.resume}

    def run_form(self, name, profile, auto_submit=True, llm=None, **kw):
        agent = FormAgent(llm=llm or StubLLM(), confirm_timeout_s=5, **kw)
        html = (FORMS / name).read_text()
        return agent.run("greenhouse", "about:blank", JOB, profile, self.resume, "resume text", self.letter,
                         self.shot, auto_submit, html_fixture=html)

    def test_complete_greenhouse_form_submits(self):
        res = self.run_form("greenhouse_like.html", self.env.profile())
        self.assertEqual(res.status, "SUBMITTED", res.error_message)
        f = res.fields_filled
        self.assertEqual(f["First Name *"], "Manish")
        self.assertEqual(f["Resume/CV *"], "general.pdf")
        self.assertEqual(f["Will you now or in the future require visa sponsorship? *"], "No")
        self.assertEqual(f["Are you legally authorized to work in the United States? *"], "Yes")
        self.assertEqual(f["Gender"], "Decline To Self Identify")
        self.assertNotIn("Website", f)  # unknown optional fields are left blank, not guessed
        self.assertEqual(self.letter_calls, 1)
        self.assertTrue(Path(res.screenshot_path).exists())

    def test_unknown_required_answer_blocks_submit(self):
        profile = self.env.profile(requires_sponsorship="")
        res = self.run_form("greenhouse_like.html", profile)
        self.assertEqual(res.status, "PENDING_REVIEW")
        self.assertIn("sponsorship", res.error_message)

    def test_review_mode_never_submits(self):
        res = self.run_form("greenhouse_like.html", self.env.profile(), auto_submit=False)
        self.assertEqual(res.status, "PENDING_REVIEW")
        self.assertIn("Review mode", res.error_message)
        self.assertIn("Email *", res.fields_filled)

    def test_lever_radio_and_cover_letter_textarea(self):
        res = self.run_form("lever_like.html", self.env.profile(willing_to_relocate="Yes"),
                            submit_selectors="#btn-submit", form_ready_selector="form input[name='name']")
        self.assertEqual(res.status, "SUBMITTED", res.error_message)
        self.assertEqual(res.fields_filled["Are you willing to relocate? *"], "Yes")
        self.assertEqual(res.fields_filled["Full name *"], "Manish Shukla")
        self.assertTrue(res.fields_filled["Additional information"].startswith("Dear Acme"))

    def test_missing_form_fails_honestly(self):
        agent = FormAgent(llm=StubLLM())
        agent.form_ready_selector = "form input"
        res = agent.run("custom", "about:blank", JOB, self.env.profile(), self.resume, "", self.letter, self.shot,
                        True, html_fixture="<p>Sorry, this job is closed</p>")
        self.assertEqual(res.status, "FAILED")
        self.assertIn("did not load", res.error_message)


if __name__ == "__main__":
    unittest.main()
