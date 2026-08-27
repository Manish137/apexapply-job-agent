"""
ATS Match Scorer & JobRight-Style Multi-Dimensional Breakdown
=============================================================
Calculates honest ATS match scores and generates structured analytics:
- "Why You Match" (Strengths, Core Competencies, Experience Fit)
- "Skills Gap & Radar" (Unheld requirements & actionable interview prep advice)
- Salary Fit & Remote Alignment Matrix
"""

from typing import List, Dict, Any, Tuple, Optional

class MatchScorer:
    def __init__(self, match_threshold: int = 70):
        self.match_threshold = match_threshold

    def calculate_match(
        self,
        candidate_skills: List[str],
        required_skills: List[str],
        nice_to_have_skills: List[str] = None,
        keywords_for_ats: List[str] = None
    ) -> Tuple[int, List[str], List[str]]:
        """
        Computes honest match score (0-100), matched skills list, and skill gap list.
        Weighted: Required (75%), Nice-to-have (15%), Keyword Density (10%).
        """
        nice_to_have = nice_to_have_skills or []
        ats_keywords = keywords_for_ats or []

        candidate_lower = {s.lower() for s in candidate_skills}

        matched_required = []
        skills_gap = []

        for req in required_skills:
            req_l = req.lower()
            if any(req_l in c or c in req_l for c in candidate_lower):
                matched_required.append(req)
            else:
                skills_gap.append(req)

        # 1. Required skills score (weight 75)
        req_total = len(required_skills)
        req_score = (len(matched_required) / req_total * 75) if req_total > 0 else 0

        # 2. Nice-to-have score (weight 15)
        matched_nice = [n for n in nice_to_have if any(n.lower() in c or c in n.lower() for c in candidate_lower)]
        nice_total = len(nice_to_have)
        nice_score = (len(matched_nice) / nice_total * 15) if nice_total > 0 else 0

        # 3. Keyword density (weight 10)
        matched_kw = [k for k in ats_keywords if any(k.lower() in c or c in k.lower() for c in candidate_lower)]
        kw_total = len(ats_keywords)
        kw_score = (len(matched_kw) / kw_total * 10) if kw_total > 0 else 0

        final_score = int(round(req_score + nice_score + kw_score))
        final_score = max(0, min(100, final_score))

        return final_score, matched_required, skills_gap

    def generate_match_breakdown(
        self,
        candidate_skills: List[str],
        candidate_years: int,
        candidate_target_salary: int,
        job: Dict[str, Any],
        job_requirements: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Generates rich, multi-dimensional JobRight-style match diagnostics.
        """
        required_skills = job_requirements.get("required_skills", [])
        nice_to_have = job_requirements.get("nice_to_have_skills", [])
        ats_keywords = job_requirements.get("keywords_for_ats", [])
        min_years = job_requirements.get("min_years_experience", 5)

        score, matched_skills, skills_gap = self.calculate_match(
            candidate_skills=candidate_skills,
            required_skills=required_skills,
            nice_to_have_skills=nice_to_have,
            keywords_for_ats=ats_keywords
        )

        # Rating badge
        if score >= 85:
            rating_badge = "STRONG_MATCH"
            badge_label = "🎯 Strong Fit"
            badge_color = "#10b981"
        elif score >= 70:
            rating_badge = "GOOD_MATCH"
            badge_label = "✅ Good Fit"
            badge_color = "#3b82f6"
        elif score >= 50:
            rating_badge = "BORDERLINE"
            badge_label = "⚠️ Borderline"
            badge_color = "#f59e0b"
        else:
            rating_badge = "POOR_FIT"
            badge_label = "❌ Low Match"
            badge_color = "#ef4444"

        # Why You Match points
        why_you_match = []
        if candidate_years >= min_years:
            why_you_match.append(f"Seniority: {candidate_years}+ years experience exceeds the {min_years}+ year requirement.")
        if matched_skills:
            top_3 = ", ".join(matched_skills[:3])
            why_you_match.append(f"Key Tech Alignment: Direct verified mastery in {top_3}.")
        why_you_match.append("Track Record: Demonstrated ROI scaling AI platforms ($900K savings) and $10M+ enterprise risk modernizations.")

        # Skills Gap & Mitigation Advice
        gap_advice = "No critical skills gap detected; candidate profiles strongly for this role."
        if skills_gap:
            gap_str = ", ".join(skills_gap[:3])
            gap_advice = f"To mitigate gap in [{gap_str}], emphasize foundational architectural agility and fast learning cycles during interviews."

        # Salary Fit Analysis
        salary_fit = "Competitive / Undisclosed Range"
        salary_str = job.get("salary_range") or ""
        if salary_str:
            salary_fit = f"Posted: {salary_str} (Candidate Target: ${candidate_target_salary:,}+)"

        # Remote Fit Analysis
        remote_flag = job.get("remote_flag", 0)
        location = job.get("location") or "Remote"
        if remote_flag or "remote" in location.lower():
            remote_fit = "🌐 100% Remote Match"
        else:
            remote_fit = f"📍 Location: {location}"

        return {
            "overall_score": score,
            "rating_badge": rating_badge,
            "badge_label": badge_label,
            "badge_color": badge_color,
            "matched_skills": matched_skills,
            "skills_gap": skills_gap,
            "why_you_match": why_you_match,
            "gap_mitigation_advice": gap_advice,
            "salary_fit": salary_fit,
            "remote_fit": remote_fit,
            "experience_match": f"{candidate_years} yrs vs {min_years} yrs required"
        }
