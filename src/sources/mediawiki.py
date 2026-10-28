"""Small MediaWiki API helpers shared by wiki-based adapters."""
from __future__ import annotations

import re
from typing import Iterator

from src.common.http import PoliteSession


def get_wikitext(sess: PoliteSession, api: str, title: str) -> str | None:
    r = sess.get(api, params={"action": "parse", "page": title, "prop": "wikitext",
                              "format": "json", "redirects": 1})
    d = r.json()
    if "error" in d:
        return None
    return d["parse"]["wikitext"]["*"]


def ask_all(sess: PoliteSession, api: str, query: str, printouts: list[str],
            page_size: int = 500) -> Iterator[tuple[str, dict]]:
    """Semantic MediaWiki ask query with offset pagination."""
    offset = 0
    while True:
        q = query + "".join(f"|?{p}" for p in printouts) + f"|limit={page_size}|offset={offset}"
        d = sess.get(api, params={"action": "ask", "query": q, "format": "json"}).json()
        results = d["query"]["results"] or {}
        yield from results.items()
        nxt = d.get("query-continue-offset")
        if not nxt or not results:
            return
        offset = int(nxt)


def file_infos(sess: PoliteSession, api: str, filenames: list[str]) -> dict[str, dict]:
    """Resolve File: names to {url, sha1, size}, 50 per request. Keyed by the given name."""
    out: dict[str, dict] = {}
    for i in range(0, len(filenames), 50):
        batch = filenames[i:i + 50]
        d = sess.get(api, params={"action": "query", "prop": "imageinfo", "iiprop": "url|sha1|size",
                                  "titles": "|".join("File:" + f for f in batch),
                                  "format": "json"}).json()["query"]
        # map normalized titles back to requested names
        norm = {n["to"]: n["from"] for n in d.get("normalized", [])}
        for page in d.get("pages", {}).values():
            req = norm.get(page["title"], page["title"]).split(":", 1)[1]
            if page.get("imageinfo"):
                info = page["imageinfo"][0]
                out[req] = {"url": info["url"], "sha1": info.get("sha1"), "size": info.get("size")}
    return out


_TEMPLATE_KEEP_LAST = re.compile(r"\{\{(?:黑幕|heimu|color|颜色|lj|lang)\|(?:[^{}|]*\|)*([^{}|]*)\}\}", re.I)
_RUBY = re.compile(r"\{\{(?:ruby|注音)\|([^{}|]*)\|[^{}]*\}\}", re.I)
_LINK = re.compile(r"\[\[(?:[^\]|]*::)?(?:[^\]|]*\|)?([^\]]*)\]\]")


def strip_markup(s: str) -> str:
    """Wikitext -> plain text for voice lines (heimu/ruby templates, links, <br>, refs)."""
    s = re.sub(r"<ref[^>]*>.*?</ref>|<ref[^>]*/>", "", s, flags=re.S)
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.I)
    for _ in range(3):  # nested templates
        s = _RUBY.sub(r"\1", s)
        s = _TEMPLATE_KEEP_LAST.sub(r"\1", s)
    s = _LINK.sub(r"\1", s)
    s = re.sub(r"<[^>]+>", "", s)
    s = re.sub(r"'{2,}", "", s)
    return s.strip()
