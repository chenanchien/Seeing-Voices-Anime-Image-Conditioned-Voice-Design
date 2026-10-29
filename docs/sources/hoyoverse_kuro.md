# Source survey: Genshin Impact / Honkai: Star Rail / Wuthering Waves

Surveyed 2026-10-28.

## Verdict: approved by the project owner ("the voice just needs to be Japanese"). Story dialogue is kept but labelled `voice_scope=story`.

## Findings from the 3-character survey (芙宁娜/胡桃, 流萤/三月七, 今汐)

- `ultemica/*` parquet shards are **sorted by speaker**, and speakers are simplified-Chinese names (matching BWIKI page names). We index the text columns of every shard with HTTP range reads (no audio), cached as `data/raw/<game>/hf_index.parquet`. Then only the shards containing playable characters are downloaded. Genshin: 161,156 rows / 2,988 speakers; Star Rail: 69,399 / 1,412; WuWa: 19,894 / 540.
- Most rows are **story dialogue**. Character voice-over is identified from the filename:
  - Genshin: `vo_<QUESTID>_…` = story; `vo_<char>_battle_*` / friendship = character VO.
  - Star Rail: `chapter*` / `side*` = story; `archive_<char>_*` = character VO.
  - WuWa: `ja_vo_<area>_main_*` etc. = story; `ja_vo_play_favor_word_<char>_*` = character VO.
- Metadata:
  - **Genshin / Star Rail**: BWIKI (`wiki.biligame.com/ys`, `/sr`) via `api.php?action=parse`, which robots allows. `Category:角色` lists 134 / 102 characters. Fields: `日文CV` (zh spelling for ys, often JP spelling for sr), `性别`, `介绍`, `角色详细`, `角色故事1-5`. Art comes from the parsed page HTML (`<名>立绘*.png` on patchwiki.biligame.com), so no File: lookups are needed.
  - **WuWa**: BWIKI `/mc/` is **disallowed** by robots. Use **encore.moe** instead (robots: allow all). `api.encore.moe/ja/character/<id>` has JP name, `favorRole.CVNameJp`, `favorRole.Sex`, introduction, skins with stand art, and `Words[].VoiceJa` (JP character voice audio). `api.encore.moe/zh-Hans/character` gives the zh names that join with HF speakers.
- Multi-CV entries exist (e.g. 流萤 `楠木ともり&笠間淳`, i.e. Firefly + SAM) → needs_review.

## Original licensing note

### Hugging Face datasets (audio)

| Dataset | Languages | Rows | Licence on card | Notes |
|---|---|---|---|---|
| Genius-Society/hoyoTTS | split `Genshin_jp`, `StarRail_jp` (+zh/en/ko) | viewer disabled | cc-by-nc-nd-4.0 (integration code); data from AI-Hobbyist (ModelScope), "final right of interpretation belonging to miHoYo" | Loader script that pulls the AI-Hobbyist packs |
| simon3000/genshin-voice | zh/en/ja/ko mixed, `language` column | 654,252 | none; "Copyright © COGNOSPHERE. All Rights Reserved." | Includes NPC/quest dialogue; `speaker` in English; 1% without speaker |
| simon3000/starrail-voice | zh/en/ja/ko mixed | 403,437 | same | 15% without speaker |
| OpenSpeechHub/Starrail-Voice-Ja | ja | 34,022 | none | |
| ultemica/genshin-impact-voices | ja only | 161,156 | `other`: "does not itself grant rights… Check the applicable terms" | Client-extracted (AI-Hobbyist), game v6.3 |
| ultemica/honkai-star-rail-voices | ja only | 69,399 | `other` | same |
| ultemica/wuthering-waves-voices | ja only | 19,894 | `other` | same |

All of these are **decrypted client dumps**, and their own cards say no rights are granted. Under the task rules ("授權不清 → 停下來回報") we have not downloaded any of them. If you approve, the Japanese-only `ultemica/*` sets are the cleanest option: one language, a speaker column, and parquet shards that stream without the full download.

### Wiki metadata (art, CV, gender, JP text)

- BWIKI (`wiki.biligame.com/ys`, `/sr`, `/mc`): character pages have `|日文CV=` (Chinese spelling, e.g. 水濑祈) and `|性别=`. Voice pages (`<角色>语音`) have JP text (`语音内容日语`) per line.
  - No licence declared (`rightsinfo` empty).
  - robots.txt disallows `/*File:*`, which also matches `api.php?...titles=File:...`, so audio/art URLs can't be resolved via imageinfo while staying within robots.
