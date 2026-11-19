"""Build the share package for teammates (Google Drive): one tar per game, usable clips only.

Each tar holds <game>/audio/... (cleaned FLAC at one sample rate), <game>/images/... (art
re-encoded as WebP, long edge capped) and <game>/<game>_{characters,clips}.jsonl with paths
rewritten relative to the package root. A game whose tar would pass --max-gb is split into
_part1, _part2, ... Run it a few games at a time when disk is short. Also written: manifests.tar.gz (all manifests + voice_actors.csv),
embeddings.tar (data/embeddings, from src.embed), README.md and SHA256SUMS. Finished tars are skipped on rerun (a tar is written as .partial first).

    python -m src.package                       # all games, 24 kHz, images ≤1536 px
    python -m src.package --games azurlane wuwa zenless   # one batch
    python -m src.package --games genshin --rate 16 --max-side 1024
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import logging
import tarfile
from datetime import date
from multiprocessing import Pool
from pathlib import Path

from PIL import Image

from src.common.io import ROOT, read_jsonl
from src.report import load_games

log = logging.getLogger("package")
Image.MAX_IMAGE_PIXELS = None  # our own downloads; some assembled Azur Lane paintings exceed 120 MP
DROP = {"audio_path", "audio_file", "wav16_path", "wav24_path", "audio_url", "exclude", "exclude_reasons"}


def webp(args: tuple[str, int]) -> bytes:
    src, max_side = args
    im = Image.open(ROOT / src)
    im = im.convert("RGBA" if im.mode in ("RGBA", "LA", "P") else "RGB")
    im.thumbnail((max_side, max_side), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "WEBP", quality=90, method=4)
    return buf.getvalue()


def add_bytes(tar: tarfile.TarFile, name: str, data: bytes) -> None:
    info = tarfile.TarInfo(name)
    info.size, info.mtime = len(data), 0
    tar.addfile(info, io.BytesIO(data))


def jsonl(rows: list[dict]) -> bytes:
    return "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows).encode()


class PartWriter:
    """Tar parts of at most max_bytes; names are fixed when the game is done."""

    def __init__(self, out: Path, stem: str, max_bytes: int):
        self.out, self.stem, self.max_bytes, self.parts = out, stem, max_bytes, []
        self.tar, self.size = None, 0

    def _open(self) -> None:
        if self.tar:
            self.tar.close()
        path = self.out / f"{self.stem}_part{len(self.parts) + 1}.tar.partial"
        self.parts.append(path)
        self.tar, self.size = tarfile.open(path, "w", format=tarfile.PAX_FORMAT), 0

    def add(self, name: str, data: bytes) -> None:
        need = len(data) + 1024
        if not self.tar or (self.size + need > self.max_bytes and self.size):
            self._open()
        add_bytes(self.tar, name, data)
        self.size += need

    def close(self) -> list[Path]:
        self.tar.close()
        if len(self.parts) == 1:
            final = [self.out / f"{self.stem}.tar"]
        else:
            final = [p.with_name(p.name.removesuffix(".partial")) for p in self.parts]
        for p, f in zip(self.parts, final):
            p.rename(f)
        return final


def package_game(game: str, chars: list[dict], clips: list[dict], out: Path, rate: int,
                 max_side: int, max_bytes: int, pool: Pool) -> list[Path]:
    stem = f"seeing-voices_{game}"
    done = sorted(out.glob(f"{stem}.tar")) + sorted(out.glob(f"{stem}_part*.tar"))
    if done:
        log.info("%s: already packaged (%s)", game, ", ".join(p.name for p in done))
        return done
    for p in out.glob(f"{stem}_part*.tar.partial"):
        p.unlink()
    w = PartWriter(out, stem, max_bytes)
    key = f"wav{rate}_path"

    usable = [c for c in clips if not c.get("exclude", True)]
    out_clips = []
    for c in usable:
        src = Path(c[key])
        rel = f"{game}/audio/{src.relative_to(f'data/processed/{game}/wav{rate}k')}"
        w.add(rel, (ROOT / src).read_bytes())
        out_clips.append({**{k: v for k, v in c.items() if k not in DROP}, "audio": rel, "sample_rate": rate * 1000})
    log.info("%s: %d clips added", game, len(out_clips))

    images, out_chars, missing = [], [], 0
    for ch in chars:
        imgs = []
        for i in ch["images"]:
            src = i.get("path")
            if not src or not (ROOT / src).exists():
                missing += 1
                continue
            rel = f"{game}/images/{Path(src).relative_to(f'data/raw/{game}/images').with_suffix('.webp')}"
            images.append((src, rel))
            imgs.append({**{k: v for k, v in i.items() if k not in ("path", "file", "assembled_by")}, "image": rel})
        out_chars.append({**ch, "images": imgs})
    for (src, rel), data in zip(images, pool.imap(webp, [(s, max_side) for s, _ in images], chunksize=8)):
        w.add(rel, data)
    log.info("%s: %d images added (%d missing on disk)", game, len(images), missing)

    w.add(f"{game}/{game}_characters.jsonl", jsonl(out_chars))
    w.add(f"{game}/{game}_clips.jsonl", jsonl(out_clips))
    parts = w.close()
    log.info("%s: wrote %s", game, ", ".join(f"{p.name} ({p.stat().st_size / 1e9:.1f} GB)" for p in parts))
    return parts


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 24), b""):
            h.update(block)
    return h.hexdigest()


def run(games: list[str] | None, rate: int, max_side: int, max_gb: float) -> None:
    out = ROOT / "data" / "export" / f"seeing-voices_{rate}k"
    out.mkdir(parents=True, exist_ok=True)
    data = load_games()
    with Pool(4) as pool:
        for game, (chars, clips) in data.items():
            if not games or game in games:
                package_game(game, chars, clips, out, rate, max_side, int(max_gb * 1e9), pool)

    with tarfile.open(out / "manifests.tar.gz", "w:gz") as t:
        for f in sorted((ROOT / "manifests").iterdir()):
            t.add(f, arcname=f"manifests/{f.name}")
        for f in sorted((ROOT / "reports").glob("*.md")):
            t.add(f, arcname=f"reports/{f.name}")
    with tarfile.open(out / "embeddings.tar", "w") as t:
        for f in sorted((ROOT / "data" / "embeddings").glob("*/*.npz")):
            if not f.name.endswith((".partial.npz", ".tmp.npz")):
                t.add(f, arcname=f"embeddings/{f.parent.name}/{f.name}")
    (out / "README.md").write_text(README.format(rate=rate, max_side=max_side, day=date.today()), encoding="utf-8")
    # batches may be uploaded and deleted in between, so keep sums of files no longer here
    sums_path = out / "SHA256SUMS"
    sums = dict(reversed(l.split("  ", 1)) for l in sums_path.read_text().splitlines()) if sums_path.exists() else {}
    tars = sorted(out.glob("*.tar")) + [out / "manifests.tar.gz"]
    for p in tars:
        if p.name not in sums or p.name in ("manifests.tar.gz", "embeddings.tar") or p.stat().st_mtime > sums_path.stat().st_mtime:
            sums[p.name] = sha256(p)
    sums_path.write_text("".join(f"{h}  {n}\n" for n, h in sorted(sums.items())))
    log.info("package at %s: %.1f GB in %d files here", out, sum(p.stat().st_size for p in tars) / 1e9, len(tars))


README = """# Seeing Voices: share package ({day})

