# Source survey: Azur Lane

Surveyed 2026-10-28. **Skipped.**

`azurlane.koumakan.jp/robots.txt`, for `User-Agent: *`:
- `Disallow: /w/` (blocks `/w/api.php`, so the MediaWiki API is unavailable)
- `Content-Signal: ai-train=no, search=yes, ai-input=no`

The operator explicitly reserves rights against AI training. This project trains a voice model, so the wiki is out of scope even though `/wiki/<Ship>/Quotes` HTML is technically crawlable. We did not fetch any ship pages.

## Update 2026-10-30: built from other sources (owner decision)

The owner asked to try the Hugging Face dump first. It works, so azurlane.koumakan.jp is still **not** used.

- **Audio + official JP text**: `TLME/AzurLane-voice-transcription` (card says MIT). One zip of 2.2 GB, 617 ships, 28,122 ogg.
  - Each ship folder has `char.json` = {algwiki voice URL: text}.
  - The URL gives the ship group (`cv-<group>`), battle lines (`cv-<group>-battle`) and the skin (`_<n>` suffix → skin id group*10+n), so clips carry outfit names.
  - 27,998 clips; 195 URLs have no file (the dataset author removed English lines).
- **Names, skins, outfit descriptions, CV**: AzurLaneTools/AzurLaneData `JP/` (ship_data_statistics, ship_skin_template, voice_actor_CN; the JP copy holds JP CV names). Only one ship (Renown META) lacks a CV.
- **Art**: algwiki.moe (no robots.txt) serves the game's painting assets: texture atlas + mesh + layer JSON + face overlays.
  - `src/sources/azurlane_paint.py` is a Python port of algwiki's own compositor (`js/azurlane_compositor.js`) and writes the assembled full-body PNG.
  - 1,895 skins in total. About 5 cached requests per skin at 1 req/s, so ~3 h.
- **Gender**: no source field. All ships are labelled `female`, `gender_source: manual` (owner decision, 2026-10-30).
