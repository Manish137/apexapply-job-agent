"""
Job Discovery for ApexApply Job Agent
=====================================
Pulls open roles straight from companies' public ATS job-board APIs
(Greenhouse, Lever, Ashby), keeps only titles that match the target titles
and US/remote locations, and ingests them as NEW jobs.

The company list lives in data/sources.json and can be edited from the API
(GET/PUT /api/sources). An unknown board name is logged and skipped.
"""

import re
import json
from pathlib import Path
from typing import Dict, List, Any, Optional

import requests

from src.db import log_audit
from src.ingestion import IngestionService

DEFAULT_DATA_DIR = Path(__file__).parent.parent / "data"

DEFAULT_SOURCES = {
    "greenhouse": ["anthropic", "cresta", "scaleai", "iterativehealth", "gleanwork", "databricks", "stripe",
                   "brex", "robinhood", "chime", "affirm", "sofi", "carta", "airtable", "vercel"],
    "lever": ["palantir", "plaid", "gigs", "lotusflare"],
    "ashby": ["odewithanthropic", "openai", "ramp", "sierra", "decagon", "harvey", "hebbia", "writer",
              "cohere", "mercury", "method", "lorikeet", "fermat", "exa", "oneschema", "tailor", "notion",
              "elevenlabs", "rogo", "baseten", "modal"],
}

DEFAULT_TARGET_TITLES = [
    "forward deployed product manager",
    "forward deployed product owner",
    "forward deployed pm",
    "deployed product manager",
    "fdpm",
]

NON_US = re.compile(
    r"\b(london|uk|united kingdom|england|toronto|vancouver|canada|india|bangalore|bengaluru|hyderabad|singapore|"
    r"sydney|melbourne|australia|germany|berlin|munich|paris|france|dublin|ireland|amsterdam|netherlands|tokyo|"
    r"japan|seoul|korea|emea|apac|europe|brazil|mexico|tel aviv|israel|zurich|stockholm|warsaw|madrid|lisbon)\b",
    re.I,
)


def title_matches(title: str, targets: List[str]) -> bool:
    words = set(re.sub(r"[^a-z0-9 ]+", " ", title.lower().replace("-", " ")).split())
    for t in targets:
        t_words = re.sub(r"[^a-z0-9 ]+", " ", t.lower().replace("-", " ")).split()
        if t_words and all(w in words for w in t_words):
            return True
    return False


def location_ok(location: str) -> bool:
    if not location:
        return True
    if NON_US.search(location) and not re.search(r"\b(us|usa|united states|remote, us|new york|san francisco)\b", location, re.I):
        return False
    return True


