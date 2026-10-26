"""
Resume Tailoring Engine for ApexApply Job Agent
===============================================
Builds the resume sent with each application from the candidate's own base resume file.

Honesty rules (enforced in code, not just in prompts):
- Experience, titles, dates, employers and metrics are copied verbatim from the base resume.
- The only text that may change per job is the professional summary, and only when an LLM
  provider is configured; a rewritten summary is rejected if it contains any number that does
  not appear in the base resume.
- Nothing about scoring or skill gaps is written into the document an employer receives.
"""

import json
import os
import re
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime

from src.db import get_connection, log_audit
from src.scoring import MatchScorer
from src.llm import LLMInterface
from src.resume_render import render_resume, parse_resume_text

DEFAULT_DATA_DIR = Path(__file__).parent.parent / "data"
PREFERRED_BASE_RESUMES = ["manish_shukla_fdpm_resume.txt", "manish_shukla_master_resume.txt"]


def numbers_in(text: str) -> set:
    return set(re.findall(r"\d[\d,.]*", text))


def replace_summary(base_text: str, new_summary: str) -> str:
    """Swaps the PROFESSIONAL SUMMARY paragraph of a plain-text resume."""
    lines = base_text.splitlines()
    out, i, replaced = [], 0, False
    while i < len(lines):
        out.append(lines[i])
        if lines[i].strip() == "PROFESSIONAL SUMMARY" and not replaced:
            i += 1
            while i < len(lines) and set(lines[i].strip()) <= set("═=-─") and lines[i].strip():
                out.append(lines[i])
                i += 1
            while i < len(lines) and lines[i].strip():
                i += 1
            out.append(new_summary)
            replaced = True
            continue
        i += 1
    return "\n".join(out) + "\n"


