"""Build the fixed train/val/test splits under splits/ (settings in configs/splits.yaml).

Unit: the character. Versions of one character (Azur Lane META / μ兵装 / ちゃん, FGO 〔オルタ〕,
Arknights alternate operators, Fate collab characters in Star Rail, ...) form a group that
always lands in one split. Two characters are grouped when they share a voice actor and,
within one game, one name stem contains the other; across games the stems must be equal.

    main            80/10/10 over groups, stratified by (game, gender). val/test characters
                    get actor_seen = seen | unseen | unknown (does a train character share a CV?)
                    and train characters get train_frac, the smallest nested subset (0.25 /
                    0.5 / 1.0) that contains them.
    actor_disjoint  80/10/10 over connected components of characters that share any actor
                    or group, so no voice actor appears in two splits.

Outputs: splits/main.csv, splits/actor_disjoint.csv, splits/groups.csv (every multi-member
group, for review) and splits/excluded.csv (characters not eligible, with the reason).

    python -m src.splits
"""
from __future__ import annotations

import csv
import logging
import random
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

from src.clean.voice_actors import MULTI_SEP, cv_key_name, cv_uid, norm_key
from src.common.io import ROOT, load_config
from src.report import load_games

log = logging.getLogger("splits")
OUT = ROOT / "splits"
PARTS = ["train", "val", "test"]


def name_stem(c: dict) -> str:
    """Name without version decorations: 大鳳(META) / 大鳳ちゃん / 〔オルタ〕 -> base name."""
    n = unicodedata.normalize("NFKC", c.get("name_ja") or c.get("name_en") or "")
    n = re.sub(r"[(〔\[【].*?[)〕\]】]", "", n)
    n = re.sub(r"ちゃん$", "", n)
    return re.sub(r"[\s・=＝]", "", n)


def actor_ids(c: dict) -> list[str]:
    """cv_uids of every actor listed on the character (several for joint casts)."""
    raw = cv_key_name(c)
    return sorted({cv_uid(norm_key(p.strip())) for p in MULTI_SEP.split(raw) if p.strip()}) if raw else []


