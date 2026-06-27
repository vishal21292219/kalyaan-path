# Architecture — Multi-channel AI Short-Form Video Pipeline

Zero-dollar pipeline that generates vertical Shorts/Reels for 6 channels and
publishes them to **YouTube + Facebook + Instagram**, fully automated on free tiers.

**Channels:** KalyaanPath (bhakti/bhajan) · Itihaasvani (itihaas) · TimeDecoders
(ancient) · GodsOfTheMind (godmind) · Money Neurons (moneurons) · Lakeerein.

```mermaid
flowchart TB
  %% ================= ORCHESTRATION =================
  subgraph CRON["⏱️ Orchestration — GitHub Actions (scheduled crons)"]
    direction LR
    DR["daily-reels.yml<br/>generation crons<br/>GoM 12/15/19 · MN · TimeDecoders"]
    CU["catchup.yml<br/>recover missed slots<br/>15:30 / 19:30 / 23:30 UTC"]
    RP["reel-poster.yml<br/>fire queued FB/IG reels at peak<br/>17/21/01 UTC + backstops"]
    RF["retry-failed.yml<br/>retry runtime failures (6h)"]
    MISC["nightly-pregen · topic-refill<br/>health-check · eval-report · lakeerein"]
  end

  %% ================= GENERATION =================
  subgraph GEN["🎬 Generation pipeline — run.py → pipeline/"]
    direction TB
    TOPIC["topic_generator<br/>pick topic + dedup"]
    SCRIPT["script_writer<br/>LLM → script + visual prompts"]
    TTS["tts → voiceover"]
    IMG["image_gen / stock_footage / kling_video"]
    MUSIC["music → bg track"]
    ASM["assembler (ffmpeg)<br/>compose · subs · brand overlays"]
    THUMB["thumbnail_gen"]
    TOPIC --> SCRIPT --> TTS --> ASM
    SCRIPT --> IMG --> ASM
    MUSIC --> ASM --> THUMB
  end

  %% ================= AI / FREE SERVICES =================
  subgraph AISVC["🧠 AI & free services"]
    LLM["Gemini / Groq / Anthropic"]
    EDGE["edge-tts / ElevenLabs"]
    IMGAPI["pollinations.ai / fal / pexels"]
  end
  SCRIPT -. uses .-> LLM
  TTS -. uses .-> EDGE
  IMG -. uses .-> IMGAPI

  %% ================= PUBLISH =================
  subgraph PUB["📤 Publishing (per-niche config)"]
    YT["uploader_youtube<br/>YouTube Data API<br/>native publishAt schedule"]
    MK["uploader_make_reel<br/>Cloudinary upload → enqueue"]
    IGU["uploader_instagram"]
  end
  THUMB --> YT
  ASM --> MK
  ASM --> IGU

  %% ================= DECOUPLED POSTER =================
  subgraph POST["🕒 Decoupled FB/IG poster"]
    PQ[("pending_reels.json<br/>scheduled queue")]
    PPR["post_pending_reels.py<br/>fire due reels at peak<br/>3h no-back-to-back · drop >6h late"]
    PQ --> PPR
  end
  MK --> PQ
  RP --> PPR

  %% ================= EXTERNAL =================
  subgraph EXT["🌐 External services"]
    CLOUD["Cloudinary<br/>public video host"]
    MAKE["Make.com 'Reel Publisher'<br/>route by fb_page_id<br/>uploadAReel + first comment"]
    DS[("Make datastore<br/>dedup by video_url")]
  end
  MK --> CLOUD
  PPR -- webhook --> MAKE
  MAKE --> DS

  %% ================= PLATFORMS =================
  subgraph PLAT["📡 Channels / Pages"]
    YTCH["YouTube ×6 channels"]
    FB["Facebook Pages"]
    IGP["Instagram"]
  end
  YT --> YTCH
  CLOUD -.-> MAKE
  MAKE --> FB
  MAKE --> IGP
  IGU --> IGP

  %% ================= STATE =================
  subgraph STATE["💾 State — data/state/ (git-committed via persist_state.py)"]
    PL[("published_log.json<br/>slot delivered?")]
    PRL[("posted_reels_log.json<br/>dedup ledger — monotonic")]
    PT[("published_titles · viral_history<br/>topic dedup")]
  end
  GEN --> PL
  PPR --> PRL
  TOPIC -. reads .-> PT

  %% ================= NOTIFY =================
  subgraph NOTIF["🔔 Notify / control"]
    DISC["Discord alerts"]
    TG["Telegram drops + control"]
  end
  PPR -.-> DISC
  GEN -.-> TG

  %% cron drives generation + posting
  DR ==> GEN
  CU ==> GEN
  RP ==> PPR
```

## Two publishing paths

| Path | How it schedules | Used by |
|------|------------------|---------|
| **YouTube** | `uploader_youtube` uploads private with a native `publishAt` → platform goes live at the exact peak. No queue. | all YT channels |
| **Facebook / Instagram** | `uploader_make_reel` uploads the mp4 to **Cloudinary** (public URL) and **queues** a record in `pending_reels.json`. `reel-poster.yml` runs `post_pending_reels.py` at each peak, which POSTs the **Make.com webhook**; the Make scenario routes by `fb_page_id` and posts the Reel + a first comment (promo link). | GoM, MN, TimeDecoders, KalyaanPath, Lakeerein |

## Reliability guarantees

- **No duplicates (G1):** `posted_reels_log.json` ledger (keyed by `video_url`, union-merged so it never loses an entry) + Make datastore dedup + `published_log.json` slot markers + topic recency.
- **No back-to-back (G2):** poster enforces a 3h per-page gap, ≤1 post/page/run; posts >6h past peak are dropped (no off-peak spam).
- **No missed slots (G3):** generation runs with a 5–6h buffer before peak; `catchup.yml` regenerates any dropped slot before its peak.
- **State survives races:** `persist_state.py` union-merges monotonic dedup files and retries the push.

## Cost stack (≈ $0/mo)

LLM = Gemini/Groq free · TTS = edge-tts · images = pollinations.ai/fal free
tiers · assembly = ffmpeg · scheduler = GitHub Actions · hosting = Cloudinary
free · FB/IG = Make.com free.

## Known constraints / risks

- **GitHub Actions minutes** (private repo = 2000 min/mo): heavy cron usage can
  exhaust them → whole pipeline (gen + posting) stops. Fix: make repo public
  (unlimited free) or set a spending limit.
- **`pending_reels.json` is a mutable file in git** → concurrent jobs can race
  on it. The ledger (monotonic) is the load-bearing dedup; the queue is
  best-effort. Permanent fix: move queue + ledger to an external KV store
  (Upstash Redis / Supabase) or use native FB scheduled-publish.
