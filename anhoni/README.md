# ANHONI — automated premium suspense comic-story channel

Fully-automated daily pipeline: **Claude writes a suspense story → fal nano-banana
renders character-locked premium comic panels → speech/thought bubbles + Ken-Burns
motion + suspense music → publishes to YouTube + Instagram + Facebook.**

Brand: **ANHONI** (अनहोनी) — SUSPENSE · THRILLER · MYSTERY (not gore/horror).
Same channel/accounts as the retired Lakeerein (renamed).

## Pipeline (per video)
| Step | Script | Cost |
|---|---|---|
| Story (dialogue-driven, 10 panels, twist, cliffhanger) | `story_gen.py` (Claude) | ~$0.01 |
| Character refs + panels (character-locked) | `gen_art.py` (fal flux/dev + nano-banana/edit) | ~$0.40 |
| Suspense music | `music_gen.py` (fal stable-audio) | ~$0.03 |
| Bubbles + motion + branding + music → mp4 | `assemble.py` (Pillow + ffmpeg) | $0 |
| Publish YT (public Short) + IG + FB | `publish.py` | $0 |
| Orchestrator (date-rotated seed, state, timing) | `daily_anhoni.py` | — |

**~$0.44 / video.** Story seeds pool: `topics_anhoni.json` (add more anytime).

## Run locally
```bash
cd anhoni
python daily_anhoni.py --dry-run   # build today's video, do NOT publish → out/<slug>/final.mp4
python daily_anhoni.py             # build + publish to YT + IG + FB
# or one step at a time:
python story_gen.py "<seed>" myslug && python gen_art.py myslug && python music_gen.py myslug && python assemble.py myslug && python publish.py myslug
```

## Automation (GitHub Actions)
Workflow: `.github/workflows/anhoni.yml` — cron **21:15 IST (15:45 UTC)** → posts
~9:30 PM IST (prime suspense time). Manual run via "Run workflow" (has a dry-run toggle).

**Secrets: ALL reused from Lakeerein — nothing new to add.** The workflow uses:
`ANTHROPIC_API_KEY`, `FAL_KEY`, `CLOUDINARY_CLOUD_NAME`, `CLOUDINARY_API_KEY`,
`CLOUDINARY_API_SECRET`, `LAKEEREIN_IG_WEBHOOK`, `YT_LAKEEREIN_TOKEN_JSON`,
`YT_LAKEEREIN_CLIENT_SECRET_JSON` (already set in the repo).

### To enable
1. `git add anhoni .github/workflows/anhoni.yml requirements.txt && git commit && git push`
2. Done — it runs nightly. (Optional: if YT upload ever fails with an auth error,
   refresh `YT_LAKEEREIN_TOKEN_JSON` secret with the freshly re-authed token from
   `lakeerein/yt_token_lakeerein.json`.)

## Notes
- IG + FB post via one Make webhook (`LAKEEREIN_IG_WEBHOOK` → both).
- Fonts resolve on macOS (Arial/Georgia) and Linux/CI (DejaVu) automatically.
- Anatomy guardrails in prompts reduce hand glitches; if one panel is bad, re-run
  `gen_art.py <slug>` or regenerate that panel — never the whole video.
- `out/` is git-ignored (generated media). `published_log.json` is committed by the cron.
