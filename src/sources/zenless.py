"""Zenless Zone Zero adapter: HoYoLAB wiki (JP name, gender, CV, profile, agent art) + the
JP agent voice-over from HF simon3000/zenless-voice.

The parquet shards mix four languages, so audio comes from the per-speaker zip archives
(speaker-archives/Japanese/...). Each <hash>.wav has a <hash>.json with voiceType; the JSON
members are read once per archive in range spans and cached, and only voiceType "char"
clips enter the manifest (hfzip:// URLs; src.download extracts them). These clips carry no
transcription, so text_ja is filled by the Whisper ASR fallback in src.clean.langid.

    python -m src.sources.zenless                     # all agents
    python -m src.sources.zenless --speakers anbi lycaon ellen   # pilot by HF speaker code
"""
from __future__ import annotations

import argparse
import json
import logging
import re
from collections import Counter
from pathlib import Path

import pyarrow.parquet as pq
import requests

from src.common.http import PoliteSession
from src.common.io import ROOT, load_config, write_jsonl
from src.sources import hf_zip
from src.sources.hfgames import GENDER, HOYOLAB_LIST, hoyolab_characters

log = logging.getLogger("zenless")
GAME = "zenless"
RAW = Path("data/raw/zenless")
norm = lambda s: re.sub(r"[^a-z0-9]", "", s.lower())


def archive_paths(cfg: dict) -> dict[str, str]:
    """Japanese speaker -> archive path inside the repo (from the archive README)."""
    dest = ROOT / RAW / "speaker_archives.md"
    if not dest.exists():
        r = requests.get(hf_zip.resolve_url(cfg["hf_repo"], cfg["archives"]), timeout=60)
        r.raise_for_status()
        dest.write_text(r.text, encoding="utf-8")
    base = cfg["archives"].rsplit("/", 1)[0]
    return {m.group(1): f"{base}/{m.group(2)}" for m in
            re.finditer(r"\| Japanese \| ([^|]+?) \| [\d,]+ \| \[Download\]\(([^)]+)\)", dest.read_text(encoding="utf-8"))}


def archive_meta(cfg: dict, file: str) -> tuple[dict, dict[str, dict]]:
    """(zip index, {wav member: clip JSON}); the JSON is cached next to the index."""
    index = hf_zip.build_index(cfg["hf_repo"], file, hf_zip.index_path(GAME, file))
    dest = hf_zip.index_path(GAME, file).with_suffix(".meta.json")
    if not dest.exists():
        names = [n for n in index if n.endswith(".json")]
        data = hf_zip.read_members(cfg["hf_repo"], file, index, names)
        dest.write_text(json.dumps({n[:-5] + ".wav": json.loads(b) for n, b in data.items()},
                                   ensure_ascii=False), encoding="utf-8")
    return index, json.loads(dest.read_text(encoding="utf-8"))


def english_names(sess: PoliteSession, cfg: dict) -> dict[str, str]:
    app, menu = cfg["hoyolab"]["app"], cfg["hoyolab"]["menu_id"]
    out, page = {}, 1
    while True:
        d = sess.post(HOYOLAB_LIST.format(app=app), headers={"x-rpc-language": "en-us", "x-rpc-wiki_app": app,
                                                             "Referer": "https://wiki.hoyolab.com/"},
                      json={"filters": [], "menu_id": menu, "page_num": page, "page_size": 30, "use_es": True}).json()["data"]
        out |= {str(e["entry_page_id"]): e["name"] for e in d["list"]}
        if not d["list"] or len(out) >= int(d["total"]):
            return out
        page += 1


def match_speakers(speakers: list[str], en: dict[str, str], cfg: dict) -> dict[str, str]:
    """HF speaker code -> HoYoLAB entry id (manual map first, then exact name / name token)."""
    by_name = {v: k for k, v in en.items()}
    out = {}
    for s in speakers:
        if s in cfg["speaker_unresolved"]:
            continue
        if s in cfg["speaker_map"]:
            out[s] = by_name[cfg["speaker_map"][s]]
            continue
        hits = [k for k, v in en.items()
                if norm(s) == norm(v) or norm(s) in {norm(t) for t in re.split(r"[\s\-.]+", v)}]
        if len(hits) == 1:
            out[s] = hits[0]
        else:
            log.warning("speaker %s: %d HoYoLAB matches, left out", s, len(hits))
    return out


