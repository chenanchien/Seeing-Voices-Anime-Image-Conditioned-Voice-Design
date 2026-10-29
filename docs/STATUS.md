# Pipeline status

Last updated: 2026-10-28 21:10 (computer about to shut down; downloads interrupted).

## How to resume

```bash
cd Seeing-Voices-Anime-Image-Conditioned-Voice-Design
nohup caffeinate -i scripts/resume.sh > data/logs/resume.log 2>&1 &
tail -f data/logs/fgo_full.log      # or arknights_full.log / bluearchive_full.log
```

`scripts/resume.sh` runs download → audio → langid → finalize for FGO, Arknights and Blue Archive in parallel (one worker per host, each host rate-limited), then voice_actors and report. Everything already done is skipped:
- downloads: existing files are skipped (FGO also checks sha1); interrupted `.part` files are re-fetched
- audio cleaning and Whisper: per-clip caches in `data/processed/<game>/`; a line cut off by the shutdown is ignored and that clip is redone
- adapters are **not** rerun: manifests are already complete, so no new wiki crawling

`caffeinate -i` keeps the Mac from sleeping while it runs (close the lid only if on power / clamshell).

## Progress at shutdown

| Game | Manifest | Download progress | Then |
|---|---|---|---|
| FGO | complete: 471 characters, 45,829 clips | ~2,200 / 45,685 audio (~1 clip/s → ~12 h left) | audio, langid, finalize |
| Arknights | complete: 366 characters, 15,319 clips | ~600 / 15,319 (torappu is slow, ~15 h) | same |
| Blue Archive | complete: 151 characters, 18,607 clips | ~1,800 / 18,607 (~5 h) | same |
| Genshin / Star Rail / WuWa | pilot only (3 characters each) | not started | waiting on decisions below |

FGO `profile_texts` are added at the end by `python -m src.sources.fgo --profiles-only` (in resume.sh).

## Pending decisions (project owner)

1. **Genshin / Star Rail gender.** HoYoLAB (the replacement for the bot-blocked BWIKI) has no gender field. Options: a manual labelling list, or a rule like Blue Archive's.
2. **Disk plan for HF story dialogue** (~200k clips): delete HF raw audio after processing (re-extractable from `data/raw/<game>/hf_index.parquet`) and store story clips at 24 kHz only (16 kHz derived on the fly). Estimated total ~72 GB of 85 GB free.
3. Then: write the HoYoLAB adapter (docs/sources/hoyoverse_kuro.md), pilot 3 characters per game, run in batches.

## To-do

- `manifests/fgo_clips.jsonl` is ~48 MB and grows after finalize. Before committing full manifests, switch large ones to `.jsonl.gz` (GitHub warns at 50 MB). Full manifests are intentionally uncommitted until the runs finish.
- Genshin/Star Rail `name_ja` and JP CV will come from HoYoLAB.
