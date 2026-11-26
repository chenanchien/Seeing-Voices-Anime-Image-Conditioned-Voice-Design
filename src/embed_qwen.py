"""Per-clip Qwen3-TTS speaker embeddings (the TTS's own x-vector, 2048-d) for M2, which trains
on clips rather than character prototypes. Needs the qwen-tts package and a GPU (run on Delta).

Embeddings keep the native scale (mean L2 norm ~17): the TTS is conditioned on them as is,
and unit-norm vectors broke Oracle synthesis. One file per game under
data/embeddings/qwen-spk/<game>.npz with `keys` (clip_uid) and `emb` (float16, NOT normalized).
Same recipe as Tianxiang's src/extract_qwen_embeddings.py (pinned checkpoint, BF16, one whole
clip at a time, no padding / resampling / trimming / normalization), for every usable clip.

Audio is read from data/processed/<game>/wav24k when the file is there, else straight out of
the share-package tar given by --tars (<dir>/seeing-voices_<game>.tar, member
<game>/audio/<same path below wav24k>): unpacking 178K small files on Delta's Lustre takes hours.

    python -m src.embed_qwen --check                 # reproduce the baseline prototypes first
    python -m src.embed_qwen --games arknights fgo   # then embed every usable clip

--check embeds the five reference clips of every val/test character in the baseline split.json
and compares their mean with speaker_prototypes.npz (cosine and norm ratio per character).
"""
from __future__ import annotations

import argparse
import io
import json
import logging
import tarfile
import time
from pathlib import Path

import numpy as np
import soundfile as sf
import torch

from src.common.io import ROOT
from src.embed import save
from src.report import load_games

log = logging.getLogger("embed_qwen")
OUT = ROOT / "data" / "embeddings" / "qwen-spk"
BASE = ROOT / "data" / "embeddings" / "qwen-speaker-prototypes-10games-raw"
MODEL = "Qwen/Qwen3-TTS-12Hz-1.7B-Base"
REVISION = "dc3a91051aad39bf1f66d58cd89988b3b1084f0b"  # the checkpoint behind the baselines


def load_model(dtype: str):
    from huggingface_hub import snapshot_download
    from qwen_tts import Qwen3TTSModel
    return Qwen3TTSModel.from_pretrained(snapshot_download(MODEL, revision=REVISION), device_map="cuda:0",
                                         dtype=getattr(torch, dtype), attn_implementation="sdpa").model


class Audio:
    """Bytes of a clip's 24 kHz file, from disk or from the game's share-package tar."""

    def __init__(self, tars: Path | None):
        self.tars, self.index = tars, {}

    def _tar(self, game: str) -> dict[str, tuple[Path, int, int]]:
        if game not in self.index:
            self.index[game] = {}
            path = self.tars / f"seeing-voices_{game}.tar" if self.tars else None
            if path and path.exists():
                with tarfile.open(path) as t:
                    self.index[game] = {m.name: (path, m.offset_data, m.size) for m in t if m.isfile()}
                log.info("%s: indexed %d files in %s", game, len(self.index[game]), path.name)
        return self.index[game]

    def get(self, clip: dict) -> str | io.BytesIO | None:
        if (ROOT / clip["wav24_path"]).exists():
            return str(ROOT / clip["wav24_path"])
        game = clip["clip_uid"].split(":", 1)[0]
        rel = Path(clip["wav24_path"]).relative_to(f"data/processed/{game}/wav24k")
        hit = self._tar(game).get(f"{game}/audio/{rel}")
        if not hit:
            return None
        path, off, size = hit
        with open(path, "rb") as f:
            f.seek(off)
            return io.BytesIO(f.read(size))


def embed(model, src: str | io.BytesIO, max_sec: float | None) -> np.ndarray:
    wav, sr = sf.read(src, dtype="float32", always_2d=False, frames=int(max_sec * 24000) if max_sec else -1)
    assert sr == 24000, f"{src}: {sr} Hz"
    if wav.ndim > 1:
        wav = wav.mean(1)
    return model.extract_speaker_embedding(wav, 24000).float().cpu().numpy()


