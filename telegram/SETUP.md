# Telegram Control — setup (one-time, ~10 min)

This is an **extra control layer**. It never touches the auto-post crons —
`telegram-control.yml` runs **only** on `repository_dispatch`.

What you'll do: create a GitHub token → deploy the Cloudflare Worker → point the
Telegram bot's webhook at it. After that, you control the pipeline from Telegram.

---

## 1. GitHub token (PAT)
- github.com → Settings → Developer settings → **Fine-grained tokens** → Generate
- Repository access: **only** `vishal21292219/kalyaan-path`
- Permissions: **Contents: Read & write**, **Actions: Read & write**, **Metadata: Read**
- Copy the token (starts `github_pat_…`). Keep it safe.

## 2. Your Telegram chat id
- Message the bot once, then open:
  `https://api.telegram.org/bot<BOT_TOKEN>/getUpdates`
- Find `"chat":{"id": <NUMBER>}` — that number is `ALLOWED_CHAT_ID`.

## 3. Deploy the Cloudflare Worker
- cloudflare.com (free) → Workers & Pages → **Create Worker** → name it `reels-control`
- Edit code → paste everything from `telegram/worker.js` → **Deploy**
- Worker → **Settings → Variables → Add (Encrypt)** these secrets:
  - `BOT_TOKEN` = your Telegram bot token
  - `GH_PAT` = token from step 1
  - `GH_REPO` = `vishal21292219/kalyaan-path`
  - `ALLOWED_CHAT_ID` = number from step 2
- Copy the Worker URL: `https://reels-control.<you>.workers.dev`

## 4. Point Telegram at the Worker
Run once (replace both values):
```
curl "https://api.telegram.org/bot<BOT_TOKEN>/setWebhook?url=https://reels-control.<you>.workers.dev"
```
You should see `{"ok":true,...}`.

## 5. Test
In Telegram, send **/help** → you should get the command menu.
Then **/status** → tap a channel → a status report comes back.

---

## Commands
| Command | What it does |
|---|---|
| `/status` | what/when posted per channel |
| `/generate` | make one video now → sent to Telegram for review |
| `/skip` | skip that channel's next scheduled topic |
| `/approve` | generate + publish to YouTube now |
| `/help` | this menu |

Every command first asks **which channel** (KalyaanPath / Itihaasvani / TimeDecoders).

To disable: remove the Telegram webhook
(`.../deleteWebhook`) — the pipeline keeps running normally.
