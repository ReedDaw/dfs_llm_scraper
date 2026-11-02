"""Thin DataForSEO v3 client: auth, retries, cost tracking."""
import logging
import os
import threading
import time

import requests

API_ROOT = "https://api.dataforseo.com/v3/"

# Task-level codes meaning "not finished yet" (DataForSEO errors appendix:
# 40601 Task Handed, 40602 Task in Queue).
PENDING_CODES = {40601, 40602}
RETRY_HTTP = {429, 500, 502, 503, 504}

log = logging.getLogger(__name__)


class DFSError(RuntimeError):
    pass


class DFSClient:
    def __init__(self, login=None, password=None, timeout=180, max_retries=4, root=API_ROOT):
        login = login or os.getenv("DFS_LOGIN")
        password = password or os.getenv("DFS_PASSWORD")
        if not login or not password:
            raise SystemExit("Set DFS_LOGIN and DFS_PASSWORD environment variables.")
        self.session = requests.Session()
        self.session.auth = (login, password)
        self.timeout = timeout
        self.max_retries = max_retries
        self.root = root
        self.cost = 0.0
        self._lock = threading.Lock()

    def _call(self, method, path, payload=None):
        url = self.root + path.lstrip("/")
        for attempt in range(1, self.max_retries + 1):
            try:
                r = self.session.request(method, url, json=payload, timeout=(10, self.timeout))
                if r.status_code in RETRY_HTTP:
                    raise requests.HTTPError(f"HTTP {r.status_code}", response=r)
                r.raise_for_status()
                data = r.json()
            except (requests.ConnectionError, requests.Timeout, requests.HTTPError) as e:
                if attempt == self.max_retries:
                    raise
                wait = 2 ** attempt
                log.warning("%s %s failed (%s); retry in %ss", method, path, e, wait)
                time.sleep(wait)
                continue

            code = data.get("status_code")
            if code == 20000:
                with self._lock:
                    self.cost += float(data.get("cost") or 0)
                return data
            # 5xxxx = DataForSEO internal error; worth a retry.
            if code and code >= 50000 and attempt < self.max_retries:
                time.sleep(2 ** attempt)
                continue
            raise DFSError(f"{path}: {code} {data.get('status_message')}")

    def post(self, path, tasks):
        return self._call("POST", path, tasks)

    def get(self, path):
        return self._call("GET", path)
