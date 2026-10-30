# Zenless Zone Zero (survey + pilot, 2026-10-30)

**Status: pilot works; the scope decision is pending with the project owner.**

## Sources
- **Audio**: HF `simon3000/zenless-voice` (game version 3.2.0)
  - 406,720 wavs, about 100k of them Japanese.
  - The parquet shards mix four languages, so audio comes from the per-speaker archives `speaker-archives/Japanese/...`.
  - Each archive holds `<hash>.wav` plus `<hash>.json` (voiceType, speaker, transcription, inGameFilename). The JSON members are read in range spans and cached as `*.meta.json`.
- **Metadata**: HoYoLAB wiki (`app zzz`, menu 8, 65 agents). It gives:
  - JP name, **性別** (so gender comes from the source), JP CV, and official profile text (`詳細`, `備考`).
  - Agent art: gallery keys `<name>・「<outfit>」`. Promo and sticker art is skipped.
  - The voice module is empty, so there are no official voice lines with text.

## Voice types (Japanese)
- **`char` (agent voice-over)**: 3,705 clips across 57 speaker codes.
  - No transcription and no in-game file name, so the text comes from Whisper ASR (`text_source: asr`), and the line type can't be classified (`category_norm: other`).
  - In the pilot these are mostly battle shouts. Lycaon: median 1.2 s, max 3.2 s, so about half fall under the 1 s minimum.
- **Story / scene types**, with source transcriptions:
  - Galgame 51,987
  - Level 6,415
  - Accompany 4,714 (hangout lines, spoken by the agent to the player)
  - Ongoing 3,387
  - Chessboard 2,676
  - Comic 2,505
  - Cinema 1,665
  - Tips 866 (in-level reactions)
  - Story is skipped per the owner decision (2026-10-28).

## Speaker codes
- **Matched automatically**: by HoYoLAB English name tokens.
- **Manual map** (`speaker_map`): in-game nicknames. anbi = Anby, aokaku = 蒼角, xiaozhao = 照, spbilly = Starlight Billy, lucy = Luciana, rina = Alexandrina.
- **Left out until confirmed** (`speaker_unresolved`, ~600 clips):

| Code | Evidence | Guess |
|---|---|---|
| Summer | no text lines | — |
| azural | no text lines | — |
| zhenzhen | no text lines | — |
| brujas | 「であります」 speech | ? |
| clara | Sons of Calydon speech (「〜でい」), talks to Burnice | Piper? |
| lisa | 「ボウヤ」, loves Bangboo (イアス) | Grace? |
| longinus | Defense Force soldier | Soldier 11? |
| norano | 「ジブン…っス」 | Manato? |
| tsubaki | child patient | NPC? |
| unagi | deadpan 「激アツ」 joke | Miyabi? |

## Pilot (anbi, billy, lycaon)
- 214 clips, all extracted.
- Gender from HoYoLAB: female / male / male. CV: 種﨑敦美 / 林勇 / 小林親弘.