- Fandom wikis (genshin-impact / honkai-star-rail / wutheringwaves): robots.txt itself returns 403 (bot protection). Skipped.
- HoYoLAB wiki (`wiki.hoyolab.com`): robots allows all, but it's a JS app with an undocumented API. Not explored further.

### Options

1. Approve `ultemica/*` audio and use BWIKI page wikitext for CV/gender/JP text only (no File: lookups). JP CV names would then need conversion from the Chinese spelling (needs_review).
2. Skip these three games.

## 2026-10-28: BWIKI blocked during the pilot

After ~30 `api.php?action=parse` requests at 1.5 s spacing, BWIKI's CDN (Tencent EdgeOne) started answering **HTTP 567** (bot protection) for `/ys/` and `/sr/`. Per project rules we stopped all BWIKI access and do not work around it. The HTTP client now never retries non-transient statuses like this.

Consequences:
- Genshin / Star Rail metadata (CV, gender, profile, art) has no working source right now. The pilot manifests from before the block (芙宁娜/胡桃/钟离, 流萤/丹恒) are complete, but the full run can't use BWIKI.
- `name_ja` was never available from BWIKI (no Japanese-name field).
- WuWa is unaffected (encore.moe). WuWa pilot extraction verified: 44.1 kHz mono, mean 7.4 s, ~180 KB/clip raw FLAC.

## 2026-10-28: HoYoLAB wiki survey (replacement for BWIKI)

Surveyed on フリーナ (Genshin) and 星神★アッハ (Star Rail). **Feasible.** robots.txt on `wiki.hoyolab.com` is `User-Agent: *` with no disallows; the API hosts have no robots.txt.

| What | Endpoint |
|---|---|
| Character list | `POST https://sg-wiki-api.hoyolab.com/hoyowiki/{genshin,hsr}/wapi/get_entry_page_list`, body `{"filters":[],"menu_id":"2"(genshin) / "104"(hsr),"page_num":N,"page_size":30,"use_es":true}`. Headers `x-rpc-language: ja-jp` (or `zh-cn` for the names that join HF speakers) and `x-rpc-wiki_app: hsr` for Star Rail. Genshin 132 entries, Star Rail 94 (incl. outfit entries like 「アベンチュリン・波と戯れる夏」 and the FGO collab). |
| Character page | `GET https://sg-wiki-api-static.hoyolab.com/hoyowiki/{game}/wapi/entry_page?entry_page_id=ID` |

Modules on the JP page:
- **ステータス / 基本情報**: 和名/英名 (fills `name_ja`), **日本語 CV in the original spelling** (水瀬いのり, 戸松遥), plus zh/en/ko CV.
- **ギャラリー**: 原画 (official art) plus distributed illustrations.
- **ストーリー**: キャラクター詳細 and キャラクターストーリー1–5 (JP profile text).
- **ボイス**: official character voice lines (Furina: 71) with JP text and per-language audio URLs (`upload-static.hoyoverse.com/hoyolab-wiki-voice/...mp3`, 日本語 included). These are the profile/friendship voice-overs missing from the HF Genshin dump.
- **No gender field** in either game (filters: rarity, region/path, element, weapon only).

Plan: metadata + character voice-over from HoYoLAB (JP); story dialogue from HF ultemica, joined on the zh-cn name. Gender stays `unknown` unless labelled manually.

## 2026-10-28: HoYoLAB adapter built (`src/sources/hfgames.py`, provider `hoyolab`)

- Genshin uses `menu_id 2`; Star Rail uses `menu_id 104` + header `x-rpc-wiki_app: hsr`. The JP voice audio label is `日本語` (genshin) / `JP` (hsr); the main art key is `原画` / `立ち絵`. `name_ja` = ja-jp page title (和名 can be ruby markup).
- Clips per character: official HoYoLAB JP voice lines (`text_source=hoyolab`), plus HF character_vo lines not already covered (deduplicated by normalized text).
- Pilot: Genshin フリーナ/鍾離/胡桃 → 422 clips; Star Rail ホタル/丹恒/丹恒・飲月/三月なのか/アベンチュリン → 429 clips.
- Grouping (configs/starrail.yaml `groups`):
  - same character in another version → merged, variant = outfit: 三月七 (存护/巡猎), 砂金•戏浪, 知更鸟•晴歌, 姬子•启行
  - different forms kept separate (like FGO/Arknights alters): 丹恒•饮月, 丹恒•腾荒
  - Trailblazer / Traveler: split by the HF male/female voice labels. The official voice lines of their shared pages are dropped, because we can't tell which voice they use.
- Gender: left `unknown` for Genshin/Star Rail (owner decision; fill later via lookup).
