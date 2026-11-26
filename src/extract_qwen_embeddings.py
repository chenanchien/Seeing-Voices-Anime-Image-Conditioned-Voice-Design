"""Standalone Qwen speaker embedding extraction, matching the corrected baselines.

Install qwen-tts==0.1.1, torch (CUDA), soundfile, numpy, huggingface-hub.
Example:
  python extract_qwen_embeddings.py --cloud /path/to/cloud --split split.json --output speaker_prototypes.npz
Use --allow-download only if the pinned checkpoint is not already cached.

Audio: mono 24 kHz, read as float32; no external padding, resampling, trimming,
or normalization. Qwen computes its own mel features, one clip at a time.
Model runs in BF16; embeddings are converted to CPU float32 before averaging.
Both per-clip embeddings and character prototypes retain their native scale.
"""
import argparse
from collections import Counter, defaultdict
import io
import json
import os
from pathlib import Path
import tarfile

import numpy as np
import soundfile as sf
import torch

MODEL = "Qwen/Qwen3-TTS-12Hz-1.7B-Base"
MODEL_REVISION = "dc3a91051aad39bf1f66d58cd89988b3b1084f0b"


def load_model(allow_download=False):
    from huggingface_hub import snapshot_download
    from qwen_tts import Qwen3TTSModel
    snapshot = snapshot_download(repo_id=MODEL, revision=MODEL_REVISION,
                                 local_files_only=not allow_download)
    return Qwen3TTSModel.from_pretrained(snapshot, device_map="cuda:0", dtype=torch.bfloat16,
                                         attn_implementation="sdpa", local_files_only=True)


def read_audio(source):
    """Read a path or file-like object exactly as in the baseline."""
    audio, rate = sf.read(source, dtype="float32")
    if rate != 24000 or audio.ndim != 1:
        raise ValueError("Expected mono 24 kHz audio")
    if not len(audio) or not np.isfinite(audio).all():
        raise ValueError("Empty or non-finite audio")
    return audio, rate


def extract(model, audio, rate):
    """Native Qwen encoder; no external padding, batching or L2 normalization."""
    if rate != 24000 or audio.ndim != 1:
        raise ValueError("Expected mono 24 kHz audio")
    with torch.inference_mode():
        value = model.model.extract_speaker_embedding(audio=audio, sr=rate)
    value = value.detach().float().cpu().reshape(-1)
    if value.shape != (2048,) or not torch.isfinite(value).all():
        raise ValueError("Invalid Qwen embedding")
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cloud", type=Path, required=True, help="Directory containing the game TAR archives")
    parser.add_argument("--split", type=Path, required=True, help="Corrected baseline split.json")
    parser.add_argument("--output", type=Path, default=Path("speaker_prototypes.npz"))
    parser.add_argument("--per-clip-output", type=Path, help="Optional NPZ of individual selected reference embeddings")
    parser.add_argument("--allow-download", action="store_true")
    parser.add_argument("--plan-only", action="store_true", help="Validate IDs without loading Qwen")
    args = parser.parse_args()
    plan = json.loads(args.split.read_text(encoding="utf8"))
    if len({r['char_uid'] for r in plan}) != len(plan) or any(len(r['reference_ids']) != 5 or len(set(r['reference_ids'])) != 5 for r in plan):
        raise ValueError("Expected unique characters and five distinct references per character")
    print("Split:", dict(Counter(r['part'] for r in plan)), flush=True)
    groups = defaultdict(list)
    for index, row in enumerate(plan):
        groups[row['game']].append((index, row))
    prototypes = [None] * len(plan)
    clip_vectors = {}
    model = None if args.plan_only else load_model(args.allow_download)
    for game, rows in sorted(groups.items()):
        with tarfile.open(args.cloud / f"seeing-voices_{game}.tar") as archive:
            clips = {}
            duplicates = set()
            with archive.extractfile(f"{game}/{game}_clips.jsonl") as manifest:
                for line in manifest:
                    if not line.strip():
                        continue
                    clip = json.loads(line)
                    uid = clip['clip_uid']
                    if uid in clips:
                        duplicates.add(uid)
                    clips[uid] = clip
            for count, (index, row) in enumerate(rows, 1):
                refs = []
                for uid in row['reference_ids']:
                    if uid not in clips or uid in duplicates or clips[uid]['char_uid'] != row['char_uid']:
                        raise ValueError(f"Invalid reference mapping: {row['char_uid']} / {uid}")
                    refs.append(clips[uid])
                if args.plan_only:
                    continue
                vecs = []
                for clip in refs:
                    with archive.extractfile(clip['audio']) as stream:
                        audio, rate = read_audio(io.BytesIO(stream.read()))
                    vector = extract(model, audio, rate)
                    vecs.append(vector)
                    if args.per_clip_output:
                        clip_vectors[clip['clip_uid']] = vector.numpy()
                prototypes[index] = torch.stack(vecs).mean(0).numpy()
                if count % 25 == 0 or count == len(rows):
                    print(f"{game}: {count}/{len(rows)}", flush=True)
            print(f"Validated {game}: {len(rows)} characters", flush=True)
    if args.plan_only:
        return
    emb = np.stack(prototypes)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('xb') as file:
        np.savez_compressed(file, keys=np.array([r['char_uid'] for r in plan]), emb=emb,
                            speaker_embedding_scale=np.array('raw_mean_v1'))
    if args.per_clip_output:
        args.per_clip_output.parent.mkdir(parents=True, exist_ok=True)
        with args.per_clip_output.open('xb') as file:
            np.savez_compressed(file, keys=np.array(list(clip_vectors)), emb=np.stack(list(clip_vectors.values())),
                                speaker_embedding_scale=np.array('raw_clip_v1'))
    print(f"Saved {args.output}: {emb.shape}, mean L2 norm={np.linalg.norm(emb, axis=1).mean():.4f}", flush=True)


if __name__ == '__main__':
    main()
