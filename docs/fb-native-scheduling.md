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

## Slots in use

- **06:30 IST** — photo, or a one-line reel 2 days a week
- **22:30 IST** — the scripted reel

Both are IST. The queue's `post_at` values are UTC (`01:00Z` = 06:30 IST,
`17:00Z` = 22:30 IST); do not mix the two up when reconciling against
`pending_reels.json`.
