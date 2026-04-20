import sqlite3
import random
import string
import logging
from decimal import Decimal
from typing import Optional

import requests
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# =========================
# Config
# =========================

TOKEN = "8762120219:AAHeN_DjtVvn5QI1R6pTHC_4qobtnXVgTy4"
ADMIN = 33872273
NOWPAYMENTS_API_KEY = "N3H3MN5-JCKMMMW-G5MEPGY-6HK4ET3"

DB_PATH = "bot_data.db"
NOW_BASE = "https://api.nowpayments.io/v1"

ECONOMY_ACCESS_CODE = "netazadi_eghtesadi"

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# =========================
# Plans
# =========================

PLAN_CATEGORIES = {
    "vip": {
        "title": "⭐ پلن VIP",
        "subtitle": "مخصوص ترید، هوش مصنوعی و گیم",
        "emoji": "⭐",
        "plans": {
            "vip5": {"name": "5GB", "price_usd": Decimal("19.20")},
            "vip10": {"name": "10GB", "price_usd": Decimal("33.35")},
            "vip20": {"name": "20GB", "price_usd": Decimal("55.55")},
            "vip30": {"name": "30GB", "price_usd": Decimal("77.75")},
        },
    },
    "eco": {
        "title": "💎 پکیج اقتصادی",
        "subtitle": "مخصوص اینستاگرام، تلگرام و وب‌گردی",
        "emoji": "💎",
        "plans": {
            "eco5": {"name": "5GB", "price_usd": Decimal("13.00")},
            "eco10": {"name": "10GB", "price_usd": Decimal("26.00")},
        },
    },
}

PAY_CURRENCIES = {
    "usdttrc20": "USDT (TRC20)",
    "usdtbsc": "USDT (BSC)",
    "ltc": "Litecoin (LTC)",
    "btc": "Bitcoin (BTC)",
}

FINAL_SUCCESS_STATUSES = {"confirmed", "sending", "finished"}


# =========================
# DB
# =========================

def db():
    return sqlite3.connect(DB_PATH)


def column_exists(cur, table_name, column_name):
    cur.execute(f"PRAGMA table_info({table_name})")
    cols = cur.fetchall()
    return any(col[1] == column_name for col in cols)


def init_db():
    conn = db()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            full_name TEXT,
            first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            economy_access INTEGER DEFAULT 0
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            category_key TEXT,
            plan_key TEXT,
            plan_name TEXT,
            price_usd TEXT,
            pay_currency TEXT,
            pay_currency_label TEXT,
            np_payment_id TEXT,
            payment_status TEXT DEFAULT 'waiting',
            pay_address TEXT,
            pay_amount TEXT,
            payin_extra_id TEXT,
            order_code TEXT,
            is_notified INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    extra_user_columns = {
        "economy_access": "INTEGER DEFAULT 0",
    }

    for col_name, col_type in extra_user_columns.items():
        if not column_exists(cur, "users", col_name):
            cur.execute(f"ALTER TABLE users ADD COLUMN {col_name} {col_type}")

    extra_order_columns = {
        "category_key": "TEXT",
        "plan_key": "TEXT",
        "plan_name": "TEXT",
        "price_usd": "TEXT",
        "pay_currency": "TEXT",
        "pay_currency_label": "TEXT",
        "np_payment_id": "TEXT",
        "payment_status": "TEXT DEFAULT 'waiting'",
        "pay_address": "TEXT",
        "pay_amount": "TEXT",
        "payin_extra_id": "TEXT",
        "order_code": "TEXT",
        "is_notified": "INTEGER DEFAULT 0",
        "updated_at": "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
    }

    for col_name, col_type in extra_order_columns.items():
        if not column_exists(cur, "orders", col_name):
            cur.execute(f"ALTER TABLE orders ADD COLUMN {col_name} {col_type}")

    conn.commit()
    conn.close()


def save_user(user):
    conn = db()
    cur = conn.cursor()
    username = f"@{user.username}" if user.username else ""
    cur.execute("""
        INSERT INTO users (user_id, username, full_name)
        VALUES (?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            username = excluded.username,
            full_name = excluded.full_name
    """, (user.id, username, user.full_name))
    conn.commit()
    conn.close()


def user_has_economy_access(user_id: int) -> bool:
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT economy_access FROM users WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    conn.close()
    return bool(row and row[0] == 1)


def grant_economy_access(user_id: int):
    conn = db()
    cur = conn.cursor()
    cur.execute("""
        UPDATE users
        SET economy_access = 1
        WHERE user_id = ?
    """, (user_id,))
    conn.commit()
    conn.close()


