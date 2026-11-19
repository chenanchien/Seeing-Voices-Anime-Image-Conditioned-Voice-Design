# genshin dataset stats

| game | characters | outfits (base+skins) | clips | usable clips | usable duration | female / male / other / unknown |
|---|---|---|---|---|---|---|
| genshin | 128 | 128 | 14035 | 13662 | 44.75 h | 64% / 34% / 0% / 2% |

## Clips by category_norm

| category_norm | usable | excluded |
|---|---|---|
| battle | 1967 | 364 |
| bond | 2661 | 1 |
| daily | 9034 | 8 |

Text filled by Whisper ASR (text_source=asr): 7. Usable clips flagged is_legacy (pre-remake recording): 0.

## Usable clips per character

min 0, p25 75, median 122, p75 134, max 236

| usable clips per character | # characters |
|---|---|
| 0 | 4 |
| 1–9 | 0 |
| 10–29 | 0 |
| 30–59 | 0 |
| 60–99 | 52 |
| 100+ | 72 |

## Exclusion reasons

| reason | clips flagged | sole reason |
|---|---|---|
| battle_shout | 363 | 363 |
| duplicate_audio | 6 | 6 |
| non_japanese | 4 | 4 |

Duration flags (not excluded): short (<1 s) 937, long (>15 s) 3464; of these, usable: short 785, long 3462.

## name_ja shared by several characters (kept separate)

_none_

## Characters with missing fields

| char_uid | name_ja | missing |
|---|---|---|
| genshin:13836 | ダニカ | cv, gender, image, usable_clips |
| genshin:13830 | アナスターシャ | cv, gender, image, usable_clips |
| genshin:9021 | ドール（女） | usable_clips |
| genshin:9020 | ドール（男） | usable_clips |
