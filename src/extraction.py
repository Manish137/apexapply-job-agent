"""
Requirement Extraction Engine for ApexApply Job Agent
=====================================================
Analyzes raw job descriptions using LLMInterface, validates structured output,
stores parsed requirements in `job_requirements` table, and transitions job status to 'ANALYZED'.
"""

import json
import uuid
from pathlib import Path
from typing import Dict, List, Any, Optional

from src.db import get_connection, log_audit
from src.llm import LLMInterface

class RequirementExtractionEngine:
    def __init__(self, db_path: Optional[Path] = None, llm: Optional[LLMInterface] = None):
        self.db_path = db_path
        self.llm = llm or LLMInterface()

    def process_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Extracts structured requirements for a single job and saves to DB."""
        conn = get_connection(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
        job_row = cursor.fetchone()

        if not job_row:
            conn.close()
            return None

        job = dict(job_row)
        desc = job.get("description_raw", "")
        title = job.get("title", "")
        company = job.get("company", "")

        # 1. LLM extraction call
        reqs = self.llm.extract_requirements(desc, title=title, company=company)

        # 2. Validation & normalization
        required_skills = reqs.get("required_skills") or []
        nice_to_have = reqs.get("nice_to_have_skills") or []
        min_years = reqs.get("min_years_experience") or 0
        education = reqs.get("education_requirement") or "Bachelor's Degree or equivalent experience"
        certifications = reqs.get("required_certifications") or []
        ats_keywords = reqs.get("keywords_for_ats") or required_skills
        contact_person = reqs.get("contact_person") or job.get("contact_person") or "Hiring Team"
        contact_email = reqs.get("contact_email") or job.get("contact_email") or ""

        req_id = f"req_{job_id}"

        # 3. Store in job_requirements
        cursor.execute("""
        INSERT OR REPLACE INTO job_requirements (
            id, job_id, required_skills, nice_to_have_skills, min_years_experience,
            education_requirement, required_certifications, keywords_for_ats, raw_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            req_id,
            job_id,
            json.dumps(required_skills),
            json.dumps(nice_to_have),
            min_years,
            education,
            json.dumps(certifications),
            json.dumps(ats_keywords),
            reqs.get("raw_json", "{}")
        ))

        # 4. Update jobs row: set status to ANALYZED, update contact info
        cursor.execute("""
        UPDATE jobs 
        SET status = 'ANALYZED', contact_person = ?, contact_email = ?
        WHERE id = ?
        """, (contact_person, contact_email, job_id))

        conn.commit()
        conn.close()

        log_audit("EXTRACT_REQUIREMENTS", "INFO", job_id, 
                  f"Extracted {len(required_skills)} required skills, {len(nice_to_have)} nice-to-have for {company}", 
                  self.db_path)

        return {
            "id": req_id,
            "job_id": job_id,
            "required_skills": required_skills,
            "nice_to_have_skills": nice_to_have,
            "min_years_experience": min_years,
            "education_requirement": education,
            "required_certifications": certifications,
            "keywords_for_ats": ats_keywords,
            "contact_person": contact_person,
            "contact_email": contact_email
        }

    def process_all_new_jobs(self) -> List[Dict[str, Any]]:
        """Processes all jobs currently in 'NEW' status."""
        conn = get_connection(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM jobs WHERE status = 'NEW'")
        rows = cursor.fetchall()
        conn.close()

        results = []
        for r in rows:
            res = self.process_job(r["id"])
            if res:
                results.append(res)
        return results
