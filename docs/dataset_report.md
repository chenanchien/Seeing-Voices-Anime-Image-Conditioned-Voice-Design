# Data: anime character voices paired with character art

**Snapshot: 2026-11-04.** The numbers cover the eight games whose pipeline has finished. Girls' Frontline and Zenless Zone Zero are still being processed (§5).

## 1. Overview

We built a dataset of Japanese anime-style game characters. Each character record has:

- one or more official character illustrations, including outfit variants
- the Japanese voice actor (CV)
- gender
- official profile text where it exists
- voice clips with Japanese transcriptions

Table 0. Totals for the eight finished games.

| | Total |
|---|---|
| Games | 8 (+2 in progress) |
| Characters | 1,993 (1,948 with at least one usable clip) |
| Voice clips | 147,069 collected, **124,263 usable** |
| Usable audio | **301.7 h** |
| Distinct voice actors | 728 (339 appear in two or more games) |
| Character images | 9,977 |

## 2. Sources

All voice audio is the original Japanese in-game voice-over. Each game combines an audio source with a metadata source:

- **Audio and transcriptions** come from one of:
  - community game-data exports
  - fan wikis
  - Hugging Face voice dumps of the game client
- **Metadata** (names, CV, gender, profile text, art) comes from official sites and game data where possible, and from wikis otherwise.
- **Extra art** for Blue Archive comes from the Blue Archive Wiki galleries: each style's Memorial Lobby illustration, plus the JP student card and pickup banner, which are tagged `promo` because they carry text overlays.

Table 1. Sources per game.

| Game | Audio / JP text | Character metadata and art |
|---|---|---|
| Fate/Grand Order | Mooncell wiki (fgo.wiki) | Atlas Academy JP export |
| Arknights | JP game data (text), PRTS wiki (audio, art) | JP game data (handbook) |
| Blue Archive | SchaleDB | SchaleDB |
| Genshin Impact | HF `ultemica/genshin-impact-voices` + HoYoLAB wiki | HoYoLAB wiki; gender from genshin-db |
| Honkai: Star Rail | HF `ultemica/honkai-star-rail-voices` + HoYoLAB wiki | HoYoLAB wiki |
| Wuthering Waves | HF `ultemica/wuthering-waves-voices` | encore.moe |
| Uma Musume | HF `Plachta/Umamusume-voice-text-pairs` | umamusume.jp (official), GameTora |
| Azur Lane | HF `TLME/AzurLane-voice-transcription` | AzurLaneData (JP game data); art from algwiki.moe |
| *Girls' Frontline* | HF `deepghs/girlsfrontline_voices_jp` | IOP Wiki |
| *Zenless Zone Zero* | HF `simon3000/zenless-voice` | HoYoLAB wiki |

**Collection policy:**
- The crawler respects robots.txt and waits at least 1 s between requests to the same host (20 s where a site asks for it).
- It sends an identifying User-Agent, and every step can be resumed.
- Large Hugging Face archives are never downloaded whole. Single clips are pulled with HTTP range requests on the zip/tar index or on parquet row groups.
- Sites that blocked bots or disallowed the needed paths were not crawled. Princess Connect! Re:Dive and Touken Ranbu were skipped for this reason, as were the Idolmaster titles, which have no bulk voice source.
- Raw audio and images are kept locally for research use and are not redistributed.

**Scope:**
- Only character voice-over is used: home-screen, interaction, bond, system and battle lines. Story and cutscene dialogue is excluded.
- Outfit variants of a character are merged into one character with several images. Characters that are distinct in the game stay separate (e.g. FGO alter versions, Arknights alternate operators).

## 3. Processing

