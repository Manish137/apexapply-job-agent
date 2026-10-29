import os
import unittest
from unittest import mock

from src.llm import LLMInterface, LLMError, _best_option


class TestLLM(unittest.TestCase):
    def test_mock_extraction_finds_fdpm_skills(self):
        res = LLMInterface("mock").extract_requirements(
            "Forward Deployed PM. 5+ years. Customer discovery with stakeholders, LLMs, SQL and KYC/AML.",
            "Forward Deployed Product Manager", "Ode")
        for skill in ("LLMs", "SQL", "Risk & Compliance", "Customer Discovery", "Forward Deployed"):
            self.assertIn(skill, res["required_skills"])
        self.assertEqual(res["min_years_experience"], 5)

    def test_real_providers_fail_loudly_without_keys(self):
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "", "ANTHROPIC_API_KEY": ""}):
            for provider in ("gemini", "claude"):
                llm = LLMInterface(provider)
                with self.assertRaises(LLMError):
                    llm.extract_requirements("jd", "t", "c")
                self.assertFalse(llm.status()["ok"])

    def test_gemini_parses_json_response(self):
        llm = LLMInterface("gemini")
        llm.gemini_key = "k"
        fake = mock.Mock(status_code=200, json=lambda: {"candidates": [{"content": {"parts": [
            {"text": '{"answer": "No", "confident": true}'}]}}]})
        with mock.patch("src.llm.requests.post", return_value=fake):
            ans = llm.answer_question("Require sponsorship?", "select", ["Yes", "No"], {"full_name": "M"}, "", {})
        self.assertEqual(ans, {"answer": "No", "confident": True})

    def test_option_answers_must_be_real_options(self):
        llm = LLMInterface("gemini")
        llm.gemini_key = "k"
        fake = mock.Mock(status_code=200, json=lambda: {"candidates": [{"content": {"parts": [
            {"text": '{"answer": "Maybe", "confident": true}'}]}}]})
        with mock.patch("src.llm.requests.post", return_value=fake):
            ans = llm.answer_question("Relocate?", "radio", ["Yes", "No"], {}, "", {})
        self.assertFalse(ans["confident"])

    def test_best_option(self):
        opts = ["Yes", "No", "Decline To Self Identify"]
        self.assertEqual(_best_option("no", opts), "No")
        self.assertEqual(_best_option("Decline", opts), "Decline To Self Identify")
        self.assertIsNone(_best_option("perhaps", opts))


if __name__ == "__main__":
    unittest.main()
