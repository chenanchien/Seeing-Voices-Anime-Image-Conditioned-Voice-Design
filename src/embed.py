"""Precompute embeddings for every image and every usable clip (needs the `embed` extra:
uv sync --extra embed). One file per game under data/embeddings/<name>/<game>.npz with
`keys` (str) and `emb` (float16, L2-normalized); src.dataset.load_embeddings reads them.

    image keys     <game>/images/<file without extension>   (same in the repo and the package)
    speaker keys   clip_uid

Models (proposal: CLIP vs SigLIP as image encoder f; a verifier that differs from the TTS's own
speaker encoder for SECS / retrieval):

    clip-l14       openai/clip-vit-large-patch14            768-d
    siglip         google/siglip-so400m-patch14-384         1152-d
    wavlm-sv       microsoft/wavlm-base-plus-sv (x-vector)  512-d, 16 kHz input

Images are composited on white and padded to a square before the model's own preprocessing,
so tall full-body art is not center-cropped. MPS (Apple GPU) crashes with torch 2.15 on macOS 14: pass --device cpu there. Clips longer than --max-sec are cut to their
first --max-sec seconds. Finished games are skipped; speaker runs save progress every
--save-every clips and resume from it.

    python -m src.embed image --model clip-l14
    python -m src.embed speaker --model wavlm-sv --games azurlane
"""
from __future__ import annotations

import argparse
import logging
import time
from pathlib import Path

import numpy as np
import soundfile as sf
import torch
from PIL import Image

from src.common.io import ROOT
from src.report import load_games

log = logging.getLogger("embed")
OUT = ROOT / "data" / "embeddings"
Image.MAX_IMAGE_PIXELS = None
MODELS = {
    "clip-l14": "openai/clip-vit-large-patch14",
    "siglip": "google/siglip-so400m-patch14-384",
    "wavlm-sv": "microsoft/wavlm-base-plus-sv",
}


def device(name: str | None = None) -> torch.device:
    if name:
        return torch.device(name)
    if torch.cuda.is_available():
        return torch.device("cuda")
    return torch.device("mps" if torch.backends.mps.is_available() else "cpu")


def image_key(game: str, path: str) -> str:
    return f"{game}/images/{Path(path).relative_to(f'data/raw/{game}/images').with_suffix('')}"


