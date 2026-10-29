# Pipeline status

Last updated: 2026-10-29 12:00, after the Mac crashed (kernel watchdog panic at ~05:18) and rebooted. Nothing is running.

## How to resume

```bash
cd Seeing-Voices-Anime-Image-Conditioned-Voice-Design
nohup scripts/resume.sh > data/logs/resume.log 2>&1 &
tail -f data/logs/fgo_full.log      # any <game>_full.log
```

`scripts/resume.sh` first finishes any Genshin / Star Rail / WuWa adapter that has no `data/raw/<game>/.adapter_full_done` marker (one at a time). Then it runs download → audio → langid → finalize for all six games, then voice_actors and report. Finished work is always skipped. It keeps the Mac awake (`caffeinate -ims`); keep it plugged in with the lid open.

## Why the crash happened, and the fix

Panic report: `watchdog timeout: no checkins from watchdogd in 94 seconds`. The system froze under load. At 05:16 the M1 (16 GB) was running Blue Archive's Whisper, Arknights' Whisper (a second MLX model), a 6-process audio pool and the FGO download at the same time.
Fix: audio cleaning and Whisper now take a machine-wide lock (`src/common/io.py:heavy_step`), so only one game runs a heavy step at a time. The audio pool is reduced to 4 workers. Downloads still run in parallel (light, one per host).
Crash damage check: 0 `.part` files, and all 27,816 files written just before the crash decode fine.

## Progress at the crash

| Game | Download | Audio cleaning | Whisper | Notes |
|---|---|---|---|---|
| FGO | 23,438 / 45,685 | not started | not started | ~6 h of download left |
| Arknights | done (13,761 files; 456 JP skin voices missing on server) | done (13,696) | just started | manifest fixed: 1,102 non-JP lines (ITA / CN dialect voice sets) removed → 14,217 clips |
| Blue Archive | done (18,361) | done (18,361) | 15,616 / 17,745 | almost finished |
| Genshin | pilot only | pilot only | pilot only | full adapter crashed on a HoYoLAB entry with `audios: null` (fixed) |
| Star Rail | pilot only | pilot only | pilot only | waits for the Genshin adapter (same host) |
| WuWa | **done**: 1,920 clips, 1,642 usable | done | done | PIPELINE_DONE |

FGO `profile_texts` are added at the end by `python -m src.sources.fgo --profiles-only` (in resume.sh).

## Decisions (project owner, 2026-10-28)

1. **Genshin / Star Rail gender**: leave `unknown` for now; fill later via lookup.
2. **Story dialogue**: skipped for now (`include_story: false` in configs/{genshin,starrail,wuwa}.yaml). Story rows remain listed in `data/raw/<game>/hf_index.parquet`.

## To-do

- `manifests/fgo_clips.jsonl` is ~48 MB and grows after finalize. Before committing full manifests, switch large ones to `.jsonl.gz` (GitHub warns at 50 MB). Full manifests stay uncommitted until the runs finish.
- `data/raw/wuwa/audio` still holds ~3,300 story clips extracted during the first pilot (before story was skipped), ~0.6 GB. Safe to delete.
