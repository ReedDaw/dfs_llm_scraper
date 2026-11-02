"""Offline tests: fixture responses shaped like the DataForSEO docs, plus a
full mocked run (no network, no spend). Run: python -m pytest -q"""
import datetime as dt

from pipeline import platforms as P
from pipeline import store
from pipeline.runner import run
from pipeline.scoring import score, summarize

KW = {"query": "cheap glasses", "category": "c", "query_type": "keyword"}
PR = {"query": "best place to buy glasses online?", "category": "c", "query_type": "prompt"}

SERP = {"tasks": [{"id": "s1", "status_code": 20000, "result": [{
    "item_types": ["organic", "ai_overview"],
    "items": [
        {"type": "ai_overview", "markdown": "Acme and RivalOne are popular.",
         "items": [{"type": "ai_overview_element", "text": "x",
                    "references": [{"url": "https://www.acme.com/a", "domain": "www.acme.com", "title": "Z"}]}],
         "references": [{"url": "https://www.acme.com/a", "title": "Z"},
                        {"url": "https://rivalone.com/b", "title": "W"}]},
        {"type": "organic", "rank_group": 1, "url": "https://rivalone.com/", "domain": "rivalone.com", "title": "W"},
        {"type": "organic", "rank_group": 2, "url": "https://www.acme.com/", "domain": "www.acme.com", "title": "Z"},
    ]}]}]}

LLM_RESPONSES = {"id": "c1", "status_code": 20000, "result": [{
    "model_name": "claude-x", "items": [{"type": "message", "sections": [
        {"type": "text", "text": "Try RivalTwo or Acme.",
         "annotations": [{"url": "https://rivaltwo.com/x", "title": "E"}]}]}]}]}

LLM_SCRAPER = {"id": "g1", "status_code": 20000, "result": [{
    "markdown": "RivalThree is a good option.", "model": "gpt-x",
    "sources": [{"url": "https://www.rivalthree.com/", "title": "G", "domain": "rivalthree.com"}],
    "items": [{"type": "chat_gpt_text", "markdown": "RivalThree is a good option."}]}]}

SETTINGS = store.parse_settings({
    "brand_domains": "acme.com", "competitor_domains": "rivalone.com, rivaltwo.com, rivalthree.com",
    "max_wait_minutes": "1", "poll_seconds": "0", "claude_model": "claude-x"})


def test_serp_organic_and_aio():
    out = P.parse_google_serp(KW, SERP)
    org = next(c for a, c in out if a["platform"] == "google_organic")
    aio_a, aio_c = next((a, c) for a, c in out if a["platform"] == "google_aio")
    assert [c["position"] for c in org] == [1, 2]
    assert aio_a["response_text"].startswith("Acme")
    assert [c["domain"] for c in aio_c] == ["acme.com", "rivalone.com"]  # deduped, www stripped


def test_no_aio():
    data = {"tasks": [{"id": "s2", "status_code": 20000, "result": [{"items": [
        {"type": "organic", "rank_group": 1, "url": "https://a.com", "domain": "a.com"}]}]}]}
    statuses = {a["platform"]: a["status"] for a, _ in P.parse_google_serp(KW, data)}
    assert statuses == {"google_organic": "ok", "google_aio": "no_ai_answer"}


def test_llm_parsers():
    (a, c), = P.parse_claude_task(PR, LLM_RESPONSES)
    assert a["model"] == "claude-x" and c[0]["domain"] == "rivaltwo.com"
    (a, c), = P.parse_chatgpt_task(PR, LLM_SCRAPER)
    assert a["model"] == "gpt-x" and c[0]["domain"] == "rivalthree.com"
    (a, c), = P.parse_gemini_task(PR, {"id": "x", "status_code": 40103, "status_message": "failed"})
    assert a["status"] == "error"


def test_scoring():
    ans, cites = [], []
    for a, c in P.parse_google_serp(KW, SERP) + P.parse_claude_task(PR, LLM_RESPONSES):
        ans.append(a); cites += c
    ans, _ = score(ans, cites, SETTINGS)
    aio = next(a for a in ans if a["platform"] == "google_aio")
    assert aio["brand_cited"] and aio["brand_best_position"] == 1 and aio["brand_mentioned"]
    assert aio["competitors_cited"] == "rivalone.com"
    cl = next(a for a in ans if a["platform"] == "claude")
    assert not cl["brand_cited"] and cl["brand_mentioned"]
    assert cl["competitors_mentioned"] == "rivaltwo.com"
    assert {r["platform"] for r in summarize(ans, SETTINGS)} == {"google_organic", "google_aio", "claude"}


def test_schedule():
    mon = dt.date(2026, 11, 2)
    assert store.should_run("weekly:mon", mon) and not store.should_run("weekly:tue", mon)
    assert store.should_run("monthly:2", mon) and not store.should_run("off", mon)


class FakeClient:
    """Async tasks report 'in queue' on the first poll, done on the second."""
    def __init__(self):
        self.cost, self.polls = 0.0, {}

    def post(self, path, tasks):
        if "task_post" in path:
            return {"tasks": [{"id": f"{path}-{t['tag']}", "status_code": 20100, "data": t} for t in tasks]}
        if "organic" in path:
            return SERP
        if "ai_mode" in path:
            return {"tasks": [{"id": "m", "status_code": 20000, "result": [{"items": []}]}]}
        return {"tasks": [LLM_RESPONSES]}  # perplexity live

    def get(self, path):
        n = self.polls[path] = self.polls.get(path, 0) + 1
        if n == 1:
            return {"tasks": [{"id": path, "status_code": 40602}]}
        return {"tasks": [LLM_RESPONSES if "claude" in path else LLM_SCRAPER]}


def test_full_mocked_run():
    ans, cites = run(FakeClient(), SETTINGS, [KW], [PR])
    plats = sorted(a["platform"] for a in ans)
    assert plats == sorted(["google_organic", "google_aio", "google_ai_mode", "perplexity",
                            "chatgpt", "gemini", "claude"])
    assert not [a for a in ans if a["status"] in ("error", "timeout")]


def test_projects_from_secret_and_placeholder(monkeypatch, tmp_path):
    import run_pipeline as R
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("PROJECTS_YAML", raising=False)
    assert R.load_projects() == []                       # nothing configured -> clean no-op
    monkeypatch.setenv("PROJECTS_YAML", "projects:\n  - name: a\n    sheet_id: REPLACE_WITH_SHEET_ID\n  - name: b\n    sheet_id: xyz\n")
    assert [p["name"] for p in R.load_projects()] == ["b"]  # placeholder rows skipped


def test_service_account_json_or_base64(monkeypatch):
    import base64, json
    key = {"type": "service_account", "client_email": "bot@x.iam.gserviceaccount.com"}
    monkeypatch.setenv("GOOGLE_SERVICE_ACCOUNT_JSON", json.dumps(key, indent=2))
    assert store.service_account_info() == key
    monkeypatch.setenv("GOOGLE_SERVICE_ACCOUNT_JSON", base64.b64encode(json.dumps(key).encode()).decode())
    assert store.service_account_info() == key