class JobSources:
    def __init__(self, db_path: Optional[Path] = None, data_dir: Optional[Path] = None, session=None):
        self.db_path = db_path
        self.data_dir = data_dir or DEFAULT_DATA_DIR
        self.config_path = self.data_dir / "sources.json"
        self.http = session or requests.Session()
        self.http.headers.update({"User-Agent": "ApexApply/3.0 (job search for one candidate)"})
        self.ingestion = IngestionService(db_path=db_path)

    def load(self) -> Dict[str, List[str]]:
        if self.config_path.exists():
            try:
                return json.loads(self.config_path.read_text())
            except json.JSONDecodeError:
                pass
        return {k: list(v) for k, v in DEFAULT_SOURCES.items()}

    def save(self, sources: Dict[str, List[str]]):
        clean = {k: sorted({s.strip() for s in sources.get(k, []) if s.strip()}) for k in ("greenhouse", "lever", "ashby")}
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self.config_path.write_text(json.dumps(clean, indent=2))

    # ─────────────────────────────────────────────────────────────
    # Per-ATS fetchers → raw job dicts for IngestionService
    # ─────────────────────────────────────────────────────────────
    def _get(self, url: str) -> Optional[Any]:
        try:
            res = self.http.get(url, timeout=30)
        except requests.RequestException as e:
            log_audit("SOURCE_ERROR", "WARNING", "", f"{url}: {e}", self.db_path)
            return None
        if res.status_code != 200:
            log_audit("SOURCE_ERROR", "WARNING", "", f"{url}: HTTP {res.status_code}", self.db_path)
            return None
        return res.json()

    def fetch_greenhouse(self, board: str) -> List[Dict[str, Any]]:
        data = self._get(f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true") or {}
        company = data.get("meta", {}).get("name") if isinstance(data.get("meta"), dict) else None
        out = []
        for j in data.get("jobs", []):
            out.append({
                "title": j.get("title", ""),
                "company": j.get("company_name") or company or board.title(),
                "url": f"https://job-boards.greenhouse.io/{board}/jobs/{j.get('id')}",
                "description": j.get("content", ""),
                "location": (j.get("location") or {}).get("name", ""),
                "date_posted": j.get("first_published") or j.get("updated_at"),
            })
        return out

    def fetch_lever(self, board: str) -> List[Dict[str, Any]]:
        data = self._get(f"https://api.lever.co/v0/postings/{board}?mode=json") or []
        out = []
        for j in data if isinstance(data, list) else []:
            cats = j.get("categories") or {}
            desc = " ".join(filter(None, [j.get("descriptionPlain"), j.get("additionalPlain")] +
                                   [f"{l.get('text', '')}: {l.get('content', '')}" for l in j.get("lists", [])]))
            salary = j.get("salaryRange") or {}
            out.append({
                "title": j.get("text", ""),
                "company": board.title(),
                "url": j.get("hostedUrl", ""),
                "description": desc,
                "location": cats.get("location") or ", ".join(cats.get("allLocations", []) or []),
                "salary": f"{salary.get('min')}-{salary.get('max')} {salary.get('currency', '')}".strip() if salary else "",
                "date_posted": j.get("createdAt"),
            })
        return out

    def fetch_ashby(self, board: str) -> List[Dict[str, Any]]:
        data = self._get(f"https://api.ashbyhq.com/posting-api/job-board/{board}?includeCompensation=true") or {}
        out = []
        for j in data.get("jobs", []):
            if j.get("isListed") is False:
                continue
            loc = j.get("location") or ""
            if j.get("isRemote") and "remote" not in loc.lower():
                loc = f"{loc} (Remote)".strip()
            comp = (j.get("compensation") or {}).get("compensationTierSummary") or ""
            out.append({
                "title": j.get("title", ""),
                "company": board.title(),
                "url": j.get("jobUrl") or f"https://jobs.ashbyhq.com/{board}/{j.get('id')}",
                "description": j.get("descriptionPlain") or j.get("descriptionHtml", ""),
                "location": loc,
                "salary": comp,
                "date_posted": j.get("publishedAt"),
            })
        return out

    def discover(self, target_titles: Optional[List[str]] = None) -> Dict[str, Any]:
        targets = target_titles or DEFAULT_TARGET_TITLES
        sources = self.load()
        fetchers = {"greenhouse": self.fetch_greenhouse, "lever": self.fetch_lever, "ashby": self.fetch_ashby}
        matched: List[Dict[str, Any]] = []
        scanned = 0
        for ats, boards in sources.items():
            for board in boards:
                jobs = fetchers[ats](board)
                scanned += len(jobs)
                matched.extend(j for j in jobs if title_matches(j["title"], targets) and location_ok(j["location"]))
        new_c, dup_c = self.ingestion.ingest_items(matched, source_id="ats_boards")
        summary = {"postings_scanned": scanned, "matched": len(matched), "new": new_c, "duplicates": dup_c,
                   "roles": [f"{j['company']}: {j['title']} ({j['location']})" for j in matched]}
        log_audit("DISCOVER", "INFO", "", f"Scanned {scanned} postings, {len(matched)} matched titles, {new_c} new", self.db_path)
        return summary