class ResumeTailoringEngine:
    def __init__(
        self,
        db_path: Optional[Path] = None,
        data_dir: Optional[Path] = None,
        llm: Optional[LLMInterface] = None,
        scorer: Optional[MatchScorer] = None
    ):
        self.db_path = db_path
        self.data_dir = data_dir or DEFAULT_DATA_DIR
        self.tailored_dir = self.data_dir / "tailored_resumes"
        self.tailored_dir.mkdir(parents=True, exist_ok=True)
        self.llm = llm or LLMInterface()
        self.scorer = scorer or MatchScorer()

    def base_resume_path(self) -> Path:
        env_path = os.getenv("BASE_RESUME_PATH")
        if env_path and Path(env_path).exists():
            return Path(env_path)
        for base_dir in (self.data_dir / "base_resumes", DEFAULT_DATA_DIR / "base_resumes"):
            for name in PREFERRED_BASE_RESUMES:
                if (base_dir / name).exists():
                    return base_dir / name
        raise FileNotFoundError("No base resume found: add one to data/base_resumes or set BASE_RESUME_PATH")

    def get_or_create_master_resume(self) -> Dict[str, Any]:
        """Registers the base resume file (the candidate's real resume) as the default in the DB."""
        path = self.base_resume_path()
        resume_id = f"base_{path.stem}"
        conn = get_connection(self.db_path)
        cursor = conn.cursor()
        cursor.execute("UPDATE base_resumes SET is_default = 0 WHERE id != ?", (resume_id,))
        cursor.execute("""
        INSERT OR REPLACE INTO base_resumes (id, name, file_path, primary_skills, is_default)
        VALUES (?, ?, ?, ?, 1)
        """, (resume_id, f"Base resume ({path.name})", str(path), json.dumps(self.resume_skills(path.read_text(encoding="utf-8")))))
        conn.commit()
        conn.close()
        return {"id": resume_id, "name": f"Base resume ({path.name})", "file_path": str(path),
                "text": path.read_text(encoding="utf-8")}

    @staticmethod
    def resume_skills(text: str) -> List[str]:
        parsed = parse_resume_text(text)
        skills: List[str] = []
        for sec in parsed["sections"]:
            if "SKILL" in sec["heading"]:
                for it in sec["items"]:
                    if ":" in it:
                        skills += [s.strip() for s in it.split(":", 1)[1].split(",") if s.strip()]
        return skills

    def tailor_for_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        conn = get_connection(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
        job_row = cursor.fetchone()
        cursor.execute("SELECT * FROM job_requirements WHERE job_id = ?", (job_id,))
        req_row = cursor.fetchone()
        conn.close()
        if not job_row or not req_row:
            return None
        job, req = dict(job_row), dict(req_row)
        required_skills = json.loads(req.get("required_skills") or "[]")
        nice_skills = json.loads(req.get("nice_to_have_skills") or "[]")
        ats_keywords = json.loads(req.get("keywords_for_ats") or "[]")

        base = self.get_or_create_master_resume()
        base_text = base["text"]
        lower = base_text.lower()

        # Candidate skills = skills listed on the resume + any requirement the resume text actually mentions.
        candidate_skills = self.resume_skills(base_text)
        # Same skill dictionary used on job descriptions, applied to the resume ("product manager" -> Product Management).
        for s in LLMInterface(provider="mock").extract_requirements(base_text)["required_skills"]:
            if s not in candidate_skills:
                candidate_skills.append(s)
        for s in required_skills + nice_skills + ats_keywords:
            if s and s.lower() in lower and s not in candidate_skills:
                candidate_skills.append(s)

        match_score, matched_skills, skills_gap = self.scorer.calculate_match(
            candidate_skills=candidate_skills,
            required_skills=required_skills,
            nice_to_have_skills=nice_skills,
            keywords_for_ats=ats_keywords
        )

        company = job.get("company", "Target Company")
        title = job.get("title", "Product Manager")

        tailored_text = base_text
        tailored_summary = ""
        if self.llm.provider != "mock":
            try:
                result = self.llm.tailor_resume(base_text, {**req, "required_skills": required_skills}, company, title)
                candidate = (result or {}).get("tailored_summary", "").strip()
                invented = numbers_in(candidate) - numbers_in(base_text)
                if candidate and not invented:
                    tailored_summary = candidate
                    tailored_text = replace_summary(base_text, candidate)
                elif invented:
                    log_audit("SUMMARY_REJECTED", "WARNING", job_id,
                              f"LLM summary used numbers not in the resume: {sorted(invented)}", self.db_path)
            except Exception as e:
                log_audit("SUMMARY_FAILED", "WARNING", job_id, str(e)[:200], self.db_path)

        safe_company = re.sub(r"[^a-zA-Z0-9_-]", "_", company.lower())
        stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        out_base = self.tailored_dir / f"Manish_Shukla_Resume_{safe_company}_{job_id}_{stamp}"
        files = render_resume(tailored_text, out_base)
        out_base.with_suffix(".txt").write_text(tailored_text, encoding="utf-8")

        tailored_id = f"tr_{job_id}"
        conn = get_connection(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
        INSERT OR REPLACE INTO tailored_resumes (
            id, job_id, base_resume_id, file_path, match_score,
            skills_added_emphasis, skills_gap, generated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (tailored_id, job_id, base["id"], files["html"], match_score,
              json.dumps(matched_skills), json.dumps(skills_gap), datetime.utcnow().isoformat()))
        cursor.execute("UPDATE jobs SET status = 'TAILORED' WHERE id = ?", (job_id,))
        conn.commit()
        conn.close()

        cover_letter_res = self.generate_cover_letter(job_id=job_id, base_resume=base, job=job, reqs=req,
                                                      matched_skills=matched_skills, match_score=match_score)

        log_audit("RESUME_TAILORED", "SUCCESS", job_id,
                  f"Resume prepared for {company} (Match Score: {match_score}%, Gaps: {len(skills_gap)})", self.db_path)

        return {
            "id": tailored_id,
            "job_id": job_id,
            "file_path": files["html"],
            "pdf_path": files["pdf"],
            "docx_path": files["docx"],
            "match_score": match_score,
            "skills_matched": matched_skills,
            "skills_gap": skills_gap,
            "tailored_summary": tailored_summary,
            "cover_letter": cover_letter_res
        }

    def generate_cover_letter(
        self,
        job_id: str,
        base_resume: Dict[str, Any],
        job: Dict[str, Any],
        reqs: Dict[str, Any],
        matched_skills: List[str],
        match_score: int
    ) -> Dict[str, Any]:
        """Short cover letter whose achievements are bullets copied verbatim from the base resume."""
        import html as htmlmod
        company = job.get("company", "Target Company")
        title = job.get("title", "Product Manager")
        recipient = job.get("contact_person") or reqs.get("contact_person") or "Hiring Team"
        recipient_email = job.get("contact_email") or reqs.get("contact_email")
        parsed = parse_resume_text(base_resume["text"])

        bullets = []
        for sec in parsed["sections"]:
            if sec["heading"] == "PROFESSIONAL EXPERIENCE":
                bullets = [it[1:].strip() for it in sec["items"] if it.startswith("•")]
        # Prefer bullets that mention what this job asks for, then the ones with hard numbers.
        wanted = [s.lower() for s in matched_skills]
        bullets.sort(key=lambda b: (-sum(w in b.lower() for w in wanted), -len(numbers_in(b))))
        picks = bullets[:3]

        salutation = f"Dear {recipient}," if recipient != "Hiring Team" else f"Dear {company} Hiring Team,"
        focus = ", ".join(matched_skills[:3]) if matched_skills else "taking AI and automation from customer problem to production"
        date_str = datetime.utcnow().strftime("%B %d, %Y")
        text_content = (
            f"{parsed['name'].title()}\n{parsed['contact']}\n\n{date_str}\n\n{salutation}\n\n"
            f"I am applying for the {title} role at {company}. I have spent 15+ years taking AI and automation "
            f"from a customer's real workflow to production inside regulated enterprises, and the work I am "
            f"proudest of is measured in outcomes the customer could see:\n"
            + "".join(f"• {b}\n" for b in picks) +
            f"\nMy background in {focus} maps directly to this role. I would welcome a conversation about "
            f"how I can help {company}'s customers get to production faster.\n\nSincerely,\n{parsed['name'].title()}\n"
        )
        e = htmlmod.escape
        html_content = (
            "<!doctype html><html><head><meta charset=utf-8><style>body{font-family:Helvetica,Arial,sans-serif;"
            "font-size:11pt;line-height:1.5;margin:0.8in;color:#111}</style></head><body>"
            + "".join(f"<p>{e(p).replace(chr(10), '<br>')}</p>" for p in text_content.split("\n\n"))
            + "</body></html>"
        )
        cl_dir = self.data_dir / "cover_letters"
        cl_dir.mkdir(parents=True, exist_ok=True)
        cl_file = cl_dir / f"cover_letter_{job_id}.html"
        cl_file.write_text(html_content, encoding="utf-8")

        from src.db import save_cover_letter
        save_cover_letter(job_id=job_id, cover_letter_text=text_content, cover_letter_html=html_content,
                          recipient_name=recipient, recipient_email=recipient_email, db_path=self.db_path)
        return {"job_id": job_id, "recipient_name": recipient, "recipient_email": recipient_email,
                "cover_letter_text": text_content, "file_path": str(cl_file)}
