"""Score generated speech (needs the `embed` and `eval` extras: uv sync --extra embed --extra eval).

Input is a CSV with one row per generated utterance: char_uid, method, path (audio file,
any sample rate) and text (the Japanese sentence it should say; optional, only for CER).
Characters, parts and reference clips come from the baseline split.json (Tianxiang's
filtered split: reference_ids are the five clips behind each prototype).

    python -m src.evaluate --outputs outputs.csv          # Oracle / B1 / B2 / ... rows
    python -m src.evaluate --real                         # reference row from held-out real clips

Metrics (all with the WavLM-SV verifier, never the TTS's own speaker encoder):
    secs        cosine to the character's reference prototype (mean of its reference clips)
    mismatch    mean cosine to the other characters' prototypes in the same part
    top1, top5  rank of the true character among all prototypes of the part
    seen/unseen secs split by whether the actor voices a training character (splits/main.csv)
    gender_acc  a logistic-regression gender classifier on WavLM embeddings of real training
                clips, applied to the generated speech (female/male characters only)
    f0_corr     Pearson correlation across characters of median F0, generated vs reference clips
    cer         Whisper large-v3-turbo transcript vs text, characters after NFKC with
                punctuation, spaces and ruby markup removed
    cer_kana    the same after converting both to hiragana (pykakasi); kanji readings are
                ambiguous (今日は -> こんにちは), so this is a secondary check

Per-file features are cached in data/eval/features.jsonl, keyed by path and mtime.
UTMOS is not computed yet.
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import random
import re
import unicodedata
from collections import defaultdict
from pathlib import Path

import numpy as np

from src.common.io import ROOT
from src.dataset import load_clips, load_embeddings, load_split

log = logging.getLogger("evaluate")
SPLIT_JSON = ROOT / "data/embeddings/qwen-speaker-prototypes-10games-raw/split.json"
OUT = ROOT / "data" / "eval"
ASR_REPO = "mlx-community/whisper-large-v3-turbo"
RUBY = re.compile(r"\{RUBY_B#[^}]*\}|\{RUBY_E#\}")


def read_audio(path: str, sr: int = 16000) -> np.ndarray:
    import librosa
    return librosa.load(path, sr=sr, mono=True)[0]


class Features:
    """WavLM-SV embedding, median F0 and Whisper transcript per audio file, cached."""

    def __init__(self, asr: bool):
        self.path = OUT / "features.jsonl"
        self.cache: dict[str, dict] = {}
        if self.path.exists():
            for line in open(self.path, encoding="utf-8"):
                r = json.loads(line)
                self.cache[r["key"]] = r
        self.asr, self._wavlm, self._whisper = asr, None, None

    def _key(self, path: str) -> str:
        return f"{path}@{Path(path).stat().st_mtime_ns}"

    def wavlm(self, wavs: list[np.ndarray]) -> np.ndarray:
        import torch
        from transformers import AutoFeatureExtractor, WavLMForXVector
        from src.embed import MODELS, min_length, unit
        if self._wavlm is None:
            self._wavlm = (AutoFeatureExtractor.from_pretrained(MODELS["wavlm-sv"]),
                           WavLMForXVector.from_pretrained(MODELS["wavlm-sv"]).eval())
        fe, model = self._wavlm
        wavs = [min_length(w[:15 * 16000]) for w in wavs]
        inp = fe(wavs, sampling_rate=16000, padding=True, return_attention_mask=True, return_tensors="pt")
        with torch.no_grad():
            return unit(model(**inp).embeddings).astype(np.float32)

    @staticmethod
    def f0(wav: np.ndarray) -> float | None:
        import librosa
        f, voiced, _ = librosa.pyin(wav, fmin=60, fmax=800, sr=16000, frame_length=1024)
        f = f[voiced & np.isfinite(f)]
        return float(np.median(f)) if len(f) else None

    def transcribe(self, wav: np.ndarray) -> str:
        import mlx_whisper
        return mlx_whisper.transcribe(wav, path_or_hf_repo=ASR_REPO, language="ja")["text"].strip()

    def get(self, paths: list[str]) -> dict[str, dict]:
        todo = [p for p in dict.fromkeys(paths) if self._key(p) not in self.cache
                or (self.asr and "asr" not in self.cache[self._key(p)])]
        with open(self.path, "a", encoding="utf-8") as f:
            for s in range(0, len(todo), 16):
                chunk = todo[s:s + 16]
                wavs = [read_audio(p) for p in chunk]
                embs = self.wavlm(wavs)
                for p, w, e in zip(chunk, wavs, embs):
                    r = {"key": self._key(p), "path": p, "emb": e.round(5).tolist(), "f0": self.f0(w)}
                    if self.asr:
                        r["asr"] = self.transcribe(w)
                    self.cache[r["key"]] = r
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
                f.flush()
                log.info("features %d/%d", min(s + 16, len(todo)), len(todo))
        return {p: self.cache[self._key(p)] for p in paths}


def norm(text: str) -> str:
    return re.sub(r"[\W_]", "", unicodedata.normalize("NFKC", RUBY.sub("", text or "")))


def hira(text: str) -> str:
    import pykakasi
    return "".join(t["hira"] for t in pykakasi.kakasi().convert(norm(text)))


def cer(ref: str, hyp: str, kana: bool = False) -> float | None:
    ref, hyp = (hira(ref), hira(hyp)) if kana else (norm(ref), norm(hyp))
    if not ref:
        return None
    prev = list(range(len(hyp) + 1))
    for i, a in enumerate(ref, 1):
        cur = [i]
        for j, b in enumerate(hyp, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (a != b)))
        prev = cur
    return prev[-1] / len(ref)


def characters() -> tuple[list[dict], dict[str, dict]]:
    rows = json.load(open(SPLIT_JSON, encoding="utf-8"))
    info = {c["char_uid"]: c for p in ("train", "val", "test") for c in load_split(p, ROOT)}
    return rows, info


def gender_classifier(rows: list[dict], info: dict[str, dict], spk: dict[str, np.ndarray]):
    from sklearn.linear_model import LogisticRegression
    X, y = [], []
    for r in rows:
        c = info[r["char_uid"]]
        if r["part"] != "train" or c["gender"] not in ("female", "male"):
            continue
        clips = load_clips([c], ROOT, max_per_char=20 if c["gender"] == "female" else 60, seed=1)
        X += [spk[k["clip_uid"]] for k in clips]
        y += [c["gender"] == "male"] * len(clips)
    return LogisticRegression(max_iter=2000, class_weight="balanced").fit(np.stack(X).astype(np.float32), y)


def real_outputs(rows: list[dict], info: dict[str, dict], part: str, per_char: int = 3) -> list[dict]:
    """Held-out real clips (non-battle, 1-15 s, not a reference clip) as a reference 'method'."""
    out = []
    for r in rows:
        if r["part"] != part:
            continue
        pool = [x for x in load_clips([info[r["char_uid"]]], ROOT, exclude_categories=["battle"], rate=16)
                if 1 <= x["duration_sec"] <= 15 and x["clip_uid"] not in r["reference_ids"]]
        random.Random(r["char_uid"]).shuffle(pool)
        out += [{"char_uid": r["char_uid"], "method": "real", "path": x["audio_path"],
                 "text": x.get("text_ja") or ""} for x in pool[:per_char]]
    return out


def score(outputs: list[dict], part: str, asr: bool) -> dict[str, dict]:
    rows, info = characters()
    rows_part = [r for r in rows if r["part"] == part]
    spk = load_embeddings("wavlm-sv", ROOT)
    uids = [r["char_uid"] for r in rows_part]
    idx = {u: i for i, u in enumerate(uids)}
    P = np.stack([np.mean([spk[k] for k in r["reference_ids"]], 0, dtype=np.float32) for r in rows_part])
    P /= np.linalg.norm(P, axis=1, keepdims=True)
    clips = {x["clip_uid"]: x for r in rows_part for x in load_clips([info[r["char_uid"]]], ROOT, rate=16)}
    ref_f0 = {}
    ref_feats = Features(asr=False).get([clips[k]["audio_path"] for r in rows_part for k in r["reference_ids"]])
    for r in rows_part:
        f = [ref_feats[clips[k]["audio_path"]]["f0"] for k in r["reference_ids"]]
        f = [x for x in f if x]
        ref_f0[r["char_uid"]] = float(np.median(f)) if f else None
    clf = gender_classifier(rows, info, spk)

    outputs = [o for o in outputs if o["char_uid"] in idx]
    feats = Features(asr=asr).get([o["path"] for o in outputs])
    by_method = defaultdict(list)
    for o in outputs:
        by_method[o["method"]].append(o)
    results = {}
    for method, os_ in by_method.items():
        E = np.stack([np.asarray(feats[o["path"]]["emb"], np.float32) for o in os_])
        S = E @ P.T
        t = np.array([idx[o["char_uid"]] for o in os_])
        matched = S[np.arange(len(t)), t]
        rank = (S > matched[:, None]).sum(1)
        mism = (S.sum(1) - matched) / (len(uids) - 1)
        seen = np.array([info[o["char_uid"]]["actor_seen"] for o in os_])
        g = np.array([info[o["char_uid"]]["gender"] for o in os_])
        known = np.isin(g, ["female", "male"])
        pred = clf.predict(E[known])
        f0g = defaultdict(list)
        for o in os_:
            if feats[o["path"]]["f0"]:
                f0g[o["char_uid"]].append(feats[o["path"]]["f0"])
        pairs = [(np.mean(v), ref_f0[u]) for u, v in f0g.items() if ref_f0.get(u)]
        res = {"n_utts": len(os_), "n_chars": len(set(t)), "secs": matched.mean(), "mismatch": mism.mean(),
               "gap": matched.mean() - mism.mean(), "top1": (rank == 0).mean() * 100, "top5": (rank < 5).mean() * 100,
               "secs_seen": matched[seen == "seen"].mean(), "secs_unseen": matched[seen == "unseen"].mean(),
               "gender_acc": (pred == (g[known] == "male")).mean() * 100,
               "f0_corr": float(np.corrcoef(np.log([a for a, _ in pairs]), np.log([b for _, b in pairs]))[0, 1])}
        if asr:
            for name, kana in (("cer", False), ("cer_kana", True)):
                c = [cer(o.get("text", ""), feats[o["path"]].get("asr", ""), kana) for o in os_]
                c = [x for x in c if x is not None]
                res[name] = float(np.mean(c)) * 100 if c else None
        results[method] = {k: (round(float(v), 4) if v is not None else None) for k, v in res.items()}
    return results


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--outputs", help="CSV: char_uid, method, path[, text]")
    ap.add_argument("--real", action="store_true", help="score held-out real clips as method 'real'")
    ap.add_argument("--part", default="test")
    ap.add_argument("--no-asr", action="store_true", help="skip Whisper / CER")
    ap.add_argument("--tag", default="results")
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    outs = []
    if a.outputs:
        with open(a.outputs, encoding="utf-8") as f:
            outs += list(csv.DictReader(f))
    if a.real:
        rows, info = characters()
        outs += real_outputs(rows, info, a.part)
    res = score(outs, a.part, asr=not a.no_asr)
    (OUT / f"{a.tag}_{a.part}.json").write_text(json.dumps(res, indent=1, ensure_ascii=False))
    for m, r in res.items():
        print(m, json.dumps(r, ensure_ascii=False))
