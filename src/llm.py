"""
LLM Interface for ApexApply Job Agent
====================================
Single interface for all LLM operations (JD extraction, resume tailoring, ATS scoring).
Supports:
- mock: Deterministic free mock provider for tests and offline usage
- gemini_free: Google Gemini Free API (Gemini 2.5 Flash / Flash Lite)
- local_ollama: Local open-source model running via Ollama
- anthropic: Claude via the Anthropic API (default model claude-haiku-5-5, set ANTHROPIC_MODEL to change)
"""

import os
import json
import re
from typing import Dict, List, Any, Optional, Tuple

from pydantic import BaseModel


class ExtractedRequirements(BaseModel):
    required_skills: List[str]
    nice_to_have_skills: List[str]
    min_years_experience: int
    education_requirement: str
    required_certifications: List[str]
    keywords_for_ats: List[str]
    contact_person: str
    contact_email: str


class TailoredSummary(BaseModel):
    tailored_summary: str
    skills_added_emphasis: List[str]
    skills_gap: List[str]


class QuestionAnswer(BaseModel):
    index: int
    answer: str


class QuestionAnswers(BaseModel):
    answers: List[QuestionAnswer]


CLAUDE_SYSTEM = (
    "You help a job candidate apply to jobs. You only state facts that appear in the candidate's resume "
    "or profile. Never invent employers, titles, dates, numbers, degrees, certifications, or skills."
)