def build(speakers: list[str] | None = None) -> None:
    cfg = load_config(GAME)
    sess = PoliteSession(min_interval=cfg["rate_limit_sec"], host_intervals=cfg["host_rate_limit_sec"])
    rows = pq.read_table(ROOT / cfg["hf_index"], columns=["language", "voice_type", "speaker"]).to_pylist()
    counts = Counter(r["speaker"] for r in rows
                     if r["language"] == "Japanese" and r["voice_type"] in cfg["voice_types"])
    wanted = sorted(s for s in counts if not speakers or s in speakers)
    to_entry = match_speakers(wanted, english_names(sess, cfg), cfg)
    meta = {m["id"]: m for m in hoyolab_characters(sess, cfg, None)}
    archives = archive_paths(cfg)
    dataset_url = f"https://huggingface.co/datasets/{cfg['hf_repo']}"

    chars, clips = {}, []
    for s in wanted:
        eid = to_entry.get(s)
        if eid is None or eid not in meta:
            continue
        m = meta[eid]
        uid = f"{GAME}:{eid}"
        if uid not in chars:
            # agent art only (gallery keys "<name>・「<outfit>」"); promo / sticker art is skipped
            images = [i | {"kind": "base", "path": str(RAW / "images" / i.pop("file"))}
                      for i in m["images"] if "・「" in (i["outfit_name"] or "")]
            chars[uid] = {
                "char_uid": uid, "game": GAME, "name_ja": m["name_ja"], "name_zh": m["name_zh"],
                "name_en": None, "gender": GENDER.get(m["gender_raw"] or "", "unknown"),
                "gender_source": "hoyolab" if m["gender_raw"] in GENDER else None,
                "gender_alt": {"raw": m["gender_raw"]} if m["gender_raw"] and m["gender_raw"] not in GENDER else {},
                "cv_name_ja": m["cv_name_ja"], "cv_name_zh": None, "cv_uid": None, "hf_speakers": [],
                "images": images, "profile_texts": m["profile_texts"], "source_urls": m["source_urls"] + [dataset_url],
            }
        chars[uid]["hf_speakers"].append(s)
        file = archives.get(cfg["archive_alias"].get(s, s))
        if not file:
            log.warning("speaker %s: no Japanese archive", s)
            continue
        index, clip_meta = archive_meta(cfg, file)
        n = 0
        for member, j in sorted(clip_meta.items()):
            if j.get("voiceType") not in cfg["voice_types"] or norm(j.get("speaker") or "") != norm(s):
                continue
            stem = member.rsplit(".", 1)[0]
            n += 1
            clips.append({
                "clip_uid": f"{GAME}:{s}:{stem}", "char_uid": uid, "outfit_name": None,
                "category": f"character_vo/{j['voiceType']}", "category_norm": "other",  # no file name to classify
                "voice_scope": "character_vo", "speaker": s, "condition": None, "is_legacy": False,
                "text_ja": (j.get("transcription") or "").strip() or None, "text_zh": None,
                "text_source": "hf" if j.get("transcription") else None,
                "audio_file": member, "audio_path": str(RAW / "audio" / s / f"{stem}.flac"),
                "audio_url": f"hfzip://{cfg['hf_repo']}/{file}#{member}", "source_sha1": None,
                "source_url": dataset_url, "is_battle_shout": False,
            })
        log.info("%s -> %s %s (%s, CV %s): %d clips (index says %d)", s, uid, m["name_ja"],
                 chars[uid]["gender"], m["cv_name_ja"], n, counts[s])
    n1 = write_jsonl(ROOT / "manifests" / f"{GAME}_characters.jsonl", list(chars.values()))
    n2 = write_jsonl(ROOT / "manifests" / f"{GAME}_clips.jsonl", clips)
    log.info("wrote %d characters, %d clips; unresolved speakers left out: %s", n1, n2,
             [s for s in wanted if s not in to_entry])


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--speakers", nargs="*", help="HF speaker code(s) for a pilot run")
    build(ap.parse_args().speakers)
