# Source survey: Blue Archive (JP)

Surveyed 2026-10-28 on 3 students: アル (10000) and ホシノ (3 styles: base / 水着 / 臨戦).

## Verdict: feasible from SchaleDB alone. Adapter built (`src/sources/bluearchive.py`). Pilot: 3 characters, 619 clips, 440 usable.

## Sources

| What | Source | Access |
|---|---|---|
| Students: name, family/personal name, CV (JP), illustrator, school | `https://schaledb.com/data/jp/students.min.json` (1.7 MB, 278 entries) | No robots.txt (SPA returns HTML) → allowed |
| Voice lines: group, JP transcription, audio path | `https://schaledb.com/data/jp/voice.min.json` (3.1 MB). Groups `Normal`, `Battle`, `Lobby`, `Event`; 18,830 lines total, 799 without transcription | same |
| Audio | `https://r2.schaledb.com/voice/<AudioClip>`, e.g. `voice/jp_aru/aru_title.mp3` (base URL from the site's StudentView JS bundle) | Cloudflare-managed robots.txt with the content-signal preamble but **no signals and no rules** ("neither grants nor restricts") |
| Art | `https://schaledb.com/images/student/portrait/<Id>.webp` (also `collection/`, `icon/`) | |
| Extra art | Blue Archive Wiki `https://bluearchive.wiki/wiki/<Name>/gallery` (Miraheze; robots.txt allows `/wiki/` articles), files on `static.wikitide.net` | `src.sources.bluearchive_gallery` |
| Open-source code | github.com/SchaleDB/SchaleDB (no licence file) | |

## Notes

- Each style (水着, 臨戦, …) is a separate student `Id`. **Decision (project owner):** one character per (FamilyName, PersonalName). Every style's portrait goes into `images`; style voice lines carry `outfit_name`. 151 characters / 278 styles.
- **No gender field in SchaleDB.** The project owner confirmed all students are female → `gender=female`, `gender_source=manual`.
- Profile text: `ProfileIntroduction` (per style), `Hobby`, plus school/club/age/height as `basic_info`.
- bluearchive.wiki: robots.txt disallows `/w/` (incl. `api.php`) except `action=mobileview`. Not needed, since SchaleDB covers everything.

## Extra art (2026-11-04)

SchaleDB has one portrait per style, so 49 students had a single image. `src.sources.bluearchive_gallery`
adds from each student's wiki gallery page:
- `memorial_lobby`: the style's Memorial Lobby illustration (official, one character, new pose and scene).
- `promo`: JP student card and pickup banner (official art with text overlays; `has_text_overlay: true`).

Left out: expression sprites (same pose as the portrait), fan kit / event / loading / 4-koma images
(several characters). Run it after `src.sources.bluearchive`, which rewrites the manifest, then
`python -m src.download bluearchive --only image`.
