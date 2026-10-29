"""Merge cleaning caches into manifests/<game>_clips.jsonl and apply exclusion rules.

Clips are never dropped: `exclude` + `exclude_reasons` mark them so thresholds can be
changed later. Idempotent — rerun after any cleaning step.

    python -m src.clean.finalize fgo
"""
from __future__ import annotations

import argparse
import logging
import re

from src.clean.audio import stats_path
from src.common.io import ROOT, read_jsonl, write_jsonl

log = logging.getLogger("clean.finalize")

# duration is only flagged (duration_flag), never excluded: the owner keeps all lengths for now
MIN_SEC, MAX_SEC = 1.0, 15.0
LANG_MIN_PROB = 0.5  # only exclude as non-Japanese when Whisper is reasonably sure
LANG_MIN_SEC = 2.0   # Whisper language ID is unreliable on short interjections
KANA = re.compile(r"[\u3040-\u30ff]")


def needs_asr(clip: dict) -> bool:
    """No source transcript, or a source 'JP' text that is really untranslated Chinese."""
    text = clip.get("text_ja") if clip.get("text_source") != "asr" else clip.get("text_ja_source")
    if clip.get("text_source") in (None, "asr") and not clip.get("text_ja_source"):
        return True
    return bool(text) and len(text) >= 8 and not KANA.search(text)

QUALITY_FIELDS = ["duration_sec", "sample_rate", "orig_sample_rate", "orig_duration_sec",
                  "loudness_lufs_orig", "trimmed_lead_sec", "trimmed_tail_sec",
                  "wav24_path", "wav16_path", "audio_sha1"]


def run(game: str) -> None:
    manifest = ROOT / "manifests" / f"{game}_clips.jsonl"
    stats = {}
    for r in read_jsonl(stats_path(game)):  # later rows win (reprocessed clips)
        stats[r["clip_uid"]] = r
    lang = {r["clip_uid"]: r for r in read_jsonl(ROOT / "data" / "processed" / game / "langid.jsonl")}

    seen_sha1: dict[str, str] = {}
    out = []
    for clip in read_jsonl(manifest):
        uid = clip["clip_uid"]
        st, lg = stats.get(uid, {}), lang.get(uid)
        for k in QUALITY_FIELDS:
            clip[k] = st.get(k)
        reasons = []
        clip["duration_flag"] = None
        if not clip.get("audio_url"):
            reasons.append("no_audio_source")
        elif not st:
            reasons.append("not_downloaded")
        elif "error" in st:
            reasons.append("decode_error")
        else:
            d = st["duration_sec"]
            clip["duration_flag"] = "short" if d < MIN_SEC else "long" if d > MAX_SEC else None
            dup_of = seen_sha1.setdefault(st["audio_sha1"], uid)
            clip["duplicate_of"] = dup_of if dup_of != uid else None
            if clip["duplicate_of"]:
                reasons.append("duplicate_audio")
        if clip.get("is_battle_shout"):
            reasons.append("battle_shout")

        clip["lang"] = lg["lang"] if lg else None
        clip["lang_prob"] = lg["lang_prob"] if lg else None
        clip["lang_uncertain"] = False
        if lg and lg["lang"] != "ja" and lg["lang_prob"] >= LANG_MIN_PROB:
            if (st.get("duration_sec") or 0) >= LANG_MIN_SEC:
                reasons.append("non_japanese")
            else:
                clip["lang_uncertain"] = True
        if needs_asr(clip) and lg and lg.get("asr_text_ja"):
            if clip.get("text_source") not in (None, "asr"):
                clip["text_ja_source"] = clip["text_ja"]  # keep the mismatched source text
            clip["text_ja"], clip["text_source"] = lg["asr_text_ja"], "asr"
        if not clip.get("text_ja"):
            reasons.append("no_text")

        clip["exclude_reasons"] = reasons
        clip["exclude"] = bool(reasons)
        out.append(clip)
    write_jsonl(manifest, out)
    log.info("%s: %d clips, %d usable", game, len(out), sum(not c["exclude"] for c in out))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("game")
    run(ap.parse_args().game)
