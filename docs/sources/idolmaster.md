# Source survey: THE IDOLM@STER (all brands)

Surveyed 2026-10-30. **Metadata available; no bulk voice source.** Pending an owner decision.

## Metadata: im@sparql (github.com/imas/imasparql, MIT)

The RDF is in the repo (`RDFs/*.rdf`, 7 MB), so a shallow git clone avoids the SPARQL server.

| Brand file | Idols | with CV | gender | profile text |
|---|---|---|---|---|
| CinderellaGirls | 193 | 99 | female | – |
| 765MillionStars | 39 | 39 | female | – |
| 283 (Shiny Colors) | 28 | 28 | female | yes |
| SideM | 49 | 49 | **male** | – |
| Gakuen | 13 | 13 | female | yes |
| 765AS / 876 / 961 | 24 | 21 | female | – |

`gender` is an explicit source label, usable as `gender_source: imasparql`. No art URLs.

## Voice audio: nothing usable at scale

- Hugging Face: no Idolmaster voice dataset (searched idolmaster, imas, shinycolors, deresute, millionlive, gakumas). The CyberHarem/BangumiBase sets are images only.
- starlight.kirara.ca (Cinderella Girls DB API): card and character data with CV, but no audio. Its robots.txt carries a Content-Signal block.
- Official sites: gakuen.idolmaster-official.jp has 2 sample voices per idol (13 idols, no transcripts). The shinycolors and portal idol pages were not reachable or had no audio.
- Fan wikis (wikiwiki.jp etc.) have line text only, no audio files.
- The remaining route is extracting game assets from the game CDN with the client's asset manifest. That is not a public website. We did not try it (licensing unclear, which per the work rules means stop and report).