class UnionFind:
    def __init__(self):
        self.parent: dict[str, str] = {}

    def find(self, x: str) -> str:
        self.parent.setdefault(x, x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[max(ra, rb)] = min(ra, rb)


def find_groups(chars: list[dict], cfg: dict) -> dict[str, str]:
    """{char_uid: group id (smallest member char_uid)}."""
    separate = {frozenset(p) for p in cfg["separate"]}
    by_actor = defaultdict(list)
    for c in chars:
        for a in actor_ids(c):
            by_actor[a].append(c)
    uf = UnionFind()
    for c in chars:
        uf.find(c["char_uid"])
    for cs in by_actor.values():
        for i, x in enumerate(cs):
            for y in cs[i + 1:]:
                sx, sy = name_stem(x), name_stem(y)
                if frozenset((x["char_uid"], y["char_uid"])) in separate or min(len(sx), len(sy)) < 2:
                    continue
                if sx == sy or (x["game"] == y["game"] and (sx in sy or sy in sx)):
                    uf.union(x["char_uid"], y["char_uid"])
    for members in cfg["merge"]:
        for m in members[1:]:
            uf.union(members[0], m)
    return {c["char_uid"]: uf.find(c["char_uid"]) for c in chars}


def assign(units: dict[str, list[dict]], strata: dict[str, str], fractions: dict[str, float],
           rng: random.Random) -> dict[str, str]:
    """{unit id: part}. Within each stratum, units (largest first, random order among equal
    sizes) go to the part furthest below its target share of characters."""
    by_stratum = defaultdict(list)
    for u in sorted(units):
        by_stratum[strata[u]].append(u)
    out = {}
    for s in sorted(by_stratum):
        us = by_stratum[s]
        rng.shuffle(us)
        us.sort(key=lambda u: -len(units[u]))
        count, total = Counter(), 0
        for u in us:
            total += len(units[u])
            part = max(PARTS, key=lambda p: (fractions[p] * total - count[p], fractions[p]))
            out[u] = part
            count[part] += len(units[u])
    return out


def majority(values) -> str:
    return Counter(values).most_common(1)[0][0]


def eligibility(chars: list[dict], clips: list[dict], cfg: dict) -> tuple[list[dict], list[dict]]:
    nonbattle = Counter(c["char_uid"] for c in clips if not c.get("exclude", True) and c["category_norm"] != "battle")
    e = cfg["eligible"]
    keep, dropped = [], []
    for c in chars:
        n_img = sum(1 for i in c["images"] if i.get("path") and (ROOT / i["path"]).exists())
        reason = ("no image on disk" if n_img < e["min_images"] else
                  f"{nonbattle[c['char_uid']]} non-battle clips" if nonbattle[c["char_uid"]] < e["min_nonbattle_clips"] else None)
        (dropped if reason else keep).append({**c, "_reason": reason, "_n_img": n_img})
    return keep, dropped


def write_csv(path: Path, header: list[str], rows: list[list]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def run() -> None:
    cfg = load_config("splits")
    chars, dropped = [], []
    for game, (cs, clips) in load_games().items():
        keep, drop = eligibility(cs, clips, cfg)
        chars += keep
        dropped += drop
    chars.sort(key=lambda c: c["char_uid"])
    by_uid = {c["char_uid"]: c for c in chars}
    group = find_groups(chars, cfg)
    groups = defaultdict(list)
    for c in chars:
        groups[group[c["char_uid"]]].append(c)
    stratum = {g: f"{majority(c['game'] for c in cs)}/{majority(c['gender'] for c in cs)}" for g, cs in groups.items()}

    # main: character-disjoint
    main = assign(groups, stratum, cfg["fractions"], random.Random(cfg["seed"]))
    part = {u: main[group[u]] for u in by_uid}
    train_actors = {a for u in by_uid if part[u] == "train" for a in actor_ids(by_uid[u])}

    def seen(c):
        a = actor_ids(c)
        return "unknown" if not a else "seen" if set(a) & train_actors else "unseen"

    # nested train subsets: same stratification, smallest fraction that contains the group
    rng, frac = random.Random(cfg["seed"] + 1), {}
    by_stratum = defaultdict(list)
    for g in sorted(groups):
        if main[g] == "train":
            by_stratum[stratum[g]].append(g)
    for gs in by_stratum.values():
        rng.shuffle(gs)
        total, done = sum(len(groups[g]) for g in gs), 0
        for g in gs:
            done += len(groups[g])
            frac[g] = next((f for f in sorted(cfg["train_subsets"]) if done <= f * total + 1e-9), 1.0)

    OUT.mkdir(exist_ok=True)
    write_csv(OUT / "main.csv", ["char_uid", "game", "name_ja", "gender", "group_id", "cv_uids", "split", "actor_seen", "train_frac"],
              [[u, c["game"], c["name_ja"], c["gender"], group[u], "|".join(actor_ids(c)), part[u],
                seen(c) if part[u] != "train" else "", frac.get(group[u], "") if part[u] == "train" else ""]
               for u, c in by_uid.items()])

    # actor_disjoint: components linked by shared actors and by groups
    uf = UnionFind()
    for c in chars:
        nodes = [f"grp:{group[c['char_uid']]}"] + [f"cv:{a}" for a in actor_ids(c)]
        for n in nodes[1:]:
            uf.union(nodes[0], n)
    comps = defaultdict(list)
    for c in chars:
        comps[uf.find(f"grp:{group[c['char_uid']]}")].append(c)
    comp_stratum = {k: majority(c["gender"] for c in cs) for k, cs in comps.items()}
    ad = assign(comps, comp_stratum, cfg["fractions"], random.Random(cfg["seed"] + 2))
    ad_part = {c["char_uid"]: ad[k] for k, cs in comps.items() for c in cs}
    write_csv(OUT / "actor_disjoint.csv", ["char_uid", "game", "name_ja", "gender", "group_id", "cv_uids", "split"],
              [[u, c["game"], c["name_ja"], c["gender"], group[u], "|".join(actor_ids(c)), ad_part[u]]
               for u, c in by_uid.items()])

    multi = sorted((g for g, cs in groups.items() if len(cs) > 1), key=lambda g: (-len(groups[g]), g))
    write_csv(OUT / "groups.csv", ["group_id", "size", "cross_game", "split", "members"],
              [[g, len(groups[g]), len({c["game"] for c in groups[g]}) > 1, main[g],
                " | ".join(f"{c['char_uid']} {c['name_ja']}" for c in groups[g])] for g in multi])
    write_csv(OUT / "excluded.csv", ["char_uid", "game", "name_ja", "reason"],
              [[c["char_uid"], c["game"], c["name_ja"], c["_reason"]] for c in sorted(dropped, key=lambda c: c["char_uid"])])

    for name, p in (("main", part), ("actor_disjoint", ad_part)):
        n = Counter(p.values())
        log.info("%s: %s characters; largest unit %d", name, {k: n[k] for k in PARTS},
                 max(len(v) for v in (groups if name == "main" else comps).values()))
    log.info("main val/test actor_seen: %s", dict(Counter(seen(by_uid[u]) for u in by_uid if part[u] != "train")))
    log.info("main train subsets: %s", dict(Counter(frac[group[u]] for u in by_uid if part[u] == "train")))
    log.info("%d eligible characters in %d groups (%d multi-member, %d cross-game); %d excluded",
             len(chars), len(groups), len(multi), sum(len({c['game'] for c in groups[g]}) > 1 for g in multi), len(dropped))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    run()