Private copy for the 10-423 project team. All audio and art belong to the game publishers:
do not re-share, make the folder public, or upload it anywhere else.

## Files

- `seeing-voices_<game>.tar` (or `_part1.tar`, `_part2.tar`, ... for large games): one game,
  usable clips only. Extract all of them into the same folder:

      for f in seeing-voices_*.tar; do tar -xf "$f"; done
      shasum -a 256 -c SHA256SUMS     # optional integrity check (run before extracting)

- `manifests.tar.gz`: the full pipeline manifests (all clips, including excluded ones with
  `exclude_reasons`), `voice_actors.csv` and the stats reports.
- `embeddings.tar`: precomputed embeddings, extract into the same folder (gives
  `embeddings/<model>/<game>.npz`; read with `src.dataset.load_embeddings`): clip-l14 and
  siglip per image, wavlm-sv per usable clip.

## Layout after extraction

    <game>/<game>_characters.jsonl   one character per line; images[].image is a path
    <game>/<game>_clips.jsonl        one usable clip per line; audio is a path
    <game>/audio/...                 mono FLAC, {rate} kHz, trimmed, -23 LUFS
    <game>/images/...                WebP, long edge at most {max_side} px
    embeddings/<model>/<game>.npz    keys + float16 unit vectors

Join clips to characters on `char_uid`, and characters to voice actors on `cv_uid`
(`manifests/voice_actors.csv`). Field definitions: docs/dataset_report.md in the repo.
"""


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", nargs="*")
    ap.add_argument("--rate", type=int, choices=[16, 24], default=24)
    ap.add_argument("--max-side", type=int, default=1536)
    ap.add_argument("--max-gb", type=float, default=19.0, help="split a game's tar above this size")
    a = ap.parse_args()
    run(a.games, a.rate, a.max_side, a.max_gb)
