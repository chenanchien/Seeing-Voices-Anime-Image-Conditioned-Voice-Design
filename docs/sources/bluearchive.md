# Source survey: Blue Archive (JP)

Surveyed 2026-10-28 on 3 students: アル (10000) and ホシノ (3 styles: base / 水着 / 臨戦).

## Verdict: feasible from SchaleDB alone. Adapter not built yet (waiting for go-ahead).

## Sources

| What | Source | Access |
|---|---|---|
| Students: name, family/personal name, CV (JP), illustrator, school | `https://schaledb.com/data/jp/students.min.json` (1.7 MB, 278 entries) | No robots.txt (SPA returns HTML) → allowed |
| Voice lines: group, JP transcription, audio path | `https://schaledb.com/data/jp/voice.min.json` (3.1 MB). Groups `Normal`, `Battle`, `Lobby`, `Event`; 18,830 lines total, 799 without transcription | same |
| Audio | `https://r2.schaledb.com/voice/<AudioClip>`, e.g. `voice/jp_aru/aru_title.mp3` (base URL from the site's StudentView JS bundle) | Cloudflare-managed robots.txt with the content-signal preamble but **no signals and no rules** ("neither grants nor restricts") |
| Art | `https://schaledb.com/images/student/portrait/<Id>.webp` (also `collection/`, `icon/`) | |
| Open-source code | github.com/SchaleDB/SchaleDB (no licence file) | |

## Notes

- Each style (水着, 臨戦, …) is a separate student `Id` sharing `PersonalName`/`CharacterVoice`. Model this as one character per (FamilyName, PersonalName) with styles as outfits, or one row per style plus `outfit_name`. **Decision needed.**
- **No gender field in SchaleDB.** Under the "don't infer" rule, gender stays `unknown` and the students go on the manual-labelling list.
- bluearchive.wiki: robots.txt disallows `/w/` (incl. `api.php`) except `action=mobileview`. Not needed, since SchaleDB covers everything.
