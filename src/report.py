"""Generate reports/<game>_stats.md for each game and reports/summary.md across games.

    python -m src.report
"""
from __future__ import annotations

import csv
import statistics
from collections import Counter, defaultdict

from src.common.io import ROOT, read_jsonl

GENDERS = ["female", "male", "other", "unknown"]


def load_games() -> dict[str, tuple[list[dict], list[dict]]]:
    games = {}
    for f in sorted((ROOT / "manifests").glob("*_characters.jsonl")):
        game = f.name.removesuffix("_characters.jsonl")
        games[game] = (list(read_jsonl(f)), list(read_jsonl(ROOT / "manifests" / f"{game}_clips.jsonl")))
    return games


def table(header: list[str], rows: list[list]) -> str:
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(str(x) for x in r) + " |" for r in rows]
    return "\n".join(lines)


def hours(sec: float) -> str:
    return f"{sec / 3600:.2f} h"


def game_row(game: str, chars: list[dict], clips: list[dict]) -> list:
    usable = [c for c in clips if not c.get("exclude", True)]
    outfits = sum(1 + sum(1 for i in c["images"] if i["kind"] == "skin") for c in chars)
    g = Counter(c["gender"] for c in chars)
    n = max(1, len(chars))
    return [game, len(chars), outfits, len(clips), len(usable),
            hours(sum(c["duration_sec"] or 0 for c in usable)),
            " / ".join(f"{g[k] / n:.0%}" for k in GENDERS)]


def per_char_distribution(chars: list[dict], clips: list[dict]) -> str:
    cnt = Counter(c["char_uid"] for c in clips if not c.get("exclude", True))
    vals = [cnt.get(c["char_uid"], 0) for c in chars]
    if not vals:
        return "_no characters_"
    bins = [(0, 0), (1, 9), (10, 29), (30, 59), (60, 99), (100, 10**9)]
    rows = [[f"{lo}" if lo == hi else (f"{lo}+" if hi > 10**8 else f"{lo}–{hi}"),
             sum(lo <= v <= hi for v in vals)] for lo, hi in bins]
    q = statistics.quantiles(vals, n=4) if len(vals) > 1 else [vals[0]] * 3
    return (f"min {min(vals)}, p25 {q[0]:.0f}, median {q[1]:.0f}, p75 {q[2]:.0f}, max {max(vals)}\n\n"
            + table(["usable clips per character", "# characters"], rows))


def exclude_reasons(clips: list[dict]) -> str:
    c = Counter(r for clip in clips for r in clip.get("exclude_reasons", []))
    only = Counter(clip["exclude_reasons"][0] for clip in clips if len(clip.get("exclude_reasons", [])) == 1)
    dur = Counter(clip.get("duration_flag") for clip in clips if clip.get("duration_flag"))
    note = (f"\n\nDuration flags (not excluded): short (<1 s) {dur['short']}, long (>15 s) {dur['long']}; "
            f"of these, usable: short {sum(1 for c in clips if c.get('duration_flag') == 'short' and not c['exclude'])}, "
            f"long {sum(1 for c in clips if c.get('duration_flag') == 'long' and not c['exclude'])}.")
    return table(["reason", "clips flagged", "sole reason"], [[r, n, only[r]] for r, n in c.most_common()]) + note


def missing_fields(chars: list[dict], clips: list[dict]) -> str:
    has_clips = {c["char_uid"] for c in clips if not c.get("exclude", True)}
    rows = []
    for c in chars:
        miss = [label for label, bad in [
            ("cv", not c.get("cv_name_ja")), ("gender", c["gender"] == "unknown"),
            ("image", not c["images"]), ("usable_clips", c["char_uid"] not in has_clips)] if bad]
        if miss:
            rows.append([c["char_uid"], c["name_ja"], ", ".join(miss)])
    return table(["char_uid", "name_ja", "missing"], rows) if rows else "_none_"


