"""AI visibility pipeline: Google SERP + AI Overview, AI Mode, Perplexity,
ChatGPT, Gemini, Claude via DataForSEO.

  python run_pipeline.py                     # every project in projects.yaml due today
  python run_pipeline.py --project my-brand --force
  python run_pipeline.py --local inputs_local --force   # CSV inputs, no Google Sheet
  python run_pipeline.py --project my-brand --dry-run      # show what would run, no API spend
"""
import argparse
import datetime as dt
import logging
import os
import sys
import time
from pathlib import Path

import yaml

from pipeline import store
from pipeline.client import DFSClient
from pipeline.platforms import PLATFORMS
from pipeline.runner import run
from pipeline.scoring import score, summarize

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("pipeline")


def plan(keywords, prompts, s):
    counts = {}
    for p in s["platforms"]:
        if p in PLATFORMS:
            counts[p] = len(keywords if PLATFORMS[p]["input"] == "keywords" else prompts)
    return counts


def run_project(name, keywords, prompts, s, sheet, args):
    counts = plan(keywords, prompts, s)
    log.info("[%s] %d keywords, %d prompts -> calls per platform: %s",
             name, len(keywords), len(prompts), counts)
    unknown = [p for p in s["platforms"] if p not in PLATFORMS]
    if unknown:
        log.warning("[%s] ignoring unknown platforms: %s", name, unknown)
    if args.dry_run:
        return 0

    started = time.time()
    run_id = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_date = run_id[:8]
    client = DFSClient()
    answers, citations = run(client, s, keywords, prompts)
    answers, citations = score(answers, citations, s)
    store.stamp(answers, run_id, run_date, name)
    store.stamp(citations, run_id, run_date, name)
    summary = summarize(answers, s)
    for row in summary:
        row.update(run_id=run_id, run_date=run_date)

    store.write_csvs(Path(args.out) / name / run_id, answers, citations, summary)
    run_log = {
        "run_id": run_id, "project": name, "keywords": len(keywords), "prompts": len(prompts),
        "answers": len(answers), "citations": len(citations),
        "errors": sum(a["status"] in ("error", "timeout") for a in answers),
        "cost_usd": round(client.cost, 4), "minutes": round((time.time() - started) / 60, 1),
    }
    if sheet is not None:
        store.write_sheet(sheet, run_log, answers, summary)
    if s["bigquery_table_prefix"]:
        store.write_bigquery(s["bigquery_table_prefix"], answers, citations)
    log.info("[%s] done: %s", name, run_log)
    return run_log["errors"]


def load_projects():
    """Real project list comes from the PROJECTS_YAML secret (CI) or a git-ignored
    projects.yaml (local), so client names and Sheet ids never live in the repo."""
    raw = os.getenv("PROJECTS_YAML", "").strip()
    if not raw and Path("projects.yaml").exists():
        raw = Path("projects.yaml").read_text()
    if not raw:
        return []
    projects = (yaml.safe_load(raw) or {}).get("projects") or []
    return [p for p in projects if p.get("sheet_id") and p["sheet_id"] != "REPLACE_WITH_SHEET_ID"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", help="run only this project from projects.yaml")
    ap.add_argument("--local", help="folder with keywords.csv / prompts.csv / settings.csv")
    ap.add_argument("--force", action="store_true", help="ignore the run_on schedule")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--out", default="output")
    args = ap.parse_args()

    if args.local:
        kw, pr, s = store.load_local(args.local)
        run_project(args.project or "local", kw, pr, s, None, args)
        return

    projects = load_projects()
    if not projects:
        log.info("No projects configured (set the PROJECTS_YAML secret or create projects.yaml). Nothing to do.")
        return
    if args.project:
        projects = [p for p in projects if p["name"] == args.project]
        if not projects:
            sys.exit(f"No project named {args.project!r} in projects.yaml")

    failures = 0
    for p in projects:
        try:
            (kw, pr, s), sheet = store.load_sheet(p["sheet_id"])
            if not (args.force or store.should_run(s["run_on"])):
                log.info("[%s] not scheduled today (run_on=%s)", p["name"], s["run_on"])
                continue
            run_project(p["name"], kw, pr, s, sheet, args)
        except Exception:
            log.exception("[%s] failed", p["name"])
            failures += 1
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
