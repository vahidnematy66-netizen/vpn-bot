import sqlite3
import random
import string
import logging
import threading
from decimal import Decimal
from typing import Optional, Tuple

import requests
from flask import Flask, request, jsonify
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
# CONFIG
# =========================

TOKEN = "8762120219:AAHeN_DjtVvn5QI1R6pTHC_4qobtnXVgTy4"
ADMIN = 33872273
OXAPAY_MERCHANT_API_KEY = "AUY80X-QAAJUL-T5ZYCC-WA7T2V"
BOT_USERNAME = "iranconnect_bot"

DB_PATH = "bot_data.db"
PORT = 8080

OXAPAY_BASE = "https://api.oxapay.com/v1"
ECONOMY_ACCESS_CODE = "netazadi_eghtesadi"

# این مسیر callback مخفیه
CALLBACK_PATH = "/oxa_payhook_83921"

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# =========================
# PLANS
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

FINAL_SUCCESS_STATUSES = {"paid"}
FAILED_STATUSES = {"failed", "expired", "cancelled"}


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
            track_id TEXT,
            payment_url TEXT,
            payment_status TEXT DEFAULT 'new',
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
        "track_id": "TEXT",
        "payment_url": "TEXT",
        "payment_status": "TEXT DEFAULT 'new'",
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
    cur.execute("UPDATE users SET economy_access = 1 WHERE user_id = ?", (user_id,))
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
    track_id: str,
    payment_url: str,
):
    conn = db()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO orders (
            user_id, category_key, plan_key, plan_name,
            price_usd, track_id, payment_url
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        user_id, category_key, plan_key, plan_name,
        price_usd, track_id, payment_url
    ))
    order_id = cur.lastrowid
    conn.commit()
    conn.close()
    return order_id


def get_order_by_id(order_id: int):
    conn = db()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, user_id, category_key, plan_key, plan_name, price_usd,
               track_id, payment_url, payment_status, order_code, is_notified
        FROM orders
        WHERE id = ?
    """, (order_id,))
    row = cur.fetchone()
    conn.close()
    return row


def get_pending_orders():
    conn = db()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, user_id, plan_name, price_usd, track_id, payment_status, order_code, is_notified
        FROM orders
        WHERE payment_status NOT IN ('paid', 'failed', 'expired', 'cancelled')
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


def update_order_status_by_track_id(track_id: str, status: str):
    conn = db()
    cur = conn.cursor()
    cur.execute("""
        UPDATE orders
        SET payment_status = ?, updated_at = CURRENT_TIMESTAMP
        WHERE track_id = ?
    """, (status, track_id))
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
        SELECT user_id, plan_name, price_usd, payment_status, order_code, is_notified
        FROM orders
        WHERE id = ?
    """, (order_id,))
    row = cur.fetchone()
    conn.close()
    return row


# =========================
# HELPERS
# =========================

def ticket_code():
    chars = string.ascii_uppercase + string.digits
    return "VPN-" + "".join(random.choice(chars) for _ in range(6))


def main_menu():
    return ReplyKeyboardMarkup(
        [["📦 پلن‌ها", "📞 پشتیبانی"]],
        resize_keyboard=True
    )


def welcome_text():
    return (
        "🌐 به ربات رسمی نت‌آزادی خوش اومدی\n\n"
        "✨ خرید سریع و امن پلن‌های VPN\n"
        "💎 پرداخت با کریپتوکارنسی (رمزارزها)\n"
        "🤖 تایید خودکار پرداخت\n"
        "🎫 دریافت Ticket ID بعد از پرداخت\n\n"
        "برای شروع از منوی پایین استفاده کن 👇"
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
        label = f'{category["emoji"]} {item["name"]} - {item["price_usd"]} USD'
        rows.append([InlineKeyboardButton(label, callback_data=f"plan_{plan_key}")])

    rows.append([InlineKeyboardButton("⬅️ بازگشت", callback_data="show_categories")])
    return InlineKeyboardMarkup(rows)


def pay_method_menu(order_id: int, payment_url: str):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💳 پرداخت با کریپتوکارنسی (رمزارزها)", url=payment_url)],
        [InlineKeyboardButton("🔎 بررسی وضعیت پرداخت", callback_data=f"checkpay_{order_id}")],
        [InlineKeyboardButton("⬅️ بازگشت به پلن‌ها", callback_data="show_categories")],
    ])


def support_back_btn():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ بازگشت", callback_data="show_categories")]
    ])