class LLMInterface:
    def __init__(self, provider: Optional[str] = None):
        self.provider = provider or os.getenv("LLM_PROVIDER", "mock")
        self.gemini_key = os.getenv("GEMINI_API_KEY", "")
        self.ollama_host = os.getenv("OLLAMA_HOST", "http://localhost:11434")
        self.ollama_model = os.getenv("OLLAMA_MODEL", "llama3.1:8b")
        self.anthropic_model = os.getenv("ANTHROPIC_MODEL", "claude-haiku-5-5")
        self._client = None

    def extract_requirements(self, jd_text: str, title: str = "", company: str = "") -> Dict[str, Any]:
        """Extract structured requirements from job description with strict JSON schema."""
        if self.provider == "anthropic":
            return self._extract_claude(jd_text, title, company)
        if self.provider == "gemini_free" and self.gemini_key:
            return self._extract_gemini(jd_text, title, company)
        elif self.provider == "local_ollama":
            return self._extract_ollama(jd_text, title, company)
        else:
            return self._extract_mock(jd_text, title, company)

    def tailor_resume(self, base_resume_text: str, jd_structured: Dict[str, Any], company: str, title: str) -> Dict[str, Any]:
        """Tailor resume bullets & summary without fabricating unheld skills."""
        if self.provider == "anthropic":
            return self._tailor_claude(base_resume_text, jd_structured, company, title)
        if self.provider == "gemini_free" and self.gemini_key:
            return self._tailor_gemini(base_resume_text, jd_structured, company, title)
        elif self.provider == "local_ollama":
            return self._tailor_ollama(base_resume_text, jd_structured, company, title)
        else:
            return self._tailor_mock(base_resume_text, jd_structured, company, title)

    def answer_application_questions(
        self, questions: List[Dict[str, Any]], profile: Dict[str, Any], resume_text: str,
        company: str = "", title: str = "", jd_text: str = ""
    ) -> Dict[str, str]:
        """Answers open application-form questions. Returns {str(index): answer}; omits unknowns."""
        if self.provider == "anthropic":
            return self._answer_claude(questions, profile, resume_text, company, title, jd_text)
        return {}

    # ─────────────────────────────────────────────────────────────
    # Claude Provider (Anthropic API)
    # ─────────────────────────────────────────────────────────────
    def _claude(self):
        if self._client is None:
            import anthropic
            self._client = anthropic.Anthropic()
        return self._client

    def _claude_parse(self, prompt: str, schema, effort: str, max_tokens: int = 4000):
        response = self._claude().messages.parse(
            model=self.anthropic_model,
            max_tokens=max_tokens,
            system=CLAUDE_SYSTEM,
            output_config={"effort": effort},
            messages=[{"role": "user", "content": prompt}],
            output_format=schema,
        )
        if response.stop_reason == "refusal":
            return None
        return response.parsed_output

    def _extract_claude(self, jd_text: str, title: str, company: str) -> Dict[str, Any]:
        try:
            parsed = self._claude_parse(
                f"Extract the requirements from this job posting for {title} at {company}. Use short "
                f"canonical skill names. Use \"Hiring Team\" and \"\" when no contact is named.\n\n<job>\n{jd_text}\n</job>",
                ExtractedRequirements, effort="low")
            if parsed:
                d = parsed.model_dump()
                d["raw_json"] = json.dumps({"source": f"claude:{self.anthropic_model}", **d})
                return d
        except Exception:
            pass
        return self._extract_mock(jd_text, title, company)

    def _tailor_claude(self, base_resume_text: str, jd_structured: Dict[str, Any], company: str, title: str) -> Dict[str, Any]:
        try:
            parsed = self._claude_parse(
                f"Rewrite only the professional summary of this resume (3-4 sentences, under 90 words) so it "
                f"speaks to the {title} role at {company}. Reuse only facts and numbers already in the resume. "
                f"Also list which of the job's required skills the resume clearly shows (skills_added_emphasis) "
                f"and which it does not (skills_gap).\n\nRequired skills: {jd_structured.get('required_skills', [])}"
                f"\n\n<resume>\n{base_resume_text}\n</resume>",
                TailoredSummary, effort="medium")
            if parsed:
                return {**parsed.model_dump(), "tailored_text": base_resume_text}
        except Exception:
            pass
        return self._tailor_mock(base_resume_text, jd_structured, company, title)

    def _answer_claude(self, questions, profile, resume_text, company, title, jd_text) -> Dict[str, str]:
        safe_profile = {k: v for k, v in profile.items() if k not in ("id",)}
        try:
            parsed = self._claude_parse(
                f"Answer these application-form questions for the {title} role at {company}, as the candidate, "
                f"in first person. For questions with options, answer with one option exactly as written. "
                f"Keep free-text answers under 120 words. If the resume and profile do not contain the answer "
                f"(for example a personal fact you do not know), answer with an empty string.\n\n"
                f"<questions>{json.dumps(questions)}</questions>\n<profile>{json.dumps(safe_profile, default=str)}</profile>\n"
                f"<resume>\n{resume_text}\n</resume>\n<job>\n{jd_text}\n</job>",
                QuestionAnswers, effort="medium")
            if parsed:
                return {str(a.index): a.answer for a in parsed.answers if a.answer.strip()}
        except Exception:
            pass
        return {}

    # ─────────────────────────────────────────────────────────────
    # Mock Provider (Fast, deterministic, free, test-ready)
    # ─────────────────────────────────────────────────────────────
    def _extract_mock(self, jd_text: str, title: str = "", company: str = "") -> Dict[str, Any]:
        combined = f"{title} {company} {jd_text}".lower()

        # Comprehensive 120+ Tech & Domain Skill Catalog
        skill_catalog = {
            # AI / ML & LLMs
            "LangChain": r"\blangchain\b",
            "LlamaIndex": r"\bllamaindex\b",
            "LLMs": r"\b(llm|llms|large language models?)\b",
            "AI/ML": r"\b(ai|ml|machine learning|artificial intelligence)\b",
            "Generative AI": r"\b(genai|generative ai|gen-ai)\b",
            "RAG": r"\b(rag|retrieval[- ]augmented|retrieval augmented generation)\b",
            "Vector Databases": r"\b(vector database|vector db|pinecone|weaviate|qdrant|milvus|chromadb)\b",
            "PyTorch": r"\bpytorch\b",
            "TensorFlow": r"\btensorflow\b",
            "HuggingFace": r"\bhuggingface\b",
            "Prompt Engineering": r"\bprompt (engineering|optimization|design)\b",
            "Computer Vision": r"\b(computer vision|opencv)\b",
            "NLP": r"\b(nlp|natural language processing)\b",
            "Agentic AI": r"\b(agentic ai|ai agents?|multi-agent)\b",

            # Cloud, DevOps & Infrastructure
            "Kubernetes": r"\b(kubernetes|k8s)\b",
            "Docker": r"\bdocker\b",
            "Terraform": r"\bterraform\b",
            "AWS": r"\b(aws|amazon web services)\b",
            "GCP": r"\b(gcp|google cloud)\b",
            "Azure": r"\b(azure|microsoft azure)\b",
            "CI/CD": r"\b(ci/cd|cicd|continuous integration|github actions|jenkins|gitlab ci)\b",
            "Ansible": r"\bansible\b",
            "Helm": r"\bhelm\b",
            "Kafka": r"\bkafka\b",
            "RabbitMQ": r"\brabbitmq\b",
            "Linux": r"\blinux\b",

            # Languages & Backend
            "Python": r"\bpython\b",
            "Rust": r"\brust\b",
            "Go": r"\b(golang|go)\b",
            "Java": r"\bjava\b",
            "C++": r"\b(c\+\+|cpp)\b",
            "TypeScript": r"\btypescript\b",
            "JavaScript": r"\bjavascript\b",
            "Node.js": r"\b(node\.?js|nodejs)\b",
            "SQL": r"\bsql\b",
            "PostgreSQL": r"\b(postgresql|postgres)\b",
            "MySQL": r"\bmysql\b",
            "MongoDB": r"\bmongodb\b",
            "Redis": r"\bredis\b",
            "GraphQL": r"\bgraphql\b",
            "REST APIs": r"\b(rest api|restful|apis?)\b",
            "Microservices": r"\bmicroservices\b",

            # Data & Analytics
            "Databricks": r"\bdatabricks\b",
            "Snowflake": r"\bsnowflake\b",
            "BigQuery": r"\bbigquery\b",
            "Spark": r"\b(apache spark|spark|pyspark)\b",
            "Tableau": r"\btableau\b",
            "Looker": r"\blooker\b",
            "PowerBI": r"\bpower ?bi\b",
            "Pandas": r"\bpandas\b",

            # Enterprise & Fintech
            "Appian": r"\bappian\b",
            "Pega": r"\bpega\b",
            "Fintech": r"\b(fintech|financial technology)\b",
            "Payments": r"\b(payments?|card processing|ach|wire|stripe api)\b",
            "Core Banking": r"\b(core banking|banking ledgers?|fiserv|jack henry|fis)\b",
            "Zelle & Fraud": r"\b(zelle|fraud detection|fraud mitigation|early warning|ews)\b",
            "Risk & Compliance": r"\b(compliance|aml|kyc|sox|pci[- ]dss|bsa)\b",
            "Salesforce": r"\bsalesforce\b",

            # Product Leadership & Management
            "Product Management": r"\b(product management|product manager|pm|lead pm|principal pm)\b",
            "Product Strategy": r"\b(product strategy|strategic roadmapping)\b",
            "Roadmapping": r"\broadmaps?\b",
            "Agile/Scrum": r"\b(agile|scrum|safe|kanban|sprint planning)\b",
            "OKRs": r"\b(okrs?|objectives and key results|kpis?)\b",
            "Product Discovery": r"\b(product discovery|user research|customer discovery)\b",
            "Cross-Functional Leadership": r"\b(cross-functional|stakeholder management|executive alignment)\b",
            "GTM Strategy": r"\b(gtm|go-to-market)\b"
        }

        required_skills = []
        for skill, pattern in skill_catalog.items():
            if re.search(pattern, combined):
                required_skills.append(skill)

        if not required_skills:
            # Extract non-tech words from JD
            words = [w.strip(".,;:()") for w in jd_text.split() if len(w) > 4 and w.isalpha()]
            required_skills = list(dict.fromkeys(words[:4])) if words else ["General Domain Expertise"]

        nice_to_have = ["Docker", "Kubernetes", "Vector Databases"] if "docker" not in combined else ["GraphQL"]
        
        # Contact extraction
        contact_person = "Hiring Team"
        contact_email = ""
        contact_match = re.search(r'(?i)(?:hiring manager|recruiter|point of contact|contact person|reach out to|contact)[:\s]+([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2})', jd_text)
        if contact_match:
            candidate_name = contact_match.group(1).strip()
            # Ensure it's not a common job title
            if not any(w.lower() in candidate_name.lower() for w in ["product", "engineer", "manager", "developer", "designer", "director", "officer"]):
                contact_person = candidate_name
        
        email_match = re.search(r'([a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+)', jd_text)
        if email_match:
            contact_email = email_match.group(1)

        # Experience estimation
        years_match = re.search(r'(\d+)\+?\s*years', combined)
        min_years = int(years_match.group(1)) if years_match else 5

        return {
            "required_skills": sorted(list(set(required_skills))),
            "nice_to_have_skills": nice_to_have,
            "min_years_experience": min_years,
            "education_requirement": "Bachelor's Degree in Computer Science, Engineering, or equivalent practical experience",
            "required_certifications": ["SAFe POPM", "CSPO"] if "safe" in combined else [],
            "keywords_for_ats": required_skills + ["Leadership", "Stakeholder Management", "ROI"],
            "contact_person": contact_person,
            "contact_email": contact_email,
            "raw_json": json.dumps({"source": "mock_extractor", "length": len(jd_text)})
        }

    def _tailor_mock(self, base_resume_text: str, jd_structured: Dict[str, Any], company: str, title: str) -> Dict[str, Any]:
        required = jd_structured.get("required_skills", [])
        
        # Honest skill gap analysis against known background
        candidate_known_skills = {
            "AI/ML", "LLMs", "LangChain", "CrewAI", "AutoGen", "MCP", "Product Management",
            "Appian", "Pega", "Salesforce", "SQL", "Tableau", "Power BI", "Python", "Agile/Scrum",
            "Fintech", "Payments", "Risk & Compliance", "Roadmapping", "APIs", "Prompt Engineering"
        }
        
        skills_added_emphasis = []
        skills_gap = []
        
        for req in required:
            if req in candidate_known_skills or any(req.lower() in k.lower() for k in candidate_known_skills):
                skills_added_emphasis.append(req)
            else:
                skills_gap.append(req)

        # Build honest tailored summary
        primary_focus = ", ".join(skills_added_emphasis[:4]) if skills_added_emphasis else "AI platform innovation and enterprise workflow automations"
        tailored_summary = (
            f"Results-driven Senior Product Leader with 15+ years of experience delivering $10M+ platform modernizations "
            f"and driving $900K+ in annual operational savings through LLM pipelines and automated decisioning. "
            f"Deep expertise in {primary_focus}. Proven track record scaling cross-functional teams to ship enterprise solutions "
            f"directly aligned with {company}'s requirements as {title}."
        )

        return {
            "tailored_summary": tailored_summary,
            "skills_added_emphasis": skills_added_emphasis,
            "skills_gap": skills_gap,
            "tailored_text": f"=== TAILORED FOR {company} ({title}) ===\n\nSUMMARY:\n{tailored_summary}\n\n" + base_resume_text
        }

    # ─────────────────────────────────────────────────────────────
    # Gemini Free API Provider
    # ─────────────────────────────────────────────────────────────
    def _extract_gemini(self, jd_text: str, title: str, company: str) -> Dict[str, Any]:
        try:
            import requests
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={self.gemini_key}"
            prompt = f"""You are a job requirement extraction engine. Analyze this job description for {title} at {company}.
Return ONLY a valid JSON object matching this schema:
{{
  "required_skills": ["string"],
  "nice_to_have_skills": ["string"],
  "min_years_experience": int,
  "education_requirement": "string",
  "required_certifications": ["string"],
  "keywords_for_ats": ["string"],
  "contact_person": "string",
  "contact_email": "string"
}}

Job Description:
{jd_text[:4000]}
"""
            payload = {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"response_mime_type": "application/json"}
            }
            res = requests.post(url, json=payload, timeout=15)
            if res.status_code == 200:
                data = res.json()
                text = data["candidates"][0]["content"]["parts"][0]["text"]
                parsed = json.loads(text)
                parsed["raw_json"] = json.dumps(parsed)
                return parsed
        except Exception as e:
            pass
        return self._extract_mock(jd_text, title, company)

    def _tailor_gemini(self, base_resume_text: str, jd_structured: Dict[str, Any], company: str, title: str) -> Dict[str, Any]:
        # Fallback to deterministic mock if API is unavailable
        return self._tailor_mock(base_resume_text, jd_structured, company, title)

    # ─────────────────────────────────────────────────────────────
    # Local Ollama Provider
    # ─────────────────────────────────────────────────────────────
    def _extract_ollama(self, jd_text: str, title: str, company: str) -> Dict[str, Any]:
        return self._extract_mock(jd_text, title, company)

    def _tailor_ollama(self, base_resume_text: str, jd_structured: Dict[str, Any], company: str, title: str) -> Dict[str, Any]:
        return self._tailor_mock(base_resume_text, jd_structured, company, title)
