import os
import logging
import requests
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, CommandHandler, CallbackQueryHandler, filters

# ──────────────────────────────────────────────
#  CONFIGURATION
# ──────────────────────────────────────────────
TOKEN           = os.getenv("TELEGRAM_TOKEN")
PROCESSOR_URL   = os.getenv("PROCESSOR_URL", "http://processor:10000/process")
N8N_WEBHOOK_URL = os.getenv("N8N_WEBHOOK_URL") 

logging.basicConfig(format="%(asctime)s | %(levelname)s | %(message)s", level=logging.INFO)
log = logging.getLogger(__name__)

CAMPAIGN_INFO_TEXT = """
💰 *ACTIVE CAMPAIGNS* 💰

*[$50] JACKBIT SPORTS*
  • YT & INSTA · 1K+ subs
  • Any sports video · Max 30 submits/social

*[$20] JACKBIT GENERAL*
  • YT & INSTA · 1K+ subs
  • Any English video · Max 30 submits/social

*[$20] LUCKY.FUN GENERAL*
  • YT & INSTA · 1K+ subs
  • Any English video · Max 25 submits/social

*[$20] BITZ.IO GENERAL*
  • YT & INSTA · 100+ subs
  • Any Eng/Ger video · Max 100 submits/social
  ⚠️ Must tag @bitzcasino on Insta!

─────────────────────────
👇 *SELECT CAMPAIGN BELOW* 👇
"""

def campaign_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⚽ JACKBIT SPORTS ($50)", callback_data="cam_jb_sports")],
        [InlineKeyboardButton("🎲 JACKBIT GEN ($20)", callback_data="cam_jb_gen"),
         InlineKeyboardButton("🍀 LUCKY.FUN ($20)", callback_data="cam_lucky")],
        [InlineKeyboardButton("🎰 BITZ.IO ($20)", callback_data="cam_bitz")],
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

# ── NEW: /start Command ──
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🤖 Bot is ALIVE and running!\n\nSend me a valid Instagram Reel, YouTube Short, or TikTok link to begin processing.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    text_lower = text.lower()
    
    if "http" not in text_lower and "www." not in text_lower:
        return 

    valid = ("instagram.com", "youtube.com", "youtu.be", "tiktok.com")
    if not any(v in text_lower for v in valid):
        await update.message.reply_text("❌ Send a valid Instagram Reel, YouTube Short, or TikTok link.")
        return

    context.user_data["url"] = text 
    await update.message.reply_text(
        CAMPAIGN_INFO_TEXT,
        parse_mode="Markdown",
        reply_markup=campaign_keyboard()
    )

async def handle_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data  = query.data

    if data.startswith("cam_"):
        campaign = data[4:]
        context.user_data["campaign"] = campaign
        
        # Make the campaign name look pretty in the confirmation msg
        camp_names = {
            "jb_sports": "JACKBIT SPORTS",
            "jb_gen": "JACKBIT GENERAL",
            "lucky": "LUCKY.FUN",
            "bitz": "BITZ.IO"
        }
        
        await query.edit_message_text(
            f"✅ Campaign: *{camp_names.get(campaign, campaign.upper())}*\n\nStep 2 — Pick logo position:",
            parse_mode="Markdown",
            reply_markup=position_keyboard()
        )

    elif data.startswith("pos_"):
        position = data[4:]
        context.user_data["position"] = position
        pos_labels = {"top": "Top Center", "bottom": "Bottom Center", "c1": "Top Left", "c2": "Bottom Right"}
        await query.edit_message_text(
            f"✅ Position: *{pos_labels.get(position, position)}*\n\nStep 3 — Where to upload?",
            parse_mode="Markdown",
            reply_markup=upload_keyboard()
        )

    elif data.startswith("upload_"):
        target = data[7:]
        context.user_data["target"] = target
        await query.edit_message_text("⚙️ Sending to the Video Processor…")
        await send_to_processor(update, context)

async def send_to_processor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    status_msg = update.callback_query.message
    
    payload = {
        "url":               context.user_data.get("url"),
        "campaign":          context.user_data.get("campaign"),
        "position":          context.user_data.get("position"),
        "target":            context.user_data.get("target"),
        "webhook_reply_url": N8N_WEBHOOK_URL
    }

    log.info("Dispatching task to processor: %s", payload)

    try:
        response = await asyncio.to_thread(
            requests.post, PROCESSOR_URL, json=payload, timeout=10
        )
        response.raise_for_status()
        
        reply = response.json()
        q_pos = reply.get("queue_position", 1)
        camp  = payload["campaign"].upper()

        if q_pos == 1:
            await status_msg.edit_text(f"✅ *Processing now!*\nCampaign: `{camp}`\n\nYou'll get a message when done.", parse_mode="Markdown")
        else:
            await status_msg.edit_text(f"✅ *Queued!* You are #{q_pos} in line.\nCampaign: `{camp}`", parse_mode="Markdown")

    except Exception as e:
        log.error("Dispatch error: %s", e)
        await status_msg.edit_text(f"❌ Error reaching Processor: {str(e)}\nMake sure the processor container is running.")

if __name__ == "__main__":
    if not TOKEN: raise RuntimeError("TELEGRAM_TOKEN env var is not set!")
    if not N8N_WEBHOOK_URL: raise RuntimeError("N8N_WEBHOOK_URL env var is not set!")

    log.info("🤖 Bot starting…")
    app = ApplicationBuilder().token(TOKEN).build()
    
    # Add handlers
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(handle_buttons))
    
    app.run_polling(drop_pending_updates=True)
