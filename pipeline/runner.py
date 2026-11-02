"""Runs every enabled platform for one project: async posts first, live calls
while those process, then polls the async tasks until done or out of time."""
import logging
import time
from concurrent.futures import ThreadPoolExecutor

from .client import DFSError
from .platforms import PLATFORMS, is_pending, _answer

log = logging.getLogger(__name__)
TASK_CREATED = 20100  # task_post success code (not 20000)


def _resolve_claude_model(client, settings):
    if settings["claude_model"].upper() != "AUTO":
        return settings["claude_model"]
    data = client.get(PLATFORMS["claude"]["models"])
    models = [m for t in data.get("tasks") or [] for m in t.get("result") or []]
    ok = [m for m in models if m.get("task_post_supported") and m.get("web_search_supported")]
    if not ok:
        raise DFSError("No Claude model supports task_post + web_search; set claude_model in Settings.")
    log.info("claude model auto-selected: %s", ok[0]["model_name"])
    return ok[0]["model_name"]


def _post_async(client, name, queries, settings):
    """Returns (pending list of (name, q, task_id), immediate error answers)."""
    spec = PLATFORMS[name]
    pending, failed = [], []
    for start in range(0, len(queries), 100):  # DFS allows 100 tasks per POST
        batch = queries[start:start + 100]
        payload = [{**spec["build"](q, settings), "tag": str(start + i)} for i, q in enumerate(batch)]
        try:
            data = client.post(spec["post"], payload)
        except Exception as e:  # whole batch failed
            failed += [(_answer(name, q, status="error", note=str(e)[:300]), []) for q in batch]
            continue
        for task in data.get("tasks") or []:
            idx = int((task.get("data") or {}).get("tag", -1))
            q = queries[idx] if 0 <= idx < len(queries) else None
            if q is None:
                continue
            if task.get("status_code") == TASK_CREATED:
                pending.append((name, q, task["id"]))
            else:
                failed.append((_answer(name, q, task.get("id", ""), "error",
                                       note=f"{task.get('status_code')} {task.get('status_message')}"), []))
    log.info("%s: %d tasks queued, %d failed to post", name, len(pending), len(failed))
    return pending, failed


def _live_one(client, name, q, settings):
    spec = PLATFORMS[name]
    try:
        data = client.post(spec["path"], [spec["build"](q, settings)])
        return spec["parse"](q, data)
    except Exception as e:
        return [(_answer(name, q, status="error", note=str(e)[:300]), [])]


def _get_one(client, item):
    name, q, tid = item
    spec = PLATFORMS[name]
    try:
        data = client.get(spec["get"].format(id=tid))
    except Exception as e:
        return item, [(_answer(name, q, tid, "error", note=str(e)[:300]), [])]
    task = (data.get("tasks") or [{}])[0]
    if is_pending(task):
        return item, None
    return item, spec["parse_task"](q, task)


def run(client, settings, keywords, prompts):
    inputs = {"keywords": keywords, "prompts": prompts}
    enabled = [p for p in settings["platforms"] if p in PLATFORMS]
    results, pending = [], []
    workers = settings["workers"]

    # 1. queue async tasks first so they process while live calls run
    for name in [p for p in enabled if PLATFORMS[p]["mode"] == "async"]:
        qs = inputs[PLATFORMS[name]["input"]]
        if not qs:
            continue
        if name == "claude":
            try:
                settings = {**settings, "claude_model": _resolve_claude_model(client, settings)}
            except Exception as e:
                log.error("claude skipped: %s", e)
                results += [(_answer("claude", q, status="error", note=str(e)[:300]), []) for q in qs]
                continue
        p, failed = _post_async(client, name, qs, settings)
        pending += p
        results += failed

    # 2. live platforms in parallel
    jobs = [(name, q) for name in enabled if PLATFORMS[name]["mode"] == "live"
            for q in inputs[PLATFORMS[name]["input"]]]
    with ThreadPoolExecutor(workers) as ex:
        for out in ex.map(lambda j: _live_one(client, j[0], j[1], settings), jobs):
            results += out
    log.info("live calls done: %d", len(jobs))

    # 3. poll async until finished or deadline
    deadline = time.time() + settings["max_wait_minutes"] * 60
    while pending and time.time() < deadline:
        still = []
        with ThreadPoolExecutor(workers) as ex:
            for item, out in ex.map(lambda it: _get_one(client, it), pending):
                if out is None:
                    still.append(item)
                else:
                    results += out
        pending = still
        log.info("async: %d still pending", len(pending))
        if pending:
            time.sleep(settings["poll_seconds"])

    for name, q, tid in pending:  # ran out of time; ids kept so they can be collected later
        results.append((_answer(name, q, tid, "timeout", note="still queued at deadline"), []))

    answers = [a for a, _ in results]
    citations = [c for _, cs in results for c in cs]
    return answers, citations
