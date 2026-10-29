# Pipeline status

Last updated: 2026-10-28 21:10 (computer about to shut down; downloads interrupted).

## How to resume

```bash
cd Seeing-Voices-Anime-Image-Conditioned-Voice-Design
nohup scripts/resume.sh > data/logs/resume.log 2>&1 &
tail -f data/logs/fgo_full.log      # or arknights_full.log / bluearchive_full.log
```

`scripts/resume.sh` runs download → audio → langid → finalize for FGO, Arknights and Blue Archive in parallel (one worker per host, each host rate-limited), then voice_actors and report. Everything already done is skipped:
- downloads: existing files are skipped (FGO also checks sha1); interrupted `.part` files are re-fetched
- audio cleaning and Whisper: per-clip caches in `data/processed/<game>/`; a line cut off by the shutdown is ignored and that clip is redone
- adapters are **not** rerun: manifests are already complete, so no new wiki crawling

resume.sh runs `caffeinate -ims` itself, so the Mac stays awake while it runs (screen may turn off). Keep it plugged in and the lid open: closing the lid without an external display still sleeps the Mac, and the network drops. 2026-10-28 22:50: a sleep (\"Wake from Deep Idle … lid\") made all downloads time out. The downloader now pauses and retries through outages instead of crashing.

## Progress at shutdown

| Game | Manifest | Download progress | Then |
|---|---|---|---|
| FGO | complete: 471 characters, 45,829 clips | ~2,200 / 45,685 audio (~1 clip/s → ~12 h left) | audio, langid, finalize |
| Arknights | complete: 366 characters, 15,319 clips | ~600 / 15,319 (torappu is slow, ~15 h) | same |
| Blue Archive | complete: 151 characters, 18,607 clips | ~1,800 / 18,607 (~5 h) | same |
| Genshin / Star Rail / WuWa | pilots built (HoYoLAB + HF character_vo; encore.moe for WuWa) | pilot download/clean running | full run after pilot review |

FGO `profile_texts` are added at the end by `python -m src.sources.fgo --profiles-only` (in resume.sh).

## Decisions (project owner, 2026-10-28)

1. **Genshin / Star Rail gender**: leave `unknown` for now; fill later via lookup.
2. **Story dialogue**: skipped for now (`include_story: false` in configs/{genshin,starrail,wuwa}.yaml). Only character voice-over is collected. Story rows remain listed in `data/raw/<game>/hf_index.parquet` for later.

## Next step

HoYoLAB adapter is built (see docs/sources/hoyoverse_kuro.md). After the pilot check, run the full adapters:
`python -m src.sources.hfgames {genshin,starrail,wuwa}`, then the same download/clean chain (add these games to GAMES in scripts/resume.sh).

## To-do

- `manifests/fgo_clips.jsonl` is ~48 MB and grows after finalize. Before committing full manifests, switch large ones to `.jsonl.gz` (GitHub warns at 50 MB). Full manifests are intentionally uncommitted until the runs finish.
- Genshin/Star Rail `name_ja` and JP CV will come from HoYoLAB.
