"""Genshin / Star Rail / Wuthering Waves adapter.

Audio + JP transcription: Hugging Face ultemica/*-voices (ja), indexed by speaker.
Character metadata (CV, gender, profile text, art): BWIKI (ys, sr) or encore.moe (wuwa).
Story dialogue is kept and labelled voice_scope=story; character voice-over is character_vo.

    python -m src.sources.hfgames genshin [--names 芙宁娜 胡桃 ...]
"""
from __future__ import annotations

import argparse
import html
import json
import logging
import re
from collections import Counter, defaultdict
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


HOYOLAB_LIST = "https://sg-wiki-api.hoyolab.com/hoyowiki/{app}/wapi/get_entry_page_list"
HOYOLAB_PAGE = "https://sg-wiki-api-static.hoyolab.com/hoyowiki/{app}/wapi/entry_page"


def hoyolab_characters(sess: PoliteSession, cfg: dict, names: list[str] | None) -> list[dict]:
    """JP name/CV/art/profile + official JP voice lines from the HoYoLAB wiki API.
    The zh-cn list gives the names that join with HF speakers (same entry_page_id)."""
    app, menu = cfg["hoyolab"]["app"], cfg["hoyolab"]["menu_id"]
    hdr = lambda lang: {"x-rpc-language": lang, "x-rpc-wiki_app": app, "Referer": "https://wiki.hoyolab.com/"}
    text = lambda h: html.unescape(re.sub(r"<br\s*/?>|</p>\s*<p>", "\n", h or "")).strip()
    plain = lambda h: re.sub(r"<[^>]+>", "", text(h)).strip()

    def entries(lang: str) -> list[dict]:
        out, page = [], 1
        while True:
            d = sess.post(HOYOLAB_LIST.format(app=app), headers=hdr(lang),
                          json={"filters": [], "menu_id": menu, "page_num": page, "page_size": 30,
                                "use_es": True}).json()["data"]
            out += d["list"]
            if not d["list"] or len(out) >= int(d["total"]):
                return out
            page += 1

    zh = {e["entry_page_id"]: e["name"] for e in entries("zh-cn")}
    out = []
    for e in entries("ja-jp"):
        eid, name_zh = e["entry_page_id"], zh.get(e["entry_page_id"], e["name"])
        if names and name_zh not in names:
            continue
        page = sess.get(HOYOLAB_PAGE.format(app=app), params={"entry_page_id": eid},
                        headers=hdr("ja-jp")).json()["data"]["page"]
        mods: dict[str, dict] = {}
        for m in page["modules"]:
            for c in m["components"]:
                mods.setdefault(c["component_id"], json.loads(c["data"] or "{}"))
        base = {i["key"]: plain(i["value"][0]) for i in mods.get("baseInfo", {}).get("list", []) if i.get("value")}
        name_ja = page["name"]  # the ja-jp page title is the JP name (和名 may be ruby markup)
        name_en = (base.get("和名 / 英名") or "").rpartition(" / ")[2].strip() or None
        cv = next((v for k, v in base.items() if "日本語" in k and "CV" in k), None)
        url = f"https://wiki.hoyolab.com/pc/{app}/entry/{eid}"
        gallery = next((v for k, v in mods.items() if k.startswith("gallery")), {})
        images = []
        for i, g in enumerate(gallery.get("list") or []):
            img = g.get("img") or ""
            if not img or img.endswith(".gif") or "モーション" in g.get("key", ""):
                continue  # idle-animation gifs are not character art
            # 原画 (genshin) / 立ち絵 (hsr) = official character art; the rest are promo / birthday illustrations
            images.append({"kind": "base" if g.get("key") in ("原画", "立ち絵") else "other", "outfit_name": g.get("key"),
                           "source_url": img, "file": f"{eid}_{i}{Path(img).suffix or '.png'}"})
        profiles = [{"lang": "ja", "kind": st.get("title"), "condition": None, "text": plain(st.get("desc")),
                     "source_url": url} for st in mods.get("story", {}).get("list") or [] if st.get("desc")]
        voices = []
        for v in mods.get("voice", {}).get("list") or []:
            ja = next((a["url"] for a in v.get("audios") or []
                       if a.get("name") in ("日本語", "JP") and a.get("url")), None)  # genshin / hsr labels
            if ja:
                # genshin appends the unlock condition to the line text: move it to `condition`
                body, _, cond = plain(v.get("desc")).partition("解放条件：")
                voices.append({"id": v.get("id"), "title": plain(v.get("title")), "text": body.strip(),
                               "condition": cond.strip() or None, "url": ja})
        out.append({"id": str(eid), "name_zh": name_zh, "name_ja": name_ja or None, "name_en": name_en or None,
                    "gender_raw": base.get("性別"),  # 性別: zzz only
                    "cv_name_ja": cv, "images": images, "profile_texts": profiles,
                    "voice_lines": voices, "source_urls": [url]})
        log.info("%s %s / %s: %d images, %d stories, %d JP voice lines", eid, name_zh, name_ja,
                 len(images), len(profiles), len(voices))
    return out


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
        # Skins[].RoleStand is a shared placeholder (a quest icon / another character's texture),
        # so art comes from RolePortrait (full-body default) and each paid skin's share illustration.
        # encore's /api/resource/ URLs serve the SPA; the files live under /resource/.
        res = lambda u: re.sub(r"^https://api(?:-v2)?\.encore\.moe/api/resource/", ec["resource"], u)
        images = []
        if d.get("RolePortrait"):
            images.append({"kind": "base", "outfit_name": "default", "source_url": res(d["RolePortrait"]),
                           "file": f"{r['Id']}_portrait{Path(d['RolePortrait']).suffix}"})
        if d.get("FormationRoleCard"):  # half-body card; the only art encore has for the newest characters
            images.append({"kind": "card", "outfit_name": "default", "source_url": res(d["FormationRoleCard"]),
                           "file": f"{r['Id']}_card{Path(d['FormationRoleCard']).suffix}"})
        for sk in d.get("Skins") or []:
            if sk.get("ShareTexturePath"):
                images.append({"kind": "skin", "outfit_name": sk.get("Name"), "source_url": res(sk["ShareTexturePath"]),
                               "file": f"{r['Id']}_{sk['Id']}{Path(sk['ShareTexturePath']).suffix}"})
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
    the HF speaker with the same name. In a group the first listed page is the base; later
    pages are versions whose art and voice lines get that version's name as outfit_name.
    Official voice lines of a page shared by several groups (e.g. one Trailblazer page, two
    voices) are dropped, since we can't tell which voice they use."""
    def members(g: dict) -> list[dict]:
        ms = [m for m in meta
              if (m["name_zh"] in g.get("pages", []) or
                  (g.get("page_prefix") and m["name_zh"].startswith(g["page_prefix"])))
              and (not g.get("where_gender") or m["gender_raw"] == g["where_gender"])]
        order = g.get("pages", [])
        return sorted(ms, key=lambda m: order.index(m["name_zh"]) if m["name_zh"] in order else len(order))

    shared = defaultdict(int)
    for g in groups:
        for m in members(g):
            shared[id(m)] += 1
    used, out = set(), []
    for g in groups:
        pages = members(g)
        if not pages:
            continue
        used.update(id(m) for m in pages)
        images, texts, voices, seen_img, seen_txt = [], [], [], set(), set()
        for idx, m in enumerate(pages):
            outfit = m["name_ja"] if idx and g.get("pages") else None
            for i in m["images"]:
                if i["source_url"] in seen_img:
                    continue
                seen_img.add(i["source_url"])
                images.append(dict(i) | ({"kind": "skin" if i["kind"] == "base" else i["kind"],
                                          "outfit_name": f"{outfit} {i['outfit_name']}"} if outfit else {}))
            for t in m["profile_texts"]:
                if t["text"] not in seen_txt:
                    seen_txt.add(t["text"])
                    texts.append(t | ({"condition": outfit} if outfit else {}))
            if shared[id(m)] == 1:
                voices += [v | {"outfit": outfit} for v in m.get("voice_lines", [])]
        first = lambda k: next((m[k] for m in pages if m[k]), None)
        out.append({"id": g["name"], "name_zh": g["name"], "name_ja": g.get("name_ja") or first("name_ja"), "name_en": first("name_en"),
                    "gender_raw": first("gender_raw"), "gender_override": g.get("gender"),
                    "cv_name_ja": g.get("cv_name_ja") or first("cv_name_ja"), "images": images, "profile_texts": texts,
                    "source_urls": [u for m in pages for u in m["source_urls"]],
                    "speakers": g["speakers"], "pages": [m["name_zh"] for m in pages], "voice_lines": voices})
    for m in meta:
        if id(m) not in used:
            out.append(m | {"speakers": [m["name_zh"]], "gender_override": None})
    return out


