# Source survey: Uma Musume Pretty Derby

Surveyed 2026-10-30. **Feasible**: same model as Genshin/Star Rail (HF client dump for audio, official/structured sources for metadata). Awaiting owner sign-off on gender labelling before the pilot.

## Audio + text: `Plachta/Umamusume-voice-text-pairs` (Hugging Face, card says MIT)

- One file, `umavoice.zip` (11.1 GB, WAV), plus `output.txt` inside the zip (`<path>|<chara_id>|<text>`, 8.6 MB). The text is the official in-game line, not ASR.
- `character_system_text/<chara_id>/snd_voi_<category>_<id>/<n>.wav`: **19,635 clips, 115 characters, 4.7 GB**. Categories include home, title, training, race, event, gacha, outgame and live, which maps naturally to `category_norm`.
- `story/data/...`: 38,239 story clips. Skipped, as for the other games.
- The zip central directory can be read with HTTP range requests, so single members can be extracted without downloading 11 GB. Same idea as the `hf://` parquet extraction.
- Per-character counts: 2–279 clips (the main roster has ~200–280).

`TLME/Umamusume-voice-transcription` (MIT, 3.2 GB, 77 characters, ~159–300 mp3 per character, text = filename) overlaps with Plachta and covers fewer characters. Not needed.

## Character ID → name / CV: GameTora

- `https://gametora.com/data/manifests/umamusume.json` → `characters.<hash>.json`: 174 characters with `char_id` (1001…, 9001…), `name_ja`, `name_en`, `va_ja`, `url_name`. All 115 Plachta IDs are present. One request.
- robots.txt allows `/data/` and has no Content-Signal. The `sex` field is not a gender label (both values occur among female characters), so it is ignored.

## Profile, CV, art: official site umamusume.jp

- robots.txt: `User-agent: *` with no Disallow.
- Nuxt payload per character: `https://umamusume.jp/character/<slug>/_payload.json` (devalue format). It has `name`, `en`, `cv`, `category` (ウマ娘 / staff), `detail` (official profile text → `profile_texts`), `catch`, and `visual[]` (outfit title such as 制服 / 勝負服 / 原案, plus a 1125×1980 PNG). 176 character pages.
- Join to GameTora by `name_ja` (and `en` as a fallback).

## Gender

No source has an explicit gender label. Every Uma Musume and every staff character in the voice set is female (owner to confirm → `gender_source: manual`, as for Blue Archive).

## Estimate

115 characters, ~19.6k clips. Audio is ~4.7 GB WAV raw, ~1.5 GB after FLAC cleaning. Art is ~2–5 PNGs per character.
