"""
Field Taxonomy Service for ApexApply Job Agent
==============================================
Manages discovered form fields per platform type and maps them to candidate profile data.
"""

import json
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime

from src.db import get_connection, log_audit

class FieldTaxonomyService:
    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path

    def register_field(
        self,
        platform_type: str,
        field_name: str,
        field_type: str,
        maps_to_profile_field: Optional[str] = None,
        is_required: bool = False,
        sample_values: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """Registers a discovered field into field_taxonomy table."""
        conn = get_connection(self.db_path)
        cursor = conn.cursor()
        field_id = f"ft_{platform_type}_{field_name.lower().replace(' ', '_')}"

        cursor.execute("""
        INSERT OR REPLACE INTO field_taxonomy (
            id, platform_type, field_name, field_type, maps_to_profile_field,
            is_required, sample_values, last_seen_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            field_id,
            platform_type,
            field_name,
            field_type,
            maps_to_profile_field or self.infer_profile_mapping(field_name),
            1 if is_required else 0,
            json.dumps(sample_values or []),
            datetime.utcnow().isoformat()
        ))

        conn.commit()
        conn.close()

        return {
            "id": field_id,
            "platform_type": platform_type,
            "field_name": field_name,
            "field_type": field_type,
            "maps_to_profile_field": maps_to_profile_field or self.infer_profile_mapping(field_name),
            "is_required": is_required
        }

    def infer_profile_mapping(self, field_label: str) -> Optional[str]:
        """Heuristic mapping from label text to standard profile keys."""
        l = field_label.lower()
        if "first name" in l or "given name" in l:
            return "first_name"
        elif "last name" in l or "family name" in l or "surname" in l:
            return "last_name"
        elif "full name" in l or "name" in l:
            return "full_name"
        elif "email" in l:
            return "email"
        elif "phone" in l or "mobile" in l:
            return "phone"
        elif "linkedin" in l:
            return "linkedin_url"
        elif "portfolio" in l or "website" in l or "github" in l:
            return "portfolio_url"
        elif "address" in l or "location" in l or "city" in l:
            return "address"
        elif "authorized" in l or "sponsorship" in l or "visa" in l or "legal" in l:
            return "work_authorization"
        elif "salary" in l or "compensation" in l:
            return "salary_expectation"
        elif "years" in l and "experience" in l:
            return "years_experience"
        elif "why" in l and ("join" in l or "work" in l or "company" in l or "role" in l):
            return "why_join"
        elif "resume" in l or "cv" in l:
            return "resume_file"
        return None

    def get_taxonomy_for_platform(self, platform_type: str) -> List[Dict[str, Any]]:
        """Fetch all known fields for a platform."""
        conn = get_connection(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM field_taxonomy WHERE platform_type = ?", (platform_type,))
        rows = cursor.fetchall()
        conn.close()
        results = []
        for r in rows:
            d = dict(r)
            d["sample_values"] = json.loads(d.get("sample_values") or "[]")
            results.append(d)
        return results

    def get_all_taxonomy(self) -> List[Dict[str, Any]]:
        """Fetch full taxonomy catalog."""
        conn = get_connection(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM field_taxonomy ORDER BY platform_type, field_name")
        rows = cursor.fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def seed_standard_taxonomy(self):
        """Seeds standard taxonomy for Greenhouse, Lever, Workday, LinkedIn."""
        platforms = ["greenhouse", "lever", "workday", "linkedin", "custom"]
        standard_fields = [
            ("First Name", "text", "first_name", True),
            ("Last Name", "text", "last_name", True),
            ("Email", "text", "email", True),
            ("Phone", "text", "phone", True),
            ("Resume/CV", "file", "resume_file", True),
            ("LinkedIn Profile", "text", "linkedin_url", True),
            ("Portfolio / Website", "text", "portfolio_url", False),
            ("Are you authorized to work in the US?", "dropdown", "work_authorization", True),
            ("Will you now or in the future require sponsorship?", "dropdown", "work_authorization", True),
            ("Desired Salary", "text", "salary_expectation", False),
            ("Why do you want to work here?", "textarea", "why_join", False)
        ]
        for p in platforms:
            for name, ftype, mapping, req in standard_fields:
                self.register_field(p, name, ftype, mapping, req)
