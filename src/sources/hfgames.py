"""Genshin / Star Rail / Wuthering Waves adapter.

Audio + JP transcription: Hugging Face ultemica/*-voices (ja), indexed by speaker.
Character metadata (CV, gender, profile text, art): BWIKI (ys, sr) or encore.moe (wuwa).
Story dialogue is kept and labelled voice_scope=story; character voice-over is character_vo.

    python -m src.sources.hfgames genshin [--names 芙宁娜 胡桃 ...]
"""
from __future__ import annotations

import argparse
import html
import logging
import re
from collections import defaultdict
from pathlib import Path

import pyarrow.parquet as pq

from src.common.http import PoliteSession
from src.common.io import ROOT, load_config, write_jsonl
from src.sources.hf_voices import build_index
from src.sources.mediawiki import strip_markup

log = logging.getLogger("hfgames")
GENDER = {"女": "female", "男": "male", "女性": "female", "男性": "male"}


# ---------- metadata providers ----------

def bwiki_characters(sess: PoliteSession, wiki: str, names: list[str] | None) -> list[dict]:
    api = f"https://wiki.biligame.com/{wiki}/api.php"
    d = sess.get(api, params={"action": "query", "list": "categorymembers", "cmtitle": "Category:角色",
                              "cmlimit": 500, "cmnamespace": 0, "format": "json"}).json()
    titles = [m["title"] for m in d["query"]["categorymembers"]]
    out = []
    for title in titles:
        if names and title not in names:
            continue
        wt = sess.get(api, params={"action": "parse", "page": title, "prop": "wikitext", "format": "json"}).json()
        wt = wt.get("parse", {}).get("wikitext", {}).get("*", "")
        fields = {}
        for k, v in re.findall(r"^\|([^=\n]+?)=(.*)$", wt, flags=re.M):
            fields.setdefault(k.strip(), v.strip())
        page_html = sess.get(api, params={"action": "parse", "page": title, "prop": "text",
                                          "format": "json"}).json()["parse"]["text"]["*"]
        url = f"https://wiki.biligame.com/{wiki}/{title}"
        profiles = []
        for key in ["介绍", "角色详细"] + sorted((k for k in fields if re.fullmatch(r"角色故事\d+", k)),
                                               key=lambda k: int(k[4:])):
            if fields.get(key):
                profiles.append({"lang": "zh", "kind": key, "condition": fields.get(f"{key}解锁条件"),
                                 "text": strip_markup(fields[key]), "source_url": url})
        out.append({
            "id": title, "name_zh": title, "name_ja": fields.get("日文名") or None,
            "name_en": fields.get("英文名称") or fields.get("外文名") or None,
            "gender_raw": fields.get("性别"), "cv_name_ja": fields.get("日文CV") or None,
            "images": bwiki_art(page_html, title), "profile_texts": profiles, "source_urls": [url],
        })
        log.info("%s: %d images, %d profile texts", title, len(out[-1]["images"]), len(profiles))
    return out


def bwiki_art(page_html: str, name: str) -> list[dict]:
    """<名>立绘*.png / <名>抽卡立绘.png from rendered HTML (thumb URLs -> originals)."""
    imgs, seen = [], set()
    for alt, src in re.findall(r'<img[^>]+alt="([^"]*)"[^>]+src="([^"]+)"', page_html):
        m = re.fullmatch(rf"{re.escape(name)}(抽卡立绘|立绘\d*)\.(png|jpg|webp)", html.unescape(alt))
        if not m or alt in seen:
            continue
        seen.add(alt)
        src = re.sub(r"/thumb/(\w/\w\w/[^/]+)/[^/]+$", r"/\1", src)
        imgs.append({"kind": "base" if m.group(1) in ("立绘", "抽卡立绘") else "other",
                     "outfit_name": m.group(1), "source_url": src, "file": alt})
    return imgs


