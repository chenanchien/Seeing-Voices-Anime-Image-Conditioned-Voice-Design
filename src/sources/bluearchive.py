"""Blue Archive adapter: SchaleDB JSON (students, JP voice) + r2.schaledb.com audio.

Styles (水着, 臨戦, ...) of one student are merged into a single character; each style
contributes a portrait image and its voice lines carry the style name as outfit_name.

    python -m src.sources.bluearchive                    # all students
    python -m src.sources.bluearchive --names アル ホシノ  # pilot by PersonalName
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

log = logging.getLogger("bluearchive")
GAME = "bluearchive"
RAW = Path("data/raw/bluearchive")


def load_json(sess: PoliteSession, cfg: dict, lang: str, file: str) -> dict:
    dest = ROOT / RAW / "schaledb" / lang / file
    if not dest.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(sess.get(cfg["schaledb"]["data"].format(lang=lang, file=file)).content)
    d = json.loads(dest.read_text(encoding="utf-8"))
    return {str(s["Id"]): s for s in d} if isinstance(d, list) else d


def categorize(bucket: str, group: str, cfg: dict) -> str:
    return next(r["norm"] for r in cfg["category_rules"]
                if r["bucket"] == bucket and group.startswith(r["prefix"]))


def style_name(s: dict) -> str | None:
    """'ホシノ（水着）' -> '水着'; base style -> None."""
    m = re.search(r"[（(](.+)[)）]$", s["Name"])
    return m.group(1) if m else None


def build(names: list[str] | None = None) -> None:
    cfg = load_config(GAME)
    sc = cfg["schaledb"]
    sess = PoliteSession(min_interval=cfg["rate_limit_sec"])
    students = load_json(sess, cfg, "jp", "students.min.json")
    voices = load_json(sess, cfg, "jp", "voice.min.json")
    localized = {field: load_json(sess, cfg, lang, "students.min.json")
                 for lang, field in sc["name_langs"].items()}

    groups: dict[tuple, list[dict]] = defaultdict(list)
    for s in students.values():
        s.update(cfg["style_override"].get(s["Id"], {}))
        # SchaleDB sometimes pads a name ("豊見 " on one style): strip it so styles still merge
        groups[(s["FamilyName"].strip(), s["PersonalName"].strip())].append(s)

    chars, clips = [], []
    for (family, personal), styles in sorted(groups.items(), key=lambda kv: min(s["Id"] for s in kv[1])):
        if names and personal not in names:
            continue
        styles.sort(key=lambda s: (style_name(s) is not None, s["Id"]))
        base = styles[0]
        uid = f"{GAME}:{base['Id']}"
        images, profiles, seen_text = [], [], set()
        for s in styles:
            outfit = style_name(s)
            url = sc["portrait"].format(id=s["Id"])
            images.append({"kind": "skin" if outfit else "base", "outfit_name": outfit or "default",
                           "source_url": url, "path": str(RAW / "images" / f"{s['Id']}.webp")})
            page = sc["student_page"].format(path=s["PathName"])
            for kind, text in [("introduction", s.get("ProfileIntroduction")), ("hobby", s.get("Hobby")),
                               ("basic_info", f"学校：{s.get('School')}　部活：{s.get('Club')}　学年：{s.get('SchoolYear')}"
                                              f"　年齢：{s.get('CharacterAge')}　身長：{s.get('CharHeightMetric')}")]:
                if text and text not in seen_text:
                    seen_text.add(text)
                    profiles.append({"lang": "ja", "kind": kind, "condition": outfit, "text": text,
                                     "source_url": page})
            for bucket, lines in voices.get(str(s["Id"]), {}).items():
                for e in lines:
                    if not e.get("AudioClip"):
                        continue
                    group = re.sub(r"\d+$", "", e["Group"])
                    norm = categorize(bucket, group, cfg)
                    clips.append({
                        "clip_uid": f"{GAME}:{s['Id']}:{e['AudioClip'].rsplit('/', 1)[-1].rsplit('.', 1)[0]}",
                        "char_uid": uid,
                        "outfit_name": outfit,
                        "category": f"{bucket}/{e['Group']}",
                        "category_norm": norm,
                        "condition": None,
                        "is_legacy": False,
                        "text_ja": e.get("Transcription") or None,
                        "text_zh": None,
                        "text_source": "wiki" if e.get("Transcription") else None,
                        "audio_file": e["AudioClip"],
                        # styles can reuse the same clip; path is shared so it downloads once
                        "audio_path": str(RAW / "audio" / e["AudioClip"]),
                        "audio_url": sc["audio"].format(clip=e["AudioClip"]),
                        "source_sha1": None,
                        "source_url": page,
                        "is_battle_shout": norm == "battle" and any(
                            group.startswith(p) for p in cfg["battle_shout_groups"]),
                    })
        loc = {field: localized[field].get(str(base["Id"]), {}) for field in localized}
        chars.append({
            "char_uid": uid,
            "game": GAME,
            "name_ja": f"{family}{personal}",
            "name_zh": (loc["name_zh"].get("FamilyName", "") + loc["name_zh"].get("PersonalName", "")) or None,
            "name_en": " ".join(x for x in (loc["name_en"].get("PersonalName"), loc["name_en"].get("FamilyName")) if x) or None,
            "gender": cfg["gender"]["value"],
            "gender_source": cfg["gender"]["source"],
            "gender_alt": {},
            "cv_name_ja": (base.get("CharacterVoice") or "").strip() or None,
            "cv_name_zh": None,
            "cv_uid": None,
            "style_ids": [s["Id"] for s in styles],
            "images": images,
            "profile_texts": profiles,
            "source_urls": [sc["student_page"].format(path=base["PathName"])],
        })
        log.info("%s %s%s: %d styles", uid, family, personal, len(styles))

    # the same AudioClip under several styles -> keep the first row only
    seen, uniq = set(), []
    for c in clips:
        if c["audio_file"] not in seen:
            seen.add(c["audio_file"])
            uniq.append(c)
    n1 = write_jsonl(ROOT / "manifests" / f"{GAME}_characters.jsonl", chars)
    n2 = write_jsonl(ROOT / "manifests" / f"{GAME}_clips.jsonl", uniq)
    log.info("wrote %d characters, %d clips (%d shared clips dropped)", n1, n2, len(clips) - n2)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--names", nargs="*", help="PersonalName(s) for a pilot run")
    build(ap.parse_args().names)
