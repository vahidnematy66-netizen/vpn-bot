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
    chars = string.ascii_uppercase + string.digits
    return "".join(random.choice(chars) for _ in range(6))

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
    context.user_data.clear()
    await update.message.reply_text(
        "سلام 👋\nبه ربات فروش VPN خوش اومدی.",
        reply_markup=menu()
    )

async def click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    d = q.data
    admin_id = q.from_user.id

    if d.startswith("reply_") and admin_id == ADMIN:
        target = int(d.split("_", 1)[1])
        context.user_data["reply_to"] = target
        await q.message.reply_text("✍️ حالا پاسخ را بفرست.")
        return

    if d.startswith("ok_") and admin_id == ADMIN:
        target = int(d.split("_", 1)[1])
        code = order_code()
        await context.bot.send_message(
            target,
            f"✅ پرداخت شما تایید شد\n\n🎟 کد سفارش: {code}\nسفارش شما در حال پیگیری است."
        )
        await q.message.reply_text(f"✅ مشتری تایید شد\n🎟 کد سفارش: {code}")
        return

    if d.startswith("no_") and admin_id == ADMIN:
        target = int(d.split("_", 1)[1])
        await context.bot.send_message(
            target,
            "❌ پرداخت شما تایید نشد.\nلطفاً اطلاعات پرداخت را دوباره بررسی کن یا با پشتیبانی در ارتباط باش."
        )
        await q.message.reply_text("❌ پیام رد برای مشتری ارسال شد.")
        return

    context.user_data.clear()

    if d == "plans":
        await q.edit_message_text("پلن مورد نظر را انتخاب کن:", reply_markup=plans())

    elif d == "support":
        context.user_data["mode"] = "support"
        await q.edit_message_text(
            "📞 پیام پشتیبانی‌ات را بفرست.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 بازگشت", callback_data="back")]
            ])
        )

    elif d == "back":
        await q.edit_message_text(
            "سلام 👋\nبه ربات فروش VPN خوش اومدی.",
            reply_markup=menu()
        )

    elif d in PLANS:
        name, price = PLANS[d]
        context.user_data["mode"] = "pay"
        context.user_data["plan"] = d
        await q.edit_message_text(
            f"✅ پلن انتخابی: {name} - {price}\n\n"
            f"💳 شبکه: BEP20\n"
            f"📍 آدرس ولت:\n{WALLET}\n\n"
            "هش تراکنش را بفرست، بعد عکس فیش را ارسال کن.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 بازگشت", callback_data="plans")]
            ])
        )

async def text_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    uid = u.idusername = f"@{u.username}" if u.username else "ندارد"
    mode = context.user_data.get("mode")

    if uid == ADMIN and context.user_data.get("reply_to"):
        target = context.user_data["reply_to"]
        await context.bot.send_message(target, f"📩 پاسخ پشتیبانی:\n\n{update.message.text}")
        await update.message.reply_text("✅ پاسخ برای مشتری ارسال شد.")
        context.user_data.pop("reply_to", None)
        return

    if mode == "support":
        await context.bot.send_message(
            ADMIN,
            f"📩 پیام پشتیبانی\n\n"
            f"👤 نام: {u.full_name}\n"
            f"🆔 User ID: {uid}\n"
            f"📎 Username: {username}\n\n"
            f"{update.message.text}",
            reply_markup=reply_btn(uid)
        )
        await update.message.reply_text("✅ پیام شما برای پشتیبانی ارسال شد.")

    elif mode == "pay":
        tx = update.message.text.strip()
        context.user_data["tx"] = tx
        context.user_data["mode"] = "receipt"
        await update.message.reply_text("✅ هش دریافت شد. حالا عکس فیش را بفرست.")

    else:
        await update.message.reply_text("از منو استفاده کن.")

async def photo_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    uid = u.id
    username = f"@{u.username}" if u.username else "ندارد"
    mode = context.user_data.get("mode")

    if mode == "support":
        await context.bot.send_photo(
            ADMIN,
            update.message.photo[-1].file_id,
            caption=(
                f"📩 عکس پشتیبانی\n\n"
                f"👤 نام: {u.full_name}\n"
                f"🆔 User ID: {uid}\n"
                f"📎 Username: {username}"
            ),
            reply_markup=reply_btn(uid)
        )
        await update.message.reply_text("✅ عکس برای پشتیبانی ارسال شد.")

    elif mode == "receipt":
        plan = context.user_data.get("plan")
        tx = context.user_data.get("tx", "")
        name, price = PLANS.get(plan, ("?", "?"))
        tx_link = f"https://bscscan.com/tx/{tx}"

        await context.bot.send_photo(
            ADMIN,
            update.message.photo[-1].file_id,
            caption=(
                f"🚨 پرداخت جدید برای بررسی\n\n"
                f"👤 نام: {u.full_name}\n"
                f"🆔 User ID: {uid}\n"
                f"📎 Username: {username}\n"
                f"📦 پلن: {name}\n"
                f"💵 مبلغ: {price}\n"
                f"🔗 هش:\n{tx}\n\n"
                f"🌐 لینک بررسی:\n{tx_link}\n\n"
                f"⚠️ این سفارش را ویژه بررسی کن."
            ),
            reply_markup=order_btns(uid)
        )

        await update.message.reply_text(
            "✅ اطلاعات پرداخت دریافت شد.\nسفارش شما برای بررسی ارسال شد."
        )
        context.user_data.clear()

    else:
        await update.message.reply_text("اول از منو شروع کن.")

app = Application.builder().token(TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(CallbackQueryHandler(click))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_msg))
app.add_handler(MessageHandler(filters.PHOTO, photo_msg))

print("Bot is running...")
app.run_polling()