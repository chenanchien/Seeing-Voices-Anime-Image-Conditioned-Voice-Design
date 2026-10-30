"""Assemble Azur Lane paintings from algwiki.moe's extracted game assets.

algwiki serves each skin as a texture atlas + mesh (painting/<skin>.png/.obj), a layer
description (painting/<skin>.json) and face overlays (paintingface/<skin>/<n>.png). The atlas
alone is a jumble of patches; this is a Python port of algwiki's own compositor
(algwiki.moe/js/azurlane_compositor.js) that puts the pieces back together.

Source files are cached in data/raw/azurlane/painting_src/, the assembled PNG is written to
the image path in manifests/azurlane_characters.jsonl. Resumable: done images are skipped.

    python -m src.sources.azurlane_paint [--limit-chars 3]
"""
from __future__ import annotations

import argparse
import io
import json
import logging
import math
import os
from pathlib import Path

import requests
from PIL import Image, ImageOps

from src.common.http import PoliteSession
from src.common.io import ROOT, load_config, read_jsonl

log = logging.getLogger("azurlane_paint")
SRC = ROOT / "data" / "raw" / "azurlane" / "painting_src"
FACE_FIX = {  # per-painting face offsets, copied from the JS compositor
    "longxiang_3": [-1, 0, -1, 0], "u110_6_n": [0, -1, 0, -1], "kelifulan_6_n": [0, -1, 0, -1],
    "baerdimo_6_n": [0, -1, 0, -1], "yalisangna_2_n": [0, -1, 0, -1], "yalisangna_2_n_hx": [0, -1, 0, -1],
    "xifujiniya": [0, 0, 0, 1], "qiye_8_n": [0, -1, 0, -1], "xiefeierde_3_n": [0, -1, 0, -1],
    "xiefeierde_4": [0, 0, 0, -1], "manchesite_3_n": [0, -1, 0, -1], "ouruola_3": [0, 0, -1, 0],
    "ouruola_h": [0, -1, 0, -1], "safuke": [0, 0, 0, -1], "safuke_hx": [0, 0, 0, -1],
    "yueke_h_n": [0, -1, 0, -1], "guanghui": [0, 0, -1, 0], "shengli": [0, -1, 0, -1],
    "shenxue_3_n": [0, -1, 0, -1], "xiao_4_n": [0, -1, 0, -1], "xiao_5_n": [0, -1, 0, -1],
    "jiahe_4_n": [0, -1, 0, -1], "dafeng_5": [-1, 0, -1, 0], "xipeierhaijunshangjiang_3_n": [0, -1, 0, -1],
    "bisimai_h_n": [0, -5, 0, -5], "huonululu_5_n": [0, -1, 0, -1], "dachao_2": [0, 0, 1, 0],
    "lemaer_4_n": [0, -1, 0, -1], "mingniabolisi": [0, 0, 0, -1], "mingniabolisi_hx": [0, 0, 0, -1],
    "mingniabolisi_3": [-1, 0, -1, 0], "mingniabolisi_3_n": [-1, 0, -1, 0], "u73_4_n": [0, -1, 0, -1],
    "shuixingjinian_3_n": [0, -1, 0, -1], "qiabayefu_2": [0, 0, 0, -1], "qiabayefu_2_n": [0, 0, 0, -1],
    "linuo_5_n": [0, -1, 0, -1], "changbo_4_n": [0, -1, 0, -1], "wokelan_2_n": [0, -1, 0, -1],
}


def rnd(n: float) -> int:
    """Round half up, as the original Python tool does."""
    f = math.floor(n)
    return f + 1 if n - f == 0.5 else round(n)


def flip(im: Image.Image) -> Image.Image:
    return ImageOps.flip(im)


class Fetcher:
    """Cached GETs of algwiki assets; returns None on 404."""

    def __init__(self, sess: PoliteSession, base: str):
        self.sess, self.base = sess, base

    def get(self, rel: str) -> bytes | None:
        dest = SRC / rel
        miss = dest.with_name(dest.name + ".404")
        if dest.exists():
            return dest.read_bytes()
        if miss.exists():
            return None
        try:
            data = self.sess.get(f"{self.base}/{rel}").content
        except requests.HTTPError as e:
            if getattr(e.response, "status_code", None) in (403, 404):
                miss.parent.mkdir(parents=True, exist_ok=True)
                miss.touch()
                return None
            raise
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        return data

    def image(self, rel: str) -> Image.Image | None:
        data = self.get(rel)
        return Image.open(io.BytesIO(data)).convert("RGBA") if data else None


