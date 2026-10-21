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
- TimeDecoders: specific impossible object + precise number + "shouldn't exist". Egypt filler is the worst-performing theme.
- Raising the floor ≠ manufacturing virality — say so plainly rather than promising breakouts.

## Secrets
Credentials live in env / GitHub secrets only. Never echo a secret into chat, a commit, or a new file. Rotating a YouTube OAuth client secret means updating BOTH the token and the client_secret GitHub secrets, not just one.