def game_report(game: str, chars: list[dict], clips: list[dict]) -> str:
    norm = Counter((c["category_norm"], c.get("exclude", True)) for c in clips)
    cats = sorted({k for k, _ in norm})
    asr = sum(1 for c in clips if c.get("text_source") == "asr")
    legacy = sum(1 for c in clips if c.get("is_legacy") and not c.get("exclude", True))
    dupe_names = [k for k, v in Counter(c["name_ja"] for c in chars).items() if v > 1]
    return "\n\n".join([
        f"# {game} dataset stats",
        table(["game", "characters", "outfits (base+skins)", "clips", "usable clips", "usable duration",
               "female / male / other / unknown"], [game_row(game, chars, clips)]),
        "## Clips by category_norm\n\n" + table(
            ["category_norm", "usable", "excluded"],
            [[k, norm[(k, False)], norm[(k, True)]] for k in cats]),
        f"Text filled by Whisper ASR (text_source=asr): {asr}. "
        f"Usable clips flagged is_legacy (pre-remake recording): {legacy}.",
        "## Usable clips per character\n\n" + per_char_distribution(chars, clips),
        "## Exclusion reasons\n\n" + exclude_reasons(clips),
        "## name_ja shared by several characters (kept separate)\n\n"
        + (", ".join(dupe_names) if dupe_names else "_none_"),
        "## Characters with missing fields\n\n" + missing_fields(chars, clips),
    ]) + "\n"


def summary(games: dict) -> str:
    rows = [game_row(g, ch, cl) for g, (ch, cl) in games.items()]
    va_path = ROOT / "manifests" / "voice_actors.csv"
    va = list(csv.DictReader(open(va_path, encoding="utf-8"))) if va_path.exists() else []
    char_names = {c["char_uid"]: c["name_ja"] for ch, _ in games.values() for c in ch}
    roles: dict[str, list[str]] = defaultdict(list)
    for ch, _ in games.values():
        for c in ch:
            if c.get("cv_uid"):
                roles[c["cv_uid"]].append(c["char_uid"])
    top = sorted(va, key=lambda r: -len(roles.get(r["cv_uid"], [])))[:30]
    top_rows = [[r["cv_name_ja"], len(roles[r["cv_uid"]]), r["games"],
                 "、".join(dict.fromkeys(char_names[u] for u in roles[r["cv_uid"]]))[:80]]
                for r in top if len(roles.get(r["cv_uid"], [])) > 1]
    cross = sum(1 for r in va if "|" in r["games"])
    parts = [
        "# Dataset summary",
        "## Per game\n\n" + table(["game", "characters", "outfits (base+skins)", "clips", "usable clips",
                                   "usable duration", "female / male / other / unknown"], rows),
        f"## Voice actors\n\nDistinct voice actors: {len(va)} (cross-game: {cross}; "
        f"needs_review: {sum(r['needs_review'] == '1' for r in va)}). See manifests/voice_actors.csv.",
        "### Top 30 voice actors by number of characters\n\n"
        + table(["cv_name_ja", "# characters", "games", "characters"], top_rows),
    ]
    for g, (ch, cl) in games.items():
        parts.append(f"## {g}: usable clips per character\n\n" + per_char_distribution(ch, cl))
        parts.append(f"## {g}: exclusion reasons\n\n" + exclude_reasons(cl))
        parts.append(f"## {g}: characters with missing fields\n\n" + missing_fields(ch, cl))
    skipped = ROOT / "docs" / "sources" / "skipped.md"
    if skipped.exists():
        parts.append("## Skipped games\n\n" + skipped.read_text(encoding="utf-8").split("\n", 1)[1].strip())
    return "\n\n".join(parts) + "\n"


def run() -> None:
    games = load_games()
    (ROOT / "reports").mkdir(exist_ok=True)
    for g, (ch, cl) in games.items():
        (ROOT / "reports" / f"{g}_stats.md").write_text(game_report(g, ch, cl), encoding="utf-8")
    (ROOT / "reports" / "summary.md").write_text(summary(games), encoding="utf-8")


if __name__ == "__main__":
    run()