1. **Audio.** Each clip goes through these steps:
   1. Converted to mono.
   2. Leading and trailing silence trimmed (frames 40 dB below the clip's peak).
   3. Loudness-normalized to −23 LUFS (ITU-R BS.1770) with a −1 dBFS peak ceiling.
   4. Written as 24 kHz and 16 kHz 16-bit FLAC.
2. **Language check.** Whisper `small` predicts the language of every clip. A clip is excluded as non-Japanese only when it is at least 2 s long and Whisper is confident (p ≥ 0.5, or p ≥ 0.9 when the source text contains kana).
3. **Transcriptions.** Source text (game data, wiki or dump) is used when available. When it is missing, or when the "Japanese" source text is actually untranslated Chinese, the Whisper transcript is used. These clips are marked `text_source = asr`.
4. **Exclusions.**
   - Short battle shouts (attack, hit and dash grunts).
   - Byte-identical duplicates.
   - Clips whose audio is missing at the source.
   - Non-Japanese and non-verbal clips.
   - Clips with no text.
   - Clips shorter than 1 s or longer than 15 s are flagged but kept.
5. **Gender.** Taken from the source where it exists (FGO, Arknights, WuWa, ZZZ).
   - Single-gender rosters (Blue Archive, Uma Musume, Azur Lane, Girls' Frontline) are labelled female by the project owner.
   - Genshin Impact uses genshin-db (gender field from game data).
   - Honkai: Star Rail was annotated manually. The basis is recorded per character: official-profile pronoun counts, plus a cited web source for recent characters.
6. **Voice actors.** CV names are merged across games by their Japanese spelling (Unicode NFKC, whitespace removed). Chinese and English spellings are kept as aliases, and ambiguous cases are flagged for review. Voice actors with no known Japanese spelling are keyed by romaji.

## 4. Statistics

Table 2. Per game, usable clips only.

| Game | Characters | Usable / collected clips | Hours | Median clip (s) | Median clips per character | Images |
|---|---|---|---|---|---|---|
| Fate/Grand Order | 469 | 31,677 / 45,829 | 89.6 | 7.1 | 58 | 2,033 |
| Azur Lane | 616 | 27,524 / 27,998 | 63.0 | 7.0 | 43 | 1,895 |
| Genshin Impact | 122 | 13,524 / 13,886 | 44.1 | 5.9 | 124 | 2,307 |
| Arknights | 365 | 10,794 / 14,217 | 37.0 | 8.9 | 30 | 1,294 |
| Uma Musume | 115 | 19,602 / 19,635 | 29.2 | 5.3 | 212 | 421 |
| Blue Archive | 148 | 14,744 / 18,607 | 24.2 | 5.0 | 94 | 1,036 |
| Honkai: Star Rail | 82 | 4,756 / 4,977 | 10.3 | 4.5 | 56 | 878 |
| Wuthering Waves | 31 | 1,642 / 1,920 | 4.4 | 3.3 | 53 | 113 |
| **Total** | **1,948** | **124,263 / 147,069** | **301.7** | | | **9,977** |

Table 3. Gender, characters with usable clips.

| Gender | Characters | Usable clips | Hours | Share of hours |
|---|---|---|---|---|
| Female | 1,593 | 103,192 | 242.1 | 80% |
| Male | 325 | 19,147 | 53.8 | 18% |
| Unknown | 30 | 1,924 | 5.8 | 2% |

Male voices come mainly from FGO (25.5 h), Genshin Impact (15.2 h) and Arknights (8.7 h).

**Voice actors.**
- 728 distinct Japanese voice actors.
  - 339 appear in two or more games; 5 appear in seven of the eight.
  - 520 voice only female characters, 149 only male characters, and 28 voice both.
- Per actor, usable audio is heavily skewed. The quartiles are 0.13 / 0.26 / 0.52 h.
  - 326 actors voice a single character; 27 voice ten or more.
  - The largest are 悠木碧 (10.4 h, dominated by Paimon in Genshin Impact) and 堀江瞬 (6.9 h, the male Traveler).
- The cross-game overlap lets the same voice be heard across different character designs, which helps us separate voice identity from character art.

**Line types (usable clips):**

| Type | Clips |
|---|---|
| Daily | 55,511 |
| Battle | 27,551 |
| Bond / affection | 16,304 |
| System | 13,074 |
| Other | 11,823 |

**Transcripts:** 96.6% of usable clips have source transcripts; 4,220 (3.4%) use Whisper ASR text.

**Durations:** 16% of usable clips are longer than 15 s and 3.6% are shorter than 1 s.

**Why clips were excluded (22,806 clips; a clip may have several reasons):**

| Reason | Clips |
|---|---|
| Battle shouts | 20,266 |
| Duplicates | 1,505 |
| Audio unavailable at the source | 1,327 |
| Non-Japanese | 128 |
| Non-verbal, undecodable or no text | ~200 |

The 1,327 clips with unavailable audio include 471 Azur Lane entries that are saved wiki error pages rather than audio, and 456 Arknights files that return 404.

## 5. In progress

These two games are still being processed. Their adapters have run, but audio cleaning and the language check are not finished.

- **Girls' Frontline**:
  - 387 characters and 12,508 clips (the source lists 20.9 h).
  - All female (owner label).
  - 374 characters have a Japanese CV name; the other 13 are voiced by 12 actors known only by romaji.
- **Zenless Zone Zero**:
  - About 55 agents.
  - Clips: agent voice-over, mostly battle lines that use ASR text, plus the agent's hangout lines and in-level reactions, which have source text.
  - Gender comes from the source and includes many male characters.
  - HF speaker codes are mapped to agents by name, and otherwise by a community datamine table.

## 6. Limitations

- **Gender and actor imbalance.** 80% of hours are female, and a few actors and characters dominate. Training should cap or reweight clips per actor and per character.
- **Line-type bias.** Battle and system lines are short and formulaic.
- **Uneven art.** Every character with usable clips has at least one image. The count ranges from 1 (common in Azur Lane and WuWa) to 54 (Genshin Impact, where promotional art is included). Single-skin Azur Lane ships have no further official art in game data. The wikis that collect it (Azur Lane Wiki, BWIKI) block crawlers, so they were not used. WuWa art is the full-body default portrait, a half-body card and paid-skin illustrations. For the 13 newest WuWa characters, only the card is available.
- **Coverage gaps.**
  - Wuthering Waves: 27 of 58 characters have no voice in the HF dump, whose game version is older.
  - Azur Lane: the HF dump covers 617 ship groups. Some well-known ships are missing, e.g. USS Enterprise (CV-6). The dump's "Enterprise" folder is HMS Enterprise, a different ship with the same Japanese name.
  - Honkai: Star Rail: 星神★アッハ has no gender label.
- **Text quality.** Wiki and ASR transcriptions may contain errors. `text_source` records the origin of each transcript.
- **Licensing.** All material belongs to the game publishers. The dataset is collected for non-commercial course research and is not redistributed.
