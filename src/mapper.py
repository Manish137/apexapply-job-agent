"""
Application Field Mapper for ApexApply Job Agent
================================================
Maps candidate profile values and custom question answers to discovered ATS form fields.
"""

from typing import Dict, List, Any, Optional

class ApplicationFieldMapper:
    def __init__(self, profile: Dict[str, Any]):
        self.profile = profile

    def map_fields(self, discovered_fields: List[Dict[str, Any]], tailored_resume_path: str = "") -> Dict[str, Any]:
        """
        Maps list of discovered form fields to profile data.
        Returns:
            {
                "mapped_fields": { field_name: value },
                "missing_required": [ field_name ],
                "ready_to_fill": bool
            }
        """
        mapped = {}
        missing_required = []

        first_name = self.profile.get("first_name") or self.profile.get("full_name", "Manish Shukla").split()[0]
        last_name = self.profile.get("last_name") or self.profile.get("full_name", "Manish Shukla").split()[-1]
        custom_answers = self.profile.get("custom_field_answers", {})

        for f in discovered_fields:
            name = f["field_name"]
            mapping_key = f.get("maps_to_profile_field") or ""
            is_req = f.get("is_required", False)

            val = None
            if mapping_key == "first_name":
                val = first_name
            elif mapping_key == "last_name":
                val = last_name
            elif mapping_key == "full_name":
                val = self.profile.get("full_name", "Manish Shukla")
            elif mapping_key == "email":
                val = self.profile.get("email", "shukla.manish80@gmail.com")
            elif mapping_key == "phone":
                val = self.profile.get("phone", "(209) 319-8716")
            elif mapping_key == "linkedin_url":
                val = self.profile.get("linkedin_url", "https://linkedin.com/in/mshukla1")
            elif mapping_key == "portfolio_url":
                val = self.profile.get("portfolio_url", "https://manishshukla.dev")
            elif mapping_key == "address":
                val = self.profile.get("address", "Tracy, CA")
            elif mapping_key == "work_authorization":
                val = self.profile.get("work_authorization", "Yes")
            elif mapping_key == "salary_expectation":
                val = self.profile.get("salary_expectation", "$180,000 - $220,000")
            elif mapping_key == "years_experience":
                val = str(self.profile.get("years_experience", 15))
            elif mapping_key == "resume_file":
                val = tailored_resume_path
            elif mapping_key == "why_join":
                val = custom_answers.get("why_join", "Passionate about scaling high-impact AI/ML platforms and workflow automations.")
            else:
                # Custom answer check
                val = custom_answers.get(name) or custom_answers.get(name.lower())

            if val is not None:
                mapped[name] = val
            elif is_req:
                missing_required.append(name)

        return {
            "mapped_fields": mapped,
            "missing_required": missing_required,
            "ready_to_fill": len(missing_required) == 0
        }
