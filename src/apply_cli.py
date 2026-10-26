"""
ApexApply command line: apply to a list of jobs from your own computer.

    python -m src.apply_cli --jobs data/jobs/fdpm_targets_2026-10-26.json            # review mode
    python -m src.apply_cli --jobs data/jobs/fdpm_targets_2026-10-26.json --auto      # auto-submit

Review mode (default) opens a visible browser per job, fills the whole form, attaches your
resume, and waits for you to check it and click Submit; it records SUBMITTED once the employer's
confirmation page appears. Auto mode submits by itself only when every required question was
answered and no CAPTCHA is present; anything else is left for you in the dashboard Review Queue.
"""

import argparse
import json
import os
from pathlib import Path

from src.db import init_db, get_connection
from src.orchestrator import JobAgentOrchestrator

ROOT = Path(__file__).parent.parent


def main():
    ap = argparse.ArgumentParser(description="Apply to jobs with ApexApply")
    ap.add_argument("--jobs", help="JSON file of jobs (title, company, url, description, location)")
    ap.add_argument("--max", type=int, default=50, help="Maximum jobs to process")
    ap.add_argument("--auto", action="store_true", help="Submit automatically when the form is fully answered")
    ap.add_argument("--headless", action="store_true", help="Run without a visible browser (auto mode only)")
    ap.add_argument("--wait", type=int, default=900, help="Seconds to wait for you to click Submit in review mode")
    ap.add_argument("--min-score", type=int, default=None, help="Skip jobs below this match score (default: dashboard preference)")
    ap.add_argument("--retry", action="store_true", help="Retry jobs that were left pending review")
    args = ap.parse_args()

    if not args.auto and args.headless:
        ap.error("--headless only works with --auto (review mode needs a visible browser)")

    db_path = Path(os.getenv("DB_PATH", ROOT / "data" / "job_agent.db"))
    init_db(db_path)
    orch = JobAgentOrchestrator(db_path=db_path, data_dir=ROOT / "data")
    orch.get_or_create_profile()

    job_ids = []
    if args.jobs:
        records = json.loads(Path(args.jobs).read_text(encoding="utf-8"))
        orch.ingestion.ingest_file(Path(args.jobs))
        conn = get_connection(db_path)
        for raw in records:
            norm = orch.ingestion.normalize_job_dict(raw)
            row = conn.execute("SELECT id FROM jobs WHERE id = ?", (norm["id"],)).fetchone()
            if row:
                job_ids.append(row["id"])
        conn.close()
    else:
        conn = get_connection(db_path)
        job_ids = [r["id"] for r in conn.execute(
            "SELECT id FROM jobs WHERE status IN ('NEW', 'ANALYZED', 'TAILORED', 'QUEUED') ORDER BY date_scraped DESC").fetchall()]
        conn.close()

    print(f"LLM provider: {orch.llm.provider}" + (f" ({orch.llm.anthropic_model})" if orch.llm.provider == "anthropic" else ""))
    print(f"Mode: {'AUTO-SUBMIT' if args.auto else 'REVIEW (you click Submit)'} | jobs: {min(len(job_ids), args.max)}\n")

    summary = {}
    for job_id in job_ids[: args.max]:
        conn = get_connection(db_path)
        job = dict(conn.execute("SELECT company, title, posting_url FROM jobs WHERE id = ?", (job_id,)).fetchone())
        conn.close()
        print(f"→ {job['company']} | {job['title']}\n  {job['posting_url']}")
        res = orch.run_pipeline_for_job(
            job_id,
            auto_submit=args.auto,
            min_score=args.min_score,
            headless=args.headless if args.auto else False,
            wait_for_user_seconds=0 if args.auto else args.wait,
            retry_pending=args.retry,
        )
        status = res.get("status")
        summary[status] = summary.get(status, 0) + 1
        app = res.get("application") or {}
        line = f"  {status}"
        if res.get("match_score") is not None:
            line += f" | match {res['match_score']}%"
        if app.get("error"):
            line += f"\n  note: {app['error']}"
        if res.get("reason"):
            line += f" | {res['reason']}"
        print(line + "\n")

    print("Done:", ", ".join(f"{k}: {v}" for k, v in summary.items()) or "no jobs")
    print("Open the dashboard Review Queue for anything still pending: python -m uvicorn dashboard.server:app --port 8765")


if __name__ == "__main__":
    main()
