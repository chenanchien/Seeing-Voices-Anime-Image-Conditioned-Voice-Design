"""Shared helpers for Hugging Face parquet voice dumps (ultemica/*-voices, ja config).

Shards are sorted by speaker, so we first index the text columns of every shard (HTTP range
reads, no audio bytes), then download only the shards that contain wanted speakers and
extract their audio to FLAC.
"""
from __future__ import annotations

import io
import logging
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import soundfile as sf
from huggingface_hub import HfFileSystem

from src.common.io import ROOT

log = logging.getLogger("hf_voices")
META_COLS = ["transcription", "speaker", "source_path"]


def shard_files(repo: str, config: str = "ja") -> list[str]:
    return sorted(HfFileSystem().glob(f"datasets/{repo}/data/{config}/*.parquet"))


def build_index(repo: str, dest: Path) -> pa.Table:
    """One row per clip: shard, row, speaker, transcription, source_path. Cached as parquet."""
    if dest.exists():
        return pq.read_table(dest)
    fs = HfFileSystem()
    parts = []
    for i, path in enumerate(shard_files(repo)):
        with fs.open(path, "rb") as f:
            t = pq.ParquetFile(f).read(columns=META_COLS)
        name = path.rsplit("/", 1)[1]
        parts.append(t.append_column("shard", pa.array([name] * len(t)))
                      .append_column("row", pa.array(range(len(t)), pa.int32())))
        if i % 20 == 0:
            log.info("%s: indexed %d shards", repo, i + 1)
    table = pa.concat_tables(parts)
    dest.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, dest)
    return table


def extract(repo: str, wanted: dict[str, list[tuple[int, str]]]) -> dict[str, int]:
    """wanted: shard name -> [(row, audio_path)]. Writes each clip as FLAC (lossless), skipping
    files that already exist, one shard in memory at a time."""
    fs = HfFileSystem()
    stats = {"ok": 0, "skipped": 0, "failed": 0}
    for shard, items in sorted(wanted.items()):
        todo = [(r, p) for r, p in items if not (ROOT / p).exists()]
        stats["skipped"] += len(items) - len(todo)
        if not todo:
            continue
        with fs.open(f"datasets/{repo}/data/ja/{shard}", "rb") as f:
            audio = pq.ParquetFile(f).read(columns=["audio"]).column("audio")
        for row, path in todo:
            try:
                y, sr = sf.read(io.BytesIO(audio[row].as_py()["bytes"]), dtype="int16")
                (ROOT / path).parent.mkdir(parents=True, exist_ok=True)
                sf.write(ROOT / path, y, sr, format="FLAC", subtype="PCM_16")
                stats["ok"] += 1
            except Exception as e:  # corrupt clip: record and continue
                log.warning("%s row %d: %s", shard, row, e)
                stats["failed"] += 1
        log.info("%s: %s", shard, stats)
    return stats