def build(game: str, names: list[str] | None = None) -> None:
    cfg = load_config(game)
    raw = Path(f"data/raw/{game}")
    sess = PoliteSession(min_interval=cfg["rate_limit_sec"], host_intervals=cfg["host_rate_limit_sec"])
    provider = cfg["metadata"]["provider"]
    meta = (bwiki_characters(sess, cfg["metadata"]["wiki"], names) if provider == "bwiki"
            else hoyolab_characters(sess, cfg, names) if provider == "hoyolab"
            else encore_characters(sess, cfg, names))
    meta = apply_groups(meta, cfg.get("groups", []))

    index = build_index(cfg["hf_repo"], ROOT / raw / "hf_index.parquet").to_pylist()
    by_speaker: dict[str, list[dict]] = defaultdict(list)
    for r in index:
        by_speaker[r["speaker"]].append(r)
    vo_re = re.compile(cfg["voice_scope"]["character_vo"])
    norm_rules = {k: re.compile(v) for k, v in cfg["category_norm"].items() if k != "default"}
    shout_re = re.compile(cfg["battle_shout"])
    title_rules = {k: re.compile(v) for k, v in cfg.get("voice_title_norm", {}).items()}
    title_shout = re.compile(cfg.get("voice_title_shout", "(?!)"))

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
        seen_text, seen_stem = set(), set()
        vid_count = Counter(v["id"] for v in m.get("voice_lines", []))
        for v in m.get("voice_lines", []):  # official JP character voice-over (HoYoLAB)
            norm = next((k for k, rx in title_rules.items() if rx.search(v["title"])), "daily")
            seen_text.add(re.sub(r"\W", "", v["text"]))
            clip_uid = f"{game}:hl:{m['id']}:{v['id']}"
            if vid_count[v["id"]] > 1:  # HoYoLAB reuses voice ids across lines: add the file hash
                clip_uid += ":" + v["url"].rsplit("/", 1)[1][:8]
            clips.append({
                "clip_uid": clip_uid, "char_uid": uid, "outfit_name": v.get("outfit"),
                "category": f"character_vo/{v['title']}", "category_norm": norm,
                "voice_scope": "character_vo", "speaker": None, "condition": v.get("condition"), "is_legacy": False,
                "text_ja": v["text"] or None, "text_zh": None, "text_source": "hoyolab" if v["text"] else None,
                "audio_file": v["url"].rsplit("/", 1)[1],
                "audio_path": str(raw / "audio" / "hoyolab" / m["id"] / v["url"].rsplit("/", 1)[1]),
                "audio_url": v["url"], "source_sha1": None, "source_url": m["source_urls"][0],
                "is_battle_shout": norm == "battle" and bool(title_shout.search(v["title"])),
            })
        for r in rows:
            fname = r["source_path"].rsplit("/", 1)[1]
            stem = fname.rsplit(".", 1)[0]
            if stem in seen_stem:
                continue  # the HF set lists a few files twice
            seen_stem.add(stem)
            scope = "character_vo" if vo_re.search(fname) else "story"
            if scope == "story" and not cfg.get("include_story", True):
                continue
            norm = "other" if scope == "story" else next(
                (k for k, rx in norm_rules.items() if rx.search(fname)), cfg["category_norm"]["default"])
            text = (r["transcription"] or "").strip()
            if text and re.sub(r"\W", "", text) in seen_text:
                continue  # same line already taken from HoYoLAB
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