def parse_obj(text: str, tw: int, th: int) -> tuple[list, list]:
    verts, uvs = [], []
    for line in text.splitlines():
        t = line.split()
        if t and t[0] == "v":
            verts.append((-float(t[1]), float(t[2])))
        elif t and t[0] == "vt":
            uvs.append((tw * float(t[1]), th * (1 - float(t[2]))))
    return verts, uvs


def mesh_canvas(tex: Image.Image, verts: list, uvs: list, size: dict) -> Image.Image:
    patches, cw, ch = [], 0, 0
    for i in range(len(uvs) // 4):
        u0, u1 = uvs[i * 4 + 1], uvs[i * 4 + 3]
        v0, v2 = verts[i * 4], verts[i * 4 + 2]
        sx, sy, ex, ey = rnd(u0[0]), rnd(u0[1]), rnd(u1[0]), rnd(u1[1])
        pw, ph = ex - sx, ey - sy
        if pw <= 0 or ph <= 0:
            continue
        cw, ch = max(cw, v0[0] + pw), max(ch, v2[1])
        patches.append((tex.crop((sx, sy, ex, ey)), v0[0], v2[1] - ph))
    out = Image.new("RGBA", (rnd(max(size["x"], cw)), rnd(max(size["y"], ch))))
    for p, vx, vy in patches:
        out.alpha_composite(flip(p), (rnd(vx), rnd(vy)))
    return flip(out)


def position_box(layer: dict, by_id: dict, x=None, y=None, w=None, h=None) -> list[float]:
    if x is None:
        x = layer["bound"]["x"] * layer["pivot"]["x"] - layer["position"]["x"]
        y = layer["bound"]["y"] * layer["pivot"]["y"] - layer["position"]["y"]
        w, h = layer["bound"]["x"], layer["bound"]["y"]
    if layer.get("parent") is not None:
        parent = by_id.get(layer["parent"])
        if not parent:
            return [-x, -y, w - x, h - y]
        w *= parent["scale"]["x"]
        h *= parent["scale"]["y"]
        x = x * parent["scale"]["x"] - parent["position"]["x"]
        y = y * parent["scale"]["y"] - parent["position"]["y"]
        return position_box(parent, by_id, x, y, w, h)
    return [-x, -y, w - x, h - y]


def compute_boxes(layers: list, name: str) -> tuple[int, int] | None:
    by_id = {l["id"]: l for l in layers}
    for l in layers:
        if l.get("size"):
            l["box"] = position_box(l, by_id)
    fix = [0.0, 0.0]
    rw = next((l for l in layers if l.get("box") and "_rw" in (l.get("name") or "")), None)
    if rw:
        fix = [rnd(rw["box"][0]) - rw["box"][0], rnd(rw["box"][1]) - rw["box"][1]]
    else:
        root = next((l for l in layers if l.get("parent") is None and l.get("box")), None)
        if root:
            child = next((l for l in layers if l.get("box") and l.get("parent") is not None
                          and l.get("name") in (root["name"], "paint")), None)
            if child:
                fix = [rnd(child["box"][0]) - child["box"][0], rnd(child["box"][1]) - child["box"][1]]
    ff = FACE_FIX.get(name, [0, 0, 0, 0])
    for l in layers:
        b = l.get("box")
        if not b:
            continue
        if l.get("name") == "face":
            b[0] += fix[0] + ff[0]
            b[1] += fix[1] + ff[1]
            b[2] += fix[0] + ff[2]
            b[3] += fix[1] + ff[3]
            b[2] = rnd(b[0]) + b[2] - b[0]
            b[3] = rnd(b[1]) + b[3] - b[1]
        b[0], b[1] = rnd(b[0]), rnd(b[1])
    boxed = [l["box"] for l in layers if l.get("box")]
    if not boxed:
        return None
    x0, y0 = min(b[0] for b in boxed), min(b[1] for b in boxed)
    x1, y1 = max(b[2] for b in boxed), max(b[3] for b in boxed)
    for b in boxed:
        b[0] -= x0; b[1] -= y0; b[2] -= x0; b[3] -= y0
    return rnd(x1 - x0), rnd(y1 - y0)


def rotate(im: Image.Image, layer: dict) -> tuple[Image.Image, float, float]:
    a = 2 * math.atan2(layer["rotation"]["z"], layer["rotation"]["w"])
    w, h = im.size
    out = im.rotate(math.degrees(a), expand=True, resample=Image.BICUBIC)
    nw, nh = out.size
    px, py = layer["pivot"]["x"] * w, layer["pivot"]["y"] * h
    dx, dy = px - w / 2, py - h / 2
    return (out, px - (nw / 2 + dx * math.cos(a) - dy * math.sin(a)),
            py - (nh / 2 + dx * math.sin(a) + dy * math.cos(a)))


def scaled(im: Image.Image, w: float, h: float) -> Image.Image:
    return im.resize((max(1, rnd(w)), max(1, rnd(h))), Image.LANCZOS)


def compose(f: Fetcher, skin: str) -> Image.Image | None:
    raw = f.get(f"painting/{skin}.json")
    if not raw:
        return None
    layers = json.loads(raw)["layers"]
    tex: dict[str, Image.Image | None] = {}
    meshes: dict[str, tuple | None] = {}
    for l in layers:
        if l.get("texture") and l["texture"] not in tex:
            tex[l["texture"]] = f.image(f"painting/{l['texture']}")
        if l.get("mesh") and l["mesh"] not in meshes:
            t, obj = tex.get(l.get("texture")), f.get(f"painting/{l['mesh']}")
            meshes[l["mesh"]] = parse_obj(obj.decode("utf-8"), *t.size) if obj and t else None
    dims = compute_boxes(layers, skin)
    if not dims:
        return None
    face_key = next((k for k in ("0", "1") if f.get(f"paintingface/{skin}/{k}.png")), None)
    face = f.image(f"paintingface/{skin}/{face_key}.png") if face_key else None
    face_sub = f.image(f"paintingface/{skin}/{face_key}_sub.png") if face_key else None

    out = Image.new("RGBA", dims)
    for l in layers:
        b = l.get("box")
        if not b:
            continue
        bw, bh = b[2] - b[0], b[3] - b[1]
        t, m, name = tex.get(l.get("texture")), meshes.get(l.get("mesh")), l.get("name")
        if m and t:
            c = mesh_canvas(t, *m, l["size"])
            im = flip(scaled(c, c.width * (bw or l["size"]["x"]) / l["size"]["x"],
                             c.height * (bh or l["size"]["y"]) / l["size"]["y"]))
        elif t and name not in ("face", "face_sub"):
            im = flip(scaled(t, bw or t.width, bh or t.height))
        elif name in ("face", "face_sub") and (face if name == "face" else face_sub):
            src = face if name == "face" else face_sub
            im = flip(scaled(src, bw or src.width, bh or src.height))
        else:
            continue
        bx, by = b[0], b[1]
        if l.get("rotation") and l["rotation"]["z"] != 0:
            im, dx, dy = rotate(im, l)
            bx, by = bx + dx, by + dy
        need = (max(out.width, im.width + rnd(bx)), max(out.height, im.height + rnd(by)))
        if need != out.size:
            grown = Image.new("RGBA", need)
            grown.paste(out, (0, 0))
            out = grown
        layer_img = Image.new("RGBA", out.size)
        layer_img.paste(im, (rnd(bx), rnd(by)))
        out = Image.alpha_composite(out, layer_img)
    out = flip(out)
    bbox = out.getbbox()  # trim fully transparent margins
    return out.crop(bbox) if bbox else None


def run(limit_chars: int | None = None) -> dict:
    cfg = load_config("azurlane")
    sess = PoliteSession(min_interval=cfg["rate_limit_sec"])
    f = Fetcher(sess, cfg["painting_base"])
    stats = {"ok": 0, "skipped": 0, "missing": 0, "failed": 0}
    chars = list(read_jsonl(ROOT / "manifests" / "azurlane_characters.jsonl"))[:limit_chars]
    for i, c in enumerate(chars, 1):
        for img in c["images"]:
            dest = ROOT / img["path"]
            if dest.exists():
                stats["skipped"] += 1
                continue
            try:
                im = compose(f, img["painting"])
            except Exception as e:  # odd layer layouts: record and continue
                log.warning("%s: %s", img["painting"], e)
                stats["failed"] += 1
                continue
            if im is None:
                stats["missing"] += 1
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp = dest.with_suffix(".part.png")
            im.save(tmp)
            os.replace(tmp, dest)
            stats["ok"] += 1
        if i % 20 == 0 or i == len(chars):
            log.info("%d/%d characters %s", i, len(chars), stats)
    return stats


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit-chars", type=int)
    run(ap.parse_args().limit_chars)