def get_all_user_ids():
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM users")
    rows = cur.fetchall()
    conn.close()
    return [r[0] for r in rows]


def create_order(
    user_id: int,
    category_key: str,
    plan_key: str,
    plan_name: str,
    price_usd: str,
    pay_currency: str,
    pay_currency_label: str,
    np_payment_id: str,
    pay_address: str,
    pay_amount: str,
    payin_extra_id: Optional[str] = None,
):
    conn = db()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO orders (
            user_id, category_key, plan_key, plan_name, price_usd,
            pay_currency, pay_currency_label, np_payment_id,
            pay_address, pay_amount, payin_extra_id
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        user_id, category_key, plan_key, plan_name, price_usd,
        pay_currency, pay_currency_label, np_payment_id,
        pay_address, pay_amount, payin_extra_id
    ))
    order_id = cur.lastrowid
    conn.commit()
    conn.close()
    return order_id


def get_order_by_id(order_id: int):
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM orders WHERE id = ?", (order_id,))
    row = cur.fetchone()
    conn.close()
    return row


def get_pending_orders():
    conn = db()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, user_id, plan_name, price_usd, pay_currency, pay_currency_label,
               np_payment_id, payment_status, order_code, is_notified
        FROM orders
        WHERE payment_status NOT IN ('confirmed', 'sending', 'finished', 'failed', 'expired', 'refunded')
    """)
    rows = cur.fetchall()
    conn.close()
    return rows


def update_order_status(order_id: int, status: str):
    conn = db()
    cur = conn.cursor()
    cur.execute("""
        UPDATE orders
        SET payment_status = ?, updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (status, order_id))
    conn.commit()
    conn.close()


def set_order_success(order_id: int, status: str, code: str):
    conn = db()
    cur = conn.cursor()
    cur.execute("""
        UPDATE orders
        SET payment_status = ?, order_code = ?, updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (status, code, order_id))
    conn.commit()
    conn.close()


def mark_order_notified(order_id: int):
    conn = db()
    cur = conn.cursor()
    cur.execute("""
        UPDATE orders
        SET is_notified = 1, updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (order_id,))
    conn.commit()
    conn.close()


def get_order_notification_state(order_id: int):
    conn = db()
    cur = conn.cursor()
    cur.execute("""
        SELECT user_id, plan_name, price_usd, pay_currency_label, payment_status, order_code, is_notified
        FROM orders
        WHERE id = ?
    """, (order_id,))
    row = cur.fetchone()
    conn.close()
    return row


# =========================
# Helpers
# =========================

def ticket_code():
    chars = string.ascii_uppercase + string.digits
    return "VPN-" + "".join(random.choice(chars) for _ in range(6))


def main_menu():
    return ReplyKeyboardMarkup(
        [["📦 پلن‌ها", "📞 پشتیبانی"]],
        resize_keyboard=True
    )


def categories_menu(user_id: int):
    rows = [
        [InlineKeyboardButton("⭐ پلن VIP", callback_data="cat_vip")]
    ]

    if user_has_economy_access(user_id):
        rows.append([InlineKeyboardButton("💎 پکیج اقتصادی", callback_data="cat_eco")])

    rows.append([InlineKeyboardButton("📞 پشتیبانی", callback_data="support")])
    return InlineKeyboardMarkup(rows)


def category_plans_menu(category_key: str):
    category = PLAN_CATEGORIES[category_key]
    rows = []

    for plan_key, item in category["plans"].items():
        label = f'{category["emoji"]} {item["name"]} - {item["price_usd"]} USDT'
        rows.append([InlineKeyboardButton(label, callback_data=f"plan_{plan_key}")])

    rows.append([InlineKeyboardButton("🔙 بازگشت", callback_data="show_categories")])
    return InlineKeyboardMarkup(rows)


def currency_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💵 USDT (TRC20)", callback_data="pay_usdttrc20")],
        [InlineKeyboardButton("💵 USDT (BSC)", callback_data="pay_usdtbsc")],
        [InlineKeyboardButton("⚡ Litecoin (LTC)", callback_data="pay_ltc")],
        [InlineKeyboardButton("🟠 Bitcoin (BTC)", callback_data="pay_btc")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="show_categories")],
    ])


def support_back_btn():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 بازگشت", callback_data="show_categories")]
    ])


def reply_btn(user_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✉️ پاسخ", callback_data=f"reply_{user_id}")]
    ])


