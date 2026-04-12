import os
import sqlite3
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

DB_PATH = "bot_data.db"


def db():
    return sqlite3.connect(DB_PATH)


def init_db():
    conn = db()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            full_name TEXT,
            first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            plan_key TEXT,
            tx_hash TEXT,
            status TEXT DEFAULT 'pending',
            order_code TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.commit()
    conn.close()


def save_user(user):
    conn = db()
    cur = conn.cursor()
    username = f"@{user.username}" if user.username else ""
    cur.execute("""
        INSERT OR REPLACE INTO users (user_id, username, full_name)
        VALUES (?, ?, ?)
    """, (user.id, username, user.full_name))
    conn.commit()
    conn.close()


def get_all_user_ids():
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM users")
    rows = cur.fetchall()
    conn.close()
    return [r[0] for r in rows]


def create_order(user_id, plan_key, tx_hash):
    conn = db()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO orders (user_id, plan_key, tx_hash)
        VALUES (?, ?, ?)
    """, (user_id, plan_key, tx_hash))
    order_id = cur.lastrowid
    conn.commit()
    conn.close()
    return order_id


def set_order_status_by_user(user_id, status, code=None):
    conn = db()
    cur = conn.cursor()
    if code:
        cur.execute("""
            UPDATE orders
            SET status = ?, order_code = ?
            WHERE user_id = ? AND status = 'pending'
        """, (status, code, user_id))
    else:
        cur.execute("""
            UPDATE orders
            SET status = ?
            WHERE user_id = ? AND status = 'pending'
        """, (status, user_id))
    conn.commit()
    conn.close()


def order_code():
    chars = string.ascii_uppercase + string.digits
    return "".join(random.choice(chars) for _ in range(6))


def main_menu():
    return ReplyKeyboardMarkup(
        [["📦 پلن‌ها", "📞 پشتیبانی"]],
        resize_keyboard=True
    )


def plans_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📦 5GB - 19$", callback_data="p5")],
        [InlineKeyboardButton("📦 10GB - 33$", callback_data="p10")],
        [InlineKeyboardButton("📦 20GB - 55$", callback_data="p20")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="back_main")]
    ])


def support_back_btn():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 بازگشت", callback_data="back_main")]
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
    user = update.effective_user
    save_user(user)
    context.user_data.clear()

    await update.message.reply_text(
        "سلام 👋\nبه ربات فروش VPN خوش اومدی.",
        reply_markup=main_menu()
    )


async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN:
        return

    if not context.args:
        await update.message.reply_text("فرمت درست:\n/broadcast متن پیام")
        return

    text = " ".join(context.args)
    users = get_all_user_ids()
    sent = 0

    for user_id in users:
        try:
            await context.bot.send_message(user_id, text)
            sent += 1
        except:
            pass

    await update.message.reply_text(f"✅ پیام برای {sent} نفر ارسال شد.")


async def click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data
    clicker_id = q.from_user.id

    if data.startswith("reply_") and clicker_id == ADMIN:
        target_id = int(data.split("_", 1)[1])
        context.user_data["reply_to"] = target_id
        await q.message.reply_text("✍️ حالا پاسخ را بفرست.")
        return

    if data.startswith("ok_") and clicker_id == ADMIN:
        target_id = int(data.split("_", 1)[1])
        code = order_code()
        set_order_status_by_user(target_id, "approved", code)

        await context.bot.send_message(
            target_id,
            f"✅ پرداخت شما تایید شد\n\n🎟 کد سفارش: {code}\nسفارش شما در حال پیگیری است."
        )
        await q.message.reply_text(f"✅ سفارش تایید شد\n🎟 کد سفارش: {code}")
        return

    if data.startswith("no_") and clicker_id == ADMIN:
        target_id = int(data.split("_", 1)[1])
        set_order_status_by_user(target_id, "rejected")

        await context.bot.send_message(
            target_id,
            "❌ پرداخت شما تایید نشد.\nلطفاً اطلاعات پرداخت را دوباره بررسی کن یا با پشتیبانی در ارتباط باش."
        )
        await q.message.reply_text("❌ پیام رد برای مشتری ارسال شد.")
        return

    context.user_data.clear()

    if data == "back_main":
        await q.edit_message_text(
            "منوی اصلی:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📦 پلن‌ها", callback_data="plans")],
                [InlineKeyboardButton("📞 پشتیبانی", callback_data="support")]
            ])
        )
        return

    if data == "plans":
        await q.edit_message_text("پلن مورد نظر را انتخاب کن:", reply_markup=plans_menu())
        return

    if data == "support":
        context.user_data["mode"] = "support"
        await q.edit_message_text(
            "📞 پیام پشتیبانی‌ات را بفرست.",
            reply_markup=support_back_btn()
        )
        return

    if data in PLANS:
        name, price = PLANS[data]
        context.user_data["mode"] = "pay"
        context.user_data["plan"] = data

        await q.edit_message_text(
            f"✅ پلن انتخابی: {name} - {price}\n\n"
            f"💳 شبکه: BEP20\n"
            f"📍 آدرس ولت:\n{WALLET}\n\n"
            "هش تراکنش را بفرست، بعد عکس فیش را ارسال کن.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 بازگشت", callback_data="plans")]
            ])
        )
        return


async def text_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    save_user(user)

    text = update.message.text
    uid = user.id
    username = f"@{user.username}" if user.username else "ندارد"
    mode = context.user_data.get("mode")

    if text == "📦 پلن‌ها":
        await update.message.reply_text("پلن مورد نظر را انتخاب کن:", reply_markup=plans_menu())
        return

    if text == "📞 پشتیبانی":
        context.user_data.clear()
        context.user_data["mode"] = "support"
        await update.message.reply_text("📞 پیام پشتیبانی‌ات را بفرست.")
        return

    if uid == ADMIN and context.user_data.get("reply_to"):
        target_id = context.user_data["reply_to"]
        await context.bot.send_message(
            target_id,
            f"📩 پاسخ پشتیبانی:\n\n{text}"
        )
        await update.message.reply_text("✅ پاسخ برای مشتری ارسال شد.")
        context.user_data.pop("reply_to", None)
        return

    if mode == "support":
        await context.bot.send_message(
            ADMIN,
            f"📩 پیام پشتیبانی\n\n"
            f"👤 نام: {user.full_name}\n"
            f"🆔 User ID: {uid}\n"
            f"📎 Username: {username}\n\n"
            f"{text}",
            reply_markup=reply_btn(uid)
        )
        await update.message.reply_text("✅ پیام شما برای پشتیبانی ارسال شد.")
        return

    if mode == "pay":
        context.user_data["tx"] = text.strip()
        context.user_data["mode"] = "receipt"
        await update.message.reply_text("✅ هش دریافت شد. حالا عکس فیش را بفرست.")
        return

    await update.message.reply_text("از منو استفاده کن.", reply_markup=main_menu())


async def photo_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    save_user(user)

    uid = user.id
    username = f"@{user.username}" if user.username else "ندارد"
    mode = context.user_data.get("mode")

    if mode == "support":
        await context.bot.send_photo(
            ADMIN,
            update.message.photo[-1].file_id,
            caption=(
                f"📩 عکس پشتیبانی\n\n"
                f"👤 نام: {user.full_name}\n"
                f"🆔 User ID: {uid}\n"
                f"📎 Username: {username}"
            ),
            reply_markup=reply_btn(uid)
        )
        await update.message.reply_text("✅ عکس برای پشتیبانی ارسال شد.")
        return

    if mode == "receipt":
        plan_key = context.user_data.get("plan")
        tx = context.user_data.get("tx", "")
        name, price = PLANS.get(plan_key, ("?", "?"))
        tx_link = f"https://bscscan.com/tx/{tx}"

        create_order(uid, plan_key, tx)

        await context.bot.send_photo(
            ADMIN,
            update.message.photo[-1].file_id,
            caption=(
                f"🚨 پرداخت جدید برای بررسی\n\n"
                f"👤 نام: {user.full_name}\n"
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

        await update.message.reply_text("✅ اطلاعات پرداخت دریافت شد.\nسفارش شما برای بررسی ارسال شد.")
        context.user_data.clear()
        return

    await update.message.reply_text("اول از منو شروع کن.", reply_markup=main_menu())


def main():
    init_db()

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("broadcast", broadcast))
    app.add_handler(CallbackQueryHandler(click))
    app.add_handler(MessageHandler(filters.PHOTO, photo_msg))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_msg))

    print("Bot is running...")
    app.run_polling()


if __name__ == "__main__":
    main()
