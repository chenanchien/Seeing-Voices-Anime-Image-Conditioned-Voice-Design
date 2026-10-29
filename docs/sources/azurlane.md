# Source survey: Azur Lane

Surveyed 2026-10-28. **Skipped.**

`azurlane.koumakan.jp/robots.txt`, for `User-Agent: *`:
- `Disallow: /w/` (blocks `/w/api.php`, so the MediaWiki API is unavailable)
- `Content-Signal: ai-train=no, search=yes, ai-input=no`

The operator explicitly reserves rights against AI training. This project trains a voice model, so the wiki is out of scope even though `/wiki/<Ship>/Quotes` HTML is technically crawlable. We did not fetch any ship pages.