def square_rgb(path: Path) -> Image.Image:
    im = Image.open(path)
    im.draft("RGB", (2048, 2048))  # JPEG: decode at reduced size
    im = im.convert("RGBA")
    if max(im.size) > 2048:
        im.thumbnail((2048, 2048), Image.LANCZOS)
    side = max(im.size)
    canvas = Image.new("RGBA", (side, side), (255, 255, 255, 255))
    canvas.alpha_composite(im, ((side - im.width) // 2, (side - im.height) // 2))
    return canvas.convert("RGB")


def min_length(wav: np.ndarray, n: int = 16000) -> np.ndarray:
    """Repeat clips shorter than 1 s: the x-vector head returns NaN for ~0.2 s inputs."""
    return np.tile(wav, -(-n // len(wav)))[:max(n, len(wav))] if len(wav) < n else wav


def unit(x: torch.Tensor) -> np.ndarray:
    return torch.nn.functional.normalize(x.float(), dim=-1).cpu().numpy().astype(np.float16)


def save(path: Path, keys: list[str], embs: list[np.ndarray]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp.npz")
    np.savez(tmp, keys=np.array(keys), emb=np.concatenate(embs) if embs else np.zeros((0, 0), np.float16))
    tmp.replace(path)


def embed_images(model_name: str, games: list[str] | None, batch: int, dev: torch.device) -> None:
    from transformers import AutoModel, AutoProcessor

    proc = AutoProcessor.from_pretrained(MODELS[model_name])
    model = AutoModel.from_pretrained(MODELS[model_name]).eval().to(dev)
    for game, (chars, _) in load_games().items():
        out = OUT / model_name / f"{game}.npz"
        if (games and game not in games) or out.exists():
            continue
        paths = sorted({i["path"] for c in chars for i in c["images"] if i.get("path") and (ROOT / i["path"]).exists()})
        keys, embs, t0 = [], [], time.time()
        for s in range(0, len(paths), batch):
            chunk = paths[s:s + batch]
            pix = proc(images=[square_rgb(ROOT / p) for p in chunk], return_tensors="pt")["pixel_values"].to(dev)
            with torch.no_grad():
                f = model.get_image_features(pixel_values=pix)
            embs.append(unit(f if isinstance(f, torch.Tensor) else f.pooler_output))
            keys += [image_key(game, p) for p in chunk]
        save(out, keys, embs)
        log.info("%s %s: %d images, %.0f s", model_name, game, len(keys), time.time() - t0)


def embed_speakers(model_name: str, games: list[str] | None, max_sec: float, batch_sec: float, save_every: int,
                   dev: torch.device) -> None:
    from transformers import AutoFeatureExtractor, WavLMForXVector

    fe = AutoFeatureExtractor.from_pretrained(MODELS[model_name])
    model = WavLMForXVector.from_pretrained(MODELS[model_name]).eval().to(dev)
    max_len = int(max_sec * 16000)
    for game, (_, clips) in load_games().items():
        out = OUT / model_name / f"{game}.npz"
        part = out.with_name(f"{game}.partial.npz")
        if (games and game not in games) or out.exists():
            continue
        todo = sorted((c for c in clips if not c.get("exclude", True)), key=lambda c: (min(c["duration_sec"], max_sec), c["clip_uid"]))
        keys, embs = [], []
        if part.exists():
            z = np.load(part)
            keys, embs = list(z["keys"]), [z["emb"]]
        done, t0 = set(keys), time.time()
        todo = [c for c in todo if c["clip_uid"] not in done]
        since = 0
        while todo:
            n, total = 0, 0.0  # batch by total audio length (clips are sorted by duration)
            while n < len(todo) and (n == 0 or total + min(todo[n]["duration_sec"], max_sec) <= batch_sec):
                total += min(todo[n]["duration_sec"], max_sec)
                n += 1
            chunk, todo = todo[:n], todo[n:]
            wavs = [min_length(sf.read(ROOT / c["wav16_path"], dtype="float32", frames=max_len)[0]) for c in chunk]
            inp = fe(wavs, sampling_rate=16000, padding=True, return_attention_mask=True, return_tensors="pt").to(dev)
            with torch.no_grad():
                e = model(**inp).embeddings
            embs.append(unit(e))
            keys += [c["clip_uid"] for c in chunk]
            since += n
            if since >= save_every:
                save(part, keys, embs)
                embs, since = [np.concatenate(embs)], 0
                log.info("%s %s: %d clips (%.0f s)", model_name, game, len(keys), time.time() - t0)
        save(out, keys, embs)
        part.unlink(missing_ok=True)
        log.info("%s %s: done, %d clips, %.0f s", model_name, game, len(keys), time.time() - t0)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("kind", choices=["image", "speaker"])
    ap.add_argument("--model", required=True, choices=list(MODELS))
    ap.add_argument("--games", nargs="*")
    ap.add_argument("--batch", type=int, default=16, help="images per batch")
    ap.add_argument("--max-sec", type=float, default=15.0)
    ap.add_argument("--batch-sec", type=float, default=120.0, help="seconds of audio per batch")
    ap.add_argument("--save-every", type=int, default=5000)
    ap.add_argument("--device", help="cuda / mps / cpu (default: cuda, else mps, else cpu); MPS crashes "
                                     "with torch 2.15 on macOS 14, use cpu there")
    a = ap.parse_args()
    log.info("device %s", device(a.device))
    if a.kind == "image":
        embed_images(a.model, a.games, a.batch, device(a.device))
    else:
        embed_speakers(a.model, a.games, a.max_sec, a.batch_sec, a.save_every, device(a.device))
