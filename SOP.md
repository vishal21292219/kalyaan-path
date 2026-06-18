# OPERATIONS SOP — bhakti-reels

**Goal: maximise page REACH + FOLLOWER growth across all channels (GoM, KalyaanPath,
Itihaasvani, TimeDecoders, Lakeerein) on YouTube + Facebook/Instagram.**

This document is the single source of truth for how the automation must behave.
Every rule here exists to protect the pages from algorithm penalties and from
operator mistakes. **Claude MUST read + follow this SOP before taking ANY action
on this project** (code change, manual post, recovery, schedule edit, deploy).

A rule in §1 (Golden Rules) being violated = a serious incident. These are not
preferences — they are invariants enforced in code so a "silly mistake" cannot
break them.

---

## §1. GOLDEN RULES (never violate)

| # | Rule | Why it matters | Enforced by |
|---|------|----------------|-------------|
| G1 | **No duplicates.** Never post the same video, or the same topic, twice to a page. | Duplicate = spam signal → reach throttled, looks unprofessional. | posted-ledger (`posted_reels_log.json`, keyed by video_url) + `published_log.json` slot marker + `pick_viral` 30-day topic recency + festival gating. |
| G2 | **No back-to-back posts.** Never post 2 reels to the SAME page within `MIN_GAP_HOURS` (default 3h). At most **1 post per page per poster run**. | Back-to-back splits the audience, cannibalises views, and the algorithm suppresses the 2nd. THIS is the mistake that just hurt GoM. | `post_pending_reels.py` spacing guard (per-channel gap check against the ledger). |
| G3 | **Slots must NOT be missed — and must post at their OWN peak.** A missed slot is an INCIDENT, not normal. Generation runs with a 5-6h buffer before its peak so cron lag/render time can't push it past the peak; catch-up runs ~1.5h before each peak as a backstop that recovers a dropped run AT its own peak. Posting late/off-peak or next-day is an absolute last resort and must be flagged. | A late or off-peak post gets low initial velocity → algorithm buries it → drags the page average. Missing entirely wastes the spend. | big gen buffer (`daily-reels.yml` GoM crons 12/15/19 UTC) + pre-peak catch-up (`catchup.yml` 15:30/19:30/23:30) + each slot's `publishAt` peak. |
| G4 | **Follow each channel's exact schedule + frequency** (see §2). Do not add/skip drops silently. | Consistency trains the algorithm + the audience. | crons + `PUBLISH_TIMES` + catch-up `SLOTS` (must stay in sync — see §4). |
| G5 | **Recovery must never flood.** A catch-up / poster recovery posts at most 1/page/run, spaced per G2/G3. Multiple stranded reels are spread across runs/peaks, never flushed together. | The exact failure mode that posted 2 GoM reels back-to-back. | poster spacing guard + catch-up per-slot. |
| G6 | **Never label Hindu beliefs "mythology"/"myth."** Use Sanatan Dharma / Hindu wisdom / Pauranik. | Hurts the core audience's sentiment → comments, unfollows. | `script_writer` + configs wording. |

---

## §2. CANONICAL SCHEDULE (the schedule that MUST be followed)

All times UTC. IST = UTC+5:30, ET = UTC−4 (EDT). GoM audience is ~60% US → peaks
are set to US prime.

| Channel | Page | Cadence | Generation (UTC) | Go-live / post peak |
|---------|------|---------|------------------|---------------------|
| **GodsOfTheMind** (godmind) | FB+IG+YT | 3/day | 12:00, 15:00, 19:00 (5-6h buffer before peak) | YT publishAt + FB reel: **17:00 / 21:00 / 01:00 UTC** = 1 PM / 5 PM / 9 PM ET. (4h apart — safe vs G2.) |
| **KalyaanPath** (bhakti mantra) | FB+YT | 1/day | 15:32 | YT 01:30 UTC (7 AM IST); FB reel immediate |
| **KalyaanPath** (bhajan) | FB+YT | Sun only | Sun 10:00 | YT 13:30 UTC (7 PM IST) |
| **TimeDecoders** (ancient) | FB+YT | 2/day | 15:37, 16:42 | YT 18:00 / 00:00 UTC; FB reel immediate |
| **Itihaasvani** (itihaas series) | YT (manual) | 1/day | 16:00 | Telegram drop → user schedules YT ~20:00 IST |
| **Itihaasvani** (Sat long-form) | YT (manual) | Sat | Sat 11:00 | Telegram drop |
| **Lakeerein** | YT+IG+FB | 1/day | GH Actions "Lakeerein Daily" 10 AM IST | YT 8:30 PM IST; IG/FB via Make immediately |

⚠️ **Known schedule risk (TimeDecoders):** the two ancient gens are ~65 min apart
and FB posts immediately → two FB reels ~1h apart can violate G2 on that page.
FIX PLANNED: route ancient FB through the queue+poster so the spacing guard
governs it (see §5 backlog). Until then, treat ancient FB spacing as a watch-item.

---

## §3. CHANGE-SAFETY PROCESS (Claude's process before any action)

The recurring incidents were caused by acting on assumptions and by lost state.
Before ANY action, Claude MUST:

1. **Verify live state, don't guess.** Read the real state from the source of
   truth: `git fetch` + check `origin/main` for `pending_reels.json`,
   `posted_reels_log.json`, `published_log.json`; check Make execution history
   (`executions_list`) to see what ACTUALLY posted. Never assume a prior run's
   claimed result.
2. **Confirm state reached origin.** A change to a state file is meaningless until
   it's on `origin/main` (Actions run from origin). After any state edit, push +
   verify `git rev-list --left-right --count HEAD...origin/main` is `0 0`.
3. **Dry-run / test before deploy.** Run `run_catchup.py --dry-run`, unit-check
   logic, validate YAML/JSON, before pushing a behavioural change.
4. **Verify after deploy.** Trigger or watch the next run; confirm it did what was
   intended (no dup, correct spacing, correct slot).
5. **One change, fully reasoned.** No piecemeal "try and see" edits to live
   pipelines. Understand the whole path first.
6. **When in doubt about an irreversible posting action, check reality first**
   (scrape the page / Make execs) rather than risk a duplicate.

---

## §4. SINGLE-SOURCE-OF-TRUTH for the schedule

The schedule currently lives in 3 hand-maintained places that MUST stay in sync:
- `.github/workflows/daily-reels.yml` (generation crons + route step)
- `run.py` `PUBLISH_TIMES` (go-live peaks)
- `run_catchup.py` `SLOTS` (recovery — must list EVERY active slot, incl. all GoM)

Whenever ANY of these changes, update all three + this SOP §2. (Backlog: collapse
into one `pipeline/slots.py` registry so they cannot drift.)

---

## §5. PRE-ACTION CHECKLIST (run through EVERY time)

- [ ] Read this SOP.
- [ ] Fetched + inspected real live state (queue, ledger, published_log, Make execs).
- [ ] Will this action risk a duplicate (G1)? → ledger/published_log checked.
- [ ] Will this action post 2+ to one page close together (G2/G3/G5)? → spacing ok.
- [ ] Does it match the canonical schedule (G4)?
- [ ] Any Hindu-sentiment wording (G6)?
- [ ] After: pushed to origin + verified in-sync + verified the run.

## Backlog (improvements, do with user's OK — not cowboy)
1. Move ancient (+ all immediate) FB posts through the queue+poster so the spacing
   guard (G2) governs every page, not just GoM.
2. Collapse schedule into one `pipeline/slots.py` registry (§4).
3. Make-async confirmation: write-back from Make to confirm the FB step truly
   succeeded after the webhook 200 (close the silent-loss gap).
