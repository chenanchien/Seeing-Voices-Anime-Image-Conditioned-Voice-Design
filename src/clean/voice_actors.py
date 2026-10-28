"""Build manifests/voice_actors.csv and write cv_uid back into every <game>_characters.jsonl.

Primary key: the Japanese name, normalized only by NFKC + whitespace removal (safe merges).
Aliases (zh / en / romaji) are attached only when a source pairs them with exactly one
Japanese name on the same character. Anything ambiguous goes to needs_review instead of
being merged.

    python -m src.clean.voice_actors
"""
from __future__ import annotations

import csv
import hashlib
import logging
import re
import unicodedata
from collections import defaultdict

from src.common.io import ROOT, read_jsonl, write_jsonl

log = logging.getLogger("clean.voice_actors")
MULTI_SEP = re.compile(r"[、,，/／&＆]| and ")
ALIAS_FIELDS = ["cv_name_zh", "cv_name_en"]


def norm_key(name: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", name))


def cv_uid(key: str) -> str:
    return "cv_" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:10]


def run() -> None:
    files = sorted((ROOT / "manifests").glob("*_characters.jsonl"))
    actors: dict[str, dict] = {}
    alias_to_keys: dict[str, set[str]] = defaultdict(set)
    notes: dict[str, list[str]] = defaultdict(list)

    def actor(key: str, raw: str) -> dict:
        return actors.setdefault(key, {"cv_name_ja": raw, "spellings": set(), "aliases": set(),
                                       "games": set(), "chars": set()})

    all_chars = {f: list(read_jsonl(f)) for f in files}
    for chars in all_chars.values():
        for c in chars:
            raw = c.get("cv_name_ja")
            if not raw:
                continue
            parts = [p.strip() for p in MULTI_SEP.split(raw) if p.strip()]
            if len(parts) > 1:  # several CVs on one character: register each, keep uid empty
                for p in parts:
                    a = actor(norm_key(p), p)
                    a["games"].add(c["game"]); a["chars"].add(c["char_uid"])
                    notes[norm_key(p)].append(f"listed jointly on {c['char_uid']} ({raw})")
                continue
            key = norm_key(raw)
            a = actor(key, raw)
            a["spellings"].add(raw)
            a["games"].add(c["game"]); a["chars"].add(c["char_uid"])
            for field in ALIAS_FIELDS:
                alias = c.get(field)
                if not alias:
                    continue
                if MULTI_SEP.search(alias):
                    notes[key].append(f"{field} lists several names on {c['char_uid']}: {alias}")
                    continue
                if norm_key(alias) != key:
                    a["aliases"].add(alias)
                    alias_to_keys[norm_key(alias)].add(key)

    for alias, keys in alias_to_keys.items():
        if len(keys) > 1:  # same alias paired with different Japanese names
            for k in keys:
                notes[k].append(f"alias '{alias}' also pairs with {sorted(keys - {k})}")
    for key, a in actors.items():
        if len(a["spellings"]) > 1:
            notes[key].append(f"merged spellings {sorted(a['spellings'])}")

    out = ROOT / "manifests" / "voice_actors.csv"
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["cv_uid", "cv_name_ja", "aliases", "games", "n_characters", "needs_review", "review_note"])
        for key, a in sorted(actors.items(), key=lambda kv: (-len(kv[1]["chars"]), kv[0])):
            w.writerow([cv_uid(key), a["cv_name_ja"], "|".join(sorted(a["aliases"])),
                        "|".join(sorted(a["games"])), len(a["chars"]),
                        int(bool(notes[key])), "; ".join(dict.fromkeys(notes[key]))])
    log.info("wrote %s: %d voice actors, %d need review", out.name, len(actors),
             sum(1 for k in actors if notes[k]))

    for path, chars in all_chars.items():
        for c in chars:
            raw = c.get("cv_name_ja")
            c["cv_uid"] = cv_uid(norm_key(raw)) if raw and not MULTI_SEP.search(raw) else None
        write_jsonl(path, chars)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    run()
