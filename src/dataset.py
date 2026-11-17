"""Load characters and clips by split. The splits are the fixed files in splits/ (built by
src.splits); everything here only filters and samples within them.

`root` is either the extracted share package (all seeing-voices_<game>.tar unpacked into one
folder) or this repo (manifests/ plus data/processed, used by the data maintainer).

    from src.dataset import load_split, load_clips

    train = load_split("train", root="~/seeing-voices")            # main split, all of train
    small = load_split("train", root=..., train_frac=0.25)          # data-size experiment
    test = load_split("test", root=..., split="actor_disjoint")
    clips = load_clips(train, root=..., max_per_char=50, exclude_categories=["battle"])

Each character dict is its manifest record plus split, group_id, cv_uids (list), multi_voice
(several CVs, e.g. Gray + Add; train only, no single voice prototype), actor_seen
(main val/test only), train_frac (main train only), and images[].image_path (absolute).
Each clip dict is its manifest record plus audio_path (absolute).
"""
from __future__ import annotations

import csv
import json
import random
from functools import lru_cache
from pathlib import Path

SPLITS = Path(__file__).resolve().parents[1] / "splits"


def _jsonl(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _is_repo(root: Path) -> bool:
    return (root / "manifests").is_dir()


@lru_cache(maxsize=None)
def _characters(root: Path, game: str) -> dict[str, dict]:
    if _is_repo(root):
        chars = _jsonl(root / "manifests" / f"{game}_characters.jsonl")
        for c in chars:
            c["images"] = [{**i, "image_path": str(root / i["path"])} for i in c["images"]
                           if i.get("path") and (root / i["path"]).exists()]
    else:
        chars = _jsonl(root / game / f"{game}_characters.jsonl")
        for c in chars:
            c["images"] = [{**i, "image_path": str(root / i["image"])} for i in c["images"]]
    return {c["char_uid"]: c for c in chars}


@lru_cache(maxsize=None)
def _clips(root: Path, game: str, rate: int) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    if _is_repo(root):
        for c in _jsonl(root / "manifests" / f"{game}_clips.jsonl"):
            if not c.get("exclude", True):
                out.setdefault(c["char_uid"], []).append({**c, "audio_path": str(root / c[f"wav{rate}_path"])})
    else:
        for c in _jsonl(root / game / f"{game}_clips.jsonl"):
            out.setdefault(c["char_uid"], []).append({**c, "audio_path": str(root / c["audio"])})
    return out


def split_table(split: str = "main") -> list[dict]:
    """Rows of splits/<split>.csv."""
    with open(SPLITS / f"{split}.csv", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_split(part: str, root: str | Path, split: str = "main", train_frac: float = 1.0,
               games: list[str] | None = None, genders: list[str] | None = None,
               drop_text_overlay: bool = False) -> list[dict]:
    """Characters of one part ("train" / "val" / "test") of a fixed split.

    train_frac (main/train only): 0.25 or 0.5 gives the nested subset for the data-size
    experiment. drop_text_overlay removes promo art with text on it (Blue Archive cards and
    banners); a character left with no image is dropped.
    """
    root = Path(root).expanduser().resolve()
    out = []
    for row in split_table(split):
        if row["split"] != part or (games and row["game"] not in games) or (genders and row["gender"] not in genders):
            continue
        if part == "train" and row.get("train_frac") and float(row["train_frac"]) > train_frac:
            continue
        c = dict(_characters(root, row["game"])[row["char_uid"]])
        if drop_text_overlay:
            c["images"] = [i for i in c["images"] if not i.get("has_text_overlay")]
            if not c["images"]:
                continue
        c.update(split=part, group_id=row["group_id"], cv_uids=row["cv_uids"].split("|") if row["cv_uids"] else [],
                 multi_voice=row.get("multi_voice") == "True", actor_seen=row.get("actor_seen") or None,
                 train_frac=float(row["train_frac"]) if row.get("train_frac") else None)
        out.append(c)
    return out


def load_clips(chars: list[dict], root: str | Path, max_per_char: int | None = None,
               categories: list[str] | None = None, exclude_categories: list[str] | None = None,
               rate: int = 24, seed: int = 0) -> list[dict]:
    """Usable clips of the given characters. categories / exclude_categories filter on
    category_norm (daily, battle, bond, system, other); max_per_char samples that many per
    character, the same ones for the same seed. rate (16 or 24) applies to the repo layout
    only; the share package holds one rate."""
    root = Path(root).expanduser().resolve()
    out = []
    for ch in chars:
        cs = [c for c in _clips(root, ch["game"], rate).get(ch["char_uid"], [])
              if (not categories or c["category_norm"] in categories)
              and (not exclude_categories or c["category_norm"] not in exclude_categories)]
        if max_per_char is not None and len(cs) > max_per_char:
            cs = random.Random(f"{seed}:{ch['char_uid']}").sample(cs, max_per_char)
        out += cs
    return out
