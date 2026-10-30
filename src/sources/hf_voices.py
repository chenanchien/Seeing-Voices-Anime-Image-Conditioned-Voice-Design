"""Shared helpers for Hugging Face parquet voice dumps (ultemica/*-voices, ja config).

Shards are sorted by speaker, so we first index the text columns of every shard (HTTP range
reads, no audio bytes), then download only the shards that contain wanted speakers and
extract their audio to FLAC.
"""
from __future__ import annotations

import io
import logging
import os
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


def extract_row_groups(repo: str, wanted: dict[str, list[tuple[int, str]]]) -> dict[str, int]:
    """wanted: shard path inside the repo -> [(row, audio_path)]. For dumps whose shards mix
    languages (simon3000/*-voice): reads only the audio column of the row groups that hold
    wanted rows, so a few clips never cost a whole multi-GB shard."""
    fs = HfFileSystem()
    stats = {"ok": 0, "skipped": 0, "failed": 0}
    for shard, items in sorted(wanted.items()):
        todo = sorted((r, p) for r, p in items if not (ROOT / p).exists())
        stats["skipped"] += len(items) - len(todo)
        if not todo:
            continue
        with fs.open(f"datasets/{repo}/{shard}", "rb") as f:
            pf = pq.ParquetFile(f)
            starts, n = [], 0
            for g in range(pf.metadata.num_row_groups):
                starts.append(n)
                n += pf.metadata.row_group(g).num_rows
            by_group: dict[int, list[tuple[int, str]]] = {}
            for row, path in todo:
                g = max(i for i, s in enumerate(starts) if s <= row)
                by_group.setdefault(g, []).append((row - starts[g], path))
            for g, rows in sorted(by_group.items()):
                audio = pf.read_row_group(g, columns=["audio"]).column("audio")
                for row, path in rows:
                    try:
                        y, sr = sf.read(io.BytesIO(audio[row].as_py()["bytes"]), dtype="int16")
                        dest = ROOT / path
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        tmp = dest.with_suffix(".part.flac")
                        sf.write(tmp, y, sr, format="FLAC", subtype="PCM_16")
                        os.replace(tmp, dest)
                        stats["ok"] += 1
                    except Exception as e:  # corrupt clip: record and continue
                        log.warning("%s row group %d row %d: %s", shard, g, row, e)
                        stats["failed"] += 1
        log.info("%s: %s", shard, stats)
    return stats


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
                dest = ROOT / path
                dest.parent.mkdir(parents=True, exist_ok=True)
                tmp = dest.with_suffix(".part.flac")  # never leave a half-written file at dest
                sf.write(tmp, y, sr, format="FLAC", subtype="PCM_16")
                os.replace(tmp, dest)
                stats["ok"] += 1
            except Exception as e:  # corrupt clip: record and continue
                log.warning("%s row %d: %s", shard, row, e)
                stats["failed"] += 1
        log.info("%s: %s", shard, stats)
    return stats
