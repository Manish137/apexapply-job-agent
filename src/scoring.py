"""
ATS Match Scorer for ApexApply Job Agent
========================================
Calculates honest ATS match scores based on candidate true qualifications vs JD requirements.
Never masks skill gaps with artificial inflation.
"""

from typing import List, Dict, Any, Tuple

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