def encore_characters(sess: PoliteSession, cfg: dict, names: list[str] | None) -> list[dict]:
    ec = cfg["encore"]
    out, seen = [], set()
    for r in sess.get(ec["list"]).json()["roleList"]:
        if (names and r["Name"] not in names) or r["Id"] in seen:
            continue
        seen.add(r["Id"])
        d = sess.get(ec["detail"].format(id=r["Id"])).json()
        fav = d.get("favorRole") or {}
        content = lambda k: ((fav.get(k) or {}).get("Content") or "").strip() or None
        url = ec["page"].format(id=r["Id"])
        clean = lambda s: re.sub(r"<[^>]+>", "", s)
        profiles = [{"lang": "ja", "kind": "introduction", "condition": None,
                     "text": clean(d["Introduction"]["Content"]), "source_url": url}] if d.get("Introduction") else []
        for st in fav.get("Stories") or fav.get("FavorStory") or []:
            if isinstance(st, dict) and st.get("Content"):
                profiles.append({"lang": "ja", "kind": f"story:{st.get('Title', '')}", "condition": None,
                                 "text": clean(st["Content"]), "source_url": url})
        images = []
        for sk in d.get("Skins") or []:
            if sk.get("RoleStand"):
                images.append({"kind": "base" if "デフォルト" in (sk.get("SubDecName") or "") else "skin",
                               "outfit_name": sk.get("Name"), "source_url": sk["RoleStand"],
                               "file": f"{r['Id']}_{sk['Id']}{Path(sk['RoleStand']).suffix or '.png'}"})
        out.append({
            "id": str(r["Id"]), "name_zh": r["Name"], "name_ja": d["Name"]["Content"],
            "name_en": None, "gender_raw": content("Sex"), "cv_name_ja": content("CVNameJp"),
            "images": images, "profile_texts": profiles, "source_urls": [url],
        })
        log.info("%s %s: %d images", r["Id"], r["Name"], len(images))
    return out


# ---------- main ----------

def apply_groups(meta: list[dict], groups: list[dict]) -> list[dict]:
    """Merge wiki pages into dataset characters per config `groups`; other pages map 1:1 to
    the HF speaker with the same name."""
    used, out = set(), []
    for g in groups:
        pages = [m for m in meta
                 if (m["name_zh"] in g.get("pages", []) or
                     (g.get("page_prefix") and m["name_zh"].startswith(g["page_prefix"])))
                 and (not g.get("where_gender") or m["gender_raw"] == g["where_gender"])]
        if not pages:
            continue
        used.update(id(m) for m in pages)
        seen_img, seen_txt = set(), set()
        images = [dict(i) for m in pages for i in m["images"]  # copies: pages can feed several groups
                  if not (i["source_url"] in seen_img or seen_img.add(i["source_url"]))]
        texts = [t for m in pages for t in m["profile_texts"] if not (t["text"] in seen_txt or seen_txt.add(t["text"]))]
        first = lambda k: next((m[k] for m in pages if m[k]), None)
        out.append({"id": g["name"], "name_zh": g["name"], "name_ja": first("name_ja"), "name_en": first("name_en"),
                    "gender_raw": first("gender_raw"), "gender_override": g.get("gender"),
                    "cv_name_ja": first("cv_name_ja"), "images": images, "profile_texts": texts,
                    "source_urls": sorted({u for m in pages for u in m["source_urls"]}),
                    "speakers": g["speakers"], "pages": [m["name_zh"] for m in pages]})
    for m in meta:
        if id(m) not in used:
            out.append(m | {"speakers": [m["name_zh"]], "gender_override": None})
    return out


