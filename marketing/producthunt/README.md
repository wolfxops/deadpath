# Product Hunt assets

Ready-to-upload images for the Deadpath launch. Filenames carry the search terms Product Hunt indexes on the gallery.

## Thumbnail — 240×240

`thumbnail/deadpath-thumbnail-240.png`

Exact **240×240** PNG. The Deadpath mark on brand blue (`#2447f9`). Upload this as the listing thumbnail.

## Gallery — 1270×760 or higher

Five frames, exported at **2540×1520** (2× of 1270×760). Upload in this order:

| # | File | What hunters see |
|---|---|---|
| 1 | `gallery/01-deadpath-dead-code-detection-for-coding-agents.png` | Hero + `deadpath judge` table |
| 2 | `gallery/02-deadpath-unused-code-false-positives.png` | Why unused-code tools get ignored |
| 3 | `gallery/03-deadpath-confidence-score-devils-advocate.png` | Graph → confidence → judge → veto-only counsel |
| 4 | `gallery/04-deadpath-16-languages-45-frameworks.png` | 16 languages, 45 frameworks, four finding kinds |
| 5 | `gallery/05-deadpath-never-auto-delete-ci.png` | block / warn / note; `auto_delete: false` |

Suggested gallery captions (paste next to each image in the PH form):

1. Dead-code detection for Claude Code, Cursor, and Codex. The graph decides. The model only vetoes.
2. Framework routes, beans, and cron jobs look unused to a naive scanner. Deadpath prices them as live.
3. Four stages stay offline. Optional LLM counsel can stop a delete. It cannot upgrade a maybe.
4. One finding shape across 16 languages and 45 frameworks, with declared path vs name precision.
5. Only ≥ 0.85 fails CI. Deadpath never deletes a file.

## Re-render

```bash
./marketing/producthunt/render.sh
```

Requires `google-chrome` headless. Sources live in `src/`.
