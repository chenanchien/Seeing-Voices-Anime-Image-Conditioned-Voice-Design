# Girls' Frontline (survey + adapter, 2026-10-30)

**Status: feasible, built.**

- **Audio, JP text and CV (romaji)**: HF `deepghs/girlsfrontline_voices_jp`
  - 12,508 clips (20.9 h) for 387 dolls; only voice sets with a single VA are kept.
  - The audio is the IOP Wiki's JP voice files, and the text is IOP Wiki's JP transcription (`text_source: wiki`).
  - `voices.tar` is uncompressed (2 GB) and `voices.json` gives each member's offset, so clips are pulled with range requests (`hf_zip.tar_index`). License: `other`.
- **Art**: IOP Wiki doll pages (`/wiki/<char_name>`), gallery "Main artworks".
  - Full artworks only; damaged and profile images are skipped.
  - The label gives the outfit: `Full artwork` is the base art, `Neural Upgrade full artwork` is MOD3, and the others are named costumes.
- **CV Japanese name**: IOP Wiki `Voice_Actor:<romaji>` pages ("Family name" + "Given name"). The romaji goes to `cv_name_en`.
- **robots.txt**: `Crawl-delay: 20`. Articles and `/images/` are allowed; `api.php?action=` and `index.php?` are disallowed. The adapter uses only article URLs, at 20 s per request.
- **Voice sets**: `voice_group` prefixes `MOD3` and `Children's Day` become the clip's `outfit_name`. The doll stays one character, like Blue Archive styles.
- **Gender**: female, `manual` (owner, 2026-10-30).
- **Profile text**: none. Neither source has official profile text, and the wiki's own prose is not used.
