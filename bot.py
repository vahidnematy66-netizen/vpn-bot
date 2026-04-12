import random
import string
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters

TOKEN = "8762120219:AAHeN_DjtVvn5QI1R6pTHC_4qobtnXVgTy4"
ADMIN = 33872273
WALLET = "0x53ed8e2548924B8B20037BBB33098aba7b89bE0D"

PLANS = {
    "p5": ("5GB", "19$"),
    "p10": ("10GB", "33$"),
    "p20": ("20GB", "55$")
}

USERS = set()

def order_code():
    chars = string.ascii_uppercase + string.digits
    return "".join(random.choice(chars) for _ in range(6))

def main_menu():
    keyboard = [
        ["📦 پلن‌ها", "📞 پشتیبانی"]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def plans_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📦 5GB - 19$", callback_data="p5")],
        [InlineKeyboardButton("📦 10GB - 33$", callback_data="p10")],
        [InlineKeyboardButton("📦 20GB - 55$", callback_data="p20")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="back")]
    ])

def reply_btn(user_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✉️ پاسخ", callback_data=f"reply_{user_id}")]
    ])

def order_btns(user_id):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✉️ پاسخ", callback_data=f"reply_{user_id}"),
            InlineKeyboardButton("✅ تایید", callback_data=f"ok_{user_id}"),
            InlineKeyboardButton("❌ رد", callback_data=f"no_{user_id}")
        ]
    ])

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    USERS.add(user_id)

    context.user_data.clear()
    await update.message.reply_text(
        "سلام 👋\nبه ربات فروش VPN خوش اومدی.",
        reply_markup=main_menu()
    )

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN:
        return

    text = " ".join(context.args)

    for user in USERS:
        try:
            await context.bot.send_message(user, text)
        except:
            pass

    await update.message.reply_text("✅ پیام برای همه ارسال شد")

async def click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    d = q.data
    admin_id = q.from_user.id

    if d.startswith("reply_") and admin_id == ADMIN:
        target = int(d.split("_")[1])
        context.user_data["reply_to"] = target
        await q.message.reply_text("✍️ جواب رو بفرست")
        return

    if d.startswith("ok_") and admin_id == ADMIN:
        target = int(d.split("_")[1])
        code = order_code()
        await context.bot.send_message(target, f"✅ تایید شد\nکد: {code}")
        return

    if d.startswith("no_") and admin_id == ADMIN:
        target = int(d.split("_")[1])
        await context.bot.send_message(target, "❌ پرداخت رد شد")
        return

    if d == "back":
        await q.edit_message_text("برگشتی به منو")
        return

    if d in PLANS:
        name, price = PLANS[d]
        context.user_data["mode"] = "pay"
        await q.edit_message_text(
            f"پلن: {name}\nقیمت: {price}\n\nهش تراکنش رو بفرست"
        )

async def text_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text

    if text == "📦 پلن‌ها":
        await update.message.reply_text("انتخاب کن:", reply_markup=plans_menu())
        return

    if text == "📞 پشتیبانی":
        context.user_data["mode"] = "support"
        await update.message.reply_text("پیامتو بفرست")
        return

    u = update.effective_user
    uid = u.id
    username = f"@{u.username}" if u.username else "ندارد"
    mode = context.user_data.get("mode")

    if uid == ADMIN and context.user_data.get("reply_to"):
        target = context.user_data["reply_to"]
        await context.bot.send_message(target, f"📩 پاسخ:\n{text}")
        context.user_data.pop("reply_to", None)
        return

    if mode == "support":
        await context.bot.send_message(
            ADMIN,
            f"📩 پیام\n{u.full_name}\n{username}\n{text}",
            reply_markup=reply_btn(uid)
        )
        await update.message.reply_text("ارسال شد")
        return

    if mode == "pay":
        context.user_data["tx"] = text
        context.user_data["mode"] = "receipt"
        await update.message.reply_text("حالا عکس بفرست")

async def photo_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    uid = u.id
    username = f"@{u.username}" if u.username else "ندارد"

    if context.user_data.get("mode") == "receipt":
        await context.bot.send_photo(
            ADMIN,
            update.message.photo[-1].file_id,
            caption=f"{u.full_name}\n{username}",
            reply_markup=order_btns(uid)
        )
        await update.message.reply_text("ثبت شد")

app = Application.builder().token(TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("broadcast", broadcast))
app.add_handler(CallbackQueryHandler(click))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_msg))
app.add_handler(MessageHandler(filters.PHOTO, photo_msg))

print("Bot is running...")
app.run_polling()
