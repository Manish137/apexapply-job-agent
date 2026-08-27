"""
Ingestion Service for ApexApply Job Agent
=========================================
Pulls and parses scraped jobs, deduplicates listings, detects platform types,
and stores records into the SQLite jobs table with status 'NEW'.
"""

import os
import json
import glob
import re
import hashlib
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime

from src.db import get_connection, log_audit

class IngestionService:
    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path

    def detect_platform_type(self, url: str) -> str:
        """Classify ATS platform from posting URL."""
        if not url:
            return "custom"
        u = url.lower()
        if "greenhouse.io" in u or "boards.greenhouse.io" in u:
            return "greenhouse"
        elif "lever.co" in u or "jobs.lever.co" in u:
            return "lever"
        elif "myworkdayjobs.com" in u or "workday" in u:
            return "workday"
        elif "linkedin.com" in u:
            return "linkedin"
        elif "ashbyhq.com" in u:
            return "ashby"
        elif "remoteok.com" in u:
            return "remoteok"
        return "custom"

    def normalize_job_dict(self, raw: Dict[str, Any], source_id: str = "") -> Dict[str, Any]:
        """Normalize raw scraped dictionary into standard jobs row schema."""
        title = raw.get("title") or raw.get("position") or raw.get("role") or "Software / Product Role"
        company = raw.get("company") or raw.get("company_name") or "Company"
        
        # Clean company if joined in title
        if company == "Unknown" and "(" in title:
            company = title.split("(")[0].strip()

        location = raw.get("location") or raw.get("job_location") or "Remote, US"
        if isinstance(location, list):
            location = ", ".join(location)

        salary = raw.get("salary") or raw.get("compensation") or "Not listed"
        url = raw.get("url") or raw.get("posting_url") or raw.get("apply_url") or raw.get("link") or ""
        
        if url.startswith("https://remoteok.comhttps://"):
            url = url.replace("https://remoteok.comhttps://", "https://")

        description = raw.get("description") or raw.get("description_raw") or raw.get("body") or raw.get("text") or ""
        # Strip HTML tags
        clean_desc = re.sub(r'<[^>]+>', ' ', description).strip()
        clean_desc = re.sub(r'\s+', ' ', clean_desc)

        date_posted = str(raw.get("date_posted") or raw.get("datePosted") or raw.get("date") or "Recent")
        date_scraped = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

        platform_type = self.detect_platform_type(url)
        remote_flag = 1 if any(k in f"{title} {location} {clean_desc}".lower() for k in ["remote", "work from home", "anywhere"]) else 0

        # Deterministic Job ID based on company + title + url
        hash_input = f"{company.strip().lower()}::{title.strip().lower()}::{url.strip()}"
        job_id = f"job_{hashlib.md5(hash_input.encode('utf-8')).hexdigest()[:12]}"

        return {
            "id": job_id,
            "source_scraper_id": source_id or raw.get("id") or "scraper_feed",
            "title": title.strip(),
            "company": company.strip(),
            "description_raw": clean_desc,
            "posting_url": url.strip(),
            "platform_type": platform_type,
            "location": location.strip(),
            "remote_flag": remote_flag,
            "salary_range": salary.strip(),
            "contact_person": raw.get("contact_person", ""),
            "contact_email": raw.get("contact_email", ""),
            "date_scraped": date_scraped,
            "date_posted": date_posted,
            "status": "NEW"
        }

    def ingest_file(self, file_path: Path) -> Tuple[int, int]:
        """Ingests a JSON file, inserts new rows, rejects duplicates. Returns (new_count, dup_count)."""
        if not file_path.exists():
            return 0, 0

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            return 0, 0

        raw_items = []
        file_scrape_date = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        if isinstance(data, list):
            raw_items = data
        elif isinstance(data, dict):
            if "generated_at" in data:
                file_scrape_date = data["generated_at"]
            if "jobs" in data and isinstance(data["jobs"], list):
                raw_items = data["jobs"]
            elif "data" in data and isinstance(data["data"], list):
                raw_items = data["data"]
            else:
                raw_items = [data]

        conn = get_connection(self.db_path)
        cursor = conn.cursor()

        new_count = 0
        dup_count = 0

        for raw in raw_items:
            if not isinstance(raw, dict) or not (raw.get("title") or raw.get("position")):
                continue

            norm = self.normalize_job_dict(raw, source_id=file_path.name)
            # Use scrape date from file metadata if available
            if "generated_at" in data:
                norm["date_scraped"] = str(data["generated_at"])
            
            # Check for existing job by ID
            cursor.execute("SELECT id FROM jobs WHERE id = ?", (norm["id"],))
            existing = cursor.fetchone()

            if existing:
                dup_count += 1
            else:
                cursor.execute("""
                INSERT INTO jobs (
                    id, source_scraper_id, title, company, description_raw,
                    posting_url, platform_type, location, remote_flag, salary_range,
                    contact_person, contact_email, date_scraped, date_posted, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    norm["id"], norm["source_scraper_id"], norm["title"], norm["company"],
                    norm["description_raw"], norm["posting_url"], norm["platform_type"],
                    norm["location"], norm["remote_flag"], norm["salary_range"],
                    norm["contact_person"], norm["contact_email"], norm["date_scraped"],
                    norm["date_posted"], norm["status"]
                ))
                new_count += 1

        conn.commit()
        conn.close()

        if new_count > 0:
            log_audit("INGEST_BATCH", "INFO", "", f"Ingested {new_count} new jobs from {file_path.name} ({dup_count} dups skipped)", self.db_path)

        return new_count, dup_count

    def scan_scraper_directories(self, search_dirs: List[Path]) -> Tuple[int, int]:
        """Scans multiple scraper directories and ingests all valid JSON files."""
        total_new = 0
        total_dup = 0
        for sdir in search_dirs:
            if not sdir.exists():
                continue
            for jf in glob.glob(str(sdir / "*.json")) + glob.glob(str(sdir / "**" / "*.json")):
                if "h1b_cache" in jf or "package" in jf or "manifest" in jf:
                    continue
                n, d = self.ingest_file(Path(jf))
                total_new += n
                total_dup += d
        return total_new, total_dup
