"""Azur Lane voice lines straight from algwiki.moe ship pages, for ships the HF dump lacks.

The HF dump (TLME/AzurLane-voice-transcription) holds 617 ship groups; the JP game has ~860
playable ones (e.g. USS Enterprise, 霞, μ兵装 variants are missing). Each algwiki ship page
lists every voice file with its zh / ja / en line in one table row:

    <tr><th>Login</th><td><audio src="../assets/cue/cv-10706/login.ogg"></td>
        <td>zh</td><td>ja</td><td>en</td></tr>

which is the same {voice URL: JP text} the dump's char.json gives, so src.sources.azurlane
treats both alike. Pages are cached under data/raw/azurlane/pages (robots.txt: none).
"""
from __future__ import annotations

import html
import logging
import re
from collections import Counter
from pathlib import Path

from src.common.http import PoliteSession
from src.sources.girlsfrontline import page

log = logging.getLogger("azurlane_algwiki")
RAW = Path("data/raw/azurlane")
ROW = re.compile(r'<tr>\s*<th[^>]*>.*?</th>\s*<td>\s*<audio[^>]*src="\.\./(assets/cue/[^"]+\.ogg)"[^>]*>\s*</audio>\s*</td>'
                 r'\s*<td>(.*?)</td>\s*<td>(.*?)</td>', re.S)


def cell(s: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", s)).strip()


def ship_voices(doc: str, base: str) -> dict[str, str]:
    """{absolute voice URL: JP line} for one ship page."""
    return {f"{base}/{src}": cell(ja) for src, _zh, ja in ROW.findall(doc)}


def missing_ships(sess: PoliteSession, cfg: dict, have: set[int], group_of) -> dict[str, tuple[str, dict[str, str]]]:
    """{algwiki slug: (ship name, voices)} for ship groups not in `have`. `group_of(url)` gives
    a voice URL's ship group; a page belongs to the group most of its voice URLs name."""
    a = cfg["algwiki"]
    listing = page(sess, a["ship_list"], RAW / "pages" / "shiplist.html") or ""
    slugs = sorted(set(re.findall(r'ships/([^"/]+)\.html', listing)))
    out, seen = {}, set(have)
    for slug in slugs:
        doc = page(sess, cfg["ship_page"].format(slug=slug), RAW / "pages" / f"{slug}.html")
        voices = ship_voices(doc or "", a["base"])
        if not voices:
            continue
        group = Counter(group_of(u) for u in voices).most_common(1)[0][0]
        if group in seen:
            continue
        seen.add(group)
        title = re.search(r"<title>/alg/ Wiki - (.*?)</title>", doc)
        out[slug] = (cell(title.group(1)) if title else slug, voices)
    log.info("algwiki: %d ship pages, %d ships not in the HF dump", len(slugs), len(out))
    return out
