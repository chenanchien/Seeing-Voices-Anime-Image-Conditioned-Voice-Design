"""Azur Lane adapter: HF dump (TLME/AzurLane-voice-transcription) for audio and official JP
line text, AzurLaneData (JP game data) for names, skins and CV, algwiki.moe for paintings
(assembled by src.sources.azurlane_paint, not by src.download).

The HF zip holds <Ship>/<line text>.ogg plus <Ship>/char.json ({algwiki voice URL: text}).
The URL gives the ship group (cv-<group>) and the skin (`_<n>` suffix, skin id group*10+n),
so every clip gets its outfit name. The wiki itself (azurlane.koumakan.jp) is not used.
Ships missing from the dump are read from algwiki ship pages (src.sources.azurlane_algwiki)
and their audio is fetched from algwiki directly.

    python -m src.sources.azurlane                     # all ships
    python -m src.sources.azurlane --names Akagi Ajax  # pilot by HF folder name
"""
from __future__ import annotations

import argparse
import json
import logging
import re
from collections import Counter, defaultdict
from pathlib import Path

from src.common.http import PoliteSession
from src.common.io import ROOT, load_config, write_jsonl
from src.sources import hf_zip
from src.sources.azurlane_algwiki import missing_ships

log = logging.getLogger("azurlane")
GAME = "azurlane"
RAW = Path("data/raw/azurlane")


def gamedata(sess: PoliteSession, cfg: dict, key: str) -> dict:
    path = cfg["gamedata_files"][key]
    dest = ROOT / RAW / "gamedata" / Path(path).name
    if not dest.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(sess.get(cfg["gamedata"].format(path=path)).content)
    return {k: v for k, v in json.loads(dest.read_text(encoding="utf-8")).items() if k != "all"}


def char_jsons(cfg: dict, index: dict) -> dict[str, dict[str, str]]:
    """HF folder -> {voice URL: text}; cached as one JSON file."""
    dest = ROOT / RAW / "char_json.json"
    if not dest.exists():
        z = cfg["hf_zip"]
        names = [n for n in index if n.endswith("/char.json")]
        data = hf_zip.read_members(z["repo"], z["file"], index, names)
        dest.write_text(json.dumps({n.split("/")[0]: json.loads(b) for n, b in data.items()},
                                   ensure_ascii=False), encoding="utf-8")
    return json.loads(dest.read_text(encoding="utf-8"))


def parse_voice(url: str) -> tuple[int, bool, str, int]:
    """'.../cue/cv-30701-battle/acb/awb/main_1_3.ogg' -> (30701, True, 'main_1', 3)."""
    m = re.search(r"/cue/cv-(\d+)(-battle)?/", url)
    stem = url.rsplit("/", 1)[1].rsplit(".", 1)[0]
    if re.fullmatch(r"(main|touch)_\d", stem):
        key, skin = stem, 0
    else:
        k = re.fullmatch(r"(.+)_(\d+)", stem)
        key, skin = (k.group(1), int(k.group(2))) if k else (stem, 0)
    return int(m.group(1)), bool(m.group(2)), key, skin


