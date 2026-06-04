/**
 * Cloudflare Worker — Telegram control for the bhakti-reels pipeline.
 *
 * Flow: you send a command in Telegram (/status, /generate, /skip, /approve) →
 * the bot shows channel buttons → you tap one → this Worker fires a GitHub
 * repository_dispatch (event "tg_control") → telegram-control.yml runs that
 * action on that channel. /help replies directly (no GitHub run).
 *
 * This is an EXTRA control layer — it never touches the auto-post crons.
 *
 * Worker secrets to set (wrangler secret put / dashboard):
 *   BOT_TOKEN        Telegram bot token
 *   GH_PAT           GitHub fine-grained PAT with "Contents: read/write" +
 *                    "Actions: read/write" on the repo (to send dispatches)
 *   GH_REPO          "owner/repo"  e.g. "vishal21292219/kalyaan-path"
 *   ALLOWED_CHAT_ID  your Telegram chat id (only you can control the bot)
 */

const CHANNELS = [
  { label: "🕉️ KalyaanPath", code: "bhakti" },
  { label: "🛕 Itihaasvani", code: "itihaas" },
  { label: "🌍 TimeDecoders", code: "ancient" },
];
const CMDS = ["status", "generate", "skip", "approve"];

export default {
  async fetch(request, env) {
    if (request.method !== "POST") return new Response("ok");
    let update;
    try { update = await request.json(); } catch { return json({ ok: true }); }

    const cb = update.callback_query;
    const msg = update.message;

    // ---- security: only the owner chat may control ----
    const chatId = String(cb?.message?.chat?.id ?? msg?.chat?.id ?? "");
    if (env.ALLOWED_CHAT_ID && chatId !== String(env.ALLOWED_CHAT_ID)) {
      return json({ ok: true }); // silently ignore strangers
    }

    // ---- button tap → fire GitHub dispatch ----
    if (cb) {
      const [command, channel] = String(cb.data || "").split(":");
      await tg(env, "answerCallbackQuery", { callback_query_id: cb.id, text: "Triggering…" });
      const ok = await dispatch(env, command, channel);
      const chName = CHANNELS.find((c) => c.code === channel)?.label || channel;
      await tg(env, "editMessageText", {
        chat_id: chatId,
        message_id: cb.message.message_id,
        text: ok
          ? `⏳ <b>${command}</b> → ${chName}\nTriggered. Result aayega yahin.`
          : `⚠️ Failed to trigger <b>${command}</b> (${chName}). Check GH_PAT/GH_REPO.`,
        parse_mode: "HTML",
      });
      return json({ ok: true });
    }

    // ---- text command ----
    if (msg && typeof msg.text === "string") {
      const cmd = msg.text.trim().replace(/^\//, "").split(/\s+/)[0].toLowerCase();

      if (cmd === "start" || cmd === "help") {
        await tg(env, "sendMessage", {
          chat_id: chatId, parse_mode: "HTML",
          text:
            "🤖 <b>Reels control</b>\n\n" +
            "/status — kya/kab post hua\n" +
            "/generate — abhi ek video banao (Telegram review)\n" +
            "/skip — aaj ka topic skip\n" +
            "/approve — YouTube pe publish\n\n" +
            "Har command ke baad channel chuno (button).",
        });
        return json({ ok: true });
      }

      if (CMDS.includes(cmd)) {
        await tg(env, "sendMessage", {
          chat_id: chatId,
          text: `Kis channel pe <b>${cmd}</b> karu?`,
          parse_mode: "HTML",
          reply_markup: {
            inline_keyboard: [CHANNELS.map((c) => ({ text: c.label, callback_data: `${cmd}:${c.code}` }))],
          },
        });
        return json({ ok: true });
      }

      await tg(env, "sendMessage", {
        chat_id: chatId,
        text: "Unknown command. /help dekho.",
      });
    }
    return json({ ok: true });
  },
};

async function dispatch(env, command, channel) {
  if (!CMDS.includes(command) || !CHANNELS.some((c) => c.code === channel)) return false;
  const res = await fetch(`https://api.github.com/repos/${env.GH_REPO}/dispatches`, {
    method: "POST",
    headers: {
      "Authorization": `Bearer ${env.GH_PAT}`,
      "Accept": "application/vnd.github+json",
      "User-Agent": "tg-reels-worker",
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ event_type: "tg_control", client_payload: { command, channel } }),
  });
  return res.status === 204;
}

async function tg(env, method, body) {
  await fetch(`https://api.telegram.org/bot${env.BOT_TOKEN}/${method}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

function json(o) {
  return new Response(JSON.stringify(o), { headers: { "Content-Type": "application/json" } });
}
