"""FGO adapter: Atlas Academy (characters, CV, gender, art) + Mooncell (JP voice lines).

Writes manifests/fgo_characters.jsonl and manifests/fgo_clips.jsonl (pre-cleaning fields).

    python -m src.sources.fgo                 # all servants
    python -m src.sources.fgo --ids 1 2 11    # pilot on selected collectionNo
"""
from __future__ import annotations

import argparse
import json
import logging
import re
from pathlib import Path

from src.common.http import PoliteSession
from src.common.io import ROOT, load_config, write_jsonl
from src.sources.mediawiki import ask_all, file_infos, get_wikitext, strip_markup

log = logging.getLogger("fgo")
GAME = "fgo"
RAW = Path("data/raw/fgo")
MOONCELL_GENDER = {"女性": "female", "男性": "male"}


# ---------- Atlas ----------

def load_atlas(sess: PoliteSession, cfg: dict) -> tuple[list[dict], dict[int, str]]:
    cache = ROOT / RAW / "atlas"
    cache.mkdir(parents=True, exist_ok=True)
    out = []
    for key in ("servants_export", "names_en_export"):
        url = cfg["atlas"][key]
        dest = cache / url.rsplit("/", 1)[1]
        if not dest.exists():
            log.info("downloading %s", url)
            dest.write_bytes(sess.get(url).content)
        out.append(json.loads(dest.read_text(encoding="utf-8")))
    servants, basic_en = out
    names_en = {s["collectionNo"]: s["name"] for s in basic_en}
    return servants, names_en


def atlas_images(svt: dict) -> list[dict]:
    no = svt["collectionNo"]
    graph = svt["extraAssets"]["charaGraph"]
    costumes = svt["profile"].get("costume") or {}
    imgs = []
    for asc, url in sorted((graph.get("ascension") or {}).items(), key=lambda kv: int(kv[0])):
        imgs.append({"kind": "base" if asc == "1" else "ascension", "outfit_name": f"ascension_{asc}",
                     "source_url": url})
    for cid, url in (graph.get("costume") or {}).items():
        name = costumes.get(cid, {}).get("name", cid)
        imgs.append({"kind": "skin", "outfit_name": name, "source_url": url})
    for img in imgs:
        img["path"] = str(RAW / "images" / f"{no:03d}" / img["source_url"].rsplit("/", 1)[1])
    return imgs


# ---------- Mooncell ----------

def iter_voice_tables(wikitext: str):
    """Yield (section_title, [row dicts]) for each {{#invoke:VoiceTable|table ...}} block."""
    for m in re.finditer(r"\{\{#invoke:VoiceTable\|table", wikitext):
        depth, i = 0, m.start()
        while i < len(wikitext):
            if wikitext.startswith("{{", i):
                depth += 1; i += 2; continue
            if wikitext.startswith("}}", i):
                depth -= 1; i += 2
                if depth == 0:
                    break
                continue
            i += 1
        body = wikitext[m.end():i - 2]
        body = re.sub(r"</?noinclude>", "", body)
        title_m = re.search(r"\|表格标题=([^\n|]*)", body)
        section = title_m.group(1).strip() if title_m else ""
        rows: dict[int, dict] = {}
        for fm in re.finditer(r"^\|([^\d=\n|]+?)(\d+)=(.*?)(?=^\||\Z)", body, flags=re.M | re.S):
            rows.setdefault(int(fm.group(2)), {})[fm.group(1).strip()] = fm.group(3).strip()
        yield section, [rows[k] for k in sorted(rows)]


def categorize(section: str, title: str, cfg: dict) -> str:
    rules = cfg["category_rules"]
    sec_norm = next((r["norm"] for r in rules["section"] if section.startswith(r["prefix"])), None)
    if sec_norm is None:
        return rules["default"]  # event / mission sections
    return next((r["norm"] for r in rules["title"] if title.startswith(r["prefix"])), sec_norm)


def outfit_from(section: str, condition: str) -> str | None:
    m = re.match(r"灵衣[（(](.+)[)）]$", section)
    if m:
        return m.group(1)
    if "灵衣" in condition:
        return condition
    return None


