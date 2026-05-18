# Bhakti Reels — Automated AI Reel Generator (Hindu Religion)

End-to-end pipeline that generates 30–60s vertical reels on Hindu deities, festivals,
shlokas, and stories from the Ramayana / Mahabharata / Puranas and uploads them to
**YouTube Shorts** and **Instagram Reels**.

Designed to run at **~$0/month** using free tiers and local tooling.

---

## Architecture

```
 ┌──────────────┐    ┌──────────────┐    ┌──────────────┐    ┌──────────────┐
 │  topic pick  │ -> │   scraper    │ -> │ script writer│ -> │     TTS      │
 │ (rotating /  │    │ (wikipedia,  │    │ (LLM, Hindi+ │    │ (edge-tts,   │
 │  festival)   │    │  sacred-texts│    │  English mix)│    │  FREE, Hindi)│
 └──────────────┘    └──────────────┘    └──────┬───────┘    └──────┬───────┘
                                                │                   │
                                                v                   v
                                         ┌──────────────┐    ┌──────────────┐
                                         │  image gen   │    │   music mix  │
                                         │(pollinations │    │ (royalty-free│
                                         │  .ai, FREE)  │    │   library)   │
                                         └──────┬───────┘    └──────┬───────┘
                                                │                   │
                                                └─────────┬─────────┘
                                                          v
                                                 ┌──────────────┐
                                                 │   assembler  │
                                                 │ (ffmpeg, Ken │
                                                 │  Burns, subs)│
                                                 └──────┬───────┘
                                                        v
                                              ┌────────────────────┐
                                              │   uploaders        │
                                              │ YouTube + Instagram│
                                              └────────────────────┘
```

## Cost stack (zero-dollar tier)

| Component       | Service                          | Cost        |
|-----------------|----------------------------------|-------------|
| LLM (script)    | Google Gemini Flash free tier    | $0 (15 RPM) |
| TTS voiceover   | `edge-tts` (Microsoft Edge)      | $0          |
| Image gen       | `pollinations.ai` (no key)       | $0          |
| Music           | Pre-downloaded royalty-free      | $0          |
| Video assembly  | `ffmpeg` (local)                 | $0          |
| Scheduler       | GitHub Actions (2000 min/mo)     | $0          |
| YouTube upload  | YouTube Data API v3              | $0          |
| Instagram upload| IG Graph API (business acct)     | $0          |

Optional upgrades when you want better quality:
- ElevenLabs TTS (~$5/mo for 30k chars)
- Stable Diffusion XL via Replicate (~$0.003/image)
- Suno / Udio for original devotional music

---

## Quick start

```bash
# 1. install
brew install ffmpeg
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2. configure
cp .env.example .env
# edit .env, add GEMINI_API_KEY (free at aistudio.google.com)

# 3. generate one reel end-to-end
python run.py --topic auto

# 4. publish to YouTube + Instagram (after one-time OAuth setup)
python run.py --topic auto --publish
```

Output ends up in `output/videos/<date>_<slug>.mp4` ready for upload.

---

## Daily auto-publish

Two options:

**A. Mac cron (local)** — add to `crontab -e`:
```
0 7 * * * cd "/Users/vishalkumar/Documents/Vishal Projects/bhakti-reels" && /usr/bin/python3 run.py --topic auto --publish >> logs/run.log 2>&1
```

**B. GitHub Actions (cloud, free)** — see `scheduler/github-actions.yml`.
Push the repo, add secrets, and it runs daily.

---

## Monetization roadmap

1. **Month 1–2**: Post 1 reel/day across both platforms. Cross-post to build watch time.
2. **YouTube Shorts Fund / AdSense**: Eligible at 1k subs + 10M Shorts views in 90 days.
3. **Instagram Reels Bonus / Brand deals**: Switch to creator/business account.
4. **Affiliate**: Link to puja items, books, Rudraksha (Amazon associates) in bio.
5. **Premium content**: Once an audience exists, release longer-form devotional videos.

---

## Content strategy (built-in topic rotation)

The pipeline rotates across these themes so you never run out:

- **Deity spotlights**: One god/goddess per day with story + mantra
- **Daily shloka**: Bhagavad Gita verse with translation + meaning
- **Festival**: Auto-detects upcoming festival from `data/topics.json` calendar
- **Stories**: 60-second retellings from Ramayana, Mahabharata, Puranas
- **Temples**: Famous temples with history + significance
- **Mantras**: Powerful mantras with chant audio + benefits

See `data/topics.json` to customize the pool.

---

## File map

```
bhakti-reels/
├── run.py                       # entry point
├── config.yaml                  # voice, resolution, branding
├── pipeline/
│   ├── topic_generator.py       # picks today's topic
│   ├── scraper.py               # Wikipedia + sacred-texts.com
│   ├── script_writer.py         # LLM → script + visual prompts
│   ├── tts.py                   # edge-tts voiceover
│   ├── image_gen.py             # pollinations.ai images
│   ├── music.py                 # bg music picker
│   ├── assembler.py             # ffmpeg compose
│   ├── uploader_youtube.py      # YT Shorts upload
│   └── uploader_instagram.py    # IG Reels upload
├── data/
│   ├── topics.json              # topic pool + festival calendar
│   └── music/                   # drop royalty-free .mp3s here
└── output/                      # generated artifacts
```

---

## Legal note

All content drawn from public-domain scriptures (Gita, Ramayana, Mahabharata,
Puranas) and Wikipedia (CC-BY-SA — credit in description). AI-generated visuals
are original. Music must be royalty-free or licensed — drop your own tracks in
`data/music/`.
