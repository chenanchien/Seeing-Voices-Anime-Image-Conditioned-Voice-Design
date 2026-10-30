"""Extract single members from a large zip on Hugging Face with HTTP range requests.

The central directory is read once and cached as an index (name, local header offset,
compressed size, method). Wanted members are sorted by offset and fetched in contiguous
spans of up to SPAN_BYTES, so 20k clips cost a few hundred requests, not 20k. Each clip is
written as 16-bit FLAC via a temp file, and existing files are skipped (resumable).
"""
from __future__ import annotations

import io
import json
import logging
import os
import struct
import time
import zipfile
import zlib
from pathlib import Path

import requests
import soundfile as sf

from src.common.http import DEFAULT_UA
from src.common.io import ROOT

log = logging.getLogger("hf_zip")
SPAN_BYTES = 64 << 20
MAX_GAP = 1 << 20  # merge members into one span when the gap between them is small
HEADER_SLACK = 30 + 2048  # local header + name + extra field (names here are < 200 bytes)


def resolve_url(repo: str, file: str) -> str:
    return f"https://huggingface.co/datasets/{repo}/resolve/main/{file}"


class _RangeReader(io.RawIOBase):
    def __init__(self, sess: requests.Session, url: str, size: int):
        self.sess, self.url, self.size, self.pos = sess, url, size, 0

    def readable(self): return True
    def seekable(self): return True
    def tell(self): return self.pos

    def seek(self, off, whence=0):
        self.pos = {0: off, 1: self.pos + off, 2: self.size + off}[whence]
        return self.pos

    def readinto(self, b):
        if self.pos >= self.size:
            return 0
        end = min(self.size, self.pos + len(b)) - 1
        data = _get_range(self.sess, self.url, self.pos, end)
        b[:len(data)] = data
        self.pos += len(data)
        return len(data)


def _session() -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = DEFAULT_UA
    return s


def _get_range(sess: requests.Session, url: str, start: int, end: int) -> bytes:
    for attempt in range(5):
        try:
            r = sess.get(url, headers={"Range": f"bytes={start}-{end}"}, timeout=120)
            if r.status_code == 206:
                return r.content
            if r.status_code not in (429, 500, 502, 503, 504):
                raise requests.HTTPError(f"{r.status_code} for {url}", response=r)
        except (requests.ConnectionError, requests.Timeout) as e:
            log.warning("range %d-%d: %s", start, end, e)
        time.sleep(30 * (attempt + 1))
    raise RuntimeError(f"giving up on {url} {start}-{end}")


def build_index(repo: str, file: str, dest: Path) -> dict[str, dict]:
    """member name -> {offset, csize, method}; cached as JSON lines at dest."""
    if not dest.exists():
        sess, url = _session(), resolve_url(repo, file)
        size = int(sess.head(url, allow_redirects=True, timeout=60).headers["content-length"])
        z = zipfile.ZipFile(io.BufferedReader(_RangeReader(sess, url, size), buffer_size=1 << 20))
        dest.parent.mkdir(parents=True, exist_ok=True)
        with open(dest.with_suffix(".tmp"), "w", encoding="utf-8") as f:
            for i in z.infolist():
                if not i.is_dir():
                    f.write(json.dumps({"name": i.filename, "offset": i.header_offset,
                                        "csize": i.compress_size, "method": i.compress_type},
                                       ensure_ascii=False) + "\n")
        os.replace(dest.with_suffix(".tmp"), dest)
    index = {}
    with open(dest, encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            index[r["name"]] = r
    return index


def read_members(repo: str, file: str, index: dict[str, dict], names: list[str]) -> dict[str, bytes]:
    """Small helper for text members (e.g. a transcript list)."""
    out, sess, url = {}, _session(), resolve_url(repo, file)
    for n in names:
        e = index[n]
        out[n] = _member_bytes(_get_range(sess, url, e["offset"], e["offset"] + HEADER_SLACK + e["csize"]), 0, e)
    return out


def _member_bytes(buf: bytes, at: int, e: dict) -> bytes:
    if buf[at:at + 4] != b"PK\x03\x04":
        raise ValueError(f"bad local header for {e['name']}")
    name_len, extra_len = struct.unpack("<HH", buf[at + 26:at + 30])
    start = at + 30 + name_len + extra_len
    data = buf[start:start + e["csize"]]
    if e["method"] == zipfile.ZIP_STORED:
        return data
    if e["method"] == zipfile.ZIP_DEFLATED:
        return zlib.decompress(data, -15)
    raise ValueError(f"unsupported compression {e['method']} for {e['name']}")


def extract(repo: str, file: str, index: dict[str, dict], wanted: list[tuple[str, str]]) -> dict[str, int]:
    """wanted: [(member name, dest path relative to ROOT)]. Audio is re-encoded to FLAC."""
    stats = {"ok": 0, "skipped": 0, "failed": 0}
    todo = []
    for name, path in wanted:
        if (ROOT / path).exists():
            stats["skipped"] += 1
        elif name not in index:
            stats["failed"] += 1
        else:
            todo.append((index[name], path))
    todo.sort(key=lambda t: t[0]["offset"])
    spans: list[list] = []
    for e, path in todo:  # member end is estimated: the local header adds name + extra bytes
        end = e["offset"] + HEADER_SLACK + e["csize"]
        if spans and e["offset"] - spans[-1][1] <= MAX_GAP and end - spans[-1][0] <= SPAN_BYTES:
            spans[-1][1] = max(spans[-1][1], end)
            spans[-1][2].append((e, path))
        else:
            spans.append([e["offset"], end, [(e, path)]])
    sess, url = _session(), resolve_url(repo, file)
    for k, (start, end, items) in enumerate(spans, 1):
        buf = _get_range(sess, url, start, end - 1)
        for e, path in items:
            try:
                raw = _member_bytes(buf, e["offset"] - start, e)
                y, sr = sf.read(io.BytesIO(raw), dtype="int16")
                dest = ROOT / path
                dest.parent.mkdir(parents=True, exist_ok=True)
                tmp = dest.with_suffix(".part.flac")
                sf.write(tmp, y, sr, format="FLAC", subtype="PCM_16")
                os.replace(tmp, dest)
                stats["ok"] += 1
            except Exception as ex:  # corrupt member: record and continue
                log.warning("%s: %s", e["name"], ex)
                stats["failed"] += 1
        log.info("%s span %d/%d: %s", file, k, len(spans), stats)
    return stats
