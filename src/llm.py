"""
LLM Interface for ApexApply Job Agent
=====================================
Single interface for all LLM operations: JD extraction, cover letters, and
answering application-form questions.

Providers (LLM_PROVIDER):
- gemini: Google Gemini API (GEMINI_API_KEY, GEMINI_MODEL)
- claude: Anthropic Claude API (ANTHROPIC_API_KEY, CLAUDE_MODEL)
- mock:   deterministic offline provider, for tests only

Real providers never silently fall back to mock output. If the provider is
misconfigured or the API fails, LLMError is raised so the job is marked FAILED
with the reason, instead of shipping template text to an employer.
"""

import os
import re
import json
import time
from typing import Dict, List, Any, Optional

import requests

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

NO_FABRICATION_RULES = (
    "Rules: Use ONLY facts that appear in the candidate's resume or profile below. "
    "Never invent employers, titles, dates, degrees, certifications, metrics, or skills. "
    "If the resume does not support a claim, leave it out."
)


class LLMError(RuntimeError):
    pass


class LLMInterface:
    def __init__(self, provider: Optional[str] = None):
        self.provider = (provider or os.getenv("LLM_PROVIDER", "gemini")).lower()
        if self.provider in ("gemini_free", "google"):
            self.provider = "gemini"
        if self.provider in ("anthropic",):
            self.provider = "claude"
        self.gemini_key = os.getenv("GEMINI_API_KEY", "")
        self.gemini_model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
        self.claude_key = os.getenv("ANTHROPIC_API_KEY", "")
        self.claude_model = os.getenv("CLAUDE_MODEL", "claude-opus-5-5")
        self._claude_client = None

    # ─────────────────────────────────────────────────────────────
    # Health check
    # ─────────────────────────────────────────────────────────────
    def status(self) -> Dict[str, Any]:
        """Reports whether the configured provider is usable, with a live test call."""
        info = {"provider": self.provider, "ok": False, "detail": ""}
        if self.provider == "mock":
            info.update(ok=True, detail="Mock provider (tests only, not for real applications)")
            return info
        try:
            out = self.complete("Reply with the single word: ready", max_tokens=20)
            info.update(ok=True, detail=f"{self._model_name()} answered: {out.strip()[:40]}")
        except LLMError as e:
            info["detail"] = str(e)
        return info

    def _model_name(self) -> str:
        return self.gemini_model if self.provider == "gemini" else self.claude_model

    # ─────────────────────────────────────────────────────────────
    # Raw completion
    # ─────────────────────────────────────────────────────────────
    def complete(self, prompt: str, system: str = "", json_mode: bool = False, max_tokens: int = 2000) -> str:
        if self.provider == "gemini":
            return self._gemini(prompt, system, json_mode, max_tokens)
        if self.provider == "claude":
            return self._claude(prompt, system, json_mode, max_tokens)
        if self.provider == "mock":
            raise LLMError("Mock provider has no free-form completion")
        raise LLMError(f"Unknown LLM_PROVIDER '{self.provider}' (use gemini or claude)")

    def _gemini(self, prompt: str, system: str, json_mode: bool, max_tokens: int) -> str:
        if not self.gemini_key:
            raise LLMError("GEMINI_API_KEY is not set")
        body: Dict[str, Any] = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"maxOutputTokens": max_tokens, "temperature": 0.4},
        }
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        if json_mode:
            body["generationConfig"]["responseMimeType"] = "application/json"

        url = GEMINI_URL.format(model=self.gemini_model)
        last_err = ""
        for attempt in range(4):
            try:
                res = requests.post(url, json=body, headers={"x-goog-api-key": self.gemini_key}, timeout=60)
            except requests.RequestException as e:
                last_err = f"network error: {e}"
                time.sleep(2 ** attempt)
                continue
            if res.status_code == 200:
                data = res.json()
                try:
                    parts = data["candidates"][0]["content"]["parts"]
                    return "".join(p.get("text", "") for p in parts)
                except (KeyError, IndexError):
                    raise LLMError(f"Gemini returned no text: {json.dumps(data)[:300]}")
            last_err = f"HTTP {res.status_code}: {res.text[:300]}"
            if res.status_code in (429, 500, 502, 503, 504):
                # Free tier is rate limited per minute; back off and retry
                time.sleep(min(60, 5 * 2 ** attempt))
                continue
            break
        raise LLMError(f"Gemini call failed ({self.gemini_model}): {last_err}")

    def _claude(self, prompt: str, system: str, json_mode: bool, max_tokens: int) -> str:
        if not self.claude_key:
            raise LLMError("ANTHROPIC_API_KEY is not set")
        import anthropic

        if self._claude_client is None:
            self._claude_client = anthropic.Anthropic(api_key=self.claude_key, max_retries=4)
        if json_mode:
            prompt += "\n\nRespond with a single JSON object only, no prose and no code fences."
        kwargs: Dict[str, Any] = {
            "model": self.claude_model,
            "max_tokens": max(max_tokens, 4000),
            "output_config": {"effort": "low"},
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            kwargs["system"] = system
        try:
            msg = self._claude_client.messages.create(**kwargs)
        except anthropic.AuthenticationError:
            raise LLMError("Claude API key was rejected (check ANTHROPIC_API_KEY)")
        except anthropic.PermissionDeniedError as e:
            raise LLMError(f"Claude API permission denied (billing/credits?): {e.message}")
        except anthropic.NotFoundError:
            raise LLMError(f"Claude model '{self.claude_model}' not found (check CLAUDE_MODEL)")
        except anthropic.RateLimitError:
            raise LLMError("Claude API rate limit hit after retries")
        except anthropic.APIStatusError as e:
            raise LLMError(f"Claude API error {e.status_code}: {e.message}")
        except anthropic.APIConnectionError:
            raise LLMError("Could not reach the Claude API (network)")
        if msg.stop_reason == "refusal":
            raise LLMError("Claude declined the request")
        return "".join(b.text for b in msg.content if b.type == "text")

    def _json(self, prompt: str, system: str = "", max_tokens: int = 2000) -> Dict[str, Any]:
        raw = self.complete(prompt, system=system, json_mode=True, max_tokens=max_tokens)
        match = re.search(r"\{.*\}", raw, re.S)
        if not match:
            raise LLMError(f"Expected JSON from {self.provider}, got: {raw[:200]}")
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError as e:
            raise LLMError(f"Invalid JSON from {self.provider}: {e}")

    # ─────────────────────────────────────────────────────────────
    # Job description extraction
    # ─────────────────────────────────────────────────────────────
    def extract_requirements(self, jd_text: str, title: str = "", company: str = "") -> Dict[str, Any]:
        if self.provider == "mock":
            return self._extract_mock(jd_text, title, company)
        prompt = f"""Extract structured requirements from this job posting for "{title}" at {company}.
Return JSON with exactly these keys:
{{"required_skills": [str], "nice_to_have_skills": [str], "min_years_experience": int,
 "education_requirement": str, "required_certifications": [str], "keywords_for_ats": [str],
 "contact_person": str, "contact_email": str}}
Use short skill phrases (1-4 words). Use "" when a contact is not named in the posting.

Job posting:
{jd_text[:12000]}"""
        data = self._json(prompt, max_tokens=1500)
        data["raw_json"] = json.dumps(data)
        return data

    # ─────────────────────────────────────────────────────────────
    # Cover letter
    # ─────────────────────────────────────────────────────────────
    def write_cover_letter(self, resume_text: str, profile: Dict[str, Any], job: Dict[str, Any]) -> str:
        """Returns the cover letter body (no letterhead, no date), plain text paragraphs."""
        company = job.get("company", "")
        title = job.get("title", "")
        if self.provider == "mock":
            return (
                f"I am applying for the {title} role at {company}.\n\n"
                "My background is summarized in the attached resume.\n\n"
                f"Thank you for considering my application.\n\nSincerely,\n{profile.get('full_name', '')}"
            )
        system = (
            "You write concise, specific cover letters for a senior candidate. "
            "Plain text only, no markdown, no placeholders like [Company]. " + NO_FABRICATION_RULES
        )
        prompt = f"""Write a cover letter for the role "{title}" at {company}.

Requirements:
- 3 short paragraphs plus a sign-off, 220-300 words total.
- Paragraph 1: why this role and company, referencing something concrete from the job description.
- Paragraph 2: 2-3 of the candidate's most relevant results from the resume, with their real numbers, mapped to what the role needs.
- Paragraph 3: how they would work in the first months (customer discovery, deployment, adoption), and a brief close.
- Start with "Dear {company} Hiring Team," and end with "Sincerely,\\n{profile.get('full_name', '')}".

Candidate profile: {json.dumps({k: profile.get(k) for k in ('full_name', 'address', 'years_experience')})}

Candidate resume:
{resume_text[:8000]}

Job description:
{(job.get('description_raw') or '')[:8000]}"""
        text = self.complete(prompt, system=system, max_tokens=1500).strip()
        if len(text) < 300:
            raise LLMError("Cover letter came back too short")
        return text

    # ─────────────────────────────────────────────────────────────
    # Application form questions
    # ─────────────────────────────────────────────────────────────
    def answer_question(
        self,
        question: str,
        field_type: str,
        options: List[str],
        profile: Dict[str, Any],
        resume_text: str,
        job: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Returns {"answer": str, "confident": bool}. For option fields the answer is one of options."""
        if self.provider == "mock":
            return self._answer_mock(question, field_type, options, profile)
        answers = profile.get("custom_field_answers") or {}
        known = {k: v for k, v in profile.items() if k != "custom_field_answers" and v not in (None, "")}
        known.update({k: v for k, v in answers.items() if v not in (None, "")})
        option_rule = (
            f'The answer MUST be exactly one of these options: {json.dumps(options)}.' if options else
            "Answer in 1-4 sentences for free-text questions, or a short value for short fields."
        )
        prompt = f"""You are filling a job application for {profile.get('full_name')} applying to "{job.get('title')}" at {job.get('company')}.

Question: {question}
Field type: {field_type}
{option_rule}

Known candidate facts (authoritative):
{json.dumps(known, indent=1)[:4000]}

Resume:
{resume_text[:6000]}

Return JSON: {{"answer": str, "confident": bool}}.
Set confident=false when the facts above do not determine the answer (for example legal, personal, or
availability questions the facts don't cover). For voluntary demographic questions choose the
"decline to answer" style option if one exists. {NO_FABRICATION_RULES}"""
        data = self._json(prompt, max_tokens=600)
        answer = str(data.get("answer", "")).strip()
        confident = bool(data.get("confident")) and bool(answer)
        if options:
            match = _best_option(answer, options)
            if not match:
                return {"answer": "", "confident": False}
            answer = match
        return {"answer": answer, "confident": confident}

    # ─────────────────────────────────────────────────────────────
    # Mock provider (tests and offline runs only)
    # ─────────────────────────────────────────────────────────────
    def _answer_mock(self, question: str, field_type: str, options: List[str], profile: Dict[str, Any]) -> Dict[str, Any]:
        answers = profile.get("custom_field_answers") or {}
        for key, val in answers.items():
            if key.replace("_", " ").lower() in question.lower() and val:
                if options:
                    m = _best_option(str(val), options)
                    return {"answer": m or "", "confident": bool(m)}
                return {"answer": str(val), "confident": True}
        return {"answer": "", "confident": False}

    def _extract_mock(self, jd_text: str, title: str = "", company: str = "") -> Dict[str, Any]:
        combined = f"{title} {company} {jd_text}".lower()
        catalog = {
            "LLMs": r"\b(llm|llms|large language models?)\b",
            "AI/ML": r"\b(ai|ml|machine learning|artificial intelligence)\b",
            "Generative AI": r"\b(genai|generative ai)\b",
            "RAG": r"\b(rag|retrieval[- ]augmented)\b",
            "Agentic AI": r"\b(agentic|ai agents?|multi-agent)\b",
            "LangChain": r"\blangchain\b",
            "Python": r"\bpython\b",
            "SQL": r"\bsql\b",
            "REST APIs": r"\b(rest api|restful|apis?)\b",
            "Kubernetes": r"\b(kubernetes|k8s)\b",
            "Docker": r"\bdocker\b",
            "AWS": r"\b(aws|amazon web services)\b",
            "Appian": r"\bappian\b",
            "Fintech": r"\b(fintech|financial technology|financial services)\b",
            "Payments": r"\b(payments?|ach|card processing)\b",
            "Risk & Compliance": r"\b(compliance|aml|kyc|sox|pci[- ]dss)\b",
            "Product Management": r"\b(product management|product manager)\b",
            "Roadmapping": r"\broadmaps?\b",
            "Agile/Scrum": r"\b(agile|scrum|safe)\b",
            "Customer Discovery": r"\b(discovery|customer research|user research)\b",
            "Stakeholder Management": r"\b(stakeholders?|cross-functional)\b",
            "Forward Deployed": r"\bforward[- ]deployed\b",
        }
        required = sorted(s for s, p in catalog.items() if re.search(p, combined))
        years = re.search(r"(\d+)\+?\s*years", combined)
        email = re.search(r"([a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+)", jd_text)
        contact = re.search(r"(?i)(?:hiring manager|recruiter|contact person|reach out to|contact)[:\s]+([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2})", jd_text)
        return {
            "required_skills": required,
            "nice_to_have_skills": [],
            "min_years_experience": int(years.group(1)) if years else 0,
            "education_requirement": "",
            "required_certifications": [],
            "keywords_for_ats": required,
            "contact_person": contact.group(1) if contact else "",
            "contact_email": email.group(1) if email else "",
            "raw_json": json.dumps({"source": "mock_extractor"}),
        }


def _best_option(answer: str, options: List[str]) -> Optional[str]:
    """Maps a model answer onto one of the allowed options."""
    a = answer.strip().lower()
    if not a:
        return None
    for o in options:
        if o.strip().lower() == a:
            return o
    for o in options:
        ol = o.strip().lower()
        if ol and (ol.startswith(a) or a.startswith(ol)):
            return o
    for o in options:
        if a in o.lower():
            return o
    return None
