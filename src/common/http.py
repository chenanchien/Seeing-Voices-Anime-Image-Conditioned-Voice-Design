"""Polite HTTP client: robots.txt check, per-host rate limit, retries with backoff."""
from __future__ import annotations

import logging
import threading
import time
import urllib.robotparser
from urllib.parse import urlsplit

import requests

log = logging.getLogger(__name__)

DEFAULT_UA = "anime-voice-dataset/0.1 (CMU 10-423 course research project; contact: caliber1385@gmail.com)"


class RobotsDisallowed(Exception):
    pass


class PoliteSession:
    """Thread-safe: each host has its own lock and minimum interval between requests."""

    def __init__(self, user_agent: str = DEFAULT_UA, min_interval: float = 1.0,
                 host_intervals: dict[str, float] | None = None, max_retries: int = 5,
                 timeout: float = 60.0):
        self.ua = user_agent
        self.min_interval = min_interval
        self.host_intervals = host_intervals or {}
        self.max_retries = max_retries
        self.timeout = timeout
        self._local = threading.local()
        self._host_locks: dict[str, threading.Lock] = {}
        self._last: dict[str, float] = {}
        self._robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}
        self._meta_lock = threading.Lock()

    @property
    def _session(self) -> requests.Session:
        s = getattr(self._local, "s", None)
        if s is None:
            s = requests.Session()
            s.headers["User-Agent"] = self.ua
            self._local.s = s
        return s

    def _host_lock(self, host: str) -> threading.Lock:
        with self._meta_lock:
            return self._host_locks.setdefault(host, threading.Lock())

    def _wait_turn(self, host: str) -> None:
        interval = max(self.min_interval, self.host_intervals.get(host, 0.0))
        wait = self._last.get(host, 0.0) + interval - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        self._last[host] = time.monotonic()

    def allowed(self, url: str) -> bool:
        parts = urlsplit(url)
        base = f"{parts.scheme}://{parts.netloc}"
        if base not in self._robots:
            rp = urllib.robotparser.RobotFileParser()
            with self._host_lock(parts.netloc):
                self._wait_turn(parts.netloc)
                try:
                    r = self._session.get(base + "/robots.txt", timeout=self.timeout)
                    if r.status_code == 200 and "text/plain" in r.headers.get("content-type", "text/plain"):
                        rp.parse(r.text.splitlines())
                    else:
                        rp = None  # no robots.txt -> everything allowed
                except requests.RequestException:
                    rp = None
            self._robots[base] = rp
        rp = self._robots[base]
        return True if rp is None else rp.can_fetch(self.ua, url)

    def get(self, url: str, *, params: dict | None = None, stream: bool = False) -> requests.Response:
        if not self.allowed(url):
            raise RobotsDisallowed(url)
        host = urlsplit(url).netloc
        for attempt in range(self.max_retries):
            with self._host_lock(host):
                self._wait_turn(host)
                try:
                    r = self._session.get(url, params=params, stream=stream, timeout=self.timeout)
                except requests.RequestException as e:
                    err: Exception | None = e
                    r = None
                else:
                    err = None
            if r is not None and r.status_code < 400:
                return r
            if r is not None and r.status_code in (403, 404, 410):
                r.raise_for_status()  # permanent; don't hammer
            if r is not None and r.status_code in (429, 503):
                retry_after = r.headers.get("Retry-After", "")
                delay = float(retry_after) if retry_after.isdigit() else 30.0 * (attempt + 1)
            else:
                delay = 2.0 ** attempt * 2
            log.warning("GET %s failed (%s), retry in %.0fs", url, err or r.status_code, delay)
            time.sleep(delay)
        raise RuntimeError(f"giving up on {url}")