def reply_btn(user_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✉️ پاسخ", callback_data=f"reply_{user_id}")]
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


def get_plan(plan_key: str) -> Tuple[Optional[str], Optional[dict]]:
    cat_key = find_category_by_plan(plan_key)
    if not cat_key:
        return None, None
    return cat_key, PLAN_CATEGORIES[cat_key]["plans"][plan_key]


def extract_invoice_fields(resp_json: dict) -> Tuple[str, str]:
    data = resp_json.get("data") if isinstance(resp_json.get("data"), dict) else resp_json
    track_id = data.get("track_id") or data.get("trackId") or ""
    payment_url = data.get("payment_url") or data.get("payLink") or ""
    return str(track_id), str(payment_url)


def extract_status(resp_json: dict) -> str:
    data = resp_json.get("data") if isinstance(resp_json.get("data"), dict) else resp_json
    status = data.get("status", "new")
    return str(status).lower()


def extract_track_id_from_callback(payload: dict) -> str:
    possible = [
        payload.get("track_id"),
        payload.get("trackId"),
        payload.get("invoice_track_id"),
    ]
    if isinstance(payload.get("data"), dict):
        possible.extend([
            payload["data"].get("track_id"),
            payload["data"].get("trackId"),
            payload["data"].get("invoice_track_id"),
        ])
    for item in possible:
        if item:
            return str(item)
    return ""


def extract_callback_status(payload: dict) -> str:
    possible = [payload.get("status")]
    if isinstance(payload.get("data"), dict):
        possible.append(payload["data"].get("status"))
    for item in possible:
        if item:
            return str(item).lower()
    return "new"


# =========================
# OXAPAY API
# =========================

def oxa_headers():
    return {
        "merchant_api_key": OXAPAY_MERCHANT_API_KEY,
        "Content-Type": "application/json",
    }


def create_oxapay_invoice(amount_usd: str, order_ref: str, description: str):
    payload = {
        "amount": float(amount_usd),
        "currency": "USD",
        "lifetime": 60,
        "fee_paid_by_payer": 1,
        "mixed_payment": False,
        "thanks_message": "پرداخت شما با موفقیت انجام شد ✅ لطفاً به ربات برگردید و وضعیت پرداخت را بررسی کنید.",
        "description": description,
        "order_id": order_ref,
        "sandbox": False,
    }

    r = requests.post(
        f"{OXAPAY_BASE}/payment/invoice",
        headers=oxa_headers(),
        json=payload,
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def get_oxapay_payment_info(track_id: str):
    r = requests.get(
        f"{OXAPAY_BASE}/payment/{track_id}",
        headers=oxa_headers(),
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


# =========================
# FLASK CALLBACK SERVER
# =========================

web_app = Flask(__name__)


@web_app.get("/")
def home():
    return "vpn-bot webhook server is running", 200


@web_app.post(CALLBACK_PATH)
def oxapay_callback():
    try:
        payload = request.get_json(silent=True) or {}
        track_id = extract_track_id_from_callback(payload)
        status = extract_callback_status(payload)

        logger.info("OxaPay callback received | track_id=%s | status=%s | payload=%s", track_id, status, payload)

        if track_id and status:
            update_order_status_by_track_id(track_id, status)

        return jsonify({"ok": True}), 200
    except Exception as e:
        logger.exception("Callback error: %s", e)
        return jsonify({"ok": False, "error": str(e)}), 500


def run_web_server():
    web_app.run(host="0.0.0.0", port=PORT, debug=False, use_reloader=False)


# =========================
# BOT HANDLERS
# =========================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    save_user(user)
    context.user_data.clear()

    await update.message.reply_text(
        welcome_text(),
        reply_markup=main_menu(),
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
            "📞 پیام پشتیبانی‌ات را بفرست.\nاگر سوالی درباره پرداخت یا دریافت کانفیگ داری، همینجا بنویس.",
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

        category = PLAN_CATEGORIES[cat_key]
        price_usd = str(plan["price_usd"])
        plan_name = plan["name"]

        try:
            order_ref = f"TG-{q.from_user.id}-{random.randint(100000, 999999)}"
            description = f"{category['title']} | {plan_name}"

            invoice = create_oxapay_invoice(
                amount_usd=price_usd,
                order_ref=order_ref,
                description=description,
            )

            track_id, payment_url = extract_invoice_fields(invoice)

            if not track_id or not payment_url:
                await q.message.reply_text("❌ ساخت لینک پرداخت ناموفق بود. دوباره تلاش کن.")
                return

            order_id = create_order(
                user_id=q.from_user.id,
                category_key=cat_key,
                plan_key=plan_key,
                plan_name=plan_name,
                price_usd=price_usd,
                track_id=track_id,
                payment_url=payment_url,
            )

            await q.message.edit_text(
                f"{category['title']}\n"
                f"({category['subtitle']})\n\n"
                f"📦 پلن: {plan_name}\n"
                f"💰 مبلغ نهایی: {price_usd} USD\n"
                f"🧾 Track ID: {track_id}\n\n"
                "برای پرداخت روی دکمه زیر بزن.\n"
                "بعد از پرداخت، ربات خودش وضعیت را بررسی می‌کند.",
                reply_markup=pay_method_menu(order_id, payment_url)
            )

        except requests.HTTPError as e:
            logger.exception("OxaPay invoice create failed")
            detail = ""
            try:
                detail = e.response.text
            except Exception:
                pass

            await q.message.reply_text("❌ ساخت لینک پرداخت ناموفق بود. دوباره تلاش کن.")
            if detail:
                await context.bot.send_message(
                    ADMIN,
                    f"⚠️ خطا در ساخت invoice اوکساپی\nUser: {q.from_user.id}\n{detail}"
                )
            return
        except Exception as e:
            logger.exception("Unexpected OxaPay error")
            await q.message.reply_text("❌ خطا در ارتباط با درگاه پرداخت.")
            await context.bot.send_message(
                ADMIN,
                f"⚠️ خطای غیرمنتظره در ساخت invoice\nUser: {q.from_user.id}\n{e}"
            )
            return
        return

    if data.startswith("checkpay_"):
        order_id = int(data.split("_", 1)[1])
        order = get_order_by_id(order_id)
        if not order:
            await q.message.reply_text("❌ سفارش پیدا نشد.")
            return

        track_id = order[6]
        current_status = order[8]

        if current_status in FINAL_SUCCESS_STATUSES:
            state = get_order_notification_state(order_id)
            if state:
                _, _, _, _, code, _ = state
                await q.message.reply_text(
                    "✅ این پرداخت قبلاً تایید شده است.\n\n"
                    f"🎫 Ticket ID: {code}\n"
                    "برای دریافت کانفیگ از بخش پشتیبانی پیام بده.",
                    reply_markup=success_support_button()
                )
            return

        try:
            info = get_oxapay_payment_info(track_id)
            payment_status = extract_status(info)
            update_order_status(order_id, payment_status)
        except Exception:
            await q.message.reply_text("⏳ هنوز نتیجه قطعی دریافت نشد. کمی بعد دوباره بررسی کن.")
            return

        if payment_status in FINAL_SUCCESS_STATUSES:
            await finalize_paid_order(order_id, context)
            return

        status_texts = {
            "new": "جدید",
            "waiting": "در انتظار پرداخت",
            "confirming": "در حال تایید شبکه",
            "paying": "پرداخت در حال انجام",
            "failed": "ناموفق",
            "expired": "منقضی‌شده",
            "cancelled": "لغوشده",
        }

        await q.message.reply_text(
            f"🔄 وضعیت فعلی پرداخت: {status_texts.get(payment_status, payment_status)}"
        )
        return


async def finalize_paid_order(order_id: int, context: ContextTypes.DEFAULT_TYPE):
    state = get_order_notification_state(order_id)
    if not state:
        return

    user_id, plan_name, price_usd, status, code, is_notified = state

    if is_notified:
        return

    if not code:
        code = ticket_code()
        set_order_success(order_id, status, code)

    try:
        await context.bot.send_message(
            user_id,
            "✅ پرداخت شما با موفقیت تایید شد\n\n"
            f"🎫 Ticket ID: {code}\n\n"
            "برای دریافت کانفیگ، لطفاً از بخش پشتیبانی به ما پیام بده.",
            reply_markup=success_support_button()
        )

        await context.bot.send_message(
            ADMIN,
            "💸 پرداخت جدید با موفقیت تایید شد\n\n"
            f"🆔 Order ID: {order_id}\n"
            f"👤 User ID: {user_id}\n"
            f"📦 پلن: {plan_name}\n"
            f"💰 مبلغ: {price_usd} USD\n"
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
        order_id, user_id, plan_name, price_usd, track_id, old_status, order_code, is_notified = row
        try:
            info = get_oxapay_payment_info(track_id)
            new_status = extract_status(info)

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
        await context.bot.send_message(target_id, f"📩 پاسخ پشتیبانی:\n\n{text}")
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
        "برای خرید نیازی به ارسال عکس فیش نیست.\nاگر سوالی داری از بخش پشتیبانی پیام بده.",
        reply_markup=main_menu()
    )


def main():
    init_db()

    flask_thread = threading.Thread(target=run_web_server, daemon=True)
    flask_thread.start()

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("broadcast", broadcast))
    app.add_handler(CallbackQueryHandler(click))
    app.add_handler(MessageHandler(filters.PHOTO, photo_msg))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_msg))

    app.job_queue.run_repeating(payment_watcher, interval=20, first=10)

    print("Bot is running...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
