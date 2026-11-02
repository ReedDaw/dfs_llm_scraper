"""One adapter per surface. Each turns a query into a DataForSEO task and
parses the response into the shared shape:

    answer   = one row per query x platform (text, status, model)
    citation = one row per cited / ranking URL

Endpoint and field names verified against docs.dataforseo.com (Oct 2026).
"""
from urllib.parse import urlparse

from .client import PENDING_CODES


# ---------- shared helpers ----------

def domain_of(url):
    try:
        return urlparse(url or "").netloc.lower().removeprefix("www.")
    except ValueError:
        return ""


def _answer(platform, q, task_id="", status="ok", text="", model="", note=""):
    return {
        "platform": platform,
        "query_type": q["query_type"],
        "query": q["query"],
        "category": q.get("category", ""),
        "model": model or "",
        "status": status,
        "note": note,
        "response_text": (text or "").strip(),
        "task_id": task_id,
    }


def _cites(platform, q, refs):
    """refs: list of dicts with url/title/domain(optional)/position(optional)."""
    out, seen = [], set()
    for ref in refs:
        url = (ref.get("url") or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        out.append({
            "platform": platform,
            "query_type": q["query_type"],
            "query": q["query"],
            "category": q.get("category", ""),
            "position": ref.get("position") or len(out) + 1,
            "url": url,
            "title": ref.get("title") or "",
            "domain": (ref.get("domain") or domain_of(url)).removeprefix("www."),
            "source_type": ref.get("source_type", "citation"),
        })
    return out


def _walk(obj, key):
    """Yield every value stored under `key` anywhere inside obj."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == key:
                yield v
            yield from _walk(v, key)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk(v, key)


def _error(platform, q, task):
    return [(_answer(platform, q, task.get("id", ""), "error",
                     note=f"{task.get('status_code')} {task.get('status_message', '')}"), [])]


# ---------- Google: organic + AI Overview, and AI Mode ----------

def _parse_ai_overview(platform, q, task_id, items):
    aio = [i for i in items if i.get("type") == "ai_overview"]
    if not aio:
        return [(_answer(platform, q, task_id, "no_ai_answer"), [])]
    out = []
    for block in aio:
        text = block.get("markdown") or "\n".join(
            t for t in _walk(block.get("items") or [], "text") if isinstance(t, str))
        refs = [r for lst in _walk(block, "references") if isinstance(lst, list)
                for r in lst if isinstance(r, dict)]
        out.append((_answer(platform, q, task_id, text=text), _cites(platform, q, refs)))
    return out


def build_google_serp(q, s):
    return {
        "keyword": q["query"], "location_code": s["location_code"],
        "language_code": s["language_code"], "device": s["device"],
        "depth": s["serp_depth"],
        # Without this, async AI Overviews come back as null (~$0.0006 extra, refunded if cached).
        "load_async_ai_overview": True,
    }


def parse_google_serp(q, data):
    out = []
    for task in data.get("tasks") or []:
        tid = task.get("id", "")
        if task.get("status_code") != 20000:
            out += _error("google_organic", q, task) + _error("google_aio", q, task)
            continue
        for result in task.get("result") or []:
            items = result.get("items") or []
            organic = [{"url": i.get("url"), "title": i.get("title"), "domain": i.get("domain"),
                        "position": i.get("rank_group"), "source_type": "organic"}
                       for i in items if i.get("type") == "organic"]
            features = sorted(set(result.get("item_types") or []))
            out.append((_answer("google_organic", q, tid, note="features: " + ",".join(features)),
                        _cites("google_organic", q, organic)))
            out += _parse_ai_overview("google_aio", q, tid, items)
    return out


def build_ai_mode(q, s):
    return {"keyword": q["query"], "location_code": s["location_code"],
            "language_code": s["language_code"], "device": s["device"]}


def parse_ai_mode(q, data):
    out = []
    for task in data.get("tasks") or []:
        if task.get("status_code") != 20000:
            out += _error("google_ai_mode", q, task)
            continue
        for result in task.get("result") or []:
            out += _parse_ai_overview("google_ai_mode", q, task.get("id", ""), result.get("items") or [])
    return out


# ---------- LLM Responses API (Perplexity, Claude) ----------

def _parse_llm_responses(platform, q, task):
    if task.get("status_code") != 20000:
        return _error(platform, q, task)
    out = []
    for result in task.get("result") or [{}]:
        texts, refs = [], []
        for item in result.get("items") or []:
            if item.get("type") != "message":
                continue
            for sec in item.get("sections") or []:
                if sec.get("type") != "text":
                    continue
                if sec.get("text"):
                    texts.append(sec["text"])
                refs += sec.get("annotations") or []
        status = "ok" if texts else "empty"
        out.append((_answer(platform, q, task.get("id", ""), status, "\n\n".join(texts),
                            result.get("model_name")), _cites(platform, q, refs)))
    return out


def build_perplexity(q, s):
    t = {"user_prompt": q["query"], "model_name": s["perplexity_model"],
         "max_output_tokens": s["max_output_tokens"]}
    if s.get("country_iso"):
        t["web_search_country_iso_code"] = s["country_iso"]
    return t


def parse_perplexity(q, data):
    return [r for t in data.get("tasks") or [] for r in _parse_llm_responses("perplexity", q, t)]


def build_claude(q, s):
    return {"user_prompt": q["query"], "model_name": s["claude_model"],
            "max_output_tokens": s["max_output_tokens"], "web_search": True,
            "force_web_search": True, "web_search_country_iso_code": s["country_iso"]}


def parse_claude_task(q, task):
    return _parse_llm_responses("claude", q, task)


# ---------- LLM Scraper API (ChatGPT, Gemini) ----------

def _parse_llm_scraper(platform, q, task):
    if task.get("status_code") != 20000:
        return _error(platform, q, task)
    out = []
    for result in task.get("result") or [{}]:
        items = result.get("items") or []
        text = result.get("markdown") or "\n\n".join(
            i.get("markdown") or i.get("text") or "" for i in items)
        sources = result.get("sources")
        if not sources:  # fall back to item-level sources
            sources = [s for lst in _walk(items, "sources") if isinstance(lst, list)
                       for s in lst if isinstance(s, dict)]
        status = "ok" if text.strip() else "empty"
        out.append((_answer(platform, q, task.get("id", ""), status, text, result.get("model") or result.get("model_name")),
                    _cites(platform, q, sources or [])))
    return out


def build_llm_scraper(q, s):
    t = {"keyword": q["query"], "location_code": s["location_code"],
         "language_code": s["language_code"], "priority": s["async_priority"]}
    return t


def build_chatgpt(q, s):
    return {**build_llm_scraper(q, s), "force_web_search": True}


def parse_chatgpt_task(q, task):
    return _parse_llm_scraper("chatgpt", q, task)


def parse_gemini_task(q, task):
    return _parse_llm_scraper("gemini", q, task)


# ---------- registry ----------
# live:  one POST returns the answer.
# async: task_post now, task_get/{id} later (cheaper, slower).

AO = "ai_optimization/"
PLATFORMS = {
    "google_serp": dict(mode="live", input="keywords",
                        path="serp/google/organic/live/advanced",
                        build=build_google_serp, parse=parse_google_serp),
    "google_ai_mode": dict(mode="live", input="prompts",
                           path="serp/google/ai_mode/live/advanced",
                           build=build_ai_mode, parse=parse_ai_mode),
    "perplexity": dict(mode="live", input="prompts",
                       path=AO + "perplexity/llm_responses/live",
                       build=build_perplexity, parse=parse_perplexity),
    "chatgpt": dict(mode="async", input="prompts",
                    post=AO + "chat_gpt/llm_scraper/task_post",
                    get=AO + "chat_gpt/llm_scraper/task_get/advanced/{id}",
                    build=build_chatgpt, parse_task=parse_chatgpt_task),
    "gemini": dict(mode="async", input="prompts",
                   post=AO + "gemini/llm_scraper/task_post",
                   get=AO + "gemini/llm_scraper/task_get/advanced/{id}",
                   build=build_llm_scraper, parse_task=parse_gemini_task),
    "claude": dict(mode="async", input="prompts",
                   post=AO + "claude/llm_responses/task_post",
                   get=AO + "claude/llm_responses/task_get/{id}",
                   build=build_claude, parse_task=parse_claude_task,
                   models=AO + "claude/llm_responses/models"),
}


def is_pending(task):
    return task.get("status_code") in PENDING_CODES
