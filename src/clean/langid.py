"""Whisper language check (+ ASR fallback when text_ja is missing).

Runs Whisper `small` on the 16 kHz cleaned WAV. Backend: batched MLX on Apple Silicon
(~3x faster), faster-whisper on CPU elsewhere. Cached per clip in
data/processed/<game>/langid.jsonl; reruns skip finished clips.

    python -m src.clean.langid fgo [--backend mlx|faster] [--batch 16]
"""
from __future__ import annotations

import argparse
import json
import logging
import platform

import soundfile as sf

from src.clean.audio import stats_path
from src.clean.finalize import needs_asr
from src.common.io import ROOT, read_jsonl

log = logging.getLogger("clean.langid")
MODEL = "small"


class MlxWhisper:
    repo = f"mlx-community/whisper-{MODEL}-mlx"

    def __init__(self):
        import mlx.core as mx
        from mlx_whisper.load_models import load_model
        self.mx, self.model = mx, load_model(self.repo)

    def detect(self, audios: list) -> list[tuple[str, float]]:
        from mlx_whisper.audio import N_SAMPLES, log_mel_spectrogram, pad_or_trim
        from mlx_whisper.decoding import detect_language
        mel = self.mx.stack([log_mel_spectrogram(pad_or_trim(self.mx.array(a), N_SAMPLES),
                                                 n_mels=self.model.dims.n_mels) for a in audios])
        _, probs = detect_language(self.model, mel)
        return [max(p.items(), key=lambda kv: kv[1]) for p in probs]

    def transcribe(self, audio) -> str:
        import mlx_whisper
        return mlx_whisper.transcribe(audio, path_or_hf_repo=self.repo, language="ja")["text"].strip()


class FasterWhisper:
    def __init__(self):
        from faster_whisper import WhisperModel
        self.model = WhisperModel(MODEL, device="cpu", compute_type="int8")

    def detect(self, audios: list) -> list[tuple[str, float]]:
        return [self.model.detect_language(a)[:2] for a in audios]

    def transcribe(self, audio) -> str:
        segs, _ = self.model.transcribe(audio, language="ja", beam_size=5)
        return "".join(s.text for s in segs).strip()


def run(game: str, backend: str | None = None, batch: int = 16) -> None:
    backend = backend or ("mlx" if platform.machine() == "arm64" and platform.system() == "Darwin" else "faster")
    out_path = ROOT / "data" / "processed" / game / "langid.jsonl"
    clips_by_uid = {c["clip_uid"]: c for c in read_jsonl(ROOT / "manifests" / f"{game}_clips.jsonl")}
    cached = {r["clip_uid"]: r for r in read_jsonl(out_path)}
    # redo clips that now need ASR but were checked without it
    done = {u for u, r in cached.items() if "asr_text_ja" in r or not needs_asr(clips_by_uid.get(u, {}))}
    stats = {r["clip_uid"]: r for r in read_jsonl(stats_path(game)) if "error" not in r}
    clips = [c for c in clips_by_uid.values() if c["clip_uid"] in stats and c["clip_uid"] not in done]
    log.info("%s: %d clips to check (%d cached), backend=%s", game, len(clips), len(done), backend)
    if not clips:
        return
    model = MlxWhisper() if backend == "mlx" else FasterWhisper()
    with open(out_path, "a", encoding="utf-8") as f:
        for i in range(0, len(clips), batch):
            chunk = clips[i:i + batch]
            audios = [sf.read(ROOT / stats[c["clip_uid"]]["wav16_path"], dtype="float32")[0] for c in chunk]
            for clip, audio, (lang, prob) in zip(chunk, audios, model.detect(audios)):
                row = {"clip_uid": clip["clip_uid"], "lang": lang, "lang_prob": round(float(prob), 3),
                       "whisper_model": f"{MODEL}/{backend}"}
                if needs_asr(clip):
                    row["asr_text_ja"] = model.transcribe(audio)
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
            f.flush()
            if (i // batch) % 25 == 0:
                log.info("%d/%d", i + len(chunk), len(clips))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("game")
    ap.add_argument("--backend", choices=["mlx", "faster"])
    ap.add_argument("--batch", type=int, default=16)
    a = ap.parse_args()
    run(a.game, a.backend, a.batch)
