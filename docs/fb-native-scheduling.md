# Scheduling GoM on Facebook's own scheduler

Worked out and used on 2026-10-23 to place 25 posts (10 photos, 4 one-line
reels, 10 scripted reels + 1) across 23 Oct – 6 Nov. Written down because the
flow has several non-obvious traps and is otherwise re-derived every time.

Everything happens in the browser as the signed-in user, through the Claude
Chrome extension. **Make is not involved.** A post scheduled here must be
removed from `data/state/pending_reels.json`, or `reel-poster.yml` fires the
Make webhook for the same video and it publishes twice. That commit has to be
**pushed** — the workflows check out `main` from the remote, so an unpushed
removal does not stop the fire.

## Which composer

| Post | URL |
|---|---|
| Photo | `business.facebook.com/latest/composer?asset_id=<PAGE_ID>` |
| Reel | `business.facebook.com/latest/reels_composer?asset_id=<PAGE_ID>` |

GoM page id: `1113214471881336`.

The reel composer is a 3-step wizard (Create → Edit → Share); scheduling lives
on the **Share** step. The photo composer is one page with a Schedule toggle.

## The file input is not in the accessibility tree

Both composers create the `<input type=file>` on demand and the usual `find`
does not see it. Arm this **before** clicking "Add photo/video" / "Add Video",
then upload to the ref that `find` then returns:

```js
if(!window.__armed){window.__armed=1;const oc=HTMLInputElement.prototype.click;
HTMLInputElement.prototype.click=function(){if(this.type==='file'){
window.__fi=this;this.id=this.id||'vk_fi';
if(!this.isConnected)document.body.appendChild(this);
this.style.cssText='position:fixed;top:0;left:0;z-index:99999;opacity:1';return;}
return oc.apply(this,arguments);};}
```

Re-arm after every page load. "Add photo/video" sits at roughly (178, 375) in
the photo composer and "Add Video" at (205, 342) in the reel composer.

## Upload size limit

The extension's upload bridge caps at **10 MB**, and a finished reel is ~50 MB.
Two-pass encode first, solving the bitrate per file against a 9.2 MB target:

```bash
vb=$(python3 -c "print(int((9200*8 - 96*$dur)/$dur))")
ffmpeg -y -i in.mp4 -c:v libx264 -b:v ${vb}k -preset slow -pass 1 -an -f mp4 /dev/null
ffmpeg -y -i in.mp4 -c:v libx264 -b:v ${vb}k -preset slow -pass 2 \
       -c:a aac -b:a 96k -movflags +faststart out.mp4
```

Checked against crops of the source: no visible loss at these bitrates.
`scripts/../scratchpad/shrink_reels.sh` does this for a list of files.

## Captions

Type the caption into the ref from `find "post text box"` (photo) or by
clicking the Description field (reel). **Use element refs, not coordinates** —
after any scroll the coordinates are stale and the click lands elsewhere.
Newlines in the typed string work. A hashtag autocomplete list opens over the
page; press Escape before moving on.

## Date and time

Each field is a separate spinbutton: date textbox (`mm/dd/yyyy`), then `hours`,
`minutes`, `meridiem`. Triple-click each, then type.

Typing `06`, `30`, `AM` into the hours field alone does **not** tab through the
segments — it overwrites the hour three times and leaves the minutes untouched.
Set each of the three refs separately. The time zone shown is Asia/Kolkata, so
type IST directly.

The photo composer's Schedule toggle sometimes renders ON while the date fields
never appear. Read `aria-checked` rather than trusting the colour — the blue
tint is the focus ring, not the state — and click once more if it is false.

## Confirming

A photo ends with "Your post is scheduled" and a boost offer: click **Maybe
later**, never Boost. A reel ends with "Reel scheduled" → **Done**.

Verify the whole set afterwards in **Planner** (month view) or
`latest/posts/scheduled_posts`, which lists every item with its type and exact
time. Check that no date carries two posts in the same slot.

## Replacing an already-scheduled post

There is no "swap the video" — delete and re-create. On the scheduled list, the
row's `…` menu → Manage post → **Delete post**, confirm, then schedule the new
file into the same slot.

## Moving an already-scheduled post

Content → Posts & reels → **Scheduled** → select the row → post details panel →
**Actions (…)** → **Reschedule post**. Edit only the fields that change (the
date textbox, `hours`, `minutes`, `meridiem` — same rules as above) and confirm.
No re-upload, the post keeps its ID. Used on 2026-10-24 to move 21 posts.

Two traps:

- **Click menu items by their text, never by coordinate.** Reels and photos
  have different "…" menus. A coordinate that hits "Reschedule post" on a reel
  hits **"Duplicate post"** on a photo, which opens a pre-filled composer. If
  that happens: Cancel → **Discard changes**, then check Published to confirm
  nothing went out.
- **The list refreshes late.** Right after a reschedule the row can still show
  the old time for a few seconds. Reload before deciding it failed.

To pull a post out of the schedule without losing it, use **Move to Drafts**
instead of Delete. It then shows in Scheduled as a "Failed to publish" row and
in **Drafts** as a normal draft — that label does not mean anything broke.

## Slots in use

| Post | IST | UTC | US Eastern (EDT → EST after 1 Nov) |
|---|---|---|---|
| Scripted reel | **00:30** | 19:00 (previous UTC day) | 3:30 PM → 2 PM |
| Photo, or a one-line reel 2 days a week | **03:30** | 22:00 (previous UTC day) | 6:30 PM → 5:30 PM |

**Why these times (measured 2026-10-24).** Business Suite → Insights → Content,
last 90 days (29 Jul – 23 Oct 2026), 81 GoM reels by publish time:

| Posted (IST) | Reels | Median views | Follows |
|---|---|---|---|
| 00:00–05:00 | 41 | 1,096 | 429 |
| 22:00–24:00 | 36 | 690 | 148 |

The gap held inside the same month (Sep 1,096 vs 769, Oct 1,112 vs 808), so it
is the slot and not the page getting older. The previous slots (22:30 reel,
06:30 photo) rested on single breakout reels (the "10.6K" and "9.3K" slots) and
were never re-checked against the whole catalogue.
Business Suite no longer shows a "when your followers are online" chart, so
re-measure this way: Insights → Content → Last 90 days, group by publish hour.

Photo timing has **not** been measured yet — only two photos had posted when
this was set. Re-check once the photo lane has 10+ posts.

The two slots are 3h apart, which equals `MIN_GAP_HOURS` in
`post_pending_reels.py`. For posts scheduled here that does not matter (Facebook
fires them itself). For anything queued through Make, a reel that posted late
can make the poster hold the 22:00 photo until its 23:00 backstop run.

Both are IST. The queue's `post_at` values are UTC (`19:00Z` = 00:30 IST and
`22:00Z` = 03:30 IST, both on the NEXT IST calendar day); do not mix the two up
when reconciling against `pending_reels.json`. `scripts/batch_reels.py` and
`scripts/batch_photos.py` default to these UTC times, and their `--start` is the
UTC date.