def post_payment_buttons(order_id: int):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 بررسی وضعیت پرداخت", callback_data=f"checkpay_{order_id}")],
        [InlineKeyboardButton("📞 پشتیبانی", callback_data="support")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="show_categories")],
    ])


def success_support_button():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📞 پیام به پشتیبانی", callback_data="support")],
        [InlineKeyboardButton("📦 بازگشت به پلن‌ها", callback_data="show_categories")],
    ])


def find_category_by_plan(plan_key: str) -> Optional[str]:
    for cat_key, cat in PLAN_CATEGORIES.items():
        if plan_key in cat["plans"]:
            return cat_key
    return None


def get_plan(plan_key: str):
    cat_key = find_category_by_plan(plan_key)
    if not cat_key:
        return None, None
    return cat_key, PLAN_CATEGORIES[cat_key]["plans"][plan_key]


# =========================
# NOWPayments API
# =========================

def np_headers():
    return {
        "x-api-key": NOWPAYMENTS_API_KEY,
        "Content-Type": "application/json",
    }


def create_nowpayment(price_amount: str, pay_currency: str, order_ref: str, order_description: str):
    payload = {
        "price_amount": float(price_amount),
        "price_currency": "usd",
        "pay_currency": pay_currency,
        "order_id": order_ref,
        "order_description": order_description,
    }

    r = requests.post(
        f"{NOW_BASE}/payment",
        headers=np_headers(),
        json=payload,
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def get_nowpayment_status(payment_id: str):
    r = requests.get(
        f"{NOW_BASE}/payment/{payment_id}",
        headers=np_headers(),
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


# =========================
# Bot handlers
# =========================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    save_user(user)
    context.user_data.clear()

    await update.message.reply_text(
        "سلام 👋\nبه ربات فروش VPN خوش اومدی.\n\n"
        "از منوی زیر دسته‌بندی موردنظرت رو انتخاب کن:",
        reply_markup=main_menu()
    )
    await update.message.reply_text(
        "📦 دسته‌بندی پلن‌ها:",
        reply_markup=categories_menu(user.id)
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
        except Exception as e:
            logger.warning("Broadcast failed to %s: %s", user_id, e)

    await update.message.reply_text(f"✅ پیام برای {sent} نفر ارسال شد.")


async def show_categories_message(target_message, user_id: int):
    await target_message.edit_text(
        "📦 دسته‌بندی پلن‌ها را انتخاب کن:",
        reply_markup=categories_menu(user_id)
    )


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

    if data == "show_categories":
        context.user_data.clear()
        await show_categories_message(q.message, q.from_user.id)
        return

    if data == "support":
        context.user_data.clear()
        context.user_data["mode"] = "support"
        await q.message.edit_text(
            "📞 پیام پشتیبانی‌ات را بفرست.\n"
            "اگر سوالی درباره پرداخت یا دریافت کانفیگ داری، همینجا بنویس.",
            reply_markup=support_back_btn()
        )
        return

    if data.startswith("cat_"):
        category_key = data.split("_", 1)[1]

        if category_key == "eco" and not user_has_economy_access(q.from_user.id):
            await q.message.reply_text("❌ دسترسی به این پکیج برای شما فعال نیست.")
            return

        category = PLAN_CATEGORIES[category_key]
        context.user_data.clear()
        context.user_data["category"] = category_key

        await q.message.edit_text(
            f"{category['title']}\n"
            f"({category['subtitle']})\n\n"
            "پلن موردنظر را انتخاب کن:",
            reply_markup=category_plans_menu(category_key)
        )
        return

    if data.startswith("plan_"):
        plan_key = data.split("_", 1)[1]
        cat_key, plan = get_plan(plan_key)
        if not plan:
            await q.message.reply_text("❌ پلن پیدا نشد.")
            return

        if cat_key == "eco" and not user_has_economy_access(q.from_user.id):
            await q.message.reply_text("❌ دسترسی به این پکیج برای شما فعال نیست.")
            return

        context.user_data["category"] = cat_key
        context.user_data["plan_key"] = plan_key

        category = PLAN_CATEGORIES[cat_key]

        await q.message.edit_text(
            f"{category['title']}\n"
            f"({category['subtitle']})\n\n"
            f"✅ پلن انتخابی: {plan['name']}\n"
            f"💰 مبلغ نهایی: {plan['price_usd']} USDT\n\n"
            "لطفاً ارز پرداخت را انتخاب کن:",
            reply_markup=currency_menu()
        )
        return

    if data.startswith("pay_"):
        pay_currency = data.split("_", 1)[1]
        pay_currency_label = PAY_CURRENCIES.get(pay_currency, pay_currency)

        plan_key = context.user_data.get("plan_key")
        if not plan_key:
            await q.message.reply_text("❌ اول پلن را انتخاب کن.")
            return

        category_key, plan = get_plan(plan_key)
        if not plan:
            await q.message.reply_text("❌ پلن پیدا نشد.")
            return

        if category_key == "eco" and not user_has_economy_access(q.from_user.id):
            await q.message.reply_text("❌ دسترسی به این پکیج برای شما فعال نیست.")
            return

        price_usd = str(plan["price_usd"])
        plan_name = plan["name"]

        order_ref = f"TG-{q.from_user.id}-{random.randint(100000, 999999)}"
        order_description = f"{PLAN_CATEGORIES[category_key]['title']} | {plan_name}"

        try:
            payment = create_nowpayment(
                price_amount=price_usd,
                pay_currency=pay_currency,
                order_ref=order_ref,
                order_description=order_description
            )
        except requests.HTTPError as e:
            logger.exception("NOWPayments create payment failed")
            detail = ""
            try:
                detail = e.response.text
            except Exception:
                pass
            await q.message.reply_text(
                "❌ ساخت لینک پرداخت ناموفق بود.\n"
                "اگر این خطا تکرار شد، ارز دیگری را انتخاب کن یا به پشتیبانی پیام بده."
            )
            if detail:
                await context.bot.send_message(
                    ADMIN,
                    f"⚠️ خطا در ساخت پرداخت NOWPayments\nUser: {q.from_user.id}\n{detail}"
                )
            return
        except Exception as e:
            logger.exception("Unexpected create payment error")
            await q.message.reply_text("❌ خطا در ارتباط با درگاه پرداخت. دوباره تلاش کن.")
            await context.bot.send_message(
                ADMIN,
                f"⚠️ خطا در ساخت پرداخت\nUser: {q.from_user.id}\n{e}"
            )
            return

        np_payment_id = str(payment.get("payment_id", ""))
        pay_address = payment.get("pay_address", "")
        pay_amount = str(payment.get("pay_amount", ""))
        payin_extra_id = payment.get("payin_extra_id") or payment.get("payin_extra_id_name") or ""

        if not np_payment_id or not pay_address or not pay_amount:
            await q.message.reply_text("❌ اطلاعات پرداخت ناقص برگشت داده شد. دوباره تلاش کن.")
            return

        order_id = create_order(
            user_id=q.from_user.id,
            category_key=category_key,
            plan_key=plan_key,
            plan_name=plan_name,
            price_usd=price_usd,
            pay_currency=pay_currency,
            pay_currency_label=pay_currency_label,
            np_payment_id=np_payment_id,
            pay_address=pay_address,
            pay_amount=pay_amount,
            payin_extra_id=payin_extra_id,
        )

        extra_line = f"\n🧷 Memo / Tag: {payin_extra_id}" if payin_extra_id else ""

        await q.message.edit_text(
            "✅ پرداخت ساخته شد\n\n"
            f"📦 پلن: {plan_name}\n"
            f"💳 ارز انتخابی: {pay_currency_label}\n"
            f"💰 مبلغ قابل پرداخت: {pay_amount} {pay_currency.upper()}\n"
            f"🏷 مبلغ پلن: {price_usd} USDT\n\n"
            "📍 آدرس پرداخت:\n"
            f"{pay_address}"
            f"{extra_line}\n\n"
            "بعد از پرداخت، ربات به‌صورت خودکار وضعیت را بررسی می‌کند.\n"
            "اگر خواستی، دکمه بررسی وضعیت را هم بزن.",
            reply_markup=post_payment_buttons(order_id)
        )
        return

    if data.startswith("checkpay_"):
        order_id = int(data.split("_", 1)[1])
        order = get_order_by_id(order_id)

        if not order:
            await q.message.reply_text("❌ سفارش پیدا نشد.")
            return

        np_payment_id = order[8]
        current_status = order[9]

        if current_status in FINAL_SUCCESS_STATUSES:
            state = get_order_notification_state(order_id)
            if state:
                _, _, _, _, _, code, _ = state
                await q.message.reply_text(
                    "✅ این پرداخت قبلاً تایید شده است.\n\n"
                    f"🎫 Ticket ID: {code}\n"
                    "برای دریافت کانفیگ از بخش پشتیبانی پیام بده.",
                    reply_markup=success_support_button()
                )
            return

        try:
            payment_data = get_nowpayment_status(np_payment_id)
            status = payment_data.get("payment_status", "waiting")
            update_order_status(order_id, status)
        except Exception:
            await q.message.reply_text(
                "⏳ هنوز نتیجه قطعی دریافت نشد.\n"
                "کمی بعد دوباره بررسی کن."
            )
            return

        if status in FINAL_SUCCESS_STATUSES:
            await finalize_paid_order(order_id, context)
            return

        status_texts = {
            "waiting": "در انتظار پرداخت",
            "confirming": "در حال تایید شبکه",
            "partially_paid": "بخشی از مبلغ پرداخت شده",
            "failed": "ناموفق",
            "expired": "منقضی شده",
        }

        await q.message.reply_text(
            f"🔄 وضعیت فعلی پرداخت: {status_texts.get(status, status)}"
        )
        return


async def finalize_paid_order(order_id: int, context: ContextTypes.DEFAULT_TYPE):
    state = get_order_notification_state(order_id)
    if not state:
        return

    user_id, plan_name, price_usd, pay_currency_label, status, code, is_notified = state

    if is_notified:
        return

    if not code:
        code = ticket_code()
        set_order_success(order_id, status, code)

    try:
        await context.bot.send_message(
            user_id,
            "✅ پرداخت شما با موفقیت تایید شد\n\n"
            f"🎫 Ticket ID: {code}\n"
            "برای دریافت کانفیگ، لطفاً از بخش پشتیبانی به ما پیام بده.",
            reply_markup=success_support_button()
        )

        await context.bot.send_message(
            ADMIN,
            "💸 پرداخت جدید با موفقیت تایید شد\n\n"
            f"🆔 Order ID: {order_id}\n"
            f"👤 User ID: {user_id}\n"
            f"📦 پلن: {plan_name}\n"
            f"💰 مبلغ: {price_usd} USDT\n"
            f"💳 ارز پرداخت: {pay_currency_label}\n"
            f"📌 وضعیت: {status}\n"
            f"🎫 Ticket ID: {code}"
        )

        mark_order_notified(order_id)
    except Exception as e:
        logger.exception("Notify finalize paid order failed: %s", e)


async def payment_watcher(context: ContextTypes.DEFAULT_TYPE):
    rows = get_pending_orders()
    if not rows:
        return

    for row in rows:
        order_id, user_id, plan_name, price_usd, pay_currency, pay_currency_label, np_payment_id, old_status, order_code, is_notified = row
        try:
            payment_data = get_nowpayment_status(np_payment_id)
            new_status = payment_data.get("payment_status", old_status)

            if new_status != old_status:
                update_order_status(order_id, new_status)

            if new_status in FINAL_SUCCESS_STATUSES:
                await finalize_paid_order(order_id, context)

        except Exception as e:
            logger.warning("payment_watcher failed for order %s: %s", order_id, e)


async def text_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    save_user(user)

    text = update.message.text.strip()
    uid = user.id
    username = f"@{user.username}" if user.username else "ندارد"
    mode = context.user_data.get("mode")

    if text == ECONOMY_ACCESS_CODE:
        if user_has_economy_access(uid):
            await update.message.reply_text(
                "✅ پکیج اقتصادی از قبل برای شما فعال شده است.",
                reply_markup=categories_menu(uid)
            )
        else:
            grant_economy_access(uid)
            await update.message.reply_text(
                "✅ پکیج اقتصادی برای شما فعال شد.",
                reply_markup=categories_menu(uid)
            )
            await context.bot.send_message(
                ADMIN,
                f"🔓 دسترسی پکیج اقتصادی فعال شد\n\n"
                f"👤 نام: {user.full_name}\n"
                f"🆔 User ID: {uid}\n"
                f"📎 Username: {username}"
            )
        return

    if text == "📦 پلن‌ها":
        context.user_data.clear()
        await update.message.reply_text(
            "📦 دسته‌بندی پلن‌ها را انتخاب کن:",
            reply_markup=categories_menu(uid)
        )
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

    await update.message.reply_text(
        "برای خرید نیازی به ارسال عکس فیش نیست.\n"
        "اگر سوالی داری از بخش پشتیبانی پیام بده.",
        reply_markup=main_menu()
    )


def main():
    init_db()

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("broadcast", broadcast))
    app.add_handler(CallbackQueryHandler(click))
    app.add_handler(MessageHandler(filters.PHOTO, photo_msg))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_msg))

    app.job_queue.run_repeating(payment_watcher, interval=60, first=20)

    print("Bot is running...")
    app.run_polling()


if __name__ == "__main__":
    main()
