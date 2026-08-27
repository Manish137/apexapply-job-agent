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

    # 9. cover_letters (JobRight & ScaleJobs style tailored cover letters)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS cover_letters (
        id TEXT PRIMARY KEY,
        job_id TEXT NOT NULL,
        application_id TEXT,
        recipient_name TEXT,
        recipient_email TEXT,
        cover_letter_text TEXT NOT NULL,
        cover_letter_html TEXT NOT NULL,
        generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE CASCADE
    );
    """)

    # 10. user_preferences (ScaleJobs & JobRight predefined configuration)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS user_preferences (
        id TEXT PRIMARY KEY,
        target_titles_json TEXT, -- JSON array of target titles
        min_salary INTEGER DEFAULT 180000,
        location_preferences_json TEXT, -- JSON array of preferred locations
        remote_only INTEGER DEFAULT 1,
        visa_status TEXT DEFAULT 'US Citizen',
        blacklisted_companies_json TEXT, -- JSON array of company names to skip
        max_daily_applications INTEGER DEFAULT 15,
        pacing_mode TEXT DEFAULT 'balanced', -- balanced, aggressive, conservative
        auto_tailor_threshold INTEGER DEFAULT 70,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # Seed default user preferences if not present
    cursor.execute("SELECT COUNT(*) as c FROM user_preferences")
    if cursor.fetchone()["c"] == 0:
        cursor.execute("""
        INSERT INTO user_preferences (
            id, target_titles_json, min_salary, location_preferences_json,
            remote_only, visa_status, blacklisted_companies_json,
            max_daily_applications, pacing_mode, auto_tailor_threshold
        ) VALUES (
            'default_preferences',
            '["Principal AI Product Manager", "Lead AI/ML PM", "Director of Product", "Senior Product Leader", "Fintech PM"]',
            180000,
            '["Remote", "San Francisco, CA", "Bay Area, CA"]',
            1,
            'US Citizen',
            '["Revature", "CyberCoders", "Dice Spam Corp"]',
            15,
            'balanced',
            70
        )
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

def get_preferences(pref_id: str = "default_preferences", db_path: Optional[Path] = None) -> Dict[str, Any]:
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM user_preferences WHERE id = ?", (pref_id,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        return {
            "id": pref_id,
            "target_titles": ["Principal AI Product Manager", "Lead AI/ML PM", "Director of Product", "Fintech PM"],
            "min_salary": 180000,
            "location_preferences": ["Remote", "San Francisco, CA"],
            "remote_only": True,
            "visa_status": "US Citizen",
            "blacklisted_companies": ["Revature", "CyberCoders"],
            "max_daily_applications": 15,
            "pacing_mode": "balanced",
            "auto_tailor_threshold": 70
        }
    d = dict(row)
    return {
        "id": d["id"],
        "target_titles": json.loads(d.get("target_titles_json") or "[]"),
        "min_salary": d.get("min_salary", 180000),
        "location_preferences": json.loads(d.get("location_preferences_json") or "[]"),
        "remote_only": bool(d.get("remote_only", 1)),
        "visa_status": d.get("visa_status", "US Citizen"),
        "blacklisted_companies": json.loads(d.get("blacklisted_companies_json") or "[]"),
        "max_daily_applications": d.get("max_daily_applications", 15),
        "pacing_mode": d.get("pacing_mode", "balanced"),
        "auto_tailor_threshold": d.get("auto_tailor_threshold", 70)
    }

def upsert_preferences(pref_data: Dict[str, Any], db_path: Optional[Path] = None):
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("""
    INSERT OR REPLACE INTO user_preferences (
        id, target_titles_json, min_salary, location_preferences_json,
        remote_only, visa_status, blacklisted_companies_json,
        max_daily_applications, pacing_mode, auto_tailor_threshold, updated_at
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        pref_data.get("id", "default_preferences"),
        json.dumps(pref_data.get("target_titles", [])),
        int(pref_data.get("min_salary", 180000)),
        json.dumps(pref_data.get("location_preferences", [])),
        1 if pref_data.get("remote_only", True) else 0,
        pref_data.get("visa_status", "US Citizen"),
        json.dumps(pref_data.get("blacklisted_companies", [])),
        int(pref_data.get("max_daily_applications", 15)),
        pref_data.get("pacing_mode", "balanced"),
        int(pref_data.get("auto_tailor_threshold", 70)),
        datetime.utcnow().isoformat()
    ))
    conn.commit()
    conn.close()

def save_cover_letter(
    job_id: str,
    cover_letter_text: str,
    cover_letter_html: str,
    recipient_name: Optional[str] = None,
    recipient_email: Optional[str] = None,
    application_id: Optional[str] = None,
    db_path: Optional[Path] = None
) -> str:
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cl_id = f"cl_{job_id}"
    cursor.execute("""
    INSERT OR REPLACE INTO cover_letters (
        id, job_id, application_id, recipient_name, recipient_email,
        cover_letter_text, cover_letter_html, generated_at
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        cl_id, job_id, application_id, recipient_name, recipient_email,
        cover_letter_text, cover_letter_html, datetime.utcnow().isoformat()
    ))
    conn.commit()
    conn.close()
    return cl_id

def get_cover_letter(job_id: str, db_path: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM cover_letters WHERE job_id = ? ORDER BY generated_at DESC LIMIT 1", (job_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

