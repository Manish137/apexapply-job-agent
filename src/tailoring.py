"""
Resume Selection & Cover Letter Engine for ApexApply Job Agent
==============================================================
Picks the right reviewed resume variant (general or fintech) for each job,
scores the match honestly against the real resume text, and writes a
job-specific cover letter with the configured LLM. Resume content is never
generated: the uploaded resume is always one of the candidate's own PDFs.
"""

import re
import json
import html
from pathlib import Path
from typing import Dict, Any, Optional
from datetime import datetime, timezone

from src.db import get_connection, log_audit, get_profile, save_cover_letter
from src.scoring import MatchScorer
from src.llm import LLMInterface
from src.candidate import ResumeStore
from src.pdf import html_to_pdf

DEFAULT_DATA_DIR = Path(__file__).parent.parent / "data"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def skill_in_text(skill: str, text_lower: str) -> bool:
    """True when every meaningful word of the skill phrase appears in the resume text."""
    words = [w for w in re.split(r"[^a-z0-9+#.]+", skill.lower()) if len(w) > 1]
    if not words:
        return False
    return all(re.search(rf"(?<![a-z0-9]){re.escape(w.rstrip('s'))}", text_lower) for w in words)


class ResumeTailoringEngine:
    def __init__(
        self,
        db_path: Optional[Path] = None,
        data_dir: Optional[Path] = None,
        llm: Optional[LLMInterface] = None,
        scorer: Optional[MatchScorer] = None,
        render_pdf: bool = True,
    ):
        self.db_path = db_path
        self.data_dir = data_dir or DEFAULT_DATA_DIR
        self.llm = llm or LLMInterface()
        self.scorer = scorer or MatchScorer()
        self.resumes = ResumeStore(self.data_dir)
        self.render_pdf = render_pdf

    def _register_base_resume(self, resume: Dict[str, Any]) -> str:
        resume_id = f"base_resume_{resume['variant']}"
        conn = get_connection(self.db_path)
        conn.execute(
            """INSERT OR REPLACE INTO base_resumes (id, name, file_path, primary_skills, is_default)
               VALUES (?, ?, ?, ?, ?)""",
            (resume_id, f"Forward Deployed PM ({resume['variant']})",
             str(self.resumes.text_path(resume["variant"])), "[]", 1 if resume["variant"] == "general" else 0),
        )
        conn.commit()
        conn.close()
        return resume_id

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

        variant = self.resumes.choose_variant(job)
        resume = self.resumes.get(variant)
        if not resume:
            log_audit("RESUME_MISSING", "ERROR", job_id,
                      f"No '{variant}' resume PDF uploaded. Upload it via /api/base-resume/{variant}.", self.db_path)
            return None
        base_resume_id = self._register_base_resume(resume)

        required = json.loads(req.get("required_skills") or "[]")
        nice = json.loads(req.get("nice_to_have_skills") or "[]")
        keywords = json.loads(req.get("keywords_for_ats") or "[]")
        text_lower = resume["text"].lower()
        held = [s for s in dict.fromkeys(required + nice + keywords) if skill_in_text(s, text_lower)]
        match_score, matched_skills, skills_gap = self.scorer.calculate_match(
            candidate_skills=held, required_skills=required,
            nice_to_have_skills=nice, keywords_for_ats=keywords,
        )

        conn = get_connection(self.db_path)
        conn.execute(
            """INSERT OR REPLACE INTO tailored_resumes (
                   id, job_id, base_resume_id, file_path, match_score,
                   skills_added_emphasis, skills_gap, generated_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (f"tr_{job_id}", job_id, base_resume_id, resume["pdf_path"], match_score,
             json.dumps(matched_skills), json.dumps(skills_gap), _now()),
        )
        conn.execute("UPDATE jobs SET status = 'TAILORED' WHERE id = ?", (job_id,))
        conn.commit()
        conn.close()

        log_audit("RESUME_SELECTED", "SUCCESS", job_id,
                  f"Using '{variant}' resume for {job.get('company')} (match {match_score}%, gaps: {', '.join(skills_gap[:6]) or 'none'})",
                  self.db_path)

        return {
            "id": f"tr_{job_id}",
            "job_id": job_id,
            "variant": variant,
            "file_path": resume["pdf_path"],
            "resume_text": resume["text"],
            "match_score": match_score,
            "skills_matched": matched_skills,
            "skills_gap": skills_gap,
        }

    def generate_cover_letter(self, job_id: str, resume_text: str, profile: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Writes the cover letter with the LLM and saves it as text and PDF. Raises LLMError on failure."""
        conn = get_connection(self.db_path)
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        conn.close()
        job = dict(row)
        profile = profile or get_profile(db_path=self.db_path) or {}

        body = self.llm.write_cover_letter(resume_text, profile, job)
        contact = " · ".join(x for x in (profile.get("address"), profile.get("phone"), profile.get("email"),
                                         profile.get("linkedin_url")) if x)
        date_str = datetime.now().strftime("%B %d, %Y")
        paragraphs = "".join(f"<p>{html.escape(p).replace(chr(10), '<br>')}</p>" for p in body.split("\n\n") if p.strip())
        letter_html = f"""<!doctype html><html><head><meta charset="utf-8"><style>
body {{ font-family: 'Inter', 'Helvetica Neue', Arial, sans-serif; font-size: 11pt; line-height: 1.5; color: #1f2933; }}
h1 {{ font-size: 18pt; margin: 0; color: #0b3d5c; letter-spacing: .5px; }}
.contact {{ font-size: 9.5pt; color: #52606d; border-bottom: 2px solid #0b3d5c; padding-bottom: 8px; margin-bottom: 18px; }}
.date {{ color: #52606d; margin-bottom: 14px; }} p {{ margin: 0 0 11px; }}
</style></head><body><h1>{html.escape(profile.get('full_name', ''))}</h1>
<div class="contact">{html.escape(contact)}</div><div class="date">{date_str}</div>{paragraphs}</body></html>"""

        cl_dir = self.data_dir / "cover_letters"
        cl_dir.mkdir(parents=True, exist_ok=True)
        pdf_path = cl_dir / f"cover_letter_{job_id}.pdf"
        if self.render_pdf:
            html_to_pdf(letter_html, pdf_path)
        text_content = f"{profile.get('full_name', '')}\n{contact}\n\n{date_str}\n\n{body}"
        save_cover_letter(job_id=job_id, cover_letter_text=text_content, cover_letter_html=letter_html,
                          recipient_name=job.get("contact_person") or "Hiring Team",
                          recipient_email=job.get("contact_email"), db_path=self.db_path)
        return {
            "job_id": job_id,
            "body": body,
            "cover_letter_text": text_content,
            "file_path": str(pdf_path) if self.render_pdf else "",
        }
