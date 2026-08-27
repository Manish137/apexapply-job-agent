import unittest
from src.llm import LLMInterface

class TestLLMInterface(unittest.TestCase):
    def setUp(self):
        self.llm = LLMInterface(provider="mock")

    def test_extract_requirements_mock(self):
        jd = "We are seeking a Lead AI Product Manager with experience in LangChain, Python, LLMs, and Agile frameworks. Hiring Manager: John Doe (john@scale.ai)."
        result = self.llm.extract_requirements(jd, title="Lead AI Product Manager", company="Scale AI")
        
        self.assertIn("LangChain", result["required_skills"])
        self.assertIn("Python", result["required_skills"])
        self.assertIn("LLMs", result["required_skills"])
        self.assertEqual(result["contact_person"], "John Doe")
        self.assertEqual(result["contact_email"], "john@scale.ai")
        self.assertIsInstance(result["min_years_experience"], int)

    def test_tailor_resume_mock(self):
        jd_reqs = {
            "required_skills": ["LangChain", "LLMs", "Rust", "Product Management"],
            "nice_to_have_skills": ["Docker"]
        }
        base_resume = "Manish Shukla - 15+ years experience in AI and Fintech Product Leadership."
        tailored = self.llm.tailor_resume(base_resume, jd_reqs, company="Anthropic", title="Principal PM")
        
        self.assertIn("LangChain", tailored["skills_added_emphasis"])
        self.assertIn("Rust", tailored["skills_gap"])  # Honestly flagged as gap, not fabricated
        self.assertIn("Anthropic", tailored["tailored_summary"])
        self.assertIn("Principal PM", tailored["tailored_summary"])

if __name__ == "__main__":
    unittest.main()
