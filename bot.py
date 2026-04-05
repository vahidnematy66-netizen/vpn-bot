import random
import string
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters

TOKEN = "8762120219:AAHeN_DjtVvn5QI1R6pTHC_4qobtnXVgTy4"
ADMIN = 33872273
WALLET = "0x53ed8e2548924B8B20037BBB33098aba7b89bE0D"

PLANS = {
    "p5": ("5GB", "19$"),
    "p10": ("10GB", "33$"),
    "p20": ("20GB", "55$")
}

def order_code():
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=6))

def menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📦 پلن‌ها", callback_data="plans")],
        [InlineKeyboardButton("📞 پشتیبانی", callback_data="support")]
    ])

def plans():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📦 5GB - 19$", callback_data="p5")],
        [InlineKeyboardButton("📦 10GB - 33$", callback_data="p10")],
        [InlineKeyboardButton("📦 20GB - 55$", callback_data="p20")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="back")]
    ])

def reply_btn(uid):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✉️ پاسخ", callback_data=f"reply_{uid}")]
    ])

def order_btns(uid):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✉️ پاسخ", callback_data=f"reply_{uid}"),
            InlineKeyboardButton("✅ تایید", callback_data=f"ok_{uid}"),
            InlineKeyboardButton("❌ رد", callback_data=f"no_{uid}")
        ]
    ])

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("سلام 👋\nبه ربات فروش VPN خوش اومدی.", reply_markup=menu())

async def click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    d = q.data

    if d.startswith("reply_") and q.from_user.id == ADMIN:
        context.user_data["reply_to"] = int(d.split("_")[1])
        await q.message.reply_text("✍️ جواب رو بفرست")
        return

    if d.startswith("ok_") and q.from_user.id == ADMIN:
        uid = int(d.split("_")[1])
        code = order_code()
        await context.bot.send_message(uid, f"✅ پرداخت تایید شد\nکد سفارش: {code}")
        await q.message.reply_text("✅ تایید شد")
        return

    if d.startswith("no_") and q.from_user.id == ADMIN:
        uid = int(d.split("_")[1])
        await context.bot.send_message(uid, "❌ پرداخت رد شد")
        await q.message.reply_text("❌ رد شد")
        return

    context.user_data.clear()

    if d == "plans":
        await q.edit_message_text("پلن رو انتخاب کن:", reply_markup=plans())

    elif d == "support":
        context.user_data["mode"] = "support"
        await q.edit_message_text("پیامتو بفرست")

    elif d == "back":
        await q.edit_message_text("سلام 👋", reply_markup=menu())

    elif d in PLANS:
        name, price = PLANS[d]
        context.user_data["mode"] = "pay"
        context.user_data["plan"] = d
        await q.edit_message_text(f"{name} - {price}\n\n{WALLET}\n\nهش رو بفرست")

async def text_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    uid = u.id
    username = f"@{u.username}" if u.username else "ندارد"
    mode = context.user_data.get("mode")

    # جواب ادمین
    if uid == ADMIN and context.user_data.get("reply_to"):
        target = context.user_data["reply_to"]
        await context.bot.send_message(target, update.message.text)
        context.user_data.pop("reply_to")
        return

    if mode == "support":
        await context.bot.send_message(
            ADMIN,
            f"📩 پشتیبانی\n{u.full_name}\n{uid}\n{username}\n\n{update.message.text}",
            reply_markup=reply_btn(uid)
        )
        await update.message.reply_text("ارسال شد")

    elif mode == "pay":
        context.user_data["tx"] = update.message.text
        context.user_data["mode"] = "receipt"
        await update.message.reply_text("عکس فیش رو بفرست")

    else:
        await update.message.reply_text("از منو استفاده کن")

async def photo_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    uid = u.id
    username = f"@{u.username}" if u.username else "ندارد"
    mode = context.user_data.get("mode")

    if mode == "receipt":
        tx = context.user_data.get("tx", "")
        plan = context.user_data.get("plan")

        await context.bot.send_photo(
            ADMIN,
            update.message.photo[-1].file_id,
            caption=f"🚨 سفارش\n{u.full_name}\n{uid}\n{username}\n{PLANS[plan]}\n{tx}",
            reply_markup=order_btns(uid)
        )

        await update.message.reply_text("ارسال شد")
        context.user_data.clear()

app = Application.builder().token(TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CallbackQueryHandler(click))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_msg))
app.add_handler(MessageHandler(filters.PHOTO, photo_msg))

print("Bot is running...")
app.run_polling()
