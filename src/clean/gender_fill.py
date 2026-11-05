"""Fill gender from configs/gender/<game>.csv where the game's own source has none.

The tables hold char_uid, gender, gender_source and the evidence for each label:
genshin-db (game data), a cited web page, or `manual` (owner-approved annotation, with the
basis written out). Characters already labelled by their source are left alone.

    python -m src.clean.gender_fill            # every game with a table
    python -m src.clean.gender_fill starrail
"""
from __future__ import annotations

import argparse
import csv
import logging

from src.common.io import ROOT, read_jsonl, write_jsonl

log = logging.getLogger("clean.gender_fill")


def run(game: str) -> None:
    with open(ROOT / "configs" / "gender" / f"{game}.csv", encoding="utf-8") as f:
        table = {r["char_uid"]: r for r in csv.DictReader(f)}
    path = ROOT / "manifests" / f"{game}_characters.jsonl"
    chars, n = list(read_jsonl(path)), 0
    for c in chars:
        r = table.get(c["char_uid"])
        if r and c.get("gender") in (None, "unknown") and r["gender"] != "unknown":
            c["gender"], c["gender_source"] = r["gender"], r["gender_source"]
            c["gender_alt"] = {**(c.get("gender_alt") or {}), "evidence": r["evidence"]}
            n += 1
    write_jsonl(path, chars)
    missing = [c["name_ja"] for c in chars if c.get("gender") in (None, "unknown")]
    log.info("%s: filled %d, still unknown %d %s", game, n, len(missing), missing)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("games", nargs="*")
    games = ap.parse_args().games or sorted(p.stem for p in (ROOT / "configs" / "gender").glob("*.csv"))
    for g in games:
        run(g)
