"""Uma Musume adapter: HF client dump (Plachta/Umamusume-voice-text-pairs) for audio and
official line text, GameTora for char_id -> name / CV, umamusume.jp for profile text and art.

Only character system voices (character_system_text/) are used; story audio is skipped.
Audio stays inside the 11 GB zip until src.download extracts single members (hfzip://).

    python -m src.sources.umamusume                  # all characters
    python -m src.sources.umamusume --ids 1001 1007  # pilot
"""
from __future__ import annotations

import argparse
import json
import logging
import re
from collections import defaultdict
from pathlib import Path

from src.common.http import PoliteSession
from src.common.io import ROOT, load_config, write_jsonl
from src.sources import hf_zip

log = logging.getLogger("umamusume")
GAME = "umamusume"
RAW = Path("data/raw/umamusume")
DEVALUE_WRAPPERS = ("Reactive", "ShallowReactive", "Ref", "ShallowRef", "EmptyRef")


def unflatten(a: list):
    """Decode a Nuxt payload (devalue flat-array format)."""
    memo: dict[int, object] = {}

    def h(i):
        if i < 0:
            return None
        if i in memo:
            return memo[i]
        v = a[i]
        if isinstance(v, list):
            r = h(v[1]) if v and v[0] in DEVALUE_WRAPPERS else [h(x) for x in v]
        elif isinstance(v, dict):
            r = {k: h(x) for k, x in v.items()}
        else:
            r = v
        memo[i] = r
        return r
    return h(0)


def cached(sess: PoliteSession, url: str, dest: Path) -> bytes:
    dest = ROOT / dest
    if not dest.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(sess.get(url).content)
    return dest.read_bytes()


def gametora_chars(sess: PoliteSession, cfg: dict) -> dict[int, dict]:
    gt = cfg["gametora"]
    manifest = json.loads(cached(sess, gt["manifest"], RAW / "gametora" / "manifest.json"))
    url = gt["data"].format(key="characters", hash=manifest["characters"])
    return {c["char_id"]: c for c in json.loads(cached(sess, url, RAW / "gametora" / "characters.json"))}


def official_pages(sess: PoliteSession, cfg: dict) -> dict[str, dict]:
    """name_ja -> official character record (with 'slug')."""
    off = cfg["official"]
    html = cached(sess, off["list"], RAW / "official" / "list.html").decode("utf-8")
    slugs = sorted(set(re.findall(r'href="/character/([a-z0-9]+)"', html)))
    pages = {}
    for slug in slugs:
        data = unflatten(json.loads(cached(sess, off["payload"].format(slug=slug),
                                           RAW / "official" / f"{slug}.json")))["data"]
        rec = next((v for v in data.values() if isinstance(v, dict) and "cv" in v and "visual" in v), None)
        if rec:
            pages[rec["name"]] = rec | {"slug": slug}
    log.info("official site: %d character pages", len(pages))
    return pages


def load_transcript(cfg: dict, index: dict) -> dict[str, tuple[int, str]]:
    """member path -> (chara_id, text) for character system voices."""
    z = cfg["hf_zip"]
    dest = ROOT / RAW / z["transcript"]
    if not dest.exists():
        dest.write_bytes(hf_zip.read_members(z["repo"], z["file"], index, [z["transcript"]])[z["transcript"]])
    out = {}
    for line in dest.read_text(encoding="utf-8").splitlines():
        parts = line.split("|", 2)
        if len(parts) == 3 and parts[0].startswith(z["prefix"]):
            out[parts[0]] = (int(parts[1]), parts[2].strip())
    return out


