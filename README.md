# Anime character art + Japanese voice + CV dataset

Data collection for the CMU 10-423 Generative AI final project *Seeing Voices: image-conditioned voice design*. For each character we collect official art, Japanese voice clips with transcripts, the voice actor (CV), and gender. **Course research use only.**

Raw media (audio, images) is never committed. The repo holds code, configs, manifests and reports; anyone can rebuild the media locally with the pipeline below.

## Layout

```
configs/<game>.yaml        source URLs, rate limits, category rules
src/common/                polite HTTP client (robots.txt, per-host rate limit, retries), IO helpers
src/sources/<game>.py      one adapter per game → manifests/<game>_characters.jsonl, <game>_clips.jsonl
src/download.py            resumable downloader (skip existing, sha1 check, one worker per host)
src/clean/audio.py         mono, trim silence, -23 LUFS, 24 kHz + 16 kHz (16-bit FLAC, lossless)
src/clean/langid.py        Whisper small language check + ASR for missing text
src/clean/finalize.py      merge quality fields, exclusion flags, checksum dedup
src/clean/voice_actors.py  manifests/voice_actors.csv + cv_uid
src/report.py              reports/<game>_stats.md, reports/summary.md
src/embed.py               CLIP / SigLIP image and WavLM-SV speaker embeddings
src/embed_qwen.py          per-clip Qwen3-TTS speaker embeddings (GPU) for M2
src/extract_qwen_embeddings.py  Qwen character prototypes behind the baselines (Tianxiang)
scripts/aws_qwen_spk.sh    download from Delta + run embed_qwen on an AWS GPU machine
docs/sources/<game>.md     per-game source survey (URLs, structure, licence, size)
data/                      gitignored: raw/<game>/, processed/<game>/
```

## Setup

```bash
uv venv -p 3.12 && uv sync      # no ffmpeg needed (libsndfile decodes mp3)
```

## Pipeline (per game)

```bash
python -m src.sources.fgo --ids 1 2 11   # pilot on 3 characters (omit --ids for all)
# other adapters: src.sources.arknights --ids char_002_amiya ..., src.sources.bluearchive --names アル ...
python -m src.download fgo               # resumable; rerun after interruption
python -m src.clean.audio fgo
python -m src.clean.langid fgo           # MLX on Apple Silicon, faster-whisper elsewhere
python -m src.clean.finalize fgo
python -m src.clean.voice_actors         # all games
python -m src.report                     # all games
```

Every step is idempotent and caches its work, so steps can be rerun at any time. Rerunning an adapter rewrites the clip manifest without quality fields; rerun `finalize` afterwards to restore them.

## Qwen speaker embeddings (per clip)

M2 trains on the TTS's own speaker embedding of every usable clip (about 155K), not only on the
character prototypes in `data/embeddings/qwen-speaker-prototypes-10games-raw/`. `src.embed_qwen`
uses the same recipe as the prototypes (Qwen3-TTS-12Hz-1.7B-Base at the pinned revision, BF16,
one whole 24 kHz clip at a time, no padding / trimming / normalization) and keeps the native
scale (mean L2 norm ~17). Output: `data/embeddings/qwen-spk/<game>.npz` with `keys` (clip_uid)
and `emb` (float16, 2048-d, not normalized).

Audio comes from two places, and both are needed: `data/processed/<game>/wav24k/` (files) and the
share-package tars `seeing-voices_<game>.tar` (read in place, no unpacking). The script takes a
clip from disk if the file is there, else from the tar.

On Delta everything is under `/work/hdd/bjop/kchien` (read access for the team on request).
Download it to another machine (asks for the NCSA password + Duo; rerun to resume):

```bash
rsync -a --partial <user>@login.delta.ncsa.illinois.edu:/work/hdd/bjop/kchien/seeing-voices/ ~/seeing-voices/
rsync -a --partial <user>@login.delta.ncsa.illinois.edu:'/work/hdd/bjop/kchien/sv-share/seeing-voices_*.tar' ~/sv-share/
```

Then, on a machine with a CUDA GPU (one A10G is enough):

```bash
cd ~/seeing-voices
uv venv -p 3.12 && . .venv/bin/activate && uv pip install qwen-tts soundfile
python -m src.embed_qwen --list-missing --tars ~/sv-share   # every game must print "0 usable clips without audio"
python -m src.embed_qwen --check --tars ~/sv-share          # cosine ~1 and norm ratio ~1.0 against the prototypes
python -m src.embed_qwen --tars ~/sv-share                  # all clips; rerun to resume
```

`scripts/aws_qwen_spk.sh` does all of the above in one go (`DELTA_USER=<user> bash scripts/aws_qwen_spk.sh`).
`--out` writes somewhere other than `data/embeddings/qwen-spk/`; finished games are skipped and a
game in progress resumes from its last save (every 2,000 clips).

## Schema

`<game>_characters.jsonl`: one row per character. Fields: `char_uid` (`<game>:<source id>`), `game`, `name_ja/zh/en`, `gender` (female/male/other/unknown, taken from the source or a manual label and never inferred by a model), `gender_source`, `gender_alt`, `cv_name_ja`, `cv_name_zh`, `cv_uid`, `images[{path, kind: base|ascension|skin|other, outfit_name, source_url}]` (all outfits of a character, several images per character), `profile_texts[{lang, kind, condition, text, source_url}]` (official profile text kept verbatim; nothing is generated), `source_urls`.

`<game>_clips.jsonl`: one row per voice line.
- Source fields: `clip_uid`, `char_uid`, `outfit_name`, `category` (raw), `category_norm` (battle|daily|bond|system|other), `voice_scope` (character_vo|story; story dialogue only in the HF-based games), `condition`, `is_legacy`, `text_ja`, `text_zh`, `text_source` (wiki|gamedata|asr), `audio_path`, `audio_url`, `source_url`, `source_sha1`.
- Quality fields: `duration_sec`, `sample_rate`, `orig_sample_rate`, `loudness_lufs_orig`, `wav24_path`, `wav16_path`, `audio_sha1`, `duplicate_of`, `lang`, `lang_prob`, `exclude`, `exclude_reasons`.

Excluded clips stay in the manifest. Duration is not an exclusion reason (all lengths kept for now); `duration_flag` marks `short` (<1 s) and `long` (>15 s) for later filtering or splitting. Exclusion reasons: `battle_shout`, `non_japanese` (Whisper prob ≥ 0.5 on clips ≥ 2 s; ≥ 0.9 when the source text has kana), `nonverbal` (source text 台詞なし), `empty_audio`, `duplicate_audio`, `no_text`, `not_downloaded`, `no_audio_source`, `decode_error`.

## Crawling policy

- Structured APIs come first (Atlas export, MediaWiki `api.php`); HTML scraping is a last resort.
- robots.txt is checked for every host.
- Requests are rate-limited to ≥ 1 s per host and identified by a descriptive User-Agent.
- On 429/503 the client backs off and honours `Retry-After`.
- If a source needs a login, is blocked, or has unclear terms, we stop and document it rather than work around it.
