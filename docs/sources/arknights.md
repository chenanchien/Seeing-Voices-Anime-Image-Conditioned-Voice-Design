# Source survey: Arknights (JP voice)

Surveyed 2026-10-28 on 3 operators: アーミヤ (char_002_amiya), チェン (char_017_huang), エクシア (char_103_angel).

## Verdict: feasible. Adapter not built yet (waiting for go-ahead).

## Sources

| What | Source | Access |
|---|---|---|
| Voice lines: title, JP text (+ zh/en/ko), audio file, trigger type, unlock condition | PRTS `https://prts.wiki/api.php` `action=parse&prop=wikitext` on `<干员名>/语音记录` | robots.txt does not disallow `/api.php` for `*`. Licence CC BY-NC-SA 4.0 (`siteinfo.rightsinfo`). |
| JP audio | `https://torappu.prts.wiki/assets/audio/<日语 path>/<file lowercased>`, e.g. `voice/char_002_amiya/cn_001.wav` | No robots rules. **Filename must be lowercased** (`CN_001.wav` → 404). WAV, ~270 KB/line. |
| CV (original Japanese name) | `Kengxxiao/ArknightsGameData_YoStar` → `ja_JP/gamedata/excel/charword_table.json` → `voiceLangDict[charId].dict.JP.cvName` | GitHub raw, one 10 MB file. 395 voice sets. No repo licence (game data © Hypergryph/Yostar). |
| Gender | PRTS operator page `|性别=女` | |
| Art | PRTS files `立绘_<名>_1.png`, `_2.png` (elite 2), `_skin<N>.png`, via `list=allimages&aiprefix=立绘_<名>` | `media.prts.wiki`, no robots rules |

## Page structure

```
{{VoiceTable|表格标题=语音记录
|语音key=char_002_amiya
|路径=日语:voice/char_002_amiya,中文-普通话:voice_cn/...,韩语:voice_kr/...,英语:voice_en/...
|标题2=交谈1
|台词2={{VoiceData/word|中文|...}}{{VoiceData/word|日文|ケルシー先生が...}}{{VoiceData/word|英文|...}}
|语音2=CN_002.wav
|触发类型2=HOME_SHOW
|条件5=提升至精英阶段1以查看
```

## Notes

- PRTS `|日文配音=` is written in simplified Chinese (黑泽朋世). Use the JP game data's `cvName` (黒沢ともよ) as `cv_name_ja`, and keep the PRTS spelling as an alias.
- Some operators/skins have separate voice keys (e.g. alter voices). They map to `outfit_name`.
- Estimated ~400 operators × ~40 lines ≈ 16k clips.