def clean_title(t: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", t)).strip()


def build(ids: list[int] | None = None) -> None:
    cfg = load_config(GAME)
    z = cfg["hf_zip"]
    sess = PoliteSession(min_interval=cfg["rate_limit_sec"])
    index = hf_zip.build_index(z["repo"], z["file"], ROOT / RAW / f"{z['file']}.index.jsonl")
    lines = load_transcript(cfg, index)
    gt = gametora_chars(sess, cfg)
    official = official_pages(sess, cfg)
    dataset_url = f"https://huggingface.co/datasets/{z['repo']}"

    by_char: dict[int, list[tuple[str, str]]] = defaultdict(list)
    for member, (cid, text) in lines.items():
        by_char[cid].append((member, text))

    chars, clips = [], []
    for cid in sorted(by_char):
        if ids and cid not in ids:
            continue
        g = gt.get(cid, {})
        name_ja = cfg["official"]["name_alias"].get(g.get("name_ja"), g.get("name_ja"))
        page = official.get(name_ja) if name_ja else None
        uid = f"{GAME}:{cid}"
        images, profiles, sources = [], [], []
        if page:
            url = cfg["official"]["page"].format(slug=page["slug"])
            sources.append(url)
            for i, v in enumerate(page.get("visual") or []):
                title = clean_title((v.get("name") or {}).get("title") or "")
                img = (v.get("image") or {}).get("url")
                if img:
                    images.append({"kind": cfg["image_kind"].get(title, "other"), "outfit_name": title or None,
                                   "source_url": img,
                                   "path": str(RAW / "images" / str(cid) / f"{i:02d}{Path(img).suffix}")})
            basic = "　".join(f"{k}：{page[f]}" for k, f in
                             [("誕生日", "birthday"), ("身長", "height"), ("体重", "weight"), ("スリーサイズ", "size")]
                             if page.get(f))
            for kind, text in [("introduction", page.get("detail")), ("catchphrase", page.get("catch")),
                               ("basic_info", basic)]:
                if text:
                    profiles.append({"lang": "ja", "kind": kind, "condition": None, "text": text.strip(),
                                     "source_url": url})
        if g.get("url_name"):
            sources.append(f"https://gametora.com/umamusume/characters/{g['url_name']}")
        chars.append({
            "char_uid": uid,
            "game": GAME,
            "name_ja": name_ja,
            "name_zh": g.get("name_zh_tw"),
            "name_en": g.get("name_en") or (page or {}).get("en"),
            "gender": cfg["gender"]["value"],
            "gender_source": cfg["gender"]["source"],
            "gender_alt": {},
            "cv_name_ja": (page or {}).get("cv") or g.get("va_ja"),
            "cv_name_zh": None,
            "cv_uid": None,
            "images": images,
            "profile_texts": profiles,
            "source_urls": sources + [dataset_url],
        })
        for member, text in sorted(by_char[cid]):
            folder, n = member.split("/")[-2:]
            cat = re.match(r"snd_voi_([a-z]+)_", folder)
            cat = cat.group(1) if cat else folder
            clips.append({
                "clip_uid": f"{GAME}:{cid}:{folder}:{n.rsplit('.', 1)[0]}",
                "char_uid": uid,
                "outfit_name": None,
                "category": folder,
                "category_norm": cfg["category_norm"].get(cat, "other"),
                "condition": None,
                "is_legacy": False,
                "voice_scope": "character_vo",
                "text_ja": text or None,
                "text_zh": None,
                "text_source": "gamedata" if text else None,
                "audio_path": str(RAW / "audio" / str(cid) / f"{folder}_{n.rsplit('.', 1)[0]}.flac"),
                "audio_url": f"hfzip://{z['repo']}/{z['file']}#{member}",
                "source_sha1": None,
                "source_url": dataset_url,
                "is_battle_shout": False,
            })
        log.info("%s %s (CV %s): %d clips, %d images%s", uid, name_ja, chars[-1]["cv_name_ja"],
                 len(by_char[cid]), len(images), "" if page else ", no official page")
    n1 = write_jsonl(ROOT / "manifests" / f"{GAME}_characters.jsonl", chars)
    n2 = write_jsonl(ROOT / "manifests" / f"{GAME}_clips.jsonl", clips)
    log.info("wrote %d characters, %d clips", n1, n2)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids", nargs="*", type=int, help="chara_id(s) for a pilot run")
    build(ap.parse_args().ids)
