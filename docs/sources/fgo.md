# Source survey: Fate/Grand Order (JP server)

Surveyed 2026-10-28 on 3 servants: マシュ (No.1), アルトリア・ペンドラゴン (No.2), エミヤ (No.11).

## Sources used

| What | Source | Access |
|---|---|---|
| Servant list, name_ja, gender, CV (JP), art | Atlas Academy export `https://api.atlasacademy.io/export/JP/nice_servant_lore.json` (~95 MB, one request) | No robots.txt (404) → allowed. Cached under `data/raw/fgo/atlas/`. |
| name_en | Atlas `export/JP/basic_servant_lang_en.json` | same |
| Voice lines (text_ja, text_zh, audio) | Mooncell `https://fgo.wiki/api.php`, `action=parse&prop=wikitext` on `<页面名>/语音` | robots.txt does not disallow `/api.php` for `*` (only `/images/`, `/index.php`, Special/User pages). Rate limit 1.5 s. |
| collectionNo ↔ Mooncell page name, CV (zh), gender (zh) | Mooncell SMW `action=ask`, query `[[序号::+]][[分类:从者]]` | Page names can't be guessed from JP names, so use the 序号 property. |
| Audio URL + sha1 | Mooncell `action=query&prop=imageinfo&iiprop=url\|sha1\|size` (50 files/request) | Files live on `media.fgo.wiki` (Aliyun OSS, no robots.txt). sha1 verified after download. |

## Why not Atlas for voice

Atlas `profile.voices[].voiceLines[]` has JP audio URLs (`static.atlasacademy.io/JP/Audio/ChrVoice_<svtId>/<id>.mp3`) but `text` is empty for almost every line (only the summon line had text for No.2). Mooncell has full JP text + ZH translation for the same lines, so Mooncell is the clip source.

## Page / API structure

Voice pages contain one `{{#invoke:VoiceTable|table|表格标题=<section> ...}}` block per section, with numbered fields:

```
|标题5=技能 1          # title (category within section)
|日文5=本気で行きましょう # JP text (may contain {{黑幕|..}}, [[links]], <br>)
|中文5=认真上吧。        # ZH translation
|条件5=第二次重制前      # optional condition (remake, owned servant, story progress)
|语音5=002di_sk1.mp3    # File: name
```

Sections seen: 战斗, 召唤和强化, 个人空间, 御主任务 其他, `灵衣(<name>)` (costume voice), plus event-specific sections.

## Field mapping

- `char_uid` = `fgo:<collectionNo>`; `gender` from Atlas (`female/male/unknown`); Mooncell gender kept in `gender_alt` for cross-check.
- `cv_name_ja` from Atlas `profile.cv`; `cv_name_zh` from Mooncell 声优 (simplified-Chinese spelling, used as alias).
- images: Atlas `extraAssets.charaGraph.ascension` 1–4 (1 = `base`, 2–4 = `ascension`) and `.costume` (`skin`, name from `profile.costume`).
- clips: `category` = `<section>/<title>`; `category_norm` via rules in `configs/fgo.yaml`; `outfit_name` from `灵衣(...)` sections; `is_legacy` when 条件 contains 重制前.

## Licensing

- Mooncell text/translations: CC BY-NC-SA 4.0 (from `siteinfo.rightsinfo`). Attribution + non-commercial + share-alike.
- Audio, art, and JP text are © TYPE-MOON / FGO PROJECT. Atlas and Mooncell redistribute game assets; we use them for non-commercial course research only and do not redistribute media (never committed to git).

## Estimated size

- Atlas JP: 487 entries; ~440 playable servants (type `normal`/`heroine`, collectionNo > 0).
- Mooncell: 529 pages match the query.
- Pilot: 466 clips for 3 servants (Mash is an outlier with 325, mostly costume voices). Expect ~25–30k clips, ~1 s/clip download at the polite rate (~7–8 h).

## Notes / caveats

- Some newer lines have audio but no JP text on the wiki yet (56/466 in the pilot) → Whisper ASR, `text_source=asr`.
- `重制前` (pre-remake) lines may predate a CV change; Mooncell lists two CVs for Mash (种田梨沙、高桥李依). Flagged in `is_legacy` and `voice_actors.csv` needs_review.
- Several servants share `name_ja` (e.g. Altria variants). They are distinct characters with different art/voice sets, so FGO characters are keyed by collectionNo, not merged by name.
- EMIYA's NP chant is in English and is correctly flagged `non_japanese`.
