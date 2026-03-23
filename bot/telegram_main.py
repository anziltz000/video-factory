import os
import logging
import requests
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, CallbackQueryHandler, filters

# ──────────────────────────────────────────────
#  CONFIGURATION  (all values come from .env)
# ──────────────────────────────────────────────
TOKEN             = os.getenv("TELEGRAM_TOKEN")
# This is now the URL that triggers your n8n workflow
N8N_WEBHOOK_URL   = os.getenv("N8N_WEBHOOK_URL") 

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO
)
log = logging.getLogger(__name__)

# ──────────────────────────────────────────────
#  CAMPAIGN INFO TEXT
# ──────────────────────────────────────────────
CAMPAIGN_INFO_TEXT = """
💰 *ACTIVE CAMPAIGNS* 💰

*[$20] LeonBET* — YT Only
  • 1K+ subs required · Any English content · 15 sec
  • Max 25 submits per social

*[$20] Bitz.io* — YT & Insta
  • Any English content · 20 sec
  • Max 100 submits per social
  ⚠️ Must tag @bitzcasino on Insta\!

*[$80] AceBet* — YT Only
  • 1K+ subs · Tier 1 streamer clips only
  • \(Kai Cenat, Speed, Jynxzi, FaZe etc\.\)
  • Max 25 submits per social

*[$80] RajBet* — YT Only
  • 1K+ subs · Any English content
  • Max 25 submits per social

─────────────────────────
👇 *SELECT CAMPAIGN BELOW* 👇
"""

# ──────────────────────────────────────────────
#  KEYBOARDS
# ──────────────────────────────────────────────
def campaign_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🦁 LeonBET ($20)",  callback_data="cam_leonbet"),
         InlineKeyboardButton("🎰 Bitz.io ($20)",  callback_data="cam_bitz")],
        [InlineKeyboardButton("🔥 AceBet ($80)",   callback_data="cam_acebet"),
         InlineKeyboardButton("💎 RajBet ($80)",   callback_data="cam_rajbet")],
    ])

def position_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⬆️ Top Center",    callback_data="pos_top"),
         InlineKeyboardButton("⬇️ Bottom Center", callback_data="pos_bottom")],
        [InlineKeyboardButton("↖️ Top Left",       callback_data="pos_c1"),
         InlineKeyboardButton("↘️ Bottom Right",   callback_data="pos_c2")],
    ])

def upload_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📸 Instagram Only", callback_data="upload_insta"),
         InlineKeyboardButton("📺 YouTube Only",   callback_data="upload_yt")],
        [InlineKeyboardButton("🚀 Upload BOTH",    callback_data="upload_both")],
    ])

# ──────────────────────────────────────────────
#  STEP 1 — User sends a video link
# ──────────────────────────────────────────────
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text.strip()
    
    # 1. Silently ignore casual chat (no "http")
    if not url.startswith("http"):
        return 

    # 2. If it is a link, validate it against allowed domains
    valid = ("instagram.com", "youtube.com", "youtu.be", "tiktok.com")
    if not any(v in url for v in valid):
        await update.message.reply_text(
            "❌ Send a valid Instagram Reel, YouTube Short, or TikTok link."
        )
        return

    context.user_data["url"] = url
    await update.message.reply_text(
        CAMPAIGN_INFO_TEXT,
        parse_mode="MarkdownV2",
        reply_markup=campaign_keyboard()
    )

# ──────────────────────────────────────────────
#  STEPS 2-4 — Button callbacks
# ──────────────────────────────────────────────
async def handle_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data  = query.data

    if data.startswith("cam_"):
        campaign = data[4:]
        context.user_data["campaign"] = campaign
        await query.edit_message_text(
            f"✅ Campaign: *{campaign.upper()}*\n\nStep 2 — Pick logo position:",
            parse_mode="Markdown",
            reply_markup=position_keyboard()
        )

    elif data.startswith("pos_"):
        position = data[4:]
        context.user_data["position"] = position
        pos_labels = {"top": "Top Center", "bottom": "Bottom Center",
                      "c1": "Top Left",    "c2":     "Bottom Right"}
        await query.edit_message_text(
            f"✅ Position: *{pos_labels.get(position, position)}*\n\nStep 3 — Where to upload?",
            parse_mode="Markdown",
            reply_markup=upload_keyboard()
        )

    elif data.startswith("upload_"):
        target = data[7:]
        context.user_data["target"] = target
        await query.edit_message_text("⚙️ Sending to the factory…")
        await send_to_n8n(update, context)

# ──────────────────────────────────────────────
#  DISPATCH to n8n Webhook
# ──────────────────────────────────────────────
async def send_to_n8n(update: Update, context: ContextTypes.DEFAULT_TYPE):
    status_msg = update.callback_query.message
    
    payload = {
        "url":      context.user_data.get("url"),
        "campaign": context.user_data.get("campaign"),
        "position": context.user_data.get("position"),
        "target":   context.user_data.get("target")
    }

    log.info("Dispatching task to n8n: %s", payload)

    try:
        # Pushing the request to n8n instead of the processor
        response = await asyncio.to_thread(
            requests.post, N8N_WEBHOOK_URL, json=payload, timeout=10
        )
        response.raise_for_status()
        
        camp = payload["campaign"].upper()
        await status_msg.edit_text(
            f"✅ *Task Sent to Factory!*\nCampaign: `{camp}`\n\nYou'll get a Telegram message when it's done\.",
            parse_mode="MarkdownV2"
        )

    except Exception as e:
        log.error("Dispatch error: %s", e)
        await status_msg.edit_text(f"❌ Error reaching n8n: {str(e)}")

# ──────────────────────────────────────────────
#  MAIN
# ──────────────────────────────────────────────
if __name__ == "__main__":
    if not TOKEN:
        raise RuntimeError("TELEGRAM_TOKEN env var is not set!")
    if not N8N_WEBHOOK_URL:
        raise RuntimeError("N8N_WEBHOOK_URL env var is not set!")

    log.info("🤖 Bot starting…")
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(handle_buttons))
    app.run_polling(drop_pending_updates=True)
