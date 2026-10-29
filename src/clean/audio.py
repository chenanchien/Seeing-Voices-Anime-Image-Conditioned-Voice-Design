"""Audio cleaning: mono, trim head/tail silence, loudness-normalize, write 24 kHz + 16 kHz audio.

Output is 16-bit FLAC (lossless, ~half the size of WAV; soundfile reads it like WAV).

Results are cached in data/processed/<game>/audio_stats.jsonl (one row per clip_uid), so
reruns only process new clips.

    python -m src.clean.audio fgo [--workers 6]
"""
from __future__ import annotations

import argparse
import json
import logging
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pyloudnorm as pyln
import soundfile as sf
import soxr

from src.common.io import ROOT, file_hash, heavy_step, read_jsonl

log = logging.getLogger("clean.audio")

SR_MAIN, SR_SPK = 24000, 16000
TARGET_LUFS = -23.0
PEAK_CEIL_DB = -1.0
TRIM_TOP_DB = 40.0   # frames quieter than (max - 40 dB) count as silence
TRIM_PAD_SEC = 0.05


def trim_silence(y: np.ndarray, sr: int) -> tuple[np.ndarray, float, float]:
    frame = int(sr * 0.01)
    n = len(y) // frame
    if n == 0:
        return y, 0.0, 0.0
    rms = np.sqrt(np.mean(y[: n * frame].reshape(n, frame) ** 2, axis=1) + 1e-12)
    db = 20 * np.log10(rms)
    voiced = np.where(db > db.max() - TRIM_TOP_DB)[0]
    if len(voiced) == 0:
        return y, 0.0, 0.0
    pad = int(TRIM_PAD_SEC * sr)
    start = max(0, voiced[0] * frame - pad)
    end = min(len(y), (voiced[-1] + 1) * frame + pad)
    return y[start:end], start / sr, (len(y) - end) / sr


def normalize(y: np.ndarray, sr: int) -> tuple[np.ndarray, float | None]:
    meter = pyln.Meter(sr)
    loud = None
    if len(y) >= int(0.4 * sr):  # BS.1770 needs at least one 400 ms block
        loud = meter.integrated_loudness(y)
        if np.isfinite(loud):
            y = y * 10 ** ((TARGET_LUFS - loud) / 20)
        else:
            loud = None
    peak = np.max(np.abs(y)) + 1e-12
    ceil = 10 ** (PEAK_CEIL_DB / 20)
    if loud is None or peak > ceil:  # short clips: peak-normalize; long clips: avoid clipping
        y = y * (ceil / peak)
    return y.astype(np.float32), loud


def process(args: tuple[str, str, str, str]) -> dict:
    clip_uid, src, out24, out16 = args
    row = {"clip_uid": clip_uid}
    try:
        y, sr = sf.read(ROOT / src, dtype="float32", always_2d=True)
    except Exception as e:
        return row | {"error": f"decode: {e}"}
    row["orig_sample_rate"], row["orig_channels"] = sr, y.shape[1]
    row["orig_duration_sec"] = round(len(y) / sr, 3)
    row["audio_sha1"] = file_hash(ROOT / src)
    y = y.mean(axis=1)
    if sr != SR_MAIN:
        y = soxr.resample(y, sr, SR_MAIN)
    y, lead, tail = trim_silence(y, SR_MAIN)
    y, loud = normalize(y, SR_MAIN)
    for path, data, rate in ((out24, y, SR_MAIN), (out16, soxr.resample(y, SR_MAIN, SR_SPK), SR_SPK)):
        (ROOT / path).parent.mkdir(parents=True, exist_ok=True)
        sf.write(ROOT / path, data, rate, format="FLAC", subtype="PCM_16")
    return row | {
        "duration_sec": round(len(y) / SR_MAIN, 3), "sample_rate": SR_MAIN,
        "trimmed_lead_sec": round(lead, 3), "trimmed_tail_sec": round(tail, 3),
        "loudness_lufs_orig": None if loud is None else round(loud, 2),
        "wav24_path": out24, "wav16_path": out16,
    }


def stats_path(game: str) -> Path:
    return ROOT / "data" / "processed" / game / "audio_stats.jsonl"


def run(game: str, workers: int = 4) -> None:
    with heavy_step(f"audio {game}"):
        _run(game, workers)


def _run(game: str, workers: int) -> None:
    cache_path = stats_path(game)
    done = {r["clip_uid"] for r in read_jsonl(cache_path) if "error" not in r}
    todo = []
    for clip in read_jsonl(ROOT / "manifests" / f"{game}_clips.jsonl"):
        if clip["clip_uid"] in done or not clip.get("audio_path") or not (ROOT / clip["audio_path"]).exists():
            continue
        stem = clip["clip_uid"].replace(":", "__").replace("/", "_")
        sub = clip["char_uid"].split(":", 1)[1]
        base = f"data/processed/{game}"
        todo.append((clip["clip_uid"], clip["audio_path"],
                     f"{base}/wav24k/{sub}/{stem}.flac", f"{base}/wav16k/{sub}/{stem}.flac"))
    log.info("%s: %d clips to process (%d cached)", game, len(todo), len(done))
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    with open(cache_path, "a", encoding="utf-8") as f, ProcessPoolExecutor(workers) as ex:
        for i, row in enumerate(ex.map(process, todo, chunksize=16), 1):
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            if i % 500 == 0:
                f.flush()
                log.info("%d/%d", i, len(todo))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("game")
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args()
    run(a.game, a.workers)
