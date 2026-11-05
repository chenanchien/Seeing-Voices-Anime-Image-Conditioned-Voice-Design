"""Girls' Frontline adapter: HF dump (deepghs/girlsfrontline_voices_jp) for audio, JP line text
(IOP Wiki transcriptions), names and CV romaji; IOP Wiki doll pages for full artworks and
voice actor pages for the CV's Japanese name.

voices.tar stays on Hugging Face: voices.json gives every member's offset, so src.download
extracts single files with range requests (hfzip:// URL, method "tar" in the index).
IOP Wiki asks for 20 s between requests; pages are cached under data/raw/girlsfrontline/pages.

    python -m src.sources.girlsfrontline              # all dolls
    python -m src.sources.girlsfrontline --ids 1 4 55 # pilot by char_id
"""
from __future__ import annotations

import argparse
import html
import json
import logging
import re
from collections import defaultdict
from pathlib import Path
from urllib.parse import quote

import pyarrow.parquet as pq
import requests

from src.common.http import PoliteSession
from src.common.io import ROOT, load_config, write_jsonl
from src.sources import hf_zip

log = logging.getLogger("girlsfrontline")
GAME = "girlsfrontline"
RAW = Path("data/raw/girlsfrontline")
GALLERY_ITEM = re.compile(r'<li class="gallerybox".*?</li>', re.S)


def hf_file(cfg: dict, key: str) -> Path:
    t = cfg["hf_tar"]
    dest = ROOT / RAW / "hf" / t[key]
    if not dest.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        r = requests.get(hf_zip.resolve_url(t["repo"], t[key]), timeout=300)
        r.raise_for_status()
        dest.write_bytes(r.content)
    return dest


def page(sess: PoliteSession, url: str, dest: Path) -> str | None:
    """Cached wiki page; a 404 is cached as an empty .404 marker."""
    dest, miss = ROOT / dest, ROOT / dest.with_suffix(".404")
    if miss.exists():
        return None
    if not dest.exists():
        try:
            r = sess.get(url)
            if "charset" not in r.headers.get("content-type", ""):
                r.encoding = "utf-8"  # requests would assume ISO-8859-1 (algwiki sends no charset)
            text = r.text
        except requests.HTTPError as e:
            if getattr(e.response, "status_code", None) == 404:
                miss.parent.mkdir(parents=True, exist_ok=True)
                miss.touch()
                return None
            raise
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text, encoding="utf-8")
    return dest.read_text(encoding="utf-8")


def wiki_title(name: str) -> str:
    return quote(name.replace(" ", "_"), safe="_()'.-")


def artworks(doc: str, base: str) -> list[tuple[str, str]]:
    """Gallery "Main artworks": [(label, full-size url)] for full (not damaged) artworks."""
    m = re.search(r'id="Main_artworks".*?<ul class="gallery[^"]*">(.*?)</ul>', doc, re.S)
    out = []
    for item in GALLERY_ITEM.findall(m.group(1) if m else ""):
        label = html.unescape(re.sub(r"<[^>]+>", "", item.split('class="gallerytext">', 1)[-1])).strip()
        src = re.search(r'src="/images/thumb/([0-9a-f]/[0-9a-f]{2}/[^/"]+)/', item)
        if src and re.search(r"full artwork$", label, re.I) and "damaged" not in label.lower():
            out.append((label, f"{base}/images/{src.group(1)}"))
    return out


def cv_japanese(doc: str | None) -> str | None:
    if not doc:
        return None
    given = re.search(r"<li>Given name:\s*([^<(]+?)\s*(?:\(|<)", doc)
    family = re.search(r"<li>Family name:\s*([^<(]+?)\s*(?:\(|<)", doc)
    if not (given and family) or not re.search(r"[぀-ヿ一-鿿]", given.group(1) + family.group(1)):
        return None
    return html.unescape(family.group(1) + given.group(1))


