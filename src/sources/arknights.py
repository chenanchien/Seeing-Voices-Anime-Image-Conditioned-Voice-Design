"""Arknights adapter: JP game data (ArknightsGameData_YoStar) + PRTS (art) + torappu (JP audio).

All text comes from the JP server tables: voice lines (charword_table), CV (voiceLangDict),
gender and profile (handbook_info_table). PRTS is only queried for the art file list.
Skin / patch-form voices (wordKey != charId) stay with the operator as outfit voices.

    python -m src.sources.arknights                                    # all operators with JP voice
    python -m src.sources.arknights --ids char_002_amiya char_017_huang  # pilot
"""
from __future__ import annotations

import argparse
import json
import logging
import re
from pathlib import Path

from src.common.http import PoliteSession
from src.common.io import ROOT, load_config, write_jsonl

log = logging.getLogger("arknights")
GAME = "arknights"
RAW = Path("data/raw/arknights")


def load_table(sess: PoliteSession, cfg: dict, server: str, file: str) -> dict:
    dest = ROOT / RAW / "gamedata" / server / file
    if not dest.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        log.info("downloading %s/%s", server, file)
        dest.write_bytes(sess.get(cfg["gamedata"][server].format(file=file)).content)
    return json.loads(dest.read_text(encoding="utf-8"))


def categorize(word: dict, cfg: dict) -> str:
    if word["unlockType"] == "FAVOR":
        return "bond"
    rules = cfg["category_rules"]
    for norm in ("battle", "system", "daily"):
        if any(word["placeType"].startswith(p) for p in rules[norm]):
            return norm
    return rules["default"]


def handbook(entry: dict | None, cfg: dict, url: str) -> tuple[str, str | None, list[dict]]:
    """-> (gender, raw gender label, profile_texts)"""
    if not entry:
        return "unknown", None, []
    texts, raw = [], None
    for s in entry.get("storyTextAudio", []):
        for st in s["stories"]:
            texts.append({"lang": "ja", "kind": s["storyTitle"], "condition": None,
                          "text": st["storyText"], "source_url": url})
        m = re.search(r"【性別】\s*([^\n【]+)", s["stories"][0]["storyText"]) if s["stories"] else None
        if m and raw is None:
            raw = m.group(1).strip()
    return cfg["gender_map"].get(raw or "", "unknown"), raw, texts


def prts_art(sess: PoliteSession, cfg: dict, zh_name: str) -> list[dict]:
    """立绘_<name>_1/_2/_skinN files, incl. patch forms like 立绘_<name>(近卫)_2."""
    d = sess.get(cfg["prts"]["api"], params={"action": "query", "list": "allimages", "aiprefix": f"立绘_{zh_name}",
                                             "ailimit": 100, "format": "json"}).json()
    pat = re.compile(rf"^立绘_{re.escape(zh_name)}(?:\((.+?)\))?_(.+)\.png$")
    imgs = []
    for f in d["query"]["allimages"]:
        m = pat.match(f["name"])
        if not m:
            continue  # another operator sharing the prefix
        form, variant = m.groups()
        kind = "base" if variant == "1" and not form else "skin" if variant.startswith("skin") else "ascension"
        imgs.append({"kind": kind, "outfit_name": f"{form + ' ' if form else ''}{variant}",
                     "source_url": f["url"], "path": str(RAW / "images" / f["name"])})
    return imgs


def build(ids: list[str] | None = None) -> None:
    cfg = load_config(GAME)
    sess = PoliteSession(min_interval=cfg["rate_limit_sec"], host_intervals=cfg["host_rate_limit_sec"])
    words = load_table(sess, cfg, "ja", "charword_table.json")
    chars_ja = load_table(sess, cfg, "ja", "character_table.json")
    skins_ja = load_table(sess, cfg, "ja", "skin_table.json")["charSkins"]
    books = load_table(sess, cfg, "ja", "handbook_info_table.json")["handbookDict"]
    chars_zh = load_table(sess, cfg, "zh", "character_table.json")
    patch = load_table(sess, cfg, "ja", "char_patch_table.json")["patchChars"]  # e.g. Amiya (Guard)
    voice_skin = {s["voiceId"]: (s.get("displaySkin") or {}).get("skinName") for s in skins_ja.values()
                  if s.get("voiceId")}

    by_char: dict[str, list[dict]] = {}
    for w in words["charWords"].values():
        by_char.setdefault(w["charId"], []).append(w)

    chars, clips = [], []
    for cid, lang in words["voiceLangDict"].items():
        if ids and cid not in ids:
            continue
        jp = lang["dict"].get("JP")
        if not jp or cid not in chars_ja:
            log.info("skip %s: no JP voice", cid)
            continue
        zh_name = chars_zh.get(cid, {}).get("name")
        page = cfg["prts"]["page"].format(name=zh_name or cid)
        gender, gender_raw, profiles = handbook(books.get(cid), cfg, page)
        uid = f"{GAME}:{cid}"
        chars.append({
            "char_uid": uid,
            "game": GAME,
            "name_ja": chars_ja[cid]["name"],
            "name_zh": zh_name,
            "name_en": chars_ja[cid].get("appellation"),
            "gender": gender,
            "gender_source": "gamedata_ja",
            "gender_alt": {"raw": gender_raw} if gender_raw and gender == "unknown" else {},
            "cv_name_ja": "、".join(jp["cvName"]) or None,
            "cv_name_zh": None,
            "cv_uid": None,
            "images": prts_art(sess, cfg, zh_name) if zh_name else [],
            "profile_texts": profiles,
            "source_urls": [page],
        })
        # other-language voice sets (ITA, CN_TOPOLECT, ...) have their own wordKey: JP only
        non_jp = {d["wordkey"].lower() for lt, d in lang["dict"].items() if lt != "JP"} - {jp["wordkey"].lower()}
        for w in sorted(by_char.get(cid, []), key=lambda w: (w["wordKey"], w["voiceIndex"])):
            if w["wordKey"].lower() in non_jp:
                continue
            asset = w["voiceAsset"].lower()
            norm = categorize(w, cfg)
            wk = w["wordKey"]
            outfit = None if wk == cid else voice_skin.get(wk) or (
                f"{patch[wk]['name']} ({patch[wk]['profession']})" if wk in patch else wk)
            clips.append({
                "clip_uid": f"{GAME}:{w['charWordId']}",
                "char_uid": uid,
                "outfit_name": outfit,
                "category": f"{w['placeType']}/{w['voiceTitle']}",
                "category_norm": norm,
                "condition": w.get("lockDescription"),
                "is_legacy": False,
                "text_ja": w.get("voiceText") or None,
                "text_zh": None,
                "text_source": "gamedata" if w.get("voiceText") else None,
                "audio_file": asset + ".wav",
                "audio_path": str(RAW / "audio" / f"{asset}.wav"),
                "audio_url": cfg["prts"]["audio"].format(asset=asset),
                "source_sha1": None,
                "source_url": page,
                "is_battle_shout": any(w["placeType"].startswith(p) for p in cfg["battle_shout_place_types"]),
            })
        log.info("%s %s: %d images, %d clips", cid, chars_ja[cid]["name"], len(chars[-1]["images"]),
                 sum(1 for c in clips if c["char_uid"] == uid))
    n1 = write_jsonl(ROOT / "manifests" / f"{GAME}_characters.jsonl", chars)
    n2 = write_jsonl(ROOT / "manifests" / f"{GAME}_clips.jsonl", clips)
    log.info("wrote %d characters, %d clips", n1, n2)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids", nargs="*", help="charId(s) for a pilot run")
    build(ap.parse_args().ids)