def check(model, audio: Audio, max_sec: float, games: list[str] | None) -> None:
    clips = {c["clip_uid"]: c for _, cs in load_games().values() for c in cs}
    z = np.load(BASE / "speaker_prototypes.npz")
    protos = dict(zip(z["keys"].tolist(), z["emb"]))
    rows = [r for r in json.load(open(BASE / "split.json", encoding="utf-8"))
            if r["part"] in ("val", "test") and (not games or r["game"] in games)]
    srcs = {r["char_uid"]: [audio.get(clips[k]) for k in r["reference_ids"]] for r in rows}
    rows = [r for r in rows if all(s is not None for s in srcs[r["char_uid"]])]
    log.info("check: %d characters with all reference audio", len(rows))
    cos, ratio = [], []
    for i, r in enumerate(rows, 1):
        e = np.mean([embed(model, s, max_sec) for s in srcs[r["char_uid"]]], 0)
        p = protos[r["char_uid"]].astype(np.float32)
        cos.append(float(e @ p / np.linalg.norm(e) / np.linalg.norm(p)))
        ratio.append(float(np.linalg.norm(e) / np.linalg.norm(p)))
        if i % 50 == 0 or i == len(rows):
            log.info("check %d/%d: cosine min %.4f mean %.4f, norm ratio %.3f-%.3f",
                     i, len(rows), min(cos), np.mean(cos), min(ratio), max(ratio))


def run(model, audio: Audio, games: list[str] | None, max_sec: float, save_every: int) -> None:
    for game, (_, clips) in load_games().items():
        out = OUT / f"{game}.npz"
        part = out.with_name(f"{game}.partial.npz")
        if (games and game not in games) or out.exists():
            continue
        todo = sorted((c for c in clips if not c.get("exclude", True)), key=lambda c: c["clip_uid"])
        missing = [c["wav24_path"] for c in todo if audio.get(c) is None]
        if missing:
            miss = OUT / f"{game}.missing.txt"
            miss.parent.mkdir(parents=True, exist_ok=True)
            miss.write_text("\n".join(missing) + "\n")
            log.error("%s: %d clips have no audio (list in %s); skipping game", game, len(missing), miss)
            continue
        keys, embs = [], []
        if part.exists():
            z = np.load(part)
            keys, embs = list(z["keys"]), [z["emb"]]
        done, t0 = set(keys), time.time()
        todo = [c for c in todo if c["clip_uid"] not in done]
        for i, c in enumerate(todo, 1):
            embs.append(embed(model, audio.get(c), max_sec)[None].astype(np.float16))
            keys.append(c["clip_uid"])
            if i % save_every == 0:
                save(part, keys, embs)
                embs = [np.concatenate(embs)]
                log.info("%s: %d/%d clips (%.0f s)", game, len(keys), len(keys) + len(todo) - i, time.time() - t0)
        save(out, keys, embs)
        part.unlink(missing_ok=True)
        log.info("%s: done, %d clips, %.0f s", game, len(keys), time.time() - t0)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", nargs="*")
    ap.add_argument("--check", action="store_true", help="compare with the baseline prototypes and exit")
    ap.add_argument("--max-sec", type=float, help="cut clips to this length (default: whole clip, as the baselines)")
    ap.add_argument("--save-every", type=int, default=2000)
    ap.add_argument("--dtype", default="bfloat16", help="model dtype (bfloat16 / float32)")
    ap.add_argument("--tars", type=Path, help="folder with the share-package tars")
    ap.add_argument("--out", type=Path, default=OUT, help=f"output folder (default {OUT})")
    ap.add_argument("--list-missing", action="store_true", help="only write <game>.missing.txt, no GPU")
    a = ap.parse_args()
    OUT = a.out
    audio = Audio(a.tars)
    if a.list_missing:
        for game, (_, clips) in load_games().items():
            if not a.games or game in a.games:
                miss = [c["wav24_path"] for c in clips if not c.get("exclude", True) and audio.get(c) is None]
                OUT.mkdir(parents=True, exist_ok=True)
                (OUT / f"{game}.missing.txt").write_text("".join(m + "\n" for m in miss))
                log.info("%s: %d usable clips without audio", game, len(miss))
    else:
        m = load_model(a.dtype)
        if a.check:
            check(m, audio, a.max_sec, a.games)
        else:
            run(m, audio, a.games, a.max_sec, a.save_every)