def build(game: str, names: list[str] | None = None) -> None:
    cfg = load_config(game)
    raw = Path(f"data/raw/{game}")
    sess = PoliteSession(min_interval=cfg["rate_limit_sec"], host_intervals=cfg["host_rate_limit_sec"])
    meta = (bwiki_characters(sess, cfg["metadata"]["wiki"], names) if cfg["metadata"]["provider"] == "bwiki"
            else encore_characters(sess, cfg, names))
    meta = apply_groups(meta, cfg.get("groups", []))

    index = build_index(cfg["hf_repo"], ROOT / raw / "hf_index.parquet").to_pylist()
    by_speaker: dict[str, list[dict]] = defaultdict(list)
    for r in index:
        by_speaker[r["speaker"]].append(r)
    vo_re = re.compile(cfg["voice_scope"]["character_vo"])
    norm_rules = {k: re.compile(v) for k, v in cfg["category_norm"].items() if k != "default"}
    shout_re = re.compile(cfg["battle_shout"])

    chars, clips, unmatched = [], [], []
    for m in meta:
        uid = f"{game}:{m['id']}"
        speakers = m["speakers"]
        rows = [r for s in speakers for r in by_speaker.get(s, [])]
        if not rows:
            unmatched.append(m["name_zh"])
        for img in m["images"]:
            img["path"] = str(raw / "images" / img.pop("file"))
        chars.append({
            "char_uid": uid, "game": game, "name_ja": m["name_ja"], "name_zh": m["name_zh"],
            "name_en": m["name_en"],
            "gender": m["gender_override"] or GENDER.get(m["gender_raw"] or "", "unknown"),
            "gender_source": "config" if m["gender_override"] else cfg["metadata"]["provider"],
            "gender_alt": {"raw": m["gender_raw"]} if m["gender_raw"] and m["gender_raw"] not in GENDER else {},
            "cv_name_ja": m["cv_name_ja"], "cv_name_zh": None, "cv_uid": None,
            "hf_speakers": speakers, "wiki_pages": m.get("pages", [m["name_zh"]]), "images": m["images"], "profile_texts": m["profile_texts"],
            "source_urls": m["source_urls"] + [f"https://huggingface.co/datasets/{cfg['hf_repo']}"],
        })
        for r in rows:
            fname = r["source_path"].rsplit("/", 1)[1]
            stem = fname.rsplit(".", 1)[0]
            scope = "character_vo" if vo_re.search(fname) else "story"
            norm = "other" if scope == "story" else next(
                (k for k, rx in norm_rules.items() if rx.search(fname)), cfg["category_norm"]["default"])
            text = (r["transcription"] or "").strip()
            line_type = re.sub(r"_?\d+[a-z]?$", "", stem)  # drop the line number
            clips.append({
                "clip_uid": f"{game}:{stem}", "char_uid": uid, "outfit_name": None,
                "category": f"{scope}/{line_type}",
                "category_norm": norm, "voice_scope": scope, "speaker": r["speaker"],
                "condition": None, "is_legacy": False,
                "text_ja": text or None, "text_zh": None, "text_source": "hf" if text else None,
                "audio_file": fname,
                "audio_path": str(raw / "audio" / r["speaker"] / f"{stem}.flac"),
                "audio_url": f"hf://{cfg['hf_repo']}/{r['shard']}#{r['row']}",
                "source_sha1": None,
                "source_url": f"https://huggingface.co/datasets/{cfg['hf_repo']}",
                "is_battle_shout": norm == "battle" and bool(shout_re.search(fname)),
            })
    if unmatched:
        log.warning("%d characters without HF speaker match (add to `groups`): %s", len(unmatched), unmatched)
    n1 = write_jsonl(ROOT / "manifests" / f"{game}_characters.jsonl", chars)
    n2 = write_jsonl(ROOT / "manifests" / f"{game}_clips.jsonl", clips)
    log.info("wrote %d characters, %d clips (%d character_vo)", n1, n2,
             sum(c["voice_scope"] == "character_vo" for c in clips))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    ap = argparse.ArgumentParser()
    ap.add_argument("game", choices=["genshin", "starrail", "wuwa"])
    ap.add_argument("--names", nargs="*", help="Chinese names for a pilot run")
    a = ap.parse_args()
    build(a.game, a.names)
