"""Add official art from the Blue Archive Wiki (bluearchive.wiki, Miraheze) gallery pages to
manifests/bluearchive_characters.jsonl. SchaleDB gives one portrait per style; the gallery
adds each style's Memorial Lobby illustration (new pose and scene) and, as kind "promo",
the JP student card and pickup banner (official art with text overlays).

Expression sprites (<Name>_00..NN) are the portrait's pose with other faces and are left out;
fan kit, event, loading and 4-koma images show several characters and are left out too.

Runs after src.sources.bluearchive (which rewrites the manifest) and before src.download.
Gallery pages are cached under data/raw/bluearchive/pages; rerunning replaces the wiki images.

    python -m src.sources.bluearchive_gallery
    python -m src.sources.bluearchive_gallery --ids 10060 10065   # pilot by char_uid number
"""
from __future__ import annotations

import argparse
import logging
import re
from collections import Counter
from pathlib import Path
from urllib.parse import quote, unquote

from src.common.http import PoliteSession
from src.common.io import ROOT, load_config, read_jsonl, write_jsonl
from src.sources.bluearchive import load_json, style_name
from src.sources.girlsfrontline import page

log = logging.getLogger("bluearchive_gallery")
GAME = "bluearchive"
RAW = Path("data/raw/bluearchive")
SOURCE = "bluearchive.wiki"
THUMB = re.compile(r'src="(?:https:)?//static\.wikitide\.net/bluearchivewiki/thumb/([0-9a-f]/[0-9a-f]{2}/[^/"]+)/')


def gallery_files(doc: str) -> dict[str, str]:
    """{file name: full-size url} for every gallery image on the page."""
    out = {}
    for item in re.findall(r'<li class="gallerybox".*?</li>', doc, re.S):
        m = THUMB.search(item)
        if m:
            out[unquote(m.group(1).rsplit("/", 1)[-1])] = f"https://static.wikitide.net/bluearchivewiki/{m.group(1)}"
    return out


def wiki_name(en: str, g: dict) -> str:
    """SchaleDB English style name -> wiki file stem part ('Aris (Armed)' -> 'Arisu_(Battle)')."""
    for old, new in g["title_override"].items():
        en = re.sub(rf"^{re.escape(old)}\b", new, en)
    en = re.sub(r"\((.+)\)$", lambda m: f"({g['outfit_alias'].get(m.group(1), m.group(1))})", en)
    return en.replace(" ", "_")


def run(ids: list[str] | None = None) -> None:
    cfg = load_config(GAME)
    g = cfg["wiki_gallery"]
    sess = PoliteSession(min_interval=cfg["rate_limit_sec"], host_intervals=cfg["host_rate_limit_sec"])
    names_en, names_ja = ({i: s["Name"] for i, s in load_json(sess, cfg, lang, "students.min.json").items()}
                          for lang in ("en", "jp"))
    names_ja.update({str(i): o["Name"] for i, o in cfg["style_override"].items()})
    path = ROOT / "manifests" / f"{GAME}_characters.jsonl"
    chars, added, no_page = list(read_jsonl(path)), Counter(), []
    for c in chars:
        if ids and c["char_uid"].split(":")[1] not in ids:
            continue
        c["images"] = [i for i in c["images"] if i.get("source") != SOURCE]
        styles = [str(s) for s in c["style_ids"]]
        base_en = names_en.get(styles[0])
        if not base_en:
            continue
        base_en = g["title_override"].get(base_en, re.sub(r"\s*\(.+\)$", "", base_en))
        title = quote(f"{base_en}/gallery".replace(" ", "_"), safe="_()'./-")
        url = g["page"].format(title=title)
        doc = page(sess, url, RAW / "pages" / f"{styles[0]}.html")
        if not doc:
            no_page.append(c["name_ja"])
            continue
        # file stem suffix (English style name, spaces as "_") -> the style's outfit_name
        outfit = {wiki_name(names_en[s], g): style_name({"Name": names_ja[s]})
                  for s in styles if s in names_en and s in names_ja}
        for file, src in gallery_files(doc).items():
            m = re.fullmatch(r"(Memorial_Lobby|Card_Jp|Banner_Jp)_(.+?)(?:_(\d+))?\.(png|jpe?g)", file, re.I)
            if not m or m.group(2) not in outfit:
                continue
            kind = "memorial_lobby" if m.group(1) == "Memorial_Lobby" else "promo"
            c["images"].append({"kind": kind, "outfit_name": outfit[m.group(2)] or "default",
                                "source_url": src, "source": SOURCE, "source_page": url,
                                "has_text_overlay": kind == "promo",
                                "path": str(RAW / "images" / "wiki" / file)})
            added[kind] += 1
        log.info("%s %s: %d images (%s)", c["char_uid"], c["name_ja"], len(c["images"]),
                 ", ".join(f"{i['kind']}:{i['outfit_name']}" for i in c["images"] if i.get("source") == SOURCE))
    write_jsonl(path, chars)
    log.info("added %s; no gallery page for %d: %s", dict(added), len(no_page), no_page)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids", nargs="*", help="char_uid number(s) for a pilot run")
    run(ap.parse_args().ids)