def build(ids: list[int] | None = None) -> None:
    cfg = load_config(GAME)
    t = cfg["hf_tar"]
    sess = PoliteSession(min_interval=cfg["rate_limit_sec"], host_intervals=cfg["host_rate_limit_sec"])
    offsets = json.loads(hf_file(cfg, "offsets").read_text(encoding="utf-8"))["files"]
    index = hf_zip.tar_index(offsets, ROOT / RAW / f"{t['file']}.index.jsonl")
    rows = pq.read_table(hf_file(cfg, "table")).to_pylist()
    dataset_url = f"https://huggingface.co/datasets/{t['repo']}"

    by_char: dict[int, list[dict]] = defaultdict(list)
    for r in rows:
        by_char[r["char_id"]].append(r)

    chars, clips, cv_cache = [], [], {}
    for cid in sorted(by_char):
        if ids and cid not in ids:
            continue
        lines = by_char[cid]
        head = lines[0]
        uid = f"{GAME}:{cid}"
        url = cfg["doll_page"].format(title=wiki_title(head["char_name"]))
        doc = page(sess, url, RAW / "pages" / "dolls" / f"{cid}.html")
        images = []
        for i, (label, src) in enumerate(artworks(doc or "", cfg["image_base"])):
            outfit = re.sub(r"\s*full artwork$", "", label, flags=re.I).strip().strip('"')
            images.append({"kind": "base" if not outfit else "skin", "outfit_name": outfit or "default",
                           "source_url": src,
                           "path": str(RAW / "images" / str(cid) / f"{i:02d}{Path(src).suffix.lower()}")})
        romaji = head["voice_actor_name"]
        if romaji not in cv_cache:
            va = page(sess, cfg["va_page"].format(title=wiki_title(romaji)),
                      RAW / "pages" / "voice_actors" / f"{romaji.replace('/', '_')}.html")
            cv_cache[romaji] = cv_japanese(va) or cfg["cv_name_ja_override"].get(romaji)
        chars.append({
            "char_uid": uid,
            "game": GAME,
            "name_ja": head["char_jpname"],
            "name_zh": head["char_cnname"],
            "name_en": head["char_enname"] or head["char_name"],
            "gender": cfg["gender"]["value"],
            "gender_source": cfg["gender"]["source"],
            "gender_alt": {},
            "cv_name_ja": cv_cache[romaji],
            "cv_name_zh": None,
            "cv_name_en": romaji,
            "cv_uid": None,
            "images": images,
            "profile_texts": [],  # no official profile text in either source
            "source_urls": [url, dataset_url] if doc else [dataset_url],
        })
        for r in sorted(lines, key=lambda r: r["filename"]):
            stem = r["filename"].rsplit(".", 1)[0]
            group = r["voice_group"] or ""
            outfit = next((o for p, o in cfg["voice_set_outfit"].items() if group.startswith(p)), None)
            title = r["voice_title"]
            clips.append({
                "clip_uid": f"{GAME}:{cid}:{stem}",
                "char_uid": uid,
                "outfit_name": outfit,
                "category": f"{group}/{title}",
                "category_norm": cfg["category_norm"].get(title, "other"),
                "condition": None,
                "is_legacy": False,
                "voice_scope": "character_vo",
                "text_ja": r["voice_text"] or None,
                "text_zh": None,
                "text_source": "wiki" if r["voice_text"] else None,
                "audio_path": str(RAW / "audio" / str(cid) / f"{stem}.flac"),
                "audio_url": f"hfzip://{t['repo']}/{t['file']}#{r['filename']}",
                "source_sha1": None,
                "source_url": r["file_url"],
                "is_battle_shout": title in ("Attack", "Defense"),
            })
        log.info("%s %s (CV %s / %s): %d clips, %d artworks%s", uid, head["char_jpname"], cv_cache[romaji],
                 romaji, len(lines), len(images), "" if doc else ", no wiki page")
    n1 = write_jsonl(ROOT / "manifests" / f"{GAME}_characters.jsonl", chars)
    n2 = write_jsonl(ROOT / "manifests" / f"{GAME}_clips.jsonl", clips)
    log.info("wrote %d characters, %d clips (%d without CV Japanese name)", n1, n2,
             sum(not c["cv_name_ja"] for c in chars))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids", nargs="*", type=int, help="char_id(s) for a pilot run")
    build(ap.parse_args().ids)
