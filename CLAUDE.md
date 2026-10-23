# bhakti-reels — project rules

Auto-loaded in this repo (channels: GodsOfTheMind, TimeDecoders, Itihaasvani, bhakti, moneurons). Global constitution: `~/.claude/CLAUDE.md`. Cross-channel publishing gotchas: `~/.claude/os/content-pipeline.md`.

## Absolute rules
1. **Never "myth"/"mythology"** in anything viewer-facing — titles, descriptions, hashtags, narration, disclosures. Use Sanatan Dharma, Hindu dharma, Hindu wisdom, Pauranik, scriptures. Viewers complained; this is settled.
2. **Deity iconography is canonical, not stylistic.** Krishna/Ram/Kartikeya = youthful clean-shaven (no beard); Vishnu clean-shaven; Hanuman = vanara; deities are mature adults, never children or feminised. **Look at the generated image yourself** before shipping — file size is not verification.
3. **Duplicate topics throttled both channels once.** Dedup on the normalised topic (strip subtitle after — : |), not the full title, and check the channel's actual recent uploads. Never manually trigger a channel while the seq-queue is loaded — manual + cron both grab min-seq before state persists.
4. **Push before dispatch**; the workflows run from the remote. A global hook blocks dispatch with unpushed commits.
5. **Catch-up floods cause throttling.** After an outage, do not let the pipeline dump a backlog in one day.

## Content direction (data-backed, don't re-litigate)
- GodsOfTheMind: felt-pain / identity-first hook, then the deity. Second-person "you/your" + contrarian reveal wins.
- TimeDecoders: **STOPPED 2026-10-23** (per user: waste of money). Gen cron, catch-up
  slot and topic refill are all off; configs/secrets intact. Do not restart it, or
  plan TD work, without him saying so. Historic direction, if it ever returns:
  specific impossible object + precise number + "shouldn't exist". Egypt filler is
  the worst-performing theme.
- Raising the floor ≠ manufacturing virality — say so plainly rather than promising breakouts.

### Measured 2026-10-23 (GoM, 28d to 21 Oct: 57.9K views, 2,977 followers)
- **Retention is the ceiling, not volume.** 60% of reel viewers leave before 3
  seconds; average play is 9–19s on a ~70s reel (13–27% completion). The first
  scene cut lands at ~9s, so the typical viewer watches ONE still picture with
  changing captions. Hook TEXT is already on frame 0 — what is missing is
  motion. Front-load the cuts before adding volume.
- **Ad revenue is a thermometer, not income.** Content Monetization pays $0.066
  per 1,000 views. ₹1 lakh/month = 17.5M views/month = 303× current. Don't plan
  around it. Creator Fast Track is out: US/Canada only and requires no Reel in
  6 months.
- **The audience is the diaspora, not India.** US 33.3%, India 8.4%, Trinidad
  8.1%, Canada 5.6%, South Africa 5.4%; Tier-1 45.5%. Age 35–54 = 60.6%, 18–24
  = 1.5%, men 63.9%. So: keep English (Hindi would be a mistake), ignore
  youth-trend formats, lean the deity mix toward the diaspora's devotional
  centre. Full note: https://claude.ai/artifact/6UCG8FUea4XwH2efp5VXQT

## Secrets
Credentials live in env / GitHub secrets only. Never echo a secret into chat, a commit, or a new file. Rotating a YouTube OAuth client secret means updating BOTH the token and the client_secret GitHub secrets, not just one.
