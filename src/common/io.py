from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Iterable, Iterator

import yaml

ROOT = Path(__file__).resolve().parents[2]


def load_config(game: str) -> dict:
    with open(ROOT / "configs" / f"{game}.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


@contextlib.contextmanager
def heavy_step(name: str):
    """Machine-wide lock for CPU/GPU-heavy steps (audio cleaning, Whisper). Running several at
    once froze the M1 (watchdog panic, 2026-10-29), so games wait their turn here."""
    lock = ROOT / "data" / ".heavy_step.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    with open(lock, "w") as f:
        logging.getLogger("io").info("%s: waiting for heavy-step lock", name)
        fcntl.flock(f, fcntl.LOCK_EX)
        logging.getLogger("io").info("%s: got heavy-step lock", name)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def read_jsonl(path: str | Path) -> Iterator[dict]:
    path = Path(path)
    if not path.exists():
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:  # last line cut off by a shutdown: that clip is redone
                    continue


def write_jsonl(path: str | Path, rows: Iterable[dict]) -> int:
    """Atomic write so an interrupted run never leaves a truncated manifest."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    n = 0
    with open(tmp, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            n += 1
    os.replace(tmp, path)
    return n


def file_hash(path: str | Path, algo: str = "sha1") -> str:
    h = hashlib.new(algo)
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()