def build(names: list[str] | None = None) -> None:
    cfg = load_config(GAME)
    z = cfg["hf_zip"]
    sess = PoliteSession(min_interval=cfg["rate_limit_sec"])
    index = hf_zip.build_index(z["repo"], z["file"], ROOT / RAW / f"{z['file']}.index.jsonl")
    folders = char_jsons(cfg, index)
    hf_groups = {Counter(parse_voice(u)[0] for u in v).most_common(1)[0][0] for v in folders.values()}
    direct = {}  # algwiki slug -> ship name, for ships the HF dump lacks (audio fetched from algwiki)
    for slug, (name, voices) in missing_ships(sess, cfg, hf_groups, lambda u: parse_voice(u)[0]).items():
        folders[slug], direct[slug] = voices, name
    stats, skins = gamedata(sess, cfg, "statistics"), gamedata(sess, cfg, "skins")
    actors = {a["code"]: a["actor_name"] for a in gamedata(sess, cfg, "actors").values()}
    name_by_group: dict[int, dict] = {}
    for s in sorted(stats.values(), key=lambda s: s["id"]):
        name_by_group.setdefault(s["id"] // 10, s)
    skins_by_group: dict[int, dict[int, dict]] = defaultdict(dict)
    for s in skins.values():
        skins_by_group[s["ship_group"]][s["id"] - s["ship_group"] * 10] = s
    dataset_url = f"https://huggingface.co/datasets/{z['repo']}"

    chars, clips, unmatched, skipped_direct = [], [], 0, []
    for folder in sorted(folders):
        if names and folder not in names:
            continue
        voices = folders[folder]
        group = Counter(parse_voice(u)[0] for u in voices).most_common(1)[0][0]
        st = name_by_group.get(group, {})
        sk = skins_by_group.get(group, {})
        base = sk.get(0, {})
        if folder in direct and not base:  # algwiki-only ship not (yet) in the JP game: no JP name / CV
            skipped_direct.append(direct[folder])
            continue
        uid = f"{GAME}:{group}"
        slug = folder if folder in direct else re.sub(r"[^a-z0-9_]", "", folder.lower().replace(" ", "_"))
        images, profiles = [], []
        for n, s in sorted(sk.items()):
            if not s.get("painting"):
                continue
            key = s["painting"].lower()  # algwiki file names are lowercase
            images.append({"kind": "base" if n == 0 else "skin", "outfit_name": s["name"] if n else "default",
                           "source_url": cfg["painting"].format(painting=key), "painting": key,
                           "assembled_by": "src.sources.azurlane_paint",
                           "path": str(RAW / "images" / str(group) / f"{key}.png")})
            if n and s.get("desc"):  # official outfit description (appearance)
                profiles.append({"lang": "ja", "kind": "outfit_description", "condition": s["name"],
                                 "text": s["desc"], "source_url": dataset_url})
        seen_members = set()
        for url, text in voices.items():
            _, battle, key, n = parse_voice(url)
            member = url if folder in direct else f"{folder}/{text}.ogg"
            if folder not in direct and member not in index:
                unmatched += 1  # line removed by the HF cleaning (e.g. English) or renamed
                continue
            if member in seen_members:  # two voice keys share one text -> one file
                continue
            seen_members.add(member)
            if key == "profile" and n == 0:
                profiles.append({"lang": "ja", "kind": "self_introduction", "condition": None,
                                 "text": text, "source_url": cfg["ship_page"].format(slug=slug) if folder in direct else dataset_url})
            stem = url.rsplit("/", 1)[1].rsplit(".", 1)[0]
            clips.append({
                "clip_uid": f"{GAME}:{group}:{'battle:' if battle else ''}{stem}",
                "char_uid": uid,
                "outfit_name": sk.get(n, {}).get("name") if n else None,
                "category": f"{'battle/' if battle else ''}{key}",
                "category_norm": "battle" if battle else cfg["category_norm"].get(key, "other"),
                "condition": None,
                "is_legacy": False,
                "voice_scope": "character_vo",
                "text_ja": text or None,
                "text_zh": None,
                "text_source": ("wiki" if folder in direct else "gamedata") if text else None,
                "audio_path": str(RAW / "audio" / str(group) / f"{'battle_' if battle else ''}{stem}.flac"),
                "audio_url": url if folder in direct else f"hfzip://{z['repo']}/{z['file']}#{member}",
                "source_sha1": None,
                "source_url": url,
                "is_battle_shout": False,
            })
        cv = actors.get(base.get("voice_actor"))
        chars.append({
            "char_uid": uid,
            "game": GAME,
            "name_ja": st.get("name") or base.get("name"),
            "name_zh": None,
            "name_en": direct.get(folder, folder),
            "gender": cfg["gender"]["value"],
            "gender_source": cfg["gender"]["source"],
            "gender_alt": {},
            "cv_name_ja": cv,
            "cv_name_zh": None,
            "cv_uid": None,
            "images": images,
            "profile_texts": profiles,
            "source_urls": [cfg["ship_page"].format(slug=slug)] + ([] if folder in direct else [dataset_url]),
        })
        log.info("%s %s / %s (CV %s): %d clips, %d skins", uid, chars[-1]["name_ja"], folder, cv,
                 sum(c["char_uid"] == uid for c in clips), len(images))
    n1 = write_jsonl(ROOT / "manifests" / f"{GAME}_characters.jsonl", chars)
    n2 = write_jsonl(ROOT / "manifests" / f"{GAME}_clips.jsonl", clips)
    log.info("wrote %d characters, %d clips (%d voice URLs without an audio file)", n1, n2, unmatched)
    log.info("from algwiki: %d ships; skipped %d not in the JP game data: %s",
             len(direct) - len(skipped_direct),
             len(skipped_direct), skipped_direct)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--names", nargs="*", help="HF folder name(s) for a pilot run")
    build(ap.parse_args().names)
