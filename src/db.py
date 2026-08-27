"""
Database Module for ApexApply Job Agent
=======================================
Single source of truth for all SQLite operations and table schemas.
Matches Section 3 Data Model verbatim.
"""

import sqlite3
import json
import os
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime

DEFAULT_DB_PATH = Path(__file__).parent.parent / "data" / "job_agent.db"

def get_connection(db_path: Optional[Path] = None) -> sqlite3.Connection:
    target_path = Path(db_path) if db_path else DEFAULT_DB_PATH
    target_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(target_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

def init_db(db_path: Optional[Path] = None):
    """Creates all SQLite tables matching Section 3 schema verbatim."""
    conn = get_connection(db_path)
    cursor = conn.cursor()

    # 1. base_resumes
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS base_resumes (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        file_path TEXT NOT NULL,
        primary_skills TEXT, -- JSON array of strings
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        is_default INTEGER DEFAULT 0
    );
    """)

    # 2. jobs
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS jobs (
        id TEXT PRIMARY KEY,
        source_scraper_id TEXT,
        title TEXT NOT NULL,
        company TEXT NOT NULL,
        description_raw TEXT,
        posting_url TEXT,
        platform_type TEXT, -- greenhouse, lever, workday, linkedin, custom
        location TEXT,
        remote_flag INTEGER DEFAULT 0,
        salary_range TEXT,
        contact_person TEXT,
        contact_email TEXT,
        date_scraped TEXT,
        date_posted TEXT,
        status TEXT DEFAULT 'NEW', -- NEW, ANALYZED, TAILORED, QUEUED, APPLIED, FAILED, SKIPPED
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # 3. job_requirements (output of Extraction Engine)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS job_requirements (
        id TEXT PRIMARY KEY,
        job_id TEXT NOT NULL,
        required_skills TEXT, -- JSON array
        nice_to_have_skills TEXT, -- JSON array
        min_years_experience INTEGER DEFAULT 0,
        education_requirement TEXT,
        required_certifications TEXT, -- JSON array
        keywords_for_ats TEXT, -- JSON array
        raw_json TEXT,
        FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE CASCADE
    );
    """)

    # 4. tailored_resumes
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS tailored_resumes (
        id TEXT PRIMARY KEY,
        job_id TEXT NOT NULL,
        base_resume_id TEXT NOT NULL,
        file_path TEXT NOT NULL,
        match_score INTEGER NOT NULL,
        skills_added_emphasis TEXT, -- JSON array
        skills_gap TEXT, -- JSON array (things not possessed, surfaced honestly)
        generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE CASCADE,
        FOREIGN KEY(base_resume_id) REFERENCES base_resumes(id)
    );
    """)

    # 5. field_taxonomy (discovered platform fields)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS field_taxonomy (
        id TEXT PRIMARY KEY,
        platform_type TEXT NOT NULL,
        field_name TEXT NOT NULL,
        field_type TEXT NOT NULL, -- text, dropdown, file, radio, checkbox, textarea
        maps_to_profile_field TEXT,
        is_required INTEGER DEFAULT 0,
        sample_values TEXT, -- JSON array
        last_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(platform_type, field_name)
    );
    """)

    # 6. applications
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS applications (
        id TEXT PRIMARY KEY,
        job_id TEXT NOT NULL,
        tailored_resume_id TEXT,
        status TEXT NOT NULL, -- DRAFT, PENDING_REVIEW, SUBMITTED, FAILED, CAPTCHA_BLOCKED
        applied_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        screenshot_before_submit_path TEXT,
        fields_filled_json TEXT, -- JSON dict
        contact_person TEXT,
        contact_email TEXT,
        skills_targeted TEXT, -- JSON array
        match_score_at_apply INTEGER,
        submission_mode TEXT DEFAULT 'manual_confirm', -- manual_confirm, auto
        response_status TEXT DEFAULT 'No response', -- No response, Rejected, Interview, Offer
        error_log TEXT,
        notes TEXT,
        FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE CASCADE,
        FOREIGN KEY(tailored_resume_id) REFERENCES tailored_resumes(id)
    );
    """)

    # 7. profile (master pre-fill data)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS profile (
        id TEXT PRIMARY KEY,
        full_name TEXT NOT NULL,
        email TEXT NOT NULL,
        phone TEXT,
        address TEXT,
        linkedin_url TEXT,
        portfolio_url TEXT,
        work_authorization TEXT,
        salary_expectation TEXT,
        years_experience INTEGER DEFAULT 15,
        custom_field_answers TEXT -- JSON dict of question templates
    );
    """)

    # 8. audit_logs (for dashboard live console)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS audit_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        level TEXT,
        action TEXT,
        job_id TEXT,
        details TEXT
    );
    """)

    conn.commit()
    conn.close()

# Helper DB Access Operations
def log_audit(action: str, level: str = "INFO", job_id: str = "", details: str = "", db_path: Optional[Path] = None):
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO audit_logs (timestamp, level, action, job_id, details) VALUES (?, ?, ?, ?, ?)",
        (datetime.utcnow().isoformat(), level, action, job_id, details)
    )
    conn.commit()
    conn.close()

def upsert_profile(profile_data: Dict[str, Any], db_path: Optional[Path] = None):
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("""
    INSERT OR REPLACE INTO profile (
        id, full_name, email, phone, address, linkedin_url, portfolio_url,
        work_authorization, salary_expectation, years_experience, custom_field_answers
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        profile_data.get("id", "default_profile"),
        profile_data["full_name"],
        profile_data["email"],
        profile_data.get("phone", ""),
        profile_data.get("address", ""),
        profile_data.get("linkedin_url", ""),
        profile_data.get("portfolio_url", ""),
        profile_data.get("work_authorization", "US Citizen / Authorized"),
        profile_data.get("salary_expectation", "$180,000 - $220,000"),
        profile_data.get("years_experience", 15),
        json.dumps(profile_data.get("custom_field_answers", {}))
    ))
    conn.commit()
    conn.close()

def get_profile(profile_id: str = "default_profile", db_path: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM profile WHERE id = ?", (profile_id,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    try:
        d["custom_field_answers"] = json.loads(d.get("custom_field_answers") or "{}")
    except:
        d["custom_field_answers"] = {}
    return d
