"""Shared resumable downloader.

Reads the per-game manifests, collects every (url, path, sha1?) item, and fetches the
missing ones. Hosts are processed in parallel (one worker per host), but each host is
rate-limited by PoliteSession. Existing files with a matching checksum are skipped, so
the run can be interrupted and restarted at any time.

    python -m src.download fgo [--limit-chars 3] [--only audio|image]
"""
from __future__ import annotations

import argparse
import logging
import os
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit

from src.common.http import PoliteSession, RobotsDisallowed
from src.common.io import ROOT, file_hash, load_config, read_jsonl
from src.sources import hf_zip
from src.sources.hf_voices import extract as hf_extract

log = logging.getLogger("download")

STREAM_ATTEMPTS = 3        # a read timeout mid-body retries that file
OUTAGE_STREAK = 10         # this many failures in a row = network probably down
OUTAGE_PAUSE_SEC = 300
RETRY_PASSES = 2           # extra passes over failed items at the end


def collect_items(game: str, limit_chars: int | None, only: str | None) -> list[dict]:
    chars = list(read_jsonl(ROOT / "manifests" / f"{game}_characters.jsonl"))
    if limit_chars:
        chars = chars[:limit_chars]
    keep = {c["char_uid"] for c in chars}
    items = []
    if only in (None, "image"):
        for c in chars:
            for img in c["images"]:
                if img.get("assembled_by"):  # built from several source files by its own step
                    continue
                items.append({"url": img["source_url"], "path": img["path"], "sha1": None})
    if only in (None, "audio"):
        for clip in read_jsonl(ROOT / "manifests" / f"{game}_clips.jsonl"):
            if clip["char_uid"] in keep and clip.get("audio_url"):
                items.append({"url": clip["audio_url"], "path": clip["audio_path"],
                              "sha1": clip.get("source_sha1")})
    seen, uniq = set(), []
    for it in items:
        if it["path"] not in seen:
            seen.add(it["path"])
            uniq.append(it)
    return uniq


def fetch_one(sess: PoliteSession, item: dict) -> str:
    dest = ROOT / item["path"]
    if dest.exists() and dest.stat().st_size > 0:
        if not item["sha1"] or file_hash(dest) == item["sha1"]:
            return "skipped"
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    for attempt in range(STREAM_ATTEMPTS):
        try:
            r = sess.get(item["url"], stream=True)
            with open(tmp, "wb") as f:
                for chunk in r.iter_content(1 << 16):
                    f.write(chunk)
            break
        except RobotsDisallowed:
            return "robots"
        except Exception as e:  # 404, timeouts, dropped connections: recorded, never fatal
            tmp.unlink(missing_ok=True)
            status = getattr(getattr(e, "response", None), "status_code", None)
            if status in (403, 404, 410) or attempt == STREAM_ATTEMPTS - 1:
                log.warning("failed %s: %s", item["url"], e)
                return "missing" if status in (404, 410) else "failed"
            time.sleep(30 * (attempt + 1))
    if item["sha1"] and file_hash(tmp) != item["sha1"]:
        log.warning("checksum mismatch %s", item["url"])
        tmp.unlink()
        return "bad_checksum"
    os.replace(tmp, dest)
    return "ok"


def run(game: str, limit_chars: int | None = None, only: str | None = None) -> dict:
    cfg = load_config(game)
    sess = PoliteSession(min_interval=cfg.get("rate_limit_sec", 1.0),
                         host_intervals=cfg.get("host_rate_limit_sec", {}))
    by_host: dict[str, list[dict]] = defaultdict(list)
    hf: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))  # repo -> shard -> rows
    hfzip: dict[tuple, list] = defaultdict(list)  # (repo, zip file) -> [(member, path)]
    for it in collect_items(game, limit_chars, only):
        if it["url"].startswith("hfzip://"):  # hfzip://<owner>/<repo>/<file.zip>#<member>
            repo_file, member = it["url"][8:].split("#", 1)
            repo, file = repo_file.rsplit("/", 1)
            hfzip[(repo, file)].append((member, it["path"]))
        elif it["url"].startswith("hf://"):  # hf://<owner>/<repo>/<shard>#<row>
            repo_shard, row = it["url"][5:].split("#")
            repo, shard = repo_shard.rsplit("/", 1)
            hf[repo][shard].append((int(row), it["path"]))
        else:
            by_host[urlsplit(it["url"]).netloc].append(it)
    for repo, wanted in hf.items():
        log.info("extracting from %s: %d shards", repo, len(wanted))
        log.info("hf done: %s", hf_extract(repo, wanted))
    for (repo, file), wanted in hfzip.items():
        index = hf_zip.build_index(repo, file, ROOT / "data" / "raw" / game / f"{file}.index.jsonl")
        log.info("extracting %d members from %s/%s", len(wanted), repo, file)
        log.info("hfzip done: %s", hf_zip.extract(repo, file, index, wanted))

    def worker(host: str) -> dict:
        stats: dict[str, int] = defaultdict(int)
        items = by_host[host]
        for p in range(1 + RETRY_PASSES):
            failed, streak = [], 0
            for i, it in enumerate(items, 1):
                res = fetch_one(sess, it)
                if res == "failed":
                    failed.append(it)
                    streak += 1
                    if streak >= OUTAGE_STREAK:  # likely offline (e.g. the Mac slept): wait, don't burn items
                        log.warning("%s: %d failures in a row, pausing %ds", host, streak, OUTAGE_PAUSE_SEC)
                        time.sleep(OUTAGE_PAUSE_SEC)
                        streak = 0
                else:
                    stats[res] += 1
                    streak = 0
                if i % 200 == 0 or i == len(items):
                    log.info("%s: pass %d %d/%d %s failed=%d", host, p + 1, i, len(items), dict(stats), len(failed))
            if not failed:
                break
            items = failed
            time.sleep(OUTAGE_PAUSE_SEC)
        stats["failed"] = len(failed)
        return dict(stats)

    with ThreadPoolExecutor(max_workers=max(1, len(by_host))) as ex:
        results = dict(zip(by_host, ex.map(worker, by_host)))
    log.info("done: %s", results)
    return results


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("game")
    ap.add_argument("--limit-chars", type=int)
    ap.add_argument("--only", choices=["audio", "image"])
    a = ap.parse_args()
    run(a.game, a.limit_chars, a.only)
