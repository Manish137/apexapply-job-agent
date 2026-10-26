import tempfile
import unittest
from pathlib import Path

from src.handlers.greenhouse import GreenhouseHandler

PROFILE = {
    "full_name": "Manish Shukla",
    "first_name": "Manish",
    "last_name": "Shukla",
    "email": "shukla.manish80@gmail.com",
    "phone": "(209) 319-8716",
    "linkedin_url": "https://linkedin.com/in/mshukla1",
    "work_authorization": "Yes",
    "custom_field_answers": {"requires_sponsorship": "No"},
}

# Shaped like a Greenhouse board form: labelled inputs, a required custom question,
# a select, a radio group, an EEO question, and a confirmation that only appears after submit.
FORM = """
<html><body>
<form id="application_form" onsubmit="event.preventDefault(); if (!document.querySelector('#question_why').value) {document.querySelector('#err').textContent='This field is required'; return;} document.body.innerHTML = '<h1>Thank you for applying.</h1><p>Your application has been received.</p>';">
  <div class="field"><label for="first_name">First Name *</label><input id="first_name" name="first_name" required></div>
  <div class="field"><label for="last_name">Last Name *</label><input id="last_name" name="last_name" required></div>
  <div class="field"><label for="email">Email *</label><input id="email" type="email" required></div>
  <div class="field"><label for="phone">Phone</label><input id="phone"></div>
  <div class="field"><label for="resume">Resume/CV *</label><input id="resume" type="file" required></div>
  <div class="field"><label for="li">LinkedIn Profile</label><input id="li" name="job_application[answers_attributes][0][text_value]"></div>
  <div class="field"><label for="question_why">Why do you want to work here? *</label><textarea id="question_why" required></textarea></div>
  <div class="field"><label for="auth">Are you legally authorized to work in the United States? *</label>
    <select id="auth" required><option value="">Select...</option><option>Yes</option><option>No</option></select></div>
  <fieldset><legend>Will you now or in the future require visa sponsorship? *</legend>
    <label><input type="radio" name="spons" value="1" required>Yes</label>
    <label><input type="radio" name="spons" value="0">No</label></fieldset>
  <div class="field"><label for="gender">Gender</label>
    <select id="gender"><option value="">Select...</option><option>Male</option><option>Female</option><option>Decline To Self Identify</option></select></div>
  <div id="err"></div>
  <button id="submit_app" type="submit">Submit Application</button>
</form></body></html>
"""


class TestFormEngine(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.resume = Path(self.tmp.name) / "resume.pdf"
        self.resume.write_bytes(b"%PDF-1.4 test")
        self.shot = str(Path(self.tmp.name) / "shot.png")

    def tearDown(self):
        self.tmp.cleanup()

    def run_form(self, auto_submit, answerer=None):
        h = GreenhouseHandler()
        h.question_answerer = answerer
        return h.fill_form({"id": "j", "posting_url": ""}, str(self.resume), PROFILE, self.shot,
                           auto_submit=auto_submit, html_fixture=FORM)

    def test_fills_real_fields_and_declines_eeo(self):
        r = self.run_form(auto_submit=False)
        f = r.fields_filled
        self.assertEqual(f["First Name *"], "Manish")
        self.assertEqual(f["Last Name *"], "Shukla")
        self.assertEqual(f["Email *"], "shukla.manish80@gmail.com")
        self.assertEqual(f["Resume/CV *"], "resume.pdf")
        self.assertEqual(f["LinkedIn Profile"], "https://linkedin.com/in/mshukla1")
        self.assertEqual(f["Are you legally authorized to work in the United States? *"], "Yes")
        self.assertEqual(f["Will you now or in the future require visa sponsorship? *"], "No")
        self.assertEqual(f["Gender"], "Decline To Self Identify")
        self.assertEqual(r.status, "PENDING_REVIEW")
        self.assertTrue(Path(self.shot).exists())

    def test_unanswered_required_question_blocks_auto_submit(self):
        r = self.run_form(auto_submit=True)
        self.assertEqual(r.status, "PENDING_REVIEW")
        self.assertIn("Why do you want to work here?", r.error_message)

    def test_auto_submit_confirmed_only_after_real_confirmation(self):
        answerer = lambda qs: {str(q["index"]): "I deploy AI into regulated enterprise workflows." for q in qs}
        r = self.run_form(auto_submit=True, answerer=answerer)
        self.assertEqual(r.status, "SUBMITTED", r.error_message)
        self.assertEqual(r.submission_mode, "auto")


if __name__ == "__main__":
    unittest.main()
