"""Inputs (Google Sheet or local CSV folder), settings, and outputs."""
import csv
import datetime as dt
import json
import logging
import os
from pathlib import Path

log = logging.getLogger(__name__)

DEFAULTS = {
    "platforms": "google_serp, google_ai_mode, perplexity, chatgpt, gemini, claude",
    "run_on": "weekly:mon",          # daily | weekly:mon..sun | monthly:1..28
    "location_code": "2840",         # United States
    "language_code": "en",
    "country_iso": "US",
    "device": "desktop",
    "serp_depth": "20",
    "max_output_tokens": "2048",
    "perplexity_model": "sonar",
    "claude_model": "AUTO",
    "async_priority": "1",           # 1 normal, 2 high (costs more, finishes faster)
    "max_wait_minutes": "90",
    "poll_seconds": "60",
    "workers": "8",
    "max_queries": "500",            # safety cap per input list
    "brand_domains": "",
    "brand_terms": "",
    "competitor_domains": "",
    "bigquery_table_prefix": "",     # e.g. myproject.ai_visibility.mybrand_
}
INT_KEYS = {"location_code", "serp_depth", "max_output_tokens", "async_priority",
            "max_wait_minutes", "poll_seconds", "workers", "max_queries"}
LIST_KEYS = {"platforms", "brand_domains", "brand_terms", "competitor_domains"}

ANSWER_FIELDS = ["run_id", "run_date", "project", "platform", "query_type", "query", "category",
                 "status", "model", "n_citations", "brand_cited", "brand_best_position",
                 "brand_mentioned", "competitors_cited", "competitors_mentioned",
                 "note", "task_id", "response_text"]
CITATION_FIELDS = ["run_id", "run_date", "project", "platform", "query_type", "query", "category",
                   "source_type", "position", "url", "title", "domain", "is_brand", "competitor"]


# ---------- settings ----------

def parse_settings(raw):
    s = dict(DEFAULTS)
    s.update({k.strip().lower(): str(v).strip() for k, v in raw.items() if k and str(v).strip()})
    out = {}
    for k, v in s.items():
        if k in INT_KEYS:
            out[k] = int(float(v))
        elif k in LIST_KEYS:
            items = [x.strip().lower() for x in v.replace("\n", ",").split(",") if x.strip()]
            if k.endswith("domains"):
                items = [x.removeprefix("https://").removeprefix("http://").removeprefix("www.").strip("/")
                         for x in items]
            out[k] = items
        else:
            out[k] = v
    return out


def should_run(run_on, today=None):
    today = today or dt.date.today()
    rule = run_on.strip().lower()
    if rule == "daily":
        return True
    if rule.startswith("weekly:"):
        return today.strftime("%a").lower()[:3] == rule.split(":")[1][:3]
    if rule.startswith("monthly:"):
        return today.day == int(rule.split(":")[1])
    if rule in ("off", "paused", "pause"):
        return False
    raise ValueError(f"Unrecognized run_on value: {run_on!r}")


# ---------- inputs ----------

def _truthy(v):
    return str(v).strip().lower() not in ("false", "no", "n", "0", "off", "paused")


def _clean(rows, col, query_type, cap):
    out, seen = [], set()
    for r in rows:
        r = {str(k).strip().lower(): v for k, v in r.items()}
        text = str(r.get(col) or "").strip()
        if not text or not _truthy(r.get("active", "")) or text.lower() in seen:
            continue
        seen.add(text.lower())
        out.append({"query": text, "category": str(r.get("category") or "").strip(),
                    "query_type": query_type})
    if len(out) > cap:
        log.warning("%s capped at %d (max_queries)", query_type, cap)
    return out[:cap]


def _finish(kw_rows, pr_rows, settings_rows):
    norm = [{str(k).strip().lower(): v for k, v in r.items()} for r in settings_rows]
    raw = {str(r.get("setting") or "").strip(): r.get("value", "") for r in norm}
    s = parse_settings(raw)
    return (_clean(kw_rows, "keyword", "keyword", s["max_queries"]),
            _clean(pr_rows, "prompt", "prompt", s["max_queries"]), s)


def load_local(folder):
    def read(name):
        p = Path(folder) / name
        if not p.exists():
            return []
        with open(p, newline="", encoding="utf-8-sig") as f:
            return list(csv.DictReader(f))
    return _finish(read("keywords.csv"), read("prompts.csv"), read("settings.csv"))


def service_account_info():
    """GOOGLE_SERVICE_ACCOUNT_JSON may hold the key file as-is or base64-encoded.
    Base64 is preferred on public repos: GitHub's log redaction can miss
    pieces of multi-line JSON secrets."""
    raw = os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"].strip()
    if not raw.startswith("{"):
        import base64
        raw = base64.b64decode(raw).decode("utf-8")
    return json.loads(raw)


def _gspread_client():
    import gspread
    return gspread.service_account_from_dict(service_account_info())


def load_sheet(sheet_id):
    sh = _gspread_client().open_by_key(sheet_id)
    tab = lambda n: sh.worksheet(n).get_all_records()
    return _finish(tab("Keywords"), tab("Prompts"), tab("Settings")), sh


# ---------- outputs ----------

def stamp(rows, run_id, run_date, project):
    for r in rows:
        r.update(run_id=run_id, run_date=run_date, project=project)
    return rows


def write_csvs(folder, answers, citations, summary):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    for name, rows, fields in (("answers.csv", answers, ANSWER_FIELDS),
                               ("citations.csv", citations, CITATION_FIELDS),
                               ("summary.csv", summary, list(summary[0]) if summary else [])):
        with open(folder / name, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
    log.info("wrote CSVs to %s", folder)


def _upsert_tab(sh, title, header, rows, append=False):
    import gspread
    try:
        ws = sh.worksheet(title)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=title, rows=100, cols=max(len(header), 1))
        ws.append_row(header)
    values = [[_cell(r.get(h, "")) for h in header] for r in rows]
    if append:
        ws.append_rows(values, value_input_option="USER_ENTERED")
    else:
        ws.clear()
        ws.update([header] + values, value_input_option="USER_ENTERED")


def _cell(v):
    v = "" if v is None else v
    return v[:2000] if isinstance(v, str) else v  # keep Sheets responsive


def write_sheet(sh, run_log, answers, summary):
    _upsert_tab(sh, "Latest Summary", list(summary[0]) if summary else ["platform"], summary)
    _upsert_tab(sh, "Latest Answers", ANSWER_FIELDS, answers)
    _upsert_tab(sh, "Run Log", list(run_log), [run_log], append=True)


def write_bigquery(prefix, answers, citations):
    from google.cloud import bigquery
    from google.oauth2 import service_account
    creds = service_account.Credentials.from_service_account_info(service_account_info())
    client = bigquery.Client(credentials=creds, project=prefix.split(".")[0])
    for suffix, rows, fields in (("answers", answers, ANSWER_FIELDS),
                                 ("citations", citations, CITATION_FIELDS)):
        if not rows:
            continue
        schema = [bigquery.SchemaField(f, "STRING") for f in fields]
        cfg = bigquery.LoadJobConfig(schema=schema, write_disposition="WRITE_APPEND",
                                     create_disposition="CREATE_IF_NEEDED")
        data = [{f: ("" if r.get(f) is None else str(r.get(f))) for f in fields} for r in rows]
        client.load_table_from_json(data, prefix + suffix, job_config=cfg).result()
        log.info("BigQuery: %d rows -> %s%s", len(rows), prefix, suffix)