def mooncell_clips(sess: PoliteSession, cfg: dict, no: int, page: str) -> list[dict]:
    api = cfg["mooncell"]["api"]
    wt = get_wikitext(sess, api, page + cfg["mooncell"]["voice_page_suffix"])
    if wt is None:
        log.warning("no voice page for %s (%s)", no, page)
        return []
    page_url = f"https://fgo.wiki/w/{page}{cfg['mooncell']['voice_page_suffix']}"
    clips, seen = [], set()
    for section, rows in iter_voice_tables(wt):
        for row in rows:
            title = strip_markup(row.get("标题", ""))
            fname = row.get("语音", "").strip()
            cond = strip_markup(row.get("条件", ""))
            stem = fname.rsplit(".", 1)[0] if fname else f"{section}_{title}_{len(clips)}"
            uid = f"{GAME}:{no}:{stem}"
            if uid in seen:  # same audio reused on the page
                continue
            seen.add(uid)
            ja = strip_markup(row.get("日文", ""))
            norm = categorize(section, title, cfg)
            clips.append({
                "clip_uid": uid,
                "char_uid": f"{GAME}:{no}",
                "outfit_name": outfit_from(section, cond),
                "category": f"{section}/{title}",
                "category_norm": norm,
                "condition": cond or None,
                # lines recorded before a remake may predate a CV change (e.g. Mash)
                "is_legacy": "重制前" in cond,
                "text_ja": ja or None,
                "text_zh": strip_markup(row.get("中文", "")) or None,
                "text_source": "wiki" if ja else None,
                "audio_file": fname or None,
                "audio_path": str(RAW / "audio" / f"{no:03d}" / fname.replace("/", "_")) if fname else None,
                "audio_url": None,
                "source_sha1": None,
                "source_url": page_url,
                "is_battle_shout": norm == "battle" and any(
                    title.startswith(p) for p in cfg["battle_shout_titles"]),
            })
    infos = file_infos(sess, api, [c["audio_file"] for c in clips if c["audio_file"]])
    for c in clips:
        info = infos.get(c["audio_file"] or "")
        if info:
            c["audio_url"], c["source_sha1"] = info["url"], info["sha1"]
    missing = sum(1 for c in clips if c["audio_file"] and not c["audio_url"])
    if missing:
        log.warning("%s: %d audio files not found on wiki", page, missing)
    return clips


def mooncell_index(sess: PoliteSession, cfg: dict) -> dict[int, dict]:
    idx = {}
    for page, res in ask_all(sess, cfg["mooncell"]["api"], cfg["mooncell"]["servant_query"],
                             ["序号", "日文名称", "声优", "性别"]):
        p = res["printouts"]
        try:
            no = int(p["序号"][0])
        except (IndexError, ValueError):
            continue
        idx[no] = {"page": page,
                   "cv_zh": [c["fulltext"] if isinstance(c, dict) else c for c in p.get("声优", [])],
                   "gender": p["性别"][0] if p.get("性别") else None}
    return idx


# ---------- main ----------

def build(ids: list[int] | None = None) -> None:
    cfg = load_config(GAME)
    sess = PoliteSession(min_interval=cfg["rate_limit_sec"], host_intervals=cfg["host_rate_limit_sec"])
    servants, names_en = load_atlas(sess, cfg)
    mc = mooncell_index(sess, cfg)
    log.info("atlas servants: %d, mooncell servants: %d", len(servants), len(mc))

    chars, clips = [], []
    for svt in sorted(servants, key=lambda s: s["collectionNo"]):
        no = svt["collectionNo"]
        if no <= 0 or svt["type"] not in cfg["atlas"]["servant_types"]:
            continue
        if ids and no not in ids:
            continue
        m = mc.get(no, {})
        gender_mc = MOONCELL_GENDER.get(m.get("gender") or "", "unknown") if m else None
        chars.append({
            "char_uid": f"{GAME}:{no}",
            "game": GAME,
            "name_ja": svt["name"],
            "name_zh": m.get("page"),
            "name_en": names_en.get(no),
            "gender": svt.get("gender") or "unknown",
            "gender_source": "atlas",
            "gender_alt": {"mooncell": gender_mc} if m else {},
            "cv_name_ja": (svt["profile"].get("cv") or "").strip() or None,
            "cv_name_zh": "、".join(m.get("cv_zh", [])) or None,
            "cv_uid": None,  # filled by src.clean.voice_actors
            "images": atlas_images(svt),
            "source_urls": [f"https://apps.atlasacademy.io/db/JP/servant/{no}"]
                           + ([f"https://fgo.wiki/w/{m['page']}"] if m else []),
        })
        if m:
            got = mooncell_clips(sess, cfg, no, m["page"])
            log.info("%03d %s: %d clips", no, m["page"], len(got))
            clips.extend(got)
        else:
            log.warning("%03d %s: not found on Mooncell", no, svt["name"])

    n1 = write_jsonl(ROOT / "manifests" / f"fgo_characters.jsonl", chars)
    n2 = write_jsonl(ROOT / "manifests" / f"fgo_clips.jsonl", clips)
    log.info("wrote %d characters, %d clips", n1, n2)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids", type=int, nargs="*")
    build(ap.parse_args().ids)
