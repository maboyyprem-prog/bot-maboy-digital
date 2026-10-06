import os
import sqlite3
import logging
import time
import random
import json
import hashlib
import hmac
import base64
import html
import asyncio
import shutil
from pathlib import Path
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from decimal import Decimal, InvalidOperation

from aiohttp import web, ClientSession
from Crypto.PublicKey import RSA
from Crypto.Signature import pkcs1_15
from Crypto.Hash import SHA256

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile,
    ReplyKeyboardMarkup, KeyboardButton
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from dotenv import load_dotenv

load_dotenv()


BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin").replace("@", "")
DEFAULT_PAYMENT_NOTE = os.getenv("PAYMENT_NOTE", "QRIS Maboyy Digital").strip()

# Payment Gateway API (optional until credentials are available)
SHOPEEPAY_ENABLED = os.getenv("SHOPEEPAY_ENABLED", "false").lower() == "true"
SHOPEEPAY_BASE_URL = os.getenv("SHOPEEPAY_BASE_URL", "").rstrip("/")
SHOPEEPAY_CLIENT_ID = os.getenv("SHOPEEPAY_CLIENT_ID", "").strip()
SHOPEEPAY_CLIENT_SECRET = os.getenv("SHOPEEPAY_CLIENT_SECRET", "").strip()
SHOPEEPAY_MERCHANT_ID = os.getenv("SHOPEEPAY_MERCHANT_ID", "").strip()
SHOPEEPAY_STORE_ID = os.getenv("SHOPEEPAY_STORE_ID", "").strip()
SHOPEEPAY_TERMINAL_ID = os.getenv("SHOPEEPAY_TERMINAL_ID", "").strip()
SHOPEEPAY_PRIVATE_KEY = os.getenv("SHOPEEPAY_PRIVATE_KEY", "").replace("\\n", "\n").strip()
SHOPEEPAY_PUBLIC_KEY = os.getenv("SHOPEEPAY_PUBLIC_KEY", "").replace("\\n", "\n").strip()
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")
PORT = int(os.getenv("PORT", "8080"))

REQUIRED_CHANNEL_ID = os.getenv("REQUIRED_CHANNEL_ID", "").strip()
REQUIRED_CHANNEL_URL = os.getenv("REQUIRED_CHANNEL_URL", "").strip()
REQUIRED_CHANNEL_NAME = os.getenv("REQUIRED_CHANNEL_NAME", "Channel Maboyy Digital").strip()

# Persistent storage / backup / announcement channels
DB_PATH = os.getenv(
    "DB_PATH",
    "/data/shop.db" if os.path.isdir("/data") else "shop.db"
).strip()
BACKUP_DIR = os.getenv(
    "BACKUP_DIR",
    "/data/backups" if os.path.isdir("/data") else "backups"
).strip()
BACKUP_INTERVAL_HOURS = max(1, int(os.getenv("BACKUP_INTERVAL_HOURS", "48")))
BACKUP_RETENTION = max(3, int(os.getenv("BACKUP_RETENTION", "20")))
ORDER_RESERVATION_MINUTES = max(5, int(os.getenv("ORDER_RESERVATION_MINUTES", "15")))

STOCK_CHANNEL_ID = os.getenv("STOCK_CHANNEL_ID", "").strip()

BOT_VERSION = "5.0"
BOT_CHANGELOG = [
    "Backup database otomatis dan retention backup.",
    "Database persisten melalui Railway Volume.",
    "Migrasi database lama ke storage persisten saat pertama kali aktif.",
    "Informasi stok channel hanya disinkronkan manual oleh owner.",
    "Data user, saldo, order, produk, voucher, dan pengaturan tetap tersimpan saat redeploy.",
]

STORE_NAME = "Maboyy Produk Digital"
STORE_FOOTER = "Aplikasi Premium • Since 2020"


logging.basicConfig(level=logging.INFO)
router = Router()
START_TIME = time.time()


# =========================
# DATABASE / PERSISTENT STORAGE
# =========================
def prepare_storage():
    db_file = Path(DB_PATH)
    db_file.parent.mkdir(parents=True, exist_ok=True)
    Path(BACKUP_DIR).mkdir(parents=True, exist_ok=True)

    # First migration from old non-volume DB to the persistent DB.
    legacy = Path("shop.db")
    if db_file.resolve() != legacy.resolve() and not db_file.exists() and legacy.exists():
        shutil.copy2(legacy, db_file)
        logging.info("Legacy database migrated to persistent storage: %s", DB_PATH)


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def has_column(conn, table, column):
    cols = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(c["name"] == column for c in cols)


def add_column_if_missing(conn, table, column, definition):
    if not has_column(conn, table, column):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def init_db():
    prepare_storage()
    conn = db()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            price INTEGER NOT NULL DEFAULT 0,
            stock INTEGER NOT NULL DEFAULT 0,
            description TEXT DEFAULT '',
            active INTEGER NOT NULL DEFAULT 1
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS product_variants (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            code TEXT DEFAULT '',
            price INTEGER NOT NULL DEFAULT 0,
            stock INTEGER NOT NULL DEFAULT 0,
            wholesale10 INTEGER NOT NULL DEFAULT 0,
            wholesale20 INTEGER NOT NULL DEFAULT 0,
            active INTEGER NOT NULL DEFAULT 1
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS vouchers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT UNIQUE NOT NULL,
            discount INTEGER NOT NULL DEFAULT 0,
            used INTEGER NOT NULL DEFAULT 0
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            username TEXT,
            product_id INTEGER NOT NULL,
            qty INTEGER NOT NULL DEFAULT 1,
            total INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL
        )
    """)



    cur.execute("""
        CREATE TABLE IF NOT EXISTS wallets (
            user_id INTEGER PRIMARY KEY,
            balance INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS wallet_ledger (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            type TEXT NOT NULL,
            amount INTEGER NOT NULL,
            balance_after INTEGER NOT NULL,
            reference TEXT DEFAULT '',
            note TEXT DEFAULT '',
            created_at TEXT NOT NULL,
            UNIQUE(type, reference, user_id)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS topups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            username TEXT DEFAULT '',
            amount INTEGER NOT NULL,
            unique_code INTEGER NOT NULL DEFAULT 0,
            payment_total INTEGER NOT NULL DEFAULT 0,
            payment_method TEXT NOT NULL DEFAULT 'QRIS_MANUAL',
            status TEXT NOT NULL DEFAULT 'pending',
            provider_reference TEXT DEFAULT '',
            created_at TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT DEFAULT ''
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS inventory_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            variant_id INTEGER NOT NULL,
            content TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'available',
            order_id INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            delivered_at TEXT DEFAULT ''
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS verified_users (
            user_id INTEGER PRIMARY KEY,
            username TEXT DEFAULT '',
            verified_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 1
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS restock_broadcast_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            variant_id INTEGER NOT NULL,
            stock_after INTEGER NOT NULL,
            sent_count INTEGER NOT NULL DEFAULT 0,
            failed_count INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS restock_subscriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            variant_id INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            UNIQUE(user_id, product_id, variant_id)
        )
    """)


    cur.execute("""
        CREATE TABLE IF NOT EXISTS reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL UNIQUE,
            user_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            rating INTEGER NOT NULL,
            comment TEXT DEFAULT '',
            created_at TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS user_security (
            user_id INTEGER PRIMARY KEY,
            blocked INTEGER NOT NULL DEFAULT 0,
            risk_score INTEGER NOT NULL DEFAULT 0,
            strikes INTEGER NOT NULL DEFAULT 0,
            last_reason TEXT DEFAULT '',
            updated_at TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS inventory_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            variant_id INTEGER NOT NULL,
            action TEXT NOT NULL,
            qty INTEGER NOT NULL DEFAULT 0,
            reference TEXT DEFAULT '',
            note TEXT DEFAULT '',
            created_at TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS voucher_usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            voucher_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            order_id INTEGER NOT NULL,
            discount_amount INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            UNIQUE(voucher_id, order_id)
        )
    """)


    cur.execute("""
        CREATE TABLE IF NOT EXISTS cart_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            variant_id INTEGER NOT NULL,
            qty INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            UNIQUE(user_id, variant_id)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS favorites (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(user_id, product_id)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS broadcast_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            segment TEXT NOT NULL,
            sent_count INTEGER NOT NULL DEFAULT 0,
            failed_count INTEGER NOT NULL DEFAULT 0,
            message_preview TEXT DEFAULT '',
            created_at TEXT NOT NULL
        )
    """)


    cur.execute("""
        CREATE TABLE IF NOT EXISTS bundle_offers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            product_a INTEGER NOT NULL,
            product_b INTEGER NOT NULL,
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL
        )
    """)

    # migrations from previous versions
    add_column_if_missing(conn, "products", "sold", "INTEGER NOT NULL DEFAULT 0")
    add_column_if_missing(conn, "products", "rating", "REAL NOT NULL DEFAULT 0")
    add_column_if_missing(conn, "products", "rating_count", "INTEGER NOT NULL DEFAULT 0")
    add_column_if_missing(conn, "products", "is_popular", "INTEGER NOT NULL DEFAULT 0")
    add_column_if_missing(conn, "products", "is_flash_sale", "INTEGER NOT NULL DEFAULT 0")
    add_column_if_missing(conn, "product_variants", "reserved_stock", "INTEGER NOT NULL DEFAULT 0")
    add_column_if_missing(conn, "product_variants", "button_label", "TEXT DEFAULT ''")
    add_column_if_missing(conn, "orders", "variant_id", "INTEGER DEFAULT 0")
    add_column_if_missing(conn, "orders", "unit_price", "INTEGER NOT NULL DEFAULT 0")
    add_column_if_missing(conn, "orders", "payment_method", "TEXT DEFAULT 'QRIS'")
    add_column_if_missing(conn, "orders", "payment_status", "TEXT DEFAULT 'unpaid'")
    add_column_if_missing(conn, "orders", "note", "TEXT DEFAULT ''")
    add_column_if_missing(conn, "orders", "unique_code", "INTEGER NOT NULL DEFAULT 0")
    add_column_if_missing(conn, "orders", "payment_total", "INTEGER NOT NULL DEFAULT 0")
    add_column_if_missing(conn, "orders", "provider_reference", "TEXT DEFAULT ''")
    add_column_if_missing(conn, "orders", "provider_qr_url", "TEXT DEFAULT ''")
    add_column_if_missing(conn, "orders", "stock_reserved", "INTEGER NOT NULL DEFAULT 0")
    add_column_if_missing(conn, "orders", "reserved_until", "TEXT DEFAULT ''")
    add_column_if_missing(conn, "orders", "completed_at", "TEXT DEFAULT ''")
    add_column_if_missing(conn, "orders", "fulfillment_status", "TEXT DEFAULT 'pending'")
    add_column_if_missing(conn, "orders", "delivery_text", "TEXT DEFAULT ''")
    add_column_if_missing(conn, "orders", "delivery_attempts", "INTEGER NOT NULL DEFAULT 0")
    add_column_if_missing(conn, "orders", "last_delivery_error", "TEXT DEFAULT ''")
    add_column_if_missing(conn, "orders", "delivery_sent_at", "TEXT DEFAULT ''")
    add_column_if_missing(conn, "orders", "voucher_code", "TEXT DEFAULT ''")
    add_column_if_missing(conn, "orders", "discount_amount", "INTEGER NOT NULL DEFAULT 0")
    add_column_if_missing(conn, "orders", "review_prompt_sent", "INTEGER NOT NULL DEFAULT 0")
    add_column_if_missing(conn, "vouchers", "min_spend", "INTEGER NOT NULL DEFAULT 0")
    add_column_if_missing(conn, "vouchers", "max_discount", "INTEGER NOT NULL DEFAULT 0")
    add_column_if_missing(conn, "vouchers", "usage_limit", "INTEGER NOT NULL DEFAULT 0")
    add_column_if_missing(conn, "vouchers", "per_user_limit", "INTEGER NOT NULL DEFAULT 1")
    add_column_if_missing(conn, "vouchers", "expires_at", "TEXT DEFAULT ''")
    add_column_if_missing(conn, "vouchers", "active", "INTEGER NOT NULL DEFAULT 1")
    add_column_if_missing(conn, "vouchers", "product_id", "INTEGER NOT NULL DEFAULT 0")
    add_column_if_missing(conn, "vouchers", "variant_id", "INTEGER NOT NULL DEFAULT 0")
    add_column_if_missing(conn, "vouchers", "new_user_only", "INTEGER NOT NULL DEFAULT 0")
    add_column_if_missing(conn, "topups", "reject_reason", "TEXT DEFAULT ''")
    add_column_if_missing(conn, "topups", "verified_at", "TEXT DEFAULT ''")
    add_column_if_missing(conn, "topups", "verified_by", "INTEGER NOT NULL DEFAULT 0")
    add_column_if_missing(conn, "orders", "cashback_applied", "INTEGER NOT NULL DEFAULT 0")

    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_inventory_variant_status "
        "ON inventory_items(variant_id, status)"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_orders_user_created "
        "ON orders(user_id, created_at)"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_orders_variant_fulfillment "
        "ON orders(variant_id, payment_status, fulfillment_status)"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_reviews_product "
        "ON reviews(product_id, created_at)"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_inventory_logs_variant "
        "ON inventory_logs(variant_id, created_at)"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_voucher_usage_user "
        "ON voucher_usage(voucher_id, user_id)"
    )

    # Default store settings (editable from /owner)
    defaults = {
        "qris_file_id": "",
        "payment_note": DEFAULT_PAYMENT_NOTE,
        "unique_code_enabled": "1",
        "unique_code_min": "1",
        "unique_code_max": "999",
        "payment_mode": "manual",
        "min_topup": "5000",
        "low_stock_threshold": "5",
        "fraud_pending_limit": "3",
        "fraud_cooldown_seconds": "8",
        "loyalty_silver": "250000",
        "loyalty_gold": "750000",
        "loyalty_vip": "2000000",
        "maintenance_mode": "0",
        "cashback_percent": "0",
        "daily_report_enabled": "1",
        "daily_report_hour": "20",
    }
    for k, v in defaults.items():
        cur.execute("INSERT OR IGNORE INTO settings(key, value) VALUES(?,?)", (k, v))

    count = cur.execute("SELECT COUNT(*) AS n FROM products").fetchone()["n"]
    if count == 0:
        samples = [
            ("Canva Pro", 25000, 10, "Akses digital sesuai ketentuan produk.", 1, 0),
            ("CapCut Pro", 30000, 8, "Voucher/aktivasi digital.", 1, 1),
            ("Music Premium", 20000, 15, "Voucher digital.", 0, 0),
            ("AI Subscription", 50000, 5, "Akses/voucher digital.", 0, 0),
            ("Email Fresh", 5000, 20, "Produk digital.", 0, 0),
        ]
        cur.executemany(
            """INSERT INTO products(name, price, stock, description, is_popular, is_flash_sale)
               VALUES(?,?,?,?,?,?)""",
            samples
        )

    # Create one default variant for products that don't have variants yet
    products = cur.execute("SELECT * FROM products WHERE active=1").fetchall()
    for p in products:
        vcount = cur.execute(
            "SELECT COUNT(*) AS n FROM product_variants WHERE product_id=?",
            (p["id"],)
        ).fetchone()["n"]
        if vcount == 0:
            cur.execute(
                """INSERT INTO product_variants
                   (product_id, name, code, price, stock, wholesale10, wholesale20)
                   VALUES(?,?,?,?,?,?,?)""",
                (p["id"], "Standard", f"P{p['id']}", p["price"], p["stock"], 0, 0)
            )

    reconcile_all_inventory_stock(conn)
    conn.commit()
    conn.close()


def rupiah(value: int) -> str:
    return f"Rp{value:,.0f}".replace(",", ".")


def is_owner(user_id: int) -> bool:
    return user_id == ADMIN_ID



async def is_channel_member(bot: Bot, user_id: int) -> bool:
    if not REQUIRED_CHANNEL_ID:
        return True

    try:
        member = await bot.get_chat_member(REQUIRED_CHANNEL_ID, user_id)
        return member.status in {"member", "administrator", "creator"}
    except Exception:
        return False



def mark_user_verified(user_id: int, username: str = ""):
    now = datetime.now().isoformat(timespec="seconds")
    conn = db()
    conn.execute(
        """INSERT INTO verified_users
           (user_id, username, verified_at, last_seen_at, active)
           VALUES(?,?,?,?,1)
           ON CONFLICT(user_id) DO UPDATE SET
             username=excluded.username,
             last_seen_at=excluded.last_seen_at,
             active=1""",
        (user_id, username or "", now, now)
    )
    conn.commit()
    conn.close()


def deactivate_verified_user(user_id: int):
    conn = db()
    conn.execute(
        "UPDATE verified_users SET active=0 WHERE user_id=?",
        (user_id,)
    )
    conn.commit()
    conn.close()


async def broadcast_restock_to_verified(
    bot: Bot,
    product_id: int,
    variant_id: int,
    stock_after: int,
):
    conn = db()
    product = conn.execute(
        "SELECT * FROM products WHERE id=?",
        (product_id,)
    ).fetchone()
    variant = conn.execute(
        "SELECT * FROM product_variants WHERE id=?",
        (variant_id,)
    ).fetchone()
    users = conn.execute(
        """SELECT user_id, username
           FROM verified_users
           WHERE active=1
           ORDER BY user_id"""
    ).fetchall()
    conn.close()

    if not product or not variant or stock_after <= 0:
        return {"sent": 0, "failed": 0}

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="🛒 Lihat Produk",
                callback_data=f"variant:{variant_id}"
            )
        ],
        [
            InlineKeyboardButton(
                text="🏠 Menu Utama",
                callback_data="home"
            )
        ]
    ])

    text = (
        "🚨 <b>RESTOCK MABOYY DIGITAL</b>\n\n"
        "Stok baru sudah tersedia.\n\n"
        f"📦 Produk: <b>{product['name']}</b>\n"
        f"🧩 Variasi: <b>{variant['name']}</b>\n"
        f"✅ Stok tersedia: <b>{stock_after}</b>\n"
        f"💰 Harga: <b>{rupiah(variant['price'])}</b>\n\n"
        "Silakan order sebelum stok habis.\n\n"
        f"<i>{STORE_FOOTER}</i>"
    )

    sent = 0
    failed = 0

    for row in users:
        user_id = int(row["user_id"])

        # Owner does not need customer restock alerts.
        if ADMIN_ID and user_id == ADMIN_ID:
            continue

        try:
            await bot.send_message(
                user_id,
                text,
                reply_markup=kb,
                parse_mode="HTML"
            )
            sent += 1
            await asyncio.sleep(0.05)

        except TelegramRetryAfter as exc:
            try:
                await asyncio.sleep(float(exc.retry_after) + 0.5)
                await bot.send_message(
                    user_id,
                    text,
                    reply_markup=kb,
                    parse_mode="HTML"
                )
                sent += 1
            except Exception:
                failed += 1

        except TelegramForbiddenError:
            failed += 1
            deactivate_verified_user(user_id)

        except Exception as exc:
            failed += 1
            logging.warning(
                "Restock broadcast failed for user %s: %s",
                user_id,
                exc
            )

    conn = db()
    conn.execute(
        """INSERT INTO restock_broadcast_log
           (variant_id, stock_after, sent_count, failed_count, created_at)
           VALUES(?,?,?,?,?)""",
        (
            variant_id,
            stock_after,
            sent,
            failed,
            datetime.now().isoformat(timespec="seconds")
        )
    )
    conn.commit()
    conn.close()

    if ADMIN_ID:
        try:
            await bot.send_message(
                ADMIN_ID,
                "📣 <b>RESTOCK ALERT SELESAI</b>\n\n"
                f"📦 {product['name']} — {variant['name']}\n"
                f"✅ Terkirim: <b>{sent}</b> user terverifikasi\n"
                f"❌ Gagal: <b>{failed}</b>\n"
                f"📊 Stok sekarang: <b>{stock_after}</b>",
                parse_mode="HTML"
            )
        except Exception:
            pass

    return {"sent": sent, "failed": failed}


def join_required_keyboard():
    rows = []
    if REQUIRED_CHANNEL_URL:
        rows.append([
            InlineKeyboardButton(
                text="📢 Join Channel",
                url=REQUIRED_CHANNEL_URL
            )
        ])

    rows.append([
        InlineKeyboardButton(
            text="✅ Saya Sudah Join",
            callback_data="verify_join"
        )
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def send_join_required(target_message: Message):
    await target_message.answer(
        "🔐 <b>VERIFIKASI CHANNEL</b>\n\n"
        f"Untuk menggunakan <b>{STORE_NAME}</b>, silakan join terlebih dahulu:\n"
        f"📢 <b>{REQUIRED_CHANNEL_NAME}</b>\n\n"
        "Setelah join, tekan tombol <b>✅ Saya Sudah Join</b>.\n"
        "Bot akan memverifikasi otomatis.",
        reply_markup=join_required_keyboard(),
        parse_mode="HTML"
    )


async def show_main_menu_message(message: Message):
    await message.answer(
        f"🛍️ <b>{STORE_NAME}</b>\n\n"
        "Selamat datang.\n"
        "Gunakan tombol menu atau nomor produk di bawah untuk akses cepat.\n\n"
        f"<i>{STORE_FOOTER}</i>",
        reply_markup=user_reply_menu(),
        parse_mode="HTML"
    )
    await message.answer(
        "Atau pilih menu berikut:",
        reply_markup=main_menu()
    )


def effective_unit_price(variant, qty):
    if qty >= 20 and variant["wholesale20"] > 0:
        return variant["wholesale20"]
    if qty >= 10 and variant["wholesale10"] > 0:
        return variant["wholesale10"]
    return variant["price"]


def invoice(order_id):
    return f"MBY-{order_id:06d}"


def get_setting(key, default=""):
    conn = db()
    row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    conn.close()
    return row["value"] if row else default


def set_setting(key, value):
    conn = db()
    conn.execute(
        """INSERT INTO settings(key, value) VALUES(?,?)
           ON CONFLICT(key) DO UPDATE SET value=excluded.value""",
        (key, str(value))
    )
    conn.commit()
    conn.close()



def ensure_wallet(user_id: int):
    conn = db()
    conn.execute(
        """INSERT OR IGNORE INTO wallets(user_id, balance, updated_at)
           VALUES(?,?,?)""",
        (user_id, 0, datetime.now().isoformat(timespec="seconds"))
    )
    conn.commit()
    row = conn.execute("SELECT * FROM wallets WHERE user_id=?", (user_id,)).fetchone()
    conn.close()
    return row


def get_balance(user_id: int) -> int:
    row = ensure_wallet(user_id)
    return int(row["balance"])


def wallet_change(user_id: int, amount: int, tx_type: str, reference: str, note: str = "") -> int:
    conn = db()
    conn.execute(
        """INSERT OR IGNORE INTO wallets(user_id, balance, updated_at)
           VALUES(?,?,?)""",
        (user_id, 0, datetime.now().isoformat(timespec="seconds"))
    )
    wallet = conn.execute("SELECT balance FROM wallets WHERE user_id=?", (user_id,)).fetchone()
    current = int(wallet["balance"])
    new_balance = current + int(amount)
    if new_balance < 0:
        conn.close()
        raise ValueError("Saldo tidak mencukupi.")

    # idempotency check
    existing = conn.execute(
        """SELECT id FROM wallet_ledger
           WHERE type=? AND reference=? AND user_id=?""",
        (tx_type, reference, user_id)
    ).fetchone()
    if existing:
        conn.close()
        return current

    conn.execute(
        "UPDATE wallets SET balance=?, updated_at=? WHERE user_id=?",
        (new_balance, datetime.now().isoformat(timespec="seconds"), user_id)
    )
    conn.execute(
        """INSERT INTO wallet_ledger
           (user_id, type, amount, balance_after, reference, note, created_at)
           VALUES(?,?,?,?,?,?,?)""",
        (
            user_id, tx_type, int(amount), new_balance, reference, note,
            datetime.now().isoformat(timespec="seconds")
        )
    )
    conn.commit()
    conn.close()
    return new_balance


def topup_invoice(topup_id: int) -> str:
    return f"TOP-{topup_id:06d}"



def available_stock(variant) -> int:
    return max(0, int(variant["stock"]) - int(variant["reserved_stock"] or 0))



def variant_button_label(variant) -> str:
    custom = ""
    try:
        custom = (variant["button_label"] or "").strip()
    except Exception:
        custom = ""
    return custom or variant["name"]



def inventory_counts(conn, variant_id: int):
    row = conn.execute(
        """SELECT
             SUM(CASE WHEN status='available' THEN 1 ELSE 0 END) AS available,
             SUM(CASE WHEN status='sold' THEN 1 ELSE 0 END) AS sold
           FROM inventory_items
           WHERE variant_id=?""",
        (variant_id,)
    ).fetchone()
    return {
        "available": int(row["available"] or 0),
        "sold": int(row["sold"] or 0),
    }


def inventory_mode(conn, variant_id: int) -> bool:
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM inventory_items WHERE variant_id=?",
        (variant_id,)
    ).fetchone()
    return int(row["n"] or 0) > 0


def sync_variant_stock_from_inventory(conn, variant_id: int):
    # Physical stock for account-based products equals credentials not yet sold.
    row = conn.execute(
        """SELECT COUNT(*) AS n
           FROM inventory_items
           WHERE variant_id=? AND status='available'""",
        (variant_id,)
    ).fetchone()
    available_items = int(row["n"] or 0)
    # Physical stock equals credentials that have not been sold.
    # reserved_stock is subtracted separately by available_stock().
    conn.execute(
        "UPDATE product_variants SET stock=? WHERE id=?",
        (available_items, variant_id)
    )



def reconcile_all_inventory_stock(conn):
    """Make actual account inventory the source of truth for stock."""
    variants = conn.execute("SELECT id FROM product_variants").fetchall()
    for row in variants:
        sync_variant_stock_from_inventory(conn, row["id"])


async def notify_fulfillment_pending(bot: Bot, order, missing: int):
    try:
        await bot.send_message(
            order["user_id"],
            "🟡 <b>PEMBAYARAN SUDAH DITERIMA</b>\n\n"
            f"🧾 Invoice: <b>{invoice(order['id'])}</b>\n"
            "Pembayaran sudah tercatat, tetapi stok akun premium belum mencukupi.\n"
            "Pesanan <b>tidak perlu dibayar ulang</b>.\n\n"
            "Akun akan dikirim otomatis setelah owner menambah stok akun.",
            parse_mode="HTML"
        )
    except Exception:
        pass

    if ADMIN_ID:
        try:
            await bot.send_message(
                ADMIN_ID,
                "⚠️ <b>PESANAN SUDAH DIBAYAR — STOK AKUN KURANG</b>\n\n"
                f"🧾 Invoice: <b>{invoice(order['id'])}</b>\n"
                f"📦 Variant ID: <code>{order['variant_id']}</code>\n"
                f"🔢 Qty: <b>{order['qty']}</b>\n"
                f"❗ Kekurangan akun: <b>{missing}</b>\n\n"
                "Buka /owner → 📦 Atur Stok → pilih produk/variasi → ➕ Tambah Akun.",
                parse_mode="HTML"
            )
        except Exception:
            pass


def split_delivery_text(delivery_text: str, max_chars: int = 3200):
    lines = [line for line in (delivery_text or "").splitlines() if line.strip()]
    chunks, current = [], []
    size = 0

    for line in lines:
        extra = len(line) + 1
        if current and size + extra > max_chars:
            chunks.append("\n".join(current))
            current = []
            size = 0
        current.append(line)
        size += extra

    if current:
        chunks.append("\n".join(current))

    return chunks or [""]


async def send_delivery_payload(bot: Bot, user_id: int, order_id: int, delivery_text: str):
    chunks = split_delivery_text(delivery_text)

    await bot.send_message(
        user_id,
        "🎁 <b>AKUN PREMIUM ANDA</b>\n\n"
        f"🧾 Invoice: <b>{invoice(order_id)}</b>\n"
        f"📦 Total data: <b>{len((delivery_text or '').splitlines())}</b>\n\n"
        "Data akun dikirim di bawah ini:",
        parse_mode="HTML"
    )

    for chunk in chunks:
        await bot.send_message(
            user_id,
            f"<pre>{html.escape(chunk)}</pre>",
            parse_mode="HTML"
        )

    await bot.send_message(
        user_id,
        "✅ <b>PESANAN SELESAI</b>\n\n"
        "Simpan data akun dengan aman dan jangan membagikannya kepada orang lain.\n\n"
        f"<i>{STORE_FOOTER}</i>",
        parse_mode="HTML"
    )


async def fulfill_order(order_id: int, bot: Bot) -> bool:
    """
    Safe fulfillment:
    1) allocate exact credentials to the order
    2) save them in the order
    3) send Telegram messages
    4) only after successful send mark delivered/sold

    If Telegram fails, the same allocated credentials are retried later.
    """
    conn = db()
    conn.execute("BEGIN IMMEDIATE")
    order = conn.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()

    if not order:
        conn.rollback()
        conn.close()
        return False

    if order["fulfillment_status"] == "delivered":
        conn.rollback()
        conn.close()
        return True

    if order["payment_status"] != "paid":
        conn.rollback()
        conn.close()
        return False

    qty = int(order["qty"])

    # Reuse credentials already allocated to this order.
    allocated = conn.execute(
        """SELECT * FROM inventory_items
           WHERE order_id=? AND status='allocated'
           ORDER BY id ASC""",
        (order_id,)
    ).fetchall()

    if allocated:
        items = allocated
    else:
        items = conn.execute(
            """SELECT * FROM inventory_items
               WHERE variant_id=? AND status='available'
               ORDER BY id ASC
               LIMIT ?""",
            (order["variant_id"], qty)
        ).fetchall()

        if len(items) < qty:
            missing = qty - len(items)
            was_pending = order["status"] == "paid_pending_delivery"
            conn.execute(
                """UPDATE orders
                   SET status='paid_pending_delivery',
                       fulfillment_status='pending'
                   WHERE id=?""",
                (order_id,)
            )
            conn.commit()
            conn.close()
            if not was_pending:
                await notify_fulfillment_pending(bot, order, missing)
            return False

        # Allocate, don't mark sold yet.
        item_ids = [item["id"] for item in items]
        placeholders = ",".join("?" for _ in item_ids)
        conn.execute(
            f"""UPDATE inventory_items
                SET status='allocated', order_id=?
                WHERE id IN ({placeholders}) AND status='available'""",
            (order_id, *item_ids)
        )

        # Convert reservation into allocated credentials.
        if int(order["stock_reserved"] or 0) == 1:
            conn.execute(
                """UPDATE product_variants
                   SET reserved_stock=MAX(0, reserved_stock-?)
                   WHERE id=?""",
                (qty, order["variant_id"])
            )

        delivery_text = "\n".join(
            f"{idx}. {item['content']}" for idx, item in enumerate(items, start=1)
        )

        sync_variant_stock_from_inventory(conn, order["variant_id"])
        conn.execute(
            """UPDATE orders
               SET fulfillment_status='sending',
                   stock_reserved=0,
                   delivery_text=?,
                   last_delivery_error=''
               WHERE id=?""",
            (delivery_text, order_id)
        )
        conn.commit()
        conn.close()

        # Re-open below using stored delivery_text.
        conn = db()
        order = conn.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
        conn.close()

    delivery_text = order["delivery_text"] or "\n".join(
        f"{idx}. {item['content']}" for idx, item in enumerate(allocated, start=1)
    )

    # If allocated existed from a previous failed send and legacy delivery_text was empty.
    if not order["delivery_text"] and delivery_text:
        conn = db()
        conn.execute(
            "UPDATE orders SET delivery_text=?, fulfillment_status='sending' WHERE id=?",
            (delivery_text, order_id)
        )
        conn.commit()
        conn.close()

    try:
        await send_delivery_payload(bot, order["user_id"], order_id, delivery_text)
    except Exception as exc:
        conn = db()
        conn.execute(
            """UPDATE orders
               SET status='paid_pending_delivery',
                   fulfillment_status='send_failed',
                   delivery_attempts=delivery_attempts+1,
                   last_delivery_error=?
               WHERE id=?""",
            (str(exc)[:500], order_id)
        )
        conn.commit()
        conn.close()

        logging.exception("Delivery send failed for order %s: %s", order_id, exc)

        if ADMIN_ID:
            try:
                await bot.send_message(
                    ADMIN_ID,
                    "⚠️ <b>PENGIRIMAN AKUN GAGAL</b>\n\n"
                    f"🧾 {invoice(order_id)}\n"
                    "Akun sudah dialokasikan dan <b>tidak akan diberikan ke user lain</b>.\n"
                    "Gunakan Pesanan Saya / kirim ulang setelah koneksi Telegram normal.",
                    parse_mode="HTML"
                )
            except Exception:
                pass
        return False

    # Telegram delivery succeeded. Finalize exactly this allocated inventory.
    conn = db()
    conn.execute("BEGIN IMMEDIATE")
    fresh = conn.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()

    if fresh and fresh["fulfillment_status"] != "delivered":
        conn.execute(
            """UPDATE inventory_items
               SET status='sold', delivered_at=?
               WHERE order_id=? AND status='allocated'""",
            (datetime.now().isoformat(timespec="seconds"), order_id)
        )
        conn.execute(
            "UPDATE products SET sold=sold+? WHERE id=?",
            (qty, fresh["product_id"])
        )
        sent_at = datetime.now().isoformat(timespec="seconds")
        conn.execute(
            """UPDATE orders
               SET status='completed',
                   fulfillment_status='delivered',
                   delivery_attempts=delivery_attempts+1,
                   last_delivery_error='',
                   delivery_sent_at=?,
                   completed_at=?
               WHERE id=?""",
            (sent_at, sent_at, order_id)
        )
        sync_variant_stock_from_inventory(conn, fresh["variant_id"])

    conn.commit()
    conn.close()
    return True


async def fulfill_pending_for_variant(variant_id: int, bot: Bot):
    conn = db()
    rows = conn.execute(
        """SELECT id FROM orders
           WHERE variant_id=?
             AND payment_status='paid'
             AND fulfillment_status!='delivered'
           ORDER BY id ASC""",
        (variant_id,)
    ).fetchall()
    conn.close()

    for row in rows:
        await fulfill_order(row["id"], bot)



def system_health_snapshot():
    conn = db()

    pending_orders = conn.execute(
        """SELECT COUNT(*) AS n FROM orders
           WHERE status='pending'"""
    ).fetchone()["n"]

    paid_pending = conn.execute(
        """SELECT COUNT(*) AS n FROM orders
           WHERE status='paid_pending_delivery'
              OR fulfillment_status IN ('pending','sending','send_failed')"""
    ).fetchone()["n"]

    send_failed = conn.execute(
        """SELECT COUNT(*) AS n FROM orders
           WHERE fulfillment_status='send_failed'"""
    ).fetchone()["n"]

    allocated_items = conn.execute(
        """SELECT COUNT(*) AS n FROM inventory_items
           WHERE status='allocated'"""
    ).fetchone()["n"]

    available_items = conn.execute(
        """SELECT COUNT(*) AS n FROM inventory_items
           WHERE status='available'"""
    ).fetchone()["n"]

    active_products = conn.execute(
        """SELECT COUNT(*) AS n FROM products WHERE active=1"""
    ).fetchone()["n"]

    active_variants = conn.execute(
        """SELECT COUNT(*) AS n FROM product_variants WHERE active=1"""
    ).fetchone()["n"]

    verified_users = conn.execute(
        """SELECT COUNT(*) AS n FROM verified_users WHERE active=1"""
    ).fetchone()["n"]

    stock_mismatch = 0
    variants = conn.execute(
        """SELECT id, stock, reserved_stock
           FROM product_variants"""
    ).fetchall()

    for row in variants:
        available = conn.execute(
            """SELECT COUNT(*) AS n
               FROM inventory_items
               WHERE variant_id=? AND status='available'""",
            (row["id"],)
        ).fetchone()["n"]
        if int(row["stock"]) != int(available or 0):
            stock_mismatch += 1

    conn.close()

    backup_dir = Path(BACKUP_DIR)
    last_backup = None
    try:
        backups = sorted(
            backup_dir.glob("maboyydigital_*.db"),
            key=lambda p: p.stat().st_mtime,
            reverse=True
        )
        if backups:
            last_backup = backups[0]
    except Exception:
        pass

    return {
        "pending_orders": int(pending_orders or 0),
        "paid_pending": int(paid_pending or 0),
        "send_failed": int(send_failed or 0),
        "allocated_items": int(allocated_items or 0),
        "available_items": int(available_items or 0),
        "active_products": int(active_products or 0),
        "active_variants": int(active_variants or 0),
        "verified_users": int(verified_users or 0),
        "stock_mismatch": int(stock_mismatch or 0),
        "db_exists": Path(DB_PATH).exists(),
        "backup_exists": bool(last_backup),
        "last_backup_name": last_backup.name if last_backup else "-",
    }


async def recover_stuck_orders(bot: Bot):
    """
    Safe recovery only:
    - retries orders already paid but not delivered
    - never creates a new charge
    - never takes a new account for already allocated send_failed orders
      unless the order has no allocation yet
    """
    conn = db()
    rows = conn.execute(
        """SELECT id FROM orders
           WHERE payment_status='paid'
             AND fulfillment_status!='delivered'
             AND status!='cancelled'
           ORDER BY id ASC"""
    ).fetchall()
    conn.close()

    recovered = 0
    still_pending = 0

    for row in rows:
        ok = await fulfill_order(row["id"], bot)
        if ok:
            recovered += 1
        else:
            still_pending += 1

    return recovered, still_pending


async def cancel_pending_order(order_id: int, bot: Bot):
    conn = db()
    conn.execute("BEGIN IMMEDIATE")
    order = conn.execute(
        "SELECT * FROM orders WHERE id=?",
        (order_id,)
    ).fetchone()

    if not order:
        conn.rollback()
        conn.close()
        return False, "Order tidak ditemukan."

    if order["payment_status"] == "paid":
        conn.rollback()
        conn.close()
        return False, "Order sudah dibayar dan tidak boleh dibatalkan."

    if order["status"] in {"cancelled", "expired", "completed"}:
        conn.rollback()
        conn.close()
        return False, f"Order sudah berstatus {order['status']}."

    release_order_reservation(conn, order)
    conn.execute(
        """UPDATE orders
           SET status='cancelled',
               payment_status='cancelled'
           WHERE id=?""",
        (order_id,)
    )
    conn.commit()
    conn.close()

    try:
        await bot.send_message(
            order["user_id"],
            "❌ <b>PESANAN DIBATALKAN</b>\n\n"
            f"🧾 Invoice: <b>{invoice(order_id)}</b>\n"
            "Pesanan dibatalkan oleh owner.\n"
            "Jika ingin membeli kembali, silakan buat order baru.",
            parse_mode="HTML"
        )
    except Exception:
        pass

    return True, "Order berhasil dibatalkan dan reservasi stok dilepas."

def reservation_expiry_iso() -> str:
    return (
        datetime.now(timezone.utc).astimezone() +
        timedelta(minutes=ORDER_RESERVATION_MINUTES)
    ).isoformat(timespec="seconds")


def recent_duplicate_checkout(
    conn,
    user_id: int,
    variant_id: int,
    qty: int,
    payment_method: str,
    seconds: int = 12,
):
    row = conn.execute(
        """SELECT *
           FROM orders
           WHERE user_id=?
             AND variant_id=?
             AND qty=?
             AND payment_method=?
           ORDER BY id DESC
           LIMIT 1""",
        (user_id, variant_id, qty, payment_method)
    ).fetchone()

    if not row:
        return None

    try:
        created = datetime.fromisoformat(row["created_at"])
        now = datetime.now(created.tzinfo) if created.tzinfo else datetime.now()
        age = (now - created).total_seconds()
    except Exception:
        return None

    if 0 <= age <= seconds:
        return row
    return None


def reserve_stock_for_order(conn, variant_id: int, qty: int) -> bool:
    row = conn.execute(
        """SELECT stock, reserved_stock
           FROM product_variants
           WHERE id=? AND active=1""",
        (variant_id,)
    ).fetchone()

    if not row:
        return False

    available = int(row["stock"]) - int(row["reserved_stock"] or 0)
    if qty <= 0 or available < qty:
        return False

    conn.execute(
        """UPDATE product_variants
           SET reserved_stock=reserved_stock+?
           WHERE id=?""",
        (qty, variant_id)
    )
    return True


def release_order_reservation(conn, order):
    if not order or int(order["stock_reserved"] or 0) != 1:
        return

    conn.execute(
        """UPDATE product_variants
           SET reserved_stock=MAX(0, reserved_stock-?)
           WHERE id=?""",
        (order["qty"], order["variant_id"])
    )
    conn.execute(
        "UPDATE orders SET stock_reserved=0 WHERE id=?",
        (order["id"],)
    )


_purchase_locks = {}


def checkout_note_keyboard(variant_id: int, qty: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="📝 Isi Catatan",
                callback_data=f"checkoutnote:add:{variant_id}:{qty}"
            )
        ],
        [
            InlineKeyboardButton(
                text="⏭️ Lewati Catatan",
                callback_data=f"checkoutnote:skip:{variant_id}:{qty}"
            )
        ],
        [
            InlineKeyboardButton(
                text="⬅️ Kembali",
                callback_data=f"variant:{variant_id}"
            )
        ]
    ])


def payment_method_keyboard(variant_id: int, qty: int):
    rows = [
        [
            InlineKeyboardButton(
                text="🎟️ Pakai Voucher",
                callback_data=f"checkoutvoucher:{variant_id}:{qty}"
            )
        ],
        [
            InlineKeyboardButton(
                text="💰 Bayar dengan Saldo Kamu",
                callback_data=f"paywallet:{variant_id}:{qty}"
            )
        ],
        [
            InlineKeyboardButton(
                text="🟡 QRIS Manual",
                callback_data=f"process:{variant_id}:{qty}"
            )
        ],
    ]

    if shopeepay_ready():
        rows.append([
            InlineKeyboardButton(
                text="⚡ QRIS Otomatis",
                callback_data=f"processauto:{variant_id}:{qty}"
            )
        ])

    rows.append([
        InlineKeyboardButton(
            text="⬅️ Kembali",
            callback_data=f"variant:{variant_id}"
        )
    ])

    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_checkout_note_from_state(data: dict) -> str:
    note = str(data.get("checkout_note", "") or "").strip()
    return note[:500]


def purchase_lock(user_id: int):
    lock = _purchase_locks.get(user_id)
    if lock is None:
        lock = asyncio.Lock()
        _purchase_locks[user_id] = lock
    return lock


async def cleanup_expired_orders(bot: Bot):
    while True:
        await asyncio.sleep(60)
        try:
            now_iso = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
            conn = db()
            conn.execute("BEGIN IMMEDIATE")
            rows = conn.execute(
                """SELECT * FROM orders
                   WHERE status='pending'
                     AND stock_reserved=1
                     AND reserved_until!=''
                     AND reserved_until < ?""",
                (now_iso,)
            ).fetchall()

            notify = []
            for order in rows:
                release_order_reservation(conn, order)
                conn.execute(
                    """UPDATE orders
                       SET status='expired', payment_status='expired'
                       WHERE id=?""",
                    (order["id"],)
                )
                notify.append((order["user_id"], order["id"]))

            conn.commit()
            conn.close()

            for user_id, order_id in notify:
                try:
                    await bot.send_message(
                        user_id,
                        "⌛ <b>PESANAN KADALUARSA</b>\n\n"
                        f"🧾 Invoice: <b>{invoice(order_id)}</b>\n"
                        "Waktu pembayaran habis dan stok reservasi sudah dilepas.\n"
                        "Silakan buat pesanan baru jika masih ingin membeli.",
                        parse_mode="HTML"
                    )
                except Exception:
                    pass
        except Exception as exc:
            logging.exception("Expired order cleanup failed: %s", exc)




def setting_int(key: str, default: int) -> int:
    try:
        return int(get_setting(key, str(default)))
    except Exception:
        return default


def loyalty_status(user_id: int):
    conn = db()
    spent = conn.execute(
        """SELECT COALESCE(SUM(total-discount_amount),0) AS n
           FROM orders
           WHERE user_id=? AND status='completed'""",
        (user_id,)
    ).fetchone()["n"]
    conn.close()

    spent = int(spent or 0)
    silver = setting_int("loyalty_silver", 250000)
    gold = setting_int("loyalty_gold", 750000)
    vip = setting_int("loyalty_vip", 2000000)

    if spent >= vip:
        return "VIP", spent
    if spent >= gold:
        return "Gold", spent
    if spent >= silver:
        return "Silver", spent
    return "Bronze", spent


def security_profile(user_id: int):
    conn = db()
    row = conn.execute(
        "SELECT * FROM user_security WHERE user_id=?",
        (user_id,)
    ).fetchone()
    conn.close()
    return row


def security_blocked(user_id: int) -> bool:
    row = security_profile(user_id)
    return bool(row and int(row["blocked"] or 0) == 1)


def security_event(user_id: int, reason: str, score: int = 1):
    now = datetime.now().isoformat(timespec="seconds")
    conn = db()
    conn.execute(
        """INSERT INTO user_security
           (user_id, blocked, risk_score, strikes, last_reason, updated_at)
           VALUES(?,0,?,?,?,?)
           ON CONFLICT(user_id) DO UPDATE SET
             risk_score=risk_score+excluded.risk_score,
             strikes=strikes+1,
             last_reason=excluded.last_reason,
             updated_at=excluded.updated_at""",
        (user_id, max(0, score), 1, reason[:250], now)
    )
    conn.commit()
    conn.close()


def anti_abuse_checkout(user_id: int, payment_method: str):
    if security_blocked(user_id):
        return False, "Akun Anda dibatasi untuk transaksi. Hubungi owner."

    conn = db()
    pending = conn.execute(
        """SELECT COUNT(*) AS n FROM orders
           WHERE user_id=? AND status='pending' AND payment_status='unpaid'""",
        (user_id,)
    ).fetchone()["n"]

    last = conn.execute(
        """SELECT created_at FROM orders
           WHERE user_id=? ORDER BY id DESC LIMIT 1""",
        (user_id,)
    ).fetchone()
    conn.close()

    limit = max(1, setting_int("fraud_pending_limit", 3))
    if payment_method != "WALLET" and int(pending or 0) >= limit:
        security_event(user_id, "Terlalu banyak invoice pending", 2)
        return False, f"Maksimal {limit} invoice belum dibayar. Selesaikan atau tunggu invoice kadaluarsa."

    if last:
        try:
            created = datetime.fromisoformat(last["created_at"])
            now = datetime.now(created.tzinfo) if created.tzinfo else datetime.now()
            age = (now - created).total_seconds()
            cooldown = max(2, setting_int("fraud_cooldown_seconds", 8))
            if age < cooldown:
                return False, f"Tunggu {cooldown} detik sebelum membuat checkout berikutnya."
        except Exception:
            pass

    return True, ""


def inventory_log(variant_id: int, action: str, qty: int, reference: str = "", note: str = ""):
    conn = db()
    conn.execute(
        """INSERT INTO inventory_logs
           (variant_id, action, qty, reference, note, created_at)
           VALUES(?,?,?,?,?,?)""",
        (
            variant_id, action, int(qty), reference[:100], note[:500],
            datetime.now().isoformat(timespec="seconds")
        )
    )
    conn.commit()
    conn.close()


def voucher_validate(code: str, user_id: int, product_id: int, variant_id: int, subtotal: int):
    code = (code or "").strip().upper()
    if not code:
        return None, 0, "Kode voucher kosong."

    conn = db()
    voucher = conn.execute(
        "SELECT * FROM vouchers WHERE code=? AND active=1",
        (code,)
    ).fetchone()

    if not voucher:
        conn.close()
        return None, 0, "Voucher tidak ditemukan / tidak aktif."

    if voucher["expires_at"]:
        try:
            if datetime.fromisoformat(voucher["expires_at"]) < datetime.now():
                conn.close()
                return None, 0, "Voucher sudah kedaluwarsa."
        except Exception:
            pass

    if int(voucher["min_spend"] or 0) > subtotal:
        minimum = int(voucher["min_spend"] or 0)
        conn.close()
        return None, 0, f"Minimum transaksi voucher {rupiah(minimum)}."

    if int(voucher["product_id"] or 0) not in (0, product_id):
        conn.close()
        return None, 0, "Voucher tidak berlaku untuk produk ini."

    if int(voucher["variant_id"] or 0) not in (0, variant_id):
        conn.close()
        return None, 0, "Voucher tidak berlaku untuk variasi ini."

    usage_limit = int(voucher["usage_limit"] or 0)
    if usage_limit > 0 and int(voucher["used"] or 0) >= usage_limit:
        conn.close()
        return None, 0, "Kuota voucher sudah habis."

    per_user = max(1, int(voucher["per_user_limit"] or 1))
    user_used = conn.execute(
        "SELECT COUNT(*) AS n FROM voucher_usage WHERE voucher_id=? AND user_id=?",
        (voucher["id"], user_id)
    ).fetchone()["n"]
    if int(user_used or 0) >= per_user:
        conn.close()
        return None, 0, "Batas pemakaian voucher Anda sudah tercapai."

    if int(voucher["new_user_only"] or 0) == 1:
        completed = conn.execute(
            "SELECT COUNT(*) AS n FROM orders WHERE user_id=? AND status='completed'",
            (user_id,)
        ).fetchone()["n"]
        if int(completed or 0) > 0:
            conn.close()
            return None, 0, "Voucher hanya untuk pelanggan baru."

    conn.close()

    discount = max(0, int(voucher["discount"] or 0))
    max_discount = int(voucher["max_discount"] or 0)
    if max_discount > 0:
        discount = min(discount, max_discount)
    discount = min(discount, subtotal)

    return voucher, discount, ""


def checkout_discount_from_state(data: dict, user_id: int, product_id: int, variant_id: int, subtotal: int):
    code = str(data.get("checkout_voucher_code", "") or "").strip().upper()
    if not code:
        return "", 0
    voucher, discount, _ = voucher_validate(code, user_id, product_id, variant_id, subtotal)
    if not voucher:
        return "", 0
    return code, discount


def record_voucher_usage(code: str, user_id: int, order_id: int, discount_amount: int):
    if not code or discount_amount <= 0:
        return
    conn = db()
    voucher = conn.execute("SELECT * FROM vouchers WHERE code=?", (code,)).fetchone()
    if not voucher:
        conn.close()
        return
    try:
        conn.execute(
            """INSERT INTO voucher_usage
               (voucher_id, user_id, order_id, discount_amount, created_at)
               VALUES(?,?,?,?,?)""",
            (
                voucher["id"], user_id, order_id, discount_amount,
                datetime.now().isoformat(timespec="seconds")
            )
        )
        conn.execute("UPDATE vouchers SET used=used+1 WHERE id=?", (voucher["id"],))
        conn.commit()
    except sqlite3.IntegrityError:
        conn.rollback()
    conn.close()


def low_stock_threshold() -> int:
    return max(0, setting_int("low_stock_threshold", 5))


async def notify_low_stock(bot: Bot, variant_id: int):
    threshold = low_stock_threshold()
    if not ADMIN_ID or threshold <= 0:
        return

    conn = db()
    variant = conn.execute(
        """SELECT v.*, p.name AS product_name
           FROM product_variants v
           JOIN products p ON p.id=v.product_id
           WHERE v.id=?""",
        (variant_id,)
    ).fetchone()
    conn.close()
    if not variant:
        return

    stock = available_stock(variant)
    if stock <= threshold:
        try:
            await bot.send_message(
                ADMIN_ID,
                "⚠️ <b>STOK MENIPIS</b>\n\n"
                f"📦 {html.escape(variant['product_name'])}\n"
                f"🧩 {html.escape(variant['name'])}\n"
                f"📉 Tersisa: <b>{stock}</b>\n"
                f"🔔 Batas alert: <b>{threshold}</b>",
                parse_mode="HTML"
            )
        except Exception:
            pass


def professional_invoice_text(order, product_name: str = "", variant_name: str = ""):
    subtotal = int(order["total"] or 0)
    discount = int(order["discount_amount"] or 0)
    final_total = int(order["payment_total"] or max(0, subtotal - discount))
    return (
        "🧾 <b>MABOYY DIGITAL • INVOICE</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"Invoice: <b>{invoice(order['id'])}</b>\n"
        f"Produk: <b>{html.escape(product_name or '-')}</b>\n"
        f"Variasi: <b>{html.escape(variant_name or '-')}</b>\n"
        f"Qty: <b>{order['qty']}</b>\n"
        f"Subtotal: <b>{rupiah(subtotal)}</b>\n"
        + (f"Voucher: <b>-{rupiah(discount)}</b>\n" if discount > 0 else "")
        + f"Total: <b>{rupiah(final_total)}</b>\n"
        f"Metode: <b>{html.escape(order['payment_method'] or '-')}</b>\n"
        f"Status: <b>{html.escape(order['status'])}</b>\n"
        "━━━━━━━━━━━━━━━━━━"
    )



def professional_invoice_for_order(order_id: int):
    conn = db()
    order = conn.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
    if not order:
        conn.close()
        return "🧾 Invoice tidak ditemukan."

    product = conn.execute(
        "SELECT name FROM products WHERE id=?",
        (order["product_id"],)
    ).fetchone()
    variant = conn.execute(
        "SELECT name FROM product_variants WHERE id=?",
        (order["variant_id"],)
    ).fetchone()
    conn.close()

    return professional_invoice_text(
        order,
        product["name"] if product else "-",
        variant["name"] if variant else "-"
    )



def maintenance_enabled() -> bool:
    return get_setting("maintenance_mode", "0") == "1"


def user_segment(user_id: int) -> str:
    conn = db()
    completed = conn.execute(
        "SELECT COUNT(*) AS n FROM orders WHERE user_id=? AND status='completed'",
        (user_id,)
    ).fetchone()["n"]
    spent = conn.execute(
        "SELECT COALESCE(SUM(payment_total),0) AS n FROM orders WHERE user_id=? AND status='completed'",
        (user_id,)
    ).fetchone()["n"]
    last = conn.execute(
        "SELECT completed_at FROM orders WHERE user_id=? AND status='completed' ORDER BY id DESC LIMIT 1",
        (user_id,)
    ).fetchone()
    conn.close()

    completed = int(completed or 0)
    spent = int(spent or 0)
    if completed == 0:
        return "new"
    if spent >= setting_int("loyalty_vip", 2000000):
        return "vip"
    if completed >= 3:
        return "returning"
    if last and last["completed_at"]:
        try:
            dt = datetime.fromisoformat(last["completed_at"])
            now = datetime.now(dt.tzinfo) if dt.tzinfo else datetime.now()
            if (now - dt).days >= 30:
                return "inactive"
        except Exception:
            pass
    return "buyer"


def segment_user_ids(segment: str):
    conn = db()
    users = conn.execute(
        "SELECT user_id FROM verified_users WHERE active=1 ORDER BY user_id"
    ).fetchall()
    conn.close()

    ids = []
    for row in users:
        uid = int(row["user_id"])
        seg = user_segment(uid)
        if segment == "all":
            ids.append(uid)
        elif segment == "buyers" and seg in {"buyer","returning","vip","inactive"}:
            ids.append(uid)
        elif segment == "returning" and seg in {"returning","vip"}:
            ids.append(uid)
        elif segment == "vip" and seg == "vip":
            ids.append(uid)
        elif segment == "inactive" and seg == "inactive":
            ids.append(uid)
        elif segment == "new" and seg == "new":
            ids.append(uid)
    return ids


async def run_system_self_test(bot: Bot):
    results = []

    try:
        conn = db()
        conn.execute("SELECT 1").fetchone()
        conn.close()
        results.append(("Database", True, DB_PATH))
    except Exception as exc:
        results.append(("Database", False, str(exc)[:100]))

    try:
        db_file = Path(DB_PATH)
        writable = db_file.parent.exists() and os.access(db_file.parent, os.W_OK)
        results.append(("Storage /data", writable, str(db_file.parent)))
    except Exception as exc:
        results.append(("Storage /data", False, str(exc)[:100]))

    try:
        me = await bot.get_me()
        results.append(("Telegram API", True, f"@{me.username or me.id}"))
    except Exception as exc:
        results.append(("Telegram API", False, str(exc)[:100]))

    try:
        qris = bool(get_setting("qris_file_id", ""))
        results.append(("QRIS Manual", qris, "Terpasang" if qris else "Belum dipasang"))
    except Exception as exc:
        results.append(("QRIS Manual", False, str(exc)[:100]))

    try:
        conn = db()
        stuck = conn.execute(
            """SELECT COUNT(*) AS n FROM orders
               WHERE payment_status='paid' AND fulfillment_status!='delivered'"""
        ).fetchone()["n"]
        mismatch = 0
        variants = conn.execute("SELECT id, stock FROM product_variants WHERE active=1").fetchall()
        for v in variants:
            real = conn.execute(
                "SELECT COUNT(*) AS n FROM inventory_items WHERE variant_id=? AND status='available'",
                (v["id"],)
            ).fetchone()["n"]
            if int(v["stock"] or 0) != int(real or 0):
                mismatch += 1
        conn.close()
        results.append(("Recovery Queue", int(stuck)==0, f"{stuck} pending"))
        results.append(("Inventory Sync", mismatch==0, f"{mismatch} mismatch"))
    except Exception as exc:
        results.append(("Recovery/Inventory", False, str(exc)[:100]))

    return results


async def send_daily_owner_report(bot: Bot):
    if not ADMIN_ID or get_setting("daily_report_enabled","1") != "1":
        return

    jakarta_now = datetime.now(ZoneInfo("Asia/Jakarta"))
    today = jakarta_now.date().isoformat()
    conn = db()
    order_count = conn.execute(
        "SELECT COUNT(*) AS n FROM orders WHERE substr(created_at,1,10)=?",
        (today,)
    ).fetchone()["n"]
    completed = conn.execute(
        "SELECT COUNT(*) AS n FROM orders WHERE status='completed' AND substr(completed_at,1,10)=?",
        (today,)
    ).fetchone()["n"]
    revenue = conn.execute(
        "SELECT COALESCE(SUM(payment_total),0) AS n FROM orders WHERE status='completed' AND substr(completed_at,1,10)=?",
        (today,)
    ).fetchone()["n"]
    pending = conn.execute(
        "SELECT COUNT(*) AS n FROM orders WHERE status IN ('pending','paid_pending_delivery')"
    ).fetchone()["n"]
    low = conn.execute(
        """SELECT COUNT(*) AS n FROM product_variants
           WHERE active=1 AND stock<=?""",
        (low_stock_threshold(),)
    ).fetchone()["n"]
    conn.close()

    await bot.send_message(
        ADMIN_ID,
        "📊 <b>LAPORAN HARIAN MABOYY DIGITAL</b>\n\n"
        f"🧾 Order hari ini: <b>{order_count}</b>\n"
        f"✅ Selesai: <b>{completed}</b>\n"
        f"💰 Omzet: <b>{rupiah(revenue)}</b>\n"
        f"⏳ Perlu perhatian: <b>{pending}</b>\n"
        f"📉 Variasi stok rendah: <b>{low}</b>\n\n"
        f"<i>{STORE_FOOTER}</i>",
        parse_mode="HTML"
    )


async def periodic_operations_loop(bot: Bot):
    last_report_date = ""
    await asyncio.sleep(30)

    while True:
        try:
            await recover_stuck_orders(bot)

            # Repair stock counters from inventory truth.
            conn = db()
            variant_ids = [
                int(r["id"]) for r in conn.execute(
                    "SELECT id FROM product_variants WHERE active=1"
                ).fetchall()
            ]
            for variant_id in variant_ids:
                sync_variant_stock_from_inventory(conn, variant_id)
            conn.commit()
            conn.close()

            # Daily report, once per day at configured local/server hour.
            now = datetime.now(ZoneInfo("Asia/Jakarta"))
            report_hour = max(0, min(23, setting_int("daily_report_hour", 20)))
            if now.hour >= report_hour and now.date().isoformat() != last_report_date:
                await send_daily_owner_report(bot)
                last_report_date = now.date().isoformat()
        except Exception as exc:
            logging.exception("Periodic operations failed: %s", exc)

        await asyncio.sleep(300)


async def apply_cashback_once(order_id: int):
    percent = max(0, min(50, setting_int("cashback_percent", 0)))
    if percent <= 0:
        return 0

    conn = db()
    conn.execute("BEGIN IMMEDIATE")
    order = conn.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
    if not order or order["status"] != "completed" or int(order["cashback_applied"] or 0) == 1:
        conn.rollback()
        conn.close()
        return 0

    base_amount = int(order["payment_total"] or order["total"] or 0)
    cashback = max(0, (base_amount * percent) // 100)
    if cashback <= 0:
        conn.execute("UPDATE orders SET cashback_applied=1 WHERE id=?", (order_id,))
        conn.commit()
        conn.close()
        return 0

    wallet = conn.execute("SELECT balance FROM wallets WHERE user_id=?", (order["user_id"],)).fetchone()
    balance = int(wallet["balance"] or 0) if wallet else 0
    new_balance = balance + cashback
    now = datetime.now().isoformat(timespec="seconds")
    conn.execute(
        """INSERT INTO wallets(user_id,balance,updated_at)
           VALUES(?,?,?)
           ON CONFLICT(user_id) DO UPDATE SET balance=excluded.balance, updated_at=excluded.updated_at""",
        (order["user_id"], new_balance, now)
    )
    conn.execute(
        """INSERT OR IGNORE INTO wallet_ledger
           (user_id,type,amount,balance_after,reference,note,created_at)
           VALUES(?,?,?,?,?,?,?)""",
        (order["user_id"], "CASHBACK", cashback, new_balance, invoice(order_id),
         f"Cashback {percent}% pembelian", now)
    )
    conn.execute("UPDATE orders SET cashback_applied=1 WHERE id=?", (order_id,))
    conn.commit()
    conn.close()
    return cashback


def get_min_topup() -> int:
    try:
        return max(1000, int(get_setting("min_topup", "5000")))
    except ValueError:
        return 5000



def channel_target(value: str):
    value = (value or "").strip()
    if not value:
        return None
    if value.lstrip("-").isdigit():
        return int(value)
    return value


def create_database_backup() -> Path:
    Path(BACKUP_DIR).mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = Path(BACKUP_DIR) / f"maboyydigital_{stamp}.db"

    src = sqlite3.connect(DB_PATH)
    dst = sqlite3.connect(str(backup_path))
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()

    backups = sorted(
        Path(BACKUP_DIR).glob("maboyydigital_*.db"),
        key=lambda p: p.stat().st_mtime,
        reverse=True
    )
    for old_file in backups[BACKUP_RETENTION:]:
        try:
            old_file.unlink()
        except Exception:
            pass

    return backup_path


async def send_backup(bot: Bot, backup_path: Path):
    # Backup hanya dikirim ke PM owner berdasarkan ADMIN_ID.
    if not ADMIN_ID:
        logging.warning("Backup dibuat tetapi ADMIN_ID belum diisi.")
        return

    try:
        await bot.send_document(
            ADMIN_ID,
            document=FSInputFile(str(backup_path)),
            caption=(
                "🗄️ <b>BACKUP OTOMATIS MABOYY DIGITAL</b>\n\n"
                f"📦 Versi bot: <b>v{BOT_VERSION}</b>\n"
                f"🕒 {datetime.now().strftime('%d-%m-%Y %H:%M:%S')}\n"
                f"💾 Database: <code>{Path(DB_PATH).name}</code>\n\n"
                "Backup ini dikirim langsung ke PM owner."
            ),
            parse_mode="HTML"
        )
    except Exception as exc:
        logging.warning("Failed to send backup to owner: %s", exc)


async def backup_loop(bot: Bot):
    # Jangan membuat backup saat bot baru start/redeploy.
    # Backup pertama baru dibuat setelah interval penuh.
    while True:
        await asyncio.sleep(BACKUP_INTERVAL_HOURS * 3600)

        try:
            backup_path = create_database_backup()
            await send_backup(bot, backup_path)
            logging.info("Automatic backup created: %s", backup_path)
        except Exception as exc:
            logging.exception("Automatic backup failed: %s", exc)


def build_stock_text() -> str:
    conn = db()
    rows = conn.execute("""
        SELECT
            p.name AS product_name,
            v.name AS variant_name,
            v.stock,
            v.reserved_stock,
            v.price,
            p.active,
            v.active
        FROM product_variants v
        JOIN products p ON p.id=v.product_id
        WHERE p.active=1 AND v.active=1
        ORDER BY p.id, v.id
    """).fetchall()
    conn.close()

    lines = [
        "📦 <b>STOK TERBARU • MABOYY DIGITAL</b>",
        "",
    ]

    if not rows:
        lines.append("Belum ada produk aktif.")
    else:
        current_product = None
        for row in rows:
            if current_product != row["product_name"]:
                current_product = row["product_name"]
                lines.append(f"\n<b>{current_product}</b>")
            available = max(0, int(row["stock"]) - int(row["reserved_stock"] or 0))
            icon = "✅" if available > 0 else "❌"
            lines.append(
                f"{icon} {row['variant_name']} — "
                f"<b>{available}</b> stok • {rupiah(row['price'])}"
            )

    lines.extend([
        "",
        f"🕒 Update: {datetime.now().strftime('%d-%m-%Y %H:%M:%S')}",
        f"<i>{STORE_FOOTER}</i>"
    ])
    return "\n".join(lines)


async def sync_stock_channel(bot: Bot):
    target = channel_target(STOCK_CHANNEL_ID)
    if not target:
        return

    text = build_stock_text()
    message_id_raw = get_setting("stock_channel_message_id", "")
    message_id = int(message_id_raw) if message_id_raw.isdigit() else None

    if message_id:
        try:
            await bot.edit_message_text(
                chat_id=target,
                message_id=message_id,
                text=text,
                parse_mode="HTML"
            )
            return
        except Exception:
            # If message was deleted or no longer editable, send a new one.
            pass

    try:
        msg = await bot.send_message(target, text, parse_mode="HTML")
        set_setting("stock_channel_message_id", msg.message_id)
    except Exception as exc:
        logging.warning("Stock channel sync failed: %s", exc)


async def startup_automation(bot: Bot):
    # Startup/redeploy tidak boleh mengubah pesan stok channel.
    # Sinkronisasi hanya terjadi saat data stok/transaksi berubah
    # atau owner menjalankan sinkron manual.
    return


def unique_code_for_order():
    if get_setting("unique_code_enabled", "1") != "1":
        return 0

    try:
        low = max(1, int(get_setting("unique_code_min", "1")))
        high = max(low, int(get_setting("unique_code_max", "999")))
    except ValueError:
        low, high = 1, 999

    return random.randint(low, high)



def shopeepay_ready():
    required = [
        SHOPEEPAY_BASE_URL,
        SHOPEEPAY_CLIENT_ID,
        SHOPEEPAY_CLIENT_SECRET,
        SHOPEEPAY_MERCHANT_ID,
        SHOPEEPAY_STORE_ID,
        SHOPEEPAY_PRIVATE_KEY,
        SHOPEEPAY_PUBLIC_KEY,
        PUBLIC_BASE_URL,
    ]
    return SHOPEEPAY_ENABLED and all(required)


def iso_timestamp():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def rsa_sha256_sign(private_key_pem: str, payload: str) -> str:
    key = RSA.import_key(private_key_pem)
    digest = SHA256.new(payload.encode("utf-8"))
    signature = pkcs1_15.new(key).sign(digest)
    return base64.b64encode(signature).decode("utf-8")


def rsa_sha256_verify(public_key_pem: str, payload: str, signature_b64: str) -> bool:
    try:
        key = RSA.import_key(public_key_pem)
        digest = SHA256.new(payload.encode("utf-8"))
        signature = base64.b64decode(signature_b64)
        pkcs1_15.new(key).verify(digest, signature)
        return True
    except Exception:
        return False


def compact_json(data) -> bytes:
    return json.dumps(data, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def transaction_signature(method: str, path: str, token: str, body: dict, timestamp: str) -> str:
    raw = compact_json(body)
    body_hash = hashlib.sha256(raw).hexdigest().lower()
    payload = f"{method}:{path}:{token}:{body_hash}:{timestamp}"
    digest = hmac.new(
        SHOPEEPAY_CLIENT_SECRET.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha512
    ).digest()
    return base64.b64encode(digest).decode("utf-8")


async def shopeepay_access_token():
    if not shopeepay_ready():
        raise RuntimeError("Payment Gateway belum dikonfigurasi lengkap.")

    path = "/v1.0/access-token/b2b"
    timestamp = iso_timestamp()
    signature = rsa_sha256_sign(
        SHOPEEPAY_PRIVATE_KEY,
        f"{SHOPEEPAY_CLIENT_ID}|{timestamp}"
    )
    headers = {
        "Content-Type": "application/json",
        "X-TIMESTAMP": timestamp,
        "X-CLIENT-KEY": SHOPEEPAY_CLIENT_ID,
        "X-SIGNATURE": signature,
    }
    body = {"grantType": "client_credentials"}

    async with ClientSession() as session:
        async with session.post(
            SHOPEEPAY_BASE_URL + path,
            json=body,
            headers=headers,
            timeout=20
        ) as resp:
            data = await resp.json(content_type=None)
            if resp.status >= 400 or not data.get("accessToken"):
                raise RuntimeError(
                    f"Gagal access token Payment Gateway: {data.get('responseMessage', resp.status)}"
                )
            return data["accessToken"]


async def shopeepay_generate_qr(order_id: int, amount: int):
    token = await shopeepay_access_token()
    path = "/v1.0/qr/qr-mpm-generate"
    timestamp = iso_timestamp()
    partner_ref = invoice(order_id)

    body = {
        "partnerReferenceNo": partner_ref,
        "amount": {
            "value": f"{amount:.2f}",
            "currency": "IDR"
        },
        "merchantId": SHOPEEPAY_MERCHANT_ID,
        "terminalId": SHOPEEPAY_TERMINAL_ID,
        "validityPeriod": (
            datetime.now(timezone.utc).astimezone() + timedelta(minutes=15)
        ).isoformat(timespec="seconds"),
        "additionalInfo": {
            "externalStoreId": SHOPEEPAY_STORE_ID,
            "convenienceFeeIndicator": "01",
            "promoIds": ""
        }
    }

    signature = transaction_signature("POST", path, token, body, timestamp)
    external_id = str(int(datetime.now().timestamp() * 1000))

    headers = {
        "Content-Type": "application/json",
        "X-TIMESTAMP": timestamp,
        "Authorization": f"Bearer {token}",
        "X-SIGNATURE": signature,
        "X-PARTNER-ID": SHOPEEPAY_CLIENT_ID,
        "X-EXTERNAL-ID": external_id,
        "CHANNEL-ID": "mweb",
    }

    async with ClientSession() as session:
        async with session.post(
            SHOPEEPAY_BASE_URL + path,
            data=compact_json(body),
            headers=headers,
            timeout=20
        ) as resp:
            data = await resp.json(content_type=None)
            qr_url = data.get("qrUrl")
            qr_content = data.get("qrContent")
            if resp.status >= 400 or (not qr_url and not qr_content):
                raise RuntimeError(
                    f"Gagal membuat QR Payment Gateway: {data.get('responseMessage', resp.status)}"
                )
            return {
                "partner_reference": partner_ref,
                "qr_url": qr_url or "",
                "qr_content": qr_content or "",
                "raw": data
            }


async def mark_order_paid(order_id: int, bot: Bot, paid_amount: int | None = None):
    conn = db()
    conn.execute("BEGIN IMMEDIATE")
    order = conn.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()

    if not order:
        conn.rollback()
        conn.close()
        return False

    # A confirmed payment must never be discarded just because the local
    # reservation already expired. Only an explicitly cancelled order is rejected.
    if order["status"] == "cancelled":
        conn.rollback()
        conn.close()
        return False

    # Idempotent payment handling: never charge/process the same order twice.
    if order["payment_status"] != "paid":
        conn.execute(
            """UPDATE orders
               SET payment_status='paid',
                   status='paid_pending_delivery'
               WHERE id=?""",
            (order_id,)
        )

    conn.commit()
    conn.close()

    # Voucher baru dihitung terpakai setelah pembayaran valid.
    record_voucher_usage(
        order["voucher_code"] or "",
        order["user_id"],
        order_id,
        int(order["discount_amount"] or 0)
    )

    # Account delivery is a separate, idempotent fulfillment step.
    delivered = await fulfill_order(order_id, bot)

    if delivered:
        try:
            await bot.send_message(
                order["user_id"],
                professional_invoice_for_order(order_id)
                + "\n\n✅ <b>Pembayaran berhasil & akun sudah dikirim.</b>\n\n"
                + f"<i>{STORE_FOOTER}</i>",
                parse_mode="HTML"
            )
        except Exception:
            pass

    return True


# =========================
# FSM
# =========================
class CheckoutState(StatesGroup):
    waiting_note = State()
    waiting_voucher = State()


class ShopToolsState(StatesGroup):
    search_product = State()


class BroadcastState(StatesGroup):
    waiting_message = State()

class BundleState(StatesGroup):
    choose_second = State()



class OwnerState(StatesGroup):
    add_product = State()
    add_variant = State()
    set_stock = State()
    stock_add_items = State()
    stock_set_number = State()
    set_price = State()
    delete_product = State()
    add_voucher = State()
    complete_order = State()
    mark_popular = State()
    mark_flash = State()
    set_qris = State()
    set_payment_note = State()
    set_unique_range = State()
    topup_amount = State()
    owner_wallet_user = State()
    owner_wallet_add = State()
    owner_wallet_subtract = State()
    owner_topup_verify = State()
    owner_min_topup = State()
    variant_button_name = State()
    security_user = State()
    low_stock_threshold = State()
    reject_topup = State()
    voucher_code = State()
    voucher_discount = State()
    voucher_min_spend = State()
    voucher_max_discount = State()
    voucher_quota = State()
    voucher_per_user = State()
    voucher_days = State()



async def safe_edit_or_answer(call: CallbackQuery, text: str, reply_markup=None, parse_mode: str = "HTML"):
    """
    Navigation-safe message update.
    Some screens are photos/captions, while others are text messages.
    Telegram rejects edit_text on media messages. This helper gracefully falls back
    to caption edit or sending a new text message, so Back buttons never look dead.
    """
    try:
        await call.message.edit_text(
            text,
            reply_markup=reply_markup,
            parse_mode=parse_mode
        )
        return
    except Exception:
        pass

    try:
        if getattr(call.message, "caption", None) is not None:
            await call.message.edit_caption(
                caption=text,
                reply_markup=reply_markup,
                parse_mode=parse_mode
            )
            return
    except Exception:
        pass

    try:
        await call.message.answer(
            text,
            reply_markup=reply_markup,
            parse_mode=parse_mode
        )
    except Exception:
        pass


# =========================
# KEYBOARDS
# =========================
def main_menu():
    kb = InlineKeyboardBuilder()
    kb.button(text="🏷️ List Produk", callback_data="products")
    kb.button(text="🔥 Produk Populer", callback_data="popular")
    kb.button(text="⚡ Flash Sale", callback_data="flash")
    kb.button(text="🎁 Voucher", callback_data="voucher_info")
    kb.button(text="📁 Laporan Stok", callback_data="stock_report")
    kb.button(text="🧾 Pesanan Saya", callback_data="my_orders")
    kb.button(text="💰 Saldo Kamu", callback_data="wallet")
    kb.adjust(2, 2, 2, 1)
    return kb.as_markup()


def user_reply_menu():
    conn = db()
    products = conn.execute(
        "SELECT id, name FROM products WHERE active=1 ORDER BY id LIMIT 25"
    ).fetchall()
    conn.close()

    keyboard = [
        [
            KeyboardButton(text="🏷️ List Produk"),
            KeyboardButton(text="🎁 Voucher"),
            KeyboardButton(text="📁 Laporan Stok"),
        ]
    ]

    # Product shortcuts: 1..N, five buttons per row.
    # Number follows the same order shown in List Produk.
    number_row = []
    for index, _product in enumerate(products, start=1):
        number_row.append(KeyboardButton(text=str(index)))
        if len(number_row) == 5:
            keyboard.append(number_row)
            number_row = []

    if number_row:
        keyboard.append(number_row)

    keyboard.append([
        KeyboardButton(text="💰 Isi Saldo"),
        KeyboardButton(text="❓ Cara Order"),
    ])

    keyboard.append([
        KeyboardButton(text="🧾 Pesanan Saya"),
        KeyboardButton(text="💬 Hubungi Owner"),
    ])

    return ReplyKeyboardMarkup(
        keyboard=keyboard,
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder="Pilih menu atau nomor produk"
    )

def owner_menu():
    kb = InlineKeyboardBuilder()
    kb.button(text="➕ Tambah Produk", callback_data="owner:add_product")
    kb.button(text="🧩 Tambah Variasi", callback_data="owner:add_variant")
    kb.button(text="📦 Atur Stok", callback_data="owner:set_stock")
    kb.button(text="🔔 Alert Stok", callback_data="owner:low_stock")
    kb.button(text="📚 Riwayat Stok", callback_data="owner:inventory_log")
    kb.button(text="🏷️ Nama Tombol Variasi", callback_data="owner:variant_button_name")
    kb.button(text="💰 Atur Harga", callback_data="owner:set_price")
    kb.button(text="🗑️ Hapus Produk", callback_data="owner:delete_product")
    kb.button(text="🧾 Pesanan", callback_data="owner:orders")
    kb.button(text="✅ Verifikasi Bayar", callback_data="owner:complete_order")
    kb.button(text="🔥 Produk Populer", callback_data="owner:mark_popular")
    kb.button(text="⚡ Flash Sale", callback_data="owner:mark_flash")
    kb.button(text="🎁 Tambah Voucher", callback_data="owner:add_voucher")
    kb.button(text="💳 Pengaturan Pembayaran", callback_data="owner:qris_settings")
    kb.button(text="💰 Manajemen Saldo", callback_data="owner:wallet")
    kb.button(text="🩺 Cek Sistem", callback_data="owner:health")
    kb.button(text="🧪 Test Sistem", callback_data="owner:selftest")
    kb.button(text="🔧 Maintenance", callback_data="owner:maintenance")
    kb.button(text="🛡️ Anti-Fraud", callback_data="owner:security")
    kb.button(text="♻️ Recovery Order", callback_data="owner:recover_orders")
    kb.button(text="📨 Kirim Ulang Akun", callback_data="owner:resend_order")
    kb.button(text="❌ Batalkan Order", callback_data="owner:cancel_order")
    kb.button(text="🗄️ Backup Sekarang", callback_data="owner:backup_now")
    kb.button(text="📢 Sinkron Stok Channel", callback_data="owner:sync_stock")
    kb.button(text="📊 Statistik", callback_data="owner:stats")
    kb.button(text="📣 Broadcast", callback_data="owner:broadcast")
    kb.button(text="👥 Segmentasi", callback_data="owner:segments")
    kb.button(text="🎯 Promo Otomatis", callback_data="owner:auto_promo")
    kb.button(text="🎁 Paket / Bundle", callback_data="owner:bundles")
    kb.button(text="📅 Laporan Harian", callback_data="owner:daily_report")
    kb.button(text="⭐ Ulasan", callback_data="owner:reviews")
    kb.button(text="🏠 Menu User", callback_data="home")
    kb.adjust(2, 2, 2, 2, 2, 2, 2, 2, 1)
    return kb.as_markup()


def back_home():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Menu Utama", callback_data="home")]
    ])


def back_owner():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Kembali", callback_data="owner:panel")]
    ])


def owner_back_button():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Kembali", callback_data="owner:panel")]
    ])



def topup_amount_keyboard(amount: int | None = None):
    minimum = get_min_topup()
    amount = max(minimum, int(amount or minimum))

    presets = [5000, 10000, 20000, 50000, 100000, 200000]
    presets = sorted({value for value in presets if value >= minimum})

    kb = InlineKeyboardBuilder()
    for value in presets:
        prefix = "✅ " if value == amount else ""
        kb.button(
            text=f"{prefix}{rupiah(value)}",
            callback_data=f"topup:set:{value}"
        )
    kb.adjust(2)

    step = 5000
    minus_value = max(minimum, amount - step)
    plus_value = amount + step

    kb.row(
        InlineKeyboardButton(
            text="➖ Rp5.000",
            callback_data=f"topup:set:{minus_value}"
        ),
        InlineKeyboardButton(
            text=f"💰 {rupiah(amount)}",
            callback_data="noop"
        ),
        InlineKeyboardButton(
            text="➕ Rp5.000",
            callback_data=f"topup:set:{plus_value}"
        )
    )
    kb.row(
        InlineKeyboardButton(
            text="✏️ Nominal Custom",
            callback_data="topup:custom"
        )
    )
    kb.row(
        InlineKeyboardButton(
            text="✅ Lanjut Pembayaran",
            callback_data=f"topup:confirm:{amount}"
        )
    )
    kb.row(
        InlineKeyboardButton(
            text="⬅️ Saldo Kamu",
            callback_data="wallet"
        )
    )
    return kb.as_markup()


def topup_confirm_keyboard(amount: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="🟡 Buat Invoice QRIS",
                callback_data=f"topup:pay:{amount}"
            )
        ],
        [
            InlineKeyboardButton(
                text="⬅️ Ubah Nominal",
                callback_data=f"topup:set:{amount}"
            )
        ],
        [
            InlineKeyboardButton(
                text="❌ Batal",
                callback_data="wallet"
            )
        ]
    ])


def wallet_menu():
    kb = InlineKeyboardBuilder()
    kb.button(text="➕ Isi Saldo", callback_data="wallet:topup")
    kb.button(text="📑 Riwayat Saldo", callback_data="wallet:history")
    kb.button(text="🛒 Belanja", callback_data="products")
    kb.button(text="⬅️ Menu Utama", callback_data="home")
    kb.adjust(2, 1, 1)
    return kb.as_markup()


def owner_wallet_menu():
    kb = InlineKeyboardBuilder()
    kb.button(text="➕ Tambah Saldo User", callback_data="owner:wallet_add")
    kb.button(text="➖ Kurangi Saldo User", callback_data="owner:wallet_sub")
    kb.button(text="✅ Verifikasi Top Up", callback_data="owner:wallet_verify")
    kb.button(text="❌ Tolak Top Up", callback_data="owner:wallet_reject")
    kb.button(text="📑 Riwayat Saldo", callback_data="owner:wallet_history")
    kb.button(text="⚙️ Minimum Top Up", callback_data="owner:min_topup")
    kb.button(text="⬅️ Kembali", callback_data="owner:panel")
    kb.adjust(2, 2, 1, 1)
    return kb.as_markup()


def qris_settings_menu():
    enabled = get_setting("unique_code_enabled", "1") == "1"
    mode = get_setting("payment_mode", "manual")
    kb = InlineKeyboardBuilder()
    kb.button(text="🖼️ Ganti QRIS Manual", callback_data="owner:qris_set")
    kb.button(text="📝 Edit Catatan", callback_data="owner:qris_note")
    kb.button(
        text=("🔢 Kode Unik: ON" if enabled else "🔢 Kode Unik: OFF"),
        callback_data="owner:qris_toggle_unique"
    )
    kb.button(text="⚙️ Rentang Kode Unik", callback_data="owner:qris_range")
    kb.button(text="👁️ Preview QRIS", callback_data="owner:qris_preview")
    kb.button(
        text=f"⚡ Mode: {'AUTO' if mode == 'auto' else 'MANUAL'}",
        callback_data="owner:qris_toggle_mode"
    )
    kb.button(text="🔌 Status Payment Gateway", callback_data="owner:shopeepay_status")
    kb.button(text="⬅️ Kembali", callback_data="owner:panel")
    kb.adjust(2, 2, 2, 1, 1)
    return kb.as_markup()


def products_keyboard(filter_sql=""):
    conn = db()
    rows = conn.execute(
        f"SELECT * FROM products WHERE active=1 {filter_sql} ORDER BY id"
    ).fetchall()
    conn.close()

    kb = InlineKeyboardBuilder()
    for row in rows:
        kb.button(text=row["name"], callback_data=f"product:{row['id']}")
    kb.adjust(2)
    kb.row(
        InlineKeyboardButton(text="🔎 Cari", callback_data="shop:search"),
        InlineKeyboardButton(text="🛒 Keranjang", callback_data="shop:cart"),
        InlineKeyboardButton(text="⭐ Favorit", callback_data="shop:favorites")
    )
    kb.row(InlineKeyboardButton(text="🎁 Paket Hemat", callback_data="shop:bundles"))
    kb.row(InlineKeyboardButton(text="⬅️ Menu Utama", callback_data="home"))
    return kb.as_markup()


def variants_keyboard(product_id):
    conn = db()
    rows = conn.execute(
        """SELECT * FROM product_variants
           WHERE product_id=? AND active=1 ORDER BY id""",
        (product_id,)
    ).fetchall()
    conn.close()

    kb = InlineKeyboardBuilder()
    for row in rows:
        label = f"{row['name']} ({available_stock(row)})"
        kb.button(text=label, callback_data=f"variant:{row['id']}")
    kb.adjust(1)
    kb.row(InlineKeyboardButton(text="⬅️ Kembali", callback_data="products"))
    return kb.as_markup()


def qty_keyboard(variant_id, qty):
    conn = db()
    variant = conn.execute(
        "SELECT * FROM product_variants WHERE id=?",
        (variant_id,)
    ).fetchone()
    conn.close()

    stock = available_stock(variant) if variant else 0
    stock = max(0, stock)
    qty = max(1, min(qty, stock if stock > 0 else 1))

    kb = InlineKeyboardBuilder()

    # Quick stock/quantity buttons.
    # Show up to 20 direct choices; if stock is higher, add MAX.
    quick_max = min(stock, 20)
    for number in range(1, quick_max + 1):
        prefix = "✅ " if number == qty else ""
        kb.button(
            text=f"{prefix}{number}",
            callback_data=f"qty:{variant_id}:{number}"
        )

    if quick_max > 0:
        kb.adjust(5)

    if stock > 20:
        kb.row(
            InlineKeyboardButton(
                text=f"📦 MAX {stock}",
                callback_data=f"qty:{variant_id}:{stock}"
            )
        )

    # Fine adjustment.
    kb.row(
        InlineKeyboardButton(
            text="➖",
            callback_data=f"qty:{variant_id}:{max(1, qty-1)}"
        ),
        InlineKeyboardButton(
            text=f"Jumlah: {qty}",
            callback_data="noop"
        ),
        InlineKeyboardButton(
            text="➕",
            callback_data=f"qty:{variant_id}:{min(stock, qty+1) if stock else qty}"
        )
    )

    if stock > 0:
        kb.row(
            InlineKeyboardButton(
                text="🛒 Lanjut Beli",
                callback_data=f"confirm:{variant_id}:{qty}"
            )
        )
    else:
        kb.row(
            InlineKeyboardButton(
                text="🔔 Notif Restock",
                callback_data=f"restock:{variant_id}"
            )
        )

    kb.row(
        InlineKeyboardButton(
            text="⬅️ Kembali",
            callback_data=f"back_product:{variant_id}"
        )
    )
    return kb.as_markup()


# =========================
# RENDER HELPERS
# =========================
def product_card(product):
    rating = (
        f"{product['rating']:.1f}/5 ({product['rating_count']} ulasan)"
        if product["rating_count"] > 0 else "Belum ada ulasan"
    )
    return (
        "┌────────────────────\n"
        f"• Produk : <b>{product['name']}</b>\n"
        f"• Stok Terjual : <b>{product['sold']}</b>\n"
        f"• Rating : <b>{rating}</b>\n"
        f"• Desk : {product['description'] or '-'}\n"
        "└────────────────────\n\n"
        f"<i>{STORE_FOOTER}</i>"
    )


def variant_card(product, variant, qty=1):
    unit = effective_unit_price(variant, qty)
    total = unit * qty
    grossir = []
    if variant["wholesale10"] > 0:
        grossir.append(f"• Min 10 : {rupiah(variant['wholesale10'])}")
    if variant["wholesale20"] > 0:
        grossir.append(f"• Min 20 : {rupiah(variant['wholesale20'])}")
    grossir_text = "\n".join(grossir) if grossir else "• Belum ada harga grosir"

    return (
        "┌────────────────────\n"
        f"• Produk : <b>{product['name']}</b>\n"
        f"• Variasi : <b>{variant['name']}</b>\n"
        f"• Kode : <code>{variant['code'] or '-'}</code>\n"
        f"• Sisa Produk : <b>{available_stock(variant)}</b>\n"
        f"• Desk : {product['description'] or '-'}\n"
        "└────────────────────\n\n"
        "┌────────────────────\n"
        f"• Jumlah : <b>{qty}</b>\n"
        f"• Harga/unit : <b>{rupiah(unit)}</b>\n"
        f"• Total Harga : <b>{rupiah(total)}</b>\n"
        "└────────────────────\n\n"
        "┌─ [ 🏷️ Harga Grosir ]\n"
        f"{grossir_text}\n"
        "└────────────────────\n\n"
        f"<i>{STORE_FOOTER}</i>"
    )


# =========================
# PUBLIC COMMANDS (ONLY 3)
# =========================
@router.message(Command("start"))
async def start(message: Message, bot: Bot):
    if not await is_channel_member(bot, message.from_user.id):
        return await send_join_required(message)

    mark_user_verified(
        message.from_user.id,
        message.from_user.username or ""
    )
    await show_main_menu_message(message)



@router.callback_query(F.data == "shop:search")
async def shop_search_start(call: CallbackQuery, state: FSMContext):
    await state.set_state(ShopToolsState.search_product)
    await call.message.edit_text(
        "🔎 <b>CARI PRODUK</b>\n\nKirim nama atau kata kunci produk.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Kembali", callback_data="products")]
        ]),
        parse_mode="HTML"
    )
    await call.answer()


@router.message(ShopToolsState.search_product)
async def shop_search_input(message: Message, state: FSMContext):
    query = (message.text or "").strip()
    if not query:
        return await message.answer("❌ Kata kunci kosong.")

    conn = db()
    rows = conn.execute(
        """SELECT * FROM products
           WHERE active=1 AND lower(name) LIKE lower(?)
           ORDER BY sold DESC, id
           LIMIT 20""",
        (f"%{query}%",)
    ).fetchall()
    conn.close()
    await state.clear()

    kb = InlineKeyboardBuilder()
    for row in rows:
        kb.button(text=row["name"], callback_data=f"product:{row['id']}")
    kb.button(text="⬅️ List Produk", callback_data="products")
    kb.adjust(1)

    await message.answer(
        "🔎 <b>HASIL PENCARIAN</b>\n\n"
        + (f"Ditemukan <b>{len(rows)}</b> produk." if rows else "Produk tidak ditemukan."),
        reply_markup=kb.as_markup(),
        parse_mode="HTML"
    )


@router.callback_query(F.data.startswith("cartadd:"))
async def cart_add(call: CallbackQuery):
    _, variant_id, qty = call.data.split(":")
    variant_id, qty = int(variant_id), max(1, int(qty))

    conn = db()
    variant = conn.execute("SELECT * FROM product_variants WHERE id=? AND active=1",(variant_id,)).fetchone()
    if not variant:
        conn.close()
        return await call.answer("Variasi tidak tersedia.", show_alert=True)

    qty = min(qty, max(1, available_stock(variant)))
    conn.execute(
        """INSERT INTO cart_items(user_id,variant_id,qty,created_at)
           VALUES(?,?,?,?)
           ON CONFLICT(user_id,variant_id) DO UPDATE SET
             qty=excluded.qty, created_at=excluded.created_at""",
        (call.from_user.id, variant_id, qty, datetime.now().isoformat(timespec="seconds"))
    )
    conn.commit()
    conn.close()
    await call.answer("Disimpan ke keranjang.", show_alert=True)


@router.callback_query(F.data == "shop:cart")
async def shop_cart(call: CallbackQuery):
    conn = db()
    rows = conn.execute(
        """SELECT c.*, v.name AS variant_name, v.price, v.stock, v.reserved_stock,
                  p.name AS product_name
           FROM cart_items c
           JOIN product_variants v ON v.id=c.variant_id
           JOIN products p ON p.id=v.product_id
           WHERE c.user_id=? AND p.active=1 AND v.active=1
           ORDER BY c.id DESC""",
        (call.from_user.id,)
    ).fetchall()
    conn.close()

    lines=["🛒 <b>KERANJANG</b>",""]
    kb=InlineKeyboardBuilder()
    if not rows:
        lines.append("Keranjang masih kosong.")
    else:
        for row in rows:
            lines.append(
                f"• {html.escape(row['product_name'])} — {html.escape(row['variant_name'])} × {row['qty']}"
            )
            kb.button(
                text=f"🛒 Beli {row['product_name']} ({row['qty']})",
                callback_data=f"confirm:{row['variant_id']}:{row['qty']}"
            )
            kb.button(text="🗑️", callback_data=f"cartremove:{row['variant_id']}")
    if rows:
        kb.button(text="💰 Checkout Semua dengan Saldo", callback_data="cartcheckout:wallet")
    kb.button(text="🔁 Beli Lagi Order Terakhir", callback_data="repeat:last")
    kb.button(text="🧾 Detail Invoice Terakhir", callback_data="invoice:last")
    kb.button(text="⬅️ List Produk", callback_data="products")
    kb.adjust(1)

    await call.message.edit_text(
        "\n".join(lines)+"\n\n<i>Checkout tetap memakai alur order biasa.</i>",
        reply_markup=kb.as_markup(),
        parse_mode="HTML"
    )
    await call.answer()


@router.callback_query(F.data.startswith("cartremove:"))
async def cart_remove(call: CallbackQuery):
    variant_id=int(call.data.split(":")[1])
    conn=db()
    conn.execute("DELETE FROM cart_items WHERE user_id=? AND variant_id=?",(call.from_user.id,variant_id))
    conn.commit(); conn.close()
    await call.answer("Dihapus dari keranjang.")
    await shop_cart(call)


@router.callback_query(F.data.startswith("favadd:"))
async def favorite_add(call: CallbackQuery):
    variant_id=int(call.data.split(":")[1])
    conn=db()
    variant=conn.execute("SELECT product_id FROM product_variants WHERE id=?",(variant_id,)).fetchone()
    if not variant:
        conn.close()
        return await call.answer("Produk tidak ditemukan.",show_alert=True)
    conn.execute(
        """INSERT OR IGNORE INTO favorites(user_id,product_id,created_at)
           VALUES(?,?,?)""",
        (call.from_user.id,variant["product_id"],datetime.now().isoformat(timespec="seconds"))
    )
    conn.commit(); conn.close()
    await call.answer("Produk ditambahkan ke favorit.",show_alert=True)


@router.callback_query(F.data == "shop:favorites")
async def shop_favorites(call: CallbackQuery):
    conn=db()
    rows=conn.execute(
        """SELECT p.* FROM favorites f
           JOIN products p ON p.id=f.product_id
           WHERE f.user_id=? AND p.active=1
           ORDER BY f.id DESC LIMIT 20""",
        (call.from_user.id,)
    ).fetchall()
    conn.close()

    kb=InlineKeyboardBuilder()
    for row in rows:
        kb.button(text=f"⭐ {row['name']}",callback_data=f"product:{row['id']}")
    kb.button(text="⬅️ List Produk",callback_data="products")
    kb.adjust(1)
    await call.message.edit_text(
        "⭐ <b>PRODUK FAVORIT</b>\n\n"+(f"{len(rows)} produk tersimpan." if rows else "Belum ada favorit."),
        reply_markup=kb.as_markup(),
        parse_mode="HTML"
    )
    await call.answer()



@router.callback_query(F.data == "cartcheckout:wallet")
async def cart_checkout_wallet(call: CallbackQuery, bot: Bot):
    if maintenance_enabled() and not is_owner(call.from_user.id):
        return await call.answer("Toko sedang maintenance.", show_alert=True)

    async with purchase_lock(call.from_user.id):
        conn=db()
        conn.execute("BEGIN IMMEDIATE")
        rows=conn.execute(
            """SELECT c.id AS cart_id, c.user_id, c.variant_id, c.qty, c.created_at AS cart_created_at,
                  v.id AS vid, v.product_id, v.name AS variant_name, v.code, v.price,
                  v.stock, v.wholesale10, v.wholesale20, v.active, v.reserved_stock,
                  v.button_label, p.id AS pid, p.name AS product_name,
                  p.active AS product_active
               FROM cart_items c
               JOIN product_variants v ON v.id=c.variant_id
               JOIN products p ON p.id=v.product_id
               WHERE c.user_id=? AND p.active=1 AND v.active=1
               ORDER BY c.id""",
            (call.from_user.id,)
        ).fetchall()

        if not rows:
            conn.rollback(); conn.close()
            return await call.answer("Keranjang kosong.",show_alert=True)

        total_all=0
        prepared=[]
        for row in rows:
            qty=max(1,int(row["qty"]))
            if available_stock(row) < qty:
                conn.rollback(); conn.close()
                return await call.answer(
                    f"Stok {row['product_name']} tidak mencukupi.",
                    show_alert=True
                )
            unit=effective_unit_price(row,qty)
            subtotal=unit*qty
            total_all+=subtotal
            prepared.append((row,qty,unit,subtotal))

        wallet=conn.execute("SELECT balance FROM wallets WHERE user_id=?",(call.from_user.id,)).fetchone()
        balance=int(wallet["balance"] or 0) if wallet else 0
        if balance < total_all:
            conn.rollback(); conn.close()
            return await call.answer(
                f"Saldo tidak cukup. Dibutuhkan {rupiah(total_all)}.",
                show_alert=True
            )

        order_ids=[]
        now=datetime.now().isoformat(timespec="seconds")
        for row,qty,unit,subtotal in prepared:
            if not reserve_stock_for_order(conn,row["vid"],qty):
                conn.rollback(); conn.close()
                return await call.answer("Stok berubah. Silakan coba lagi.",show_alert=True)

            cur=conn.execute(
                """INSERT INTO orders
                   (user_id,username,product_id,variant_id,qty,unit_price,total,status,
                    payment_method,payment_status,note,unique_code,payment_total,
                    stock_reserved,reserved_until,fulfillment_status,created_at,
                    voucher_code,discount_amount)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    call.from_user.id,call.from_user.username or "",row["pid"],row["vid"],
                    qty,unit,subtotal,"paid_pending_delivery","WALLET","paid","",
                    0,subtotal,1,"","pending",now,"",0
                )
            )
            order_ids.append(cur.lastrowid)

        new_balance=balance-total_all
        conn.execute(
            """INSERT INTO wallets(user_id,balance,updated_at)
               VALUES(?,?,?)
               ON CONFLICT(user_id) DO UPDATE SET balance=excluded.balance, updated_at=excluded.updated_at""",
            (call.from_user.id,new_balance,now)
        )
        group_ref=f"CART-{int(time.time())}"
        conn.execute(
            """INSERT INTO wallet_ledger(user_id,type,amount,balance_after,reference,note,created_at)
               VALUES(?,?,?,?,?,?,?)""",
            (call.from_user.id,"PURCHASE",-total_all,new_balance,group_ref,
             f"Checkout keranjang {len(order_ids)} item",now)
        )
        conn.execute("DELETE FROM cart_items WHERE user_id=?",(call.from_user.id,))
        conn.commit(); conn.close()

    delivered=0
    for oid in order_ids:
        if await fulfill_order(oid,bot):
            delivered+=1

    await call.message.edit_text(
        "✅ <b>CHECKOUT KERANJANG SELESAI</b>\n\n"
        f"🧾 Invoice dibuat: <b>{len(order_ids)}</b>\n"
        f"📦 Berhasil dikirim: <b>{delivered}</b>\n"
        f"💰 Total: <b>{rupiah(total_all)}</b>\n"
        f"💵 Sisa saldo: <b>{rupiah(new_balance)}</b>\n\n"
        "Setiap produk tetap memiliki invoice sendiri sehingga recovery dan pengiriman akun tetap aman.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🏠 Menu Utama",callback_data="home")]
        ]),
        parse_mode="HTML"
    )
    await call.answer("Checkout keranjang berhasil.")


@router.callback_query(F.data == "repeat:last")
async def repeat_last_order(call: CallbackQuery):
    conn=db()
    row=conn.execute(
        """SELECT * FROM orders
           WHERE user_id=? AND status='completed'
           ORDER BY id DESC LIMIT 1""",
        (call.from_user.id,)
    ).fetchone()
    if not row:
        conn.close()
        return await call.answer("Belum ada order selesai untuk dibeli lagi.",show_alert=True)
    variant=conn.execute("SELECT * FROM product_variants WHERE id=? AND active=1",(row["variant_id"],)).fetchone()
    conn.close()
    if not variant or available_stock(variant) < int(row["qty"]):
        return await call.answer("Produk terakhir sedang tidak tersedia.",show_alert=True)

    await call.message.edit_text(
        "🔁 <b>BELI LAGI</b>\n\n"
        f"Invoice sebelumnya: <b>{invoice(row['id'])}</b>\n"
        f"Qty: <b>{row['qty']}</b>\n\n"
        "Lanjut menggunakan alur order biasa:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="🛒 Lanjut",
                callback_data=f"confirm:{row['variant_id']}:{row['qty']}"
            )],
            [InlineKeyboardButton(text="⬅️ Kembali",callback_data="shop:cart")]
        ]),
        parse_mode="HTML"
    )
    await call.answer()


@router.callback_query(F.data == "invoice:last")
async def last_invoice_detail(call: CallbackQuery):
    conn=db()
    row=conn.execute(
        "SELECT * FROM orders WHERE user_id=? ORDER BY id DESC LIMIT 1",
        (call.from_user.id,)
    ).fetchone()
    conn.close()
    if not row:
        return await call.answer("Belum ada invoice.",show_alert=True)

    await call.message.edit_text(
        professional_invoice_for_order(row["id"]),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Kembali",callback_data="shop:cart")]
        ]),
        parse_mode="HTML"
    )
    await call.answer()


@router.callback_query(F.data == "shop:bundles")
async def shop_bundles(call: CallbackQuery):
    conn=db()
    rows=conn.execute(
        """SELECT b.*, p1.name AS name_a, p2.name AS name_b
           FROM bundle_offers b
           JOIN products p1 ON p1.id=b.product_a
           JOIN products p2 ON p2.id=b.product_b
           WHERE b.active=1 AND p1.active=1 AND p2.active=1
           ORDER BY b.id DESC LIMIT 20"""
    ).fetchall()
    conn.close()

    kb=InlineKeyboardBuilder()
    lines=["🎁 <b>PAKET HEMAT</b>",""]
    if not rows:
        lines.append("Belum ada paket aktif.")
    else:
        for row in rows:
            lines.append(f"• <b>{html.escape(row['name'])}</b>\n  {html.escape(row['name_a'])} + {html.escape(row['name_b'])}")
            kb.button(text=f"🛒 {row['name']}",callback_data=f"bundleadd:{row['id']}")
    kb.button(text="⬅️ List Produk",callback_data="products")
    kb.adjust(1)
    await call.message.edit_text("\n".join(lines),reply_markup=kb.as_markup(),parse_mode="HTML")
    await call.answer()


@router.callback_query(F.data.startswith("bundleadd:"))
async def bundle_add_cart(call: CallbackQuery):
    bundle_id=int(call.data.split(":")[1])
    conn=db()
    bundle=conn.execute("SELECT * FROM bundle_offers WHERE id=? AND active=1",(bundle_id,)).fetchone()
    if not bundle:
        conn.close()
        return await call.answer("Paket tidak tersedia.",show_alert=True)

    added=0
    for pid in (bundle["product_a"],bundle["product_b"]):
        variant=conn.execute(
            """SELECT * FROM product_variants
               WHERE product_id=? AND active=1
               ORDER BY id LIMIT 1""",
            (pid,)
        ).fetchone()
        if variant and available_stock(variant)>0:
            conn.execute(
                """INSERT INTO cart_items(user_id,variant_id,qty,created_at)
                   VALUES(?,?,1,?)
                   ON CONFLICT(user_id,variant_id) DO UPDATE SET qty=1,created_at=excluded.created_at""",
                (call.from_user.id,variant["id"],datetime.now().isoformat(timespec="seconds"))
            )
            added+=1
    conn.commit(); conn.close()
    await call.answer(f"{added} produk paket masuk keranjang.",show_alert=True)


@router.message(Command("owner"))
async def owner(message: Message, state: FSMContext):
    await state.clear()
    if not is_owner(message.from_user.id):
        return await message.answer("⛔ Panel owner hanya dapat diakses pemilik bot.")

    await message.answer(
        f"🛠️ <b>PANEL OWNER • {STORE_NAME}</b>\n\n"
        "Semua pengaturan toko ada di tombol berikut.\n\n"
        f"<i>{STORE_FOOTER}</i>",
        reply_markup=owner_menu(),
        parse_mode="HTML"
    )



@router.callback_query(F.data == "owner:panel")
async def owner_panel_callback(call: CallbackQuery, state: FSMContext):
    if not is_owner(call.from_user.id):
        return await call.answer("Akses ditolak.", show_alert=True)

    await state.clear()
    text = (
        f"🛠️ <b>PANEL OWNER • {STORE_NAME}</b>\n\n"
        "Semua pengaturan toko ada di tombol berikut.\n\n"
        f"<i>{STORE_FOOTER}</i>"
    )

    try:
        await call.message.edit_text(
            text,
            reply_markup=owner_menu(),
            parse_mode="HTML"
        )
    except Exception:
        # Handles cases where current message is a photo/document/caption and can't be edit_text'ed.
        try:
            await call.message.delete()
        except Exception:
            pass
        await call.message.answer(
            text,
            reply_markup=owner_menu(),
            parse_mode="HTML"
        )
    await call.answer()

@router.message(Command("ping"))
async def ping(message: Message):
    started = time.perf_counter()
    sent = await message.answer("🏓 Mengecek bot...")
    latency = int((time.perf_counter() - started) * 1000)
    uptime = int(time.time() - START_TIME)
    h, rem = divmod(uptime, 3600)
    m, s = divmod(rem, 60)

    await sent.edit_text(
        "🏓 <b>PONG!</b>\n\n"
        f"⚡ Response: <b>{latency} ms</b>\n"
        "🟢 Status: <b>Online</b>\n"
        f"⏱️ Uptime: <b>{h}j {m}m {s}d</b>\n\n"
        f"<i>{STORE_FOOTER}</i>",
        parse_mode="HTML"
    )


# =========================
# USER FLOW
# =========================

@router.callback_query(F.data == "verify_join")
async def verify_join(call: CallbackQuery, bot: Bot):
    if await is_channel_member(bot, call.from_user.id):
        mark_user_verified(
            call.from_user.id,
            call.from_user.username or ""
        )
        await call.answer("✅ Terverifikasi!", show_alert=True)
        await call.message.edit_text(
            f"🛍️ <b>{STORE_NAME}</b>\n\n"
            "✅ Verifikasi berhasil.\n"
            "Silakan pilih menu:\n\n"
            f"<i>{STORE_FOOTER}</i>",
            reply_markup=main_menu(),
            parse_mode="HTML"
        )
    else:
        await call.answer(
            "❌ Belum terdeteksi join channel. Silakan join lalu coba lagi.",
            show_alert=True
        )


@router.callback_query(F.data == "noop")
async def noop(call: CallbackQuery):
    await call.answer()


@router.callback_query(F.data == "home")
async def cb_home(call: CallbackQuery, state: FSMContext, bot: Bot):
    await state.clear()

    if not await is_channel_member(bot, call.from_user.id):
        await safe_edit_or_answer(call, 
            "🔐 <b>VERIFIKASI CHANNEL</b>\n\n"
            f"Silakan join <b>{REQUIRED_CHANNEL_NAME}</b> terlebih dahulu.",
            reply_markup=join_required_keyboard(),
            parse_mode="HTML"
        )
        return await call.answer()

    mark_user_verified(
        call.from_user.id,
        call.from_user.username or ""
    )

    await call.message.edit_text(
        f"🛍️ <b>{STORE_NAME}</b>\n\n"
        "Selamat datang.\n"
        "Silakan pilih menu:\n\n"
        f"<i>{STORE_FOOTER}</i>",
        reply_markup=main_menu(),
        parse_mode="HTML"
    )
    await call.answer()


async def show_product_list(call, title, filter_sql=""):
    conn = db()
    rows = conn.execute(
        f"SELECT * FROM products WHERE active=1 {filter_sql} ORDER BY id"
    ).fetchall()
    conn.close()

    if not rows:
        text = f"{title}\n\nBelum ada produk.\n\n<i>{STORE_FOOTER}</i>"
    else:
        lines = [title, ""]
        for i, row in enumerate(rows, 1):
            lines.append(f"[{i}] {row['name']}")
        lines.append(f"\nPilih produk di bawah.\n\n<i>{STORE_FOOTER}</i>")
        text = "\n".join(lines)

    await safe_edit_or_answer(
        call,
        text,
        reply_markup=products_keyboard(filter_sql),
        parse_mode="HTML"
    )
    await call.answer()


@router.callback_query(F.data == "products")
async def products(call: CallbackQuery):
    await show_product_list(call, "🏷️ <b>LIST PRODUK</b>")


@router.callback_query(F.data == "popular")
async def popular(call: CallbackQuery):
    await show_product_list(call, "🔥 <b>PRODUK POPULER</b>", "AND is_popular=1")


@router.callback_query(F.data == "flash")
async def flash(call: CallbackQuery):
    await show_product_list(call, "⚡ <b>FLASH SALE</b>", "AND is_flash_sale=1")


@router.callback_query(F.data.startswith("product:"))
async def product_detail(call: CallbackQuery):
    try:
        product_id = int(call.data.split(":")[1])
    except Exception:
        return await call.answer("Produk tidak valid.", show_alert=True)

    conn = db()
    product = conn.execute(
        "SELECT * FROM products WHERE id=? AND active=1",
        (product_id,)
    ).fetchone()

    variants = conn.execute(
        """SELECT *
           FROM product_variants
           WHERE product_id=? AND active=1
           ORDER BY id""",
        (product_id,)
    ).fetchall()
    conn.close()

    if not product:
        return await call.answer("Produk tidak ditemukan / sudah tidak aktif.", show_alert=True)

    sold = int(product["sold"] or 0)

    text = (
        "╭────────────────────╮\n"
        f"• <b>Produk:</b> {html.escape(product['name'])}\n"
        f"• <b>Terjual:</b> {sold}\n"
        f"• ⭐ <b>Rating:</b> {float(product['rating'] or 0):.1f}/5 ({int(product['rating_count'] or 0)} ulasan)\n"
        f"• <b>Deskripsi:</b> {html.escape(product['description'] or '-')}\n"
        "╰────────────────────╯\n\n"
        "╭────────────────────╮\n"
        "📦 <b>VARIASI • HARGA • STOK</b>\n"
    )

    if variants:
        for index, variant in enumerate(variants, start=1):
            stock = available_stock(variant)
            stock_icon = "✅" if stock > 0 else "❌"
            text += (
                f"\n{index}. <b>{html.escape(variant['name'])}</b>\n"
                f"   💰 Harga: <b>{rupiah(variant['price'])}</b>\n"
                f"   {stock_icon} Stok: <b>{stock}</b>\n"
            )
    else:
        text += "\n<i>Belum ada variasi aktif.</i>\n"

    text += (
        "\n╰────────────────────╯\n\n"
        f"<i>{STORE_FOOTER}</i>\n\n"
        "Pilih variasi:"
    )

    kb = InlineKeyboardBuilder()

    for variant in variants:
        stock = available_stock(variant)
        if stock > 0:
            button_text = (
                f"{variant_button_label(variant)} ({stock})"
            )
        else:
            button_text = (
                f"{variant_button_label(variant)} (0)"
            )

        kb.button(
            text=button_text,
            callback_data=f"variant:{variant['id']}"
        )

    kb.button(text="⬅️ Kembali", callback_data="products")
    kb.adjust(1)

    await safe_edit_or_answer(
        call,
        text,
        reply_markup=kb.as_markup(),
        parse_mode="HTML"
    )
    await call.answer()

@router.callback_query(F.data.startswith("back_product:"))
async def back_product(call: CallbackQuery):
    variant_id = int(call.data.split(":")[1])
    conn = db()
    variant = conn.execute("SELECT * FROM product_variants WHERE id=?", (variant_id,)).fetchone()
    product = conn.execute("SELECT * FROM products WHERE id=?", (variant["product_id"],)).fetchone() if variant else None
    conn.close()
    if not product:
        return await call.answer("Produk tidak ditemukan.", show_alert=True)

    await safe_edit_or_answer(
        call,
        product_card(product) + "\n\nPilih variasi:",
        reply_markup=variants_keyboard(product["id"]),
        parse_mode="HTML"
    )
    await call.answer()


@router.callback_query(F.data.startswith("variant:"))
async def variant_detail(call: CallbackQuery):
    variant_id = int(call.data.split(":")[1])
    conn = db()
    variant = conn.execute("SELECT * FROM product_variants WHERE id=?", (variant_id,)).fetchone()
    product = conn.execute("SELECT * FROM products WHERE id=?", (variant["product_id"],)).fetchone() if variant else None
    conn.close()

    if not variant or not product:
        return await call.answer("Variasi tidak ditemukan.", show_alert=True)

    await safe_edit_or_answer(
        call,
        variant_card(product, variant, 1),
        reply_markup=qty_keyboard(variant_id, 1),
        parse_mode="HTML"
    )
    await call.answer()


@router.callback_query(F.data.startswith("qty:"))
async def change_qty(call: CallbackQuery):
    _, variant_id, qty = call.data.split(":")
    variant_id, qty = int(variant_id), max(1, int(qty))

    conn = db()
    variant = conn.execute("SELECT * FROM product_variants WHERE id=?", (variant_id,)).fetchone()
    product = conn.execute("SELECT * FROM products WHERE id=?", (variant["product_id"],)).fetchone() if variant else None
    conn.close()

    if not variant or not product:
        return await call.answer("Variasi tidak ditemukan.", show_alert=True)

    current_available = available_stock(variant)
    if current_available > 0 and qty > current_available:
        qty = current_available
        await call.answer("Jumlah disesuaikan dengan stok tersedia.", show_alert=True)
    else:
        await call.answer()

    await call.message.edit_text(
        variant_card(product, variant, qty),
        reply_markup=qty_keyboard(variant_id, qty),
        parse_mode="HTML"
    )


@router.callback_query(F.data.startswith("restock:"))
async def restock(call: CallbackQuery):
    variant_id = int(call.data.split(":")[1])
    conn = db()
    variant = conn.execute("SELECT * FROM product_variants WHERE id=?", (variant_id,)).fetchone()
    if not variant:
        conn.close()
        return await call.answer("Variasi tidak ditemukan.", show_alert=True)

    try:
        conn.execute(
            """INSERT OR IGNORE INTO restock_subscriptions
               (user_id, product_id, variant_id, created_at)
               VALUES(?,?,?,?)""",
            (call.from_user.id, variant["product_id"], variant_id, datetime.now().isoformat(timespec="seconds"))
        )
        conn.commit()
    finally:
        conn.close()

    await call.answer("🔔 Notifikasi restock diaktifkan.", show_alert=True)


@router.callback_query(F.data.startswith("confirm:"))
async def confirm_order(call: CallbackQuery, state: FSMContext):
    _, variant_id, qty = call.data.split(":")
    variant_id, qty = int(variant_id), max(1, int(qty))

    conn = db()
    variant = conn.execute(
        "SELECT * FROM product_variants WHERE id=? AND active=1",
        (variant_id,)
    ).fetchone()
    product = conn.execute(
        "SELECT * FROM products WHERE id=? AND active=1",
        (variant["product_id"],)
    ).fetchone() if variant else None
    conn.close()

    if not variant or not product:
        return await call.answer("Produk tidak tersedia.", show_alert=True)

    if available_stock(variant) < qty:
        return await call.answer("Stok tidak mencukupi.", show_alert=True)

    unit = effective_unit_price(variant, qty)
    total = unit * qty

    await state.update_data(
        checkout_variant_id=variant_id,
        checkout_qty=qty,
        checkout_note=""
    )

    await call.message.edit_text(
        "🧾 <b>KONFIRMASI PESANAN</b>\n\n"
        f"📦 Produk: <b>{product['name']}</b>\n"
        f"🧩 Variasi: <b>{variant['name']}</b>\n"
        f"🔢 Jumlah: <b>{qty}</b>\n"
        f"💰 Harga/unit: <b>{rupiah(unit)}</b>\n"
        f"💵 Total: <b>{rupiah(total)}</b>\n\n"
        "Sebelum lanjut ke pembayaran, Anda bisa menambahkan catatan untuk pesanan ini.\n"
        "Contoh: email tujuan, nama profil, request tertentu, atau informasi lain yang dibutuhkan.",
        reply_markup=checkout_note_keyboard(variant_id, qty),
        parse_mode="HTML"
    )
    await call.answer()


@router.callback_query(F.data.startswith("checkoutnote:add:"))
async def checkout_note_add(call: CallbackQuery, state: FSMContext):
    _, _, variant_id, qty = call.data.split(":")
    variant_id, qty = int(variant_id), max(1, int(qty))

    await state.update_data(
        checkout_variant_id=variant_id,
        checkout_qty=qty
    )
    await state.set_state(CheckoutState.waiting_note)

    await call.message.edit_text(
        "📝 <b>ISI CATATAN PESANAN</b>\n\n"
        "Kirim catatan yang ingin disertakan pada pesanan.\n\n"
        "Contoh:\n"
        "<code>Email tujuan: nama@email.com\n"
        "Profil: Anak\n"
        "Catatan: jangan ubah password</code>\n\n"
        "Maksimal 500 karakter.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="⬅️ Kembali",
                    callback_data=f"confirm:{variant_id}:{qty}"
                )
            ]
        ]),
        parse_mode="HTML"
    )
    await call.answer()


@router.message(CheckoutState.waiting_note)
async def checkout_note_input(message: Message, state: FSMContext):
    data = await state.get_data()
    variant_id = int(data.get("checkout_variant_id", 0))
    qty = int(data.get("checkout_qty", 1))

    note = (message.text or "").strip()
    if not note:
        return await message.answer("❌ Catatan tidak boleh kosong. Kirim teks catatan.")

    if len(note) > 500:
        return await message.answer(
            f"❌ Catatan terlalu panjang ({len(note)} karakter). Maksimal 500 karakter."
        )

    await state.update_data(checkout_note=note)
    await state.set_state(None)

    await message.answer(
        "✅ <b>CATATAN DISIMPAN</b>\n\n"
        f"<blockquote>{html.escape(note)}</blockquote>\n\n"
        "Silakan pilih metode pembayaran:",
        reply_markup=payment_method_keyboard(variant_id, qty),
        parse_mode="HTML"
    )


@router.callback_query(F.data.startswith("checkoutnote:skip:"))
async def checkout_note_skip(call: CallbackQuery, state: FSMContext):
    _, _, variant_id, qty = call.data.split(":")
    variant_id, qty = int(variant_id), max(1, int(qty))

    await state.update_data(
        checkout_variant_id=variant_id,
        checkout_qty=qty,
        checkout_note=""
    )
    await state.set_state(None)

    await call.message.edit_text(
        "💳 <b>PILIH METODE PEMBAYARAN</b>\n\n"
        "Catatan pesanan dilewati.\n\n"
        "Silakan pilih metode pembayaran:",
        reply_markup=payment_method_keyboard(variant_id, qty),
        parse_mode="HTML"
    )
    await call.answer()

@router.callback_query(F.data.startswith("payselect:"))
async def payment_select(call: CallbackQuery):
    _, variant_id, qty = call.data.split(":")
    variant_id, qty = int(variant_id), max(1, int(qty))

    mode = get_setting("payment_mode", "manual")
    auto_ready = shopeepay_ready()

    kb = InlineKeyboardBuilder()

    balance = get_balance(call.from_user.id)
    kb.button(
        text=f"💰 Saldo Kamu ({rupiah(balance)})",
        callback_data=f"paywallet:{variant_id}:{qty}"
    )

    # Manual is always available as fallback
    kb.button(
        text="🟡 QRIS Pribadi + Kode Unik",
        callback_data=f"process:{variant_id}:{qty}"
    )

    # Auto only appears when enabled + credentials complete
    if auto_ready:
        kb.button(
            text="⚡ QRIS Otomatis",
            callback_data=f"processauto:{variant_id}:{qty}"
        )

    kb.button(text="⬅️ Kembali", callback_data=f"variant:{variant_id}")
    kb.adjust(1)

    auto_status = "✅ Siap" if auto_ready else "⚪ Belum dikonfigurasi"
    preferred = "Payment Gateway Otomatis" if mode == "auto" else "QRIS Manual"

    await call.message.edit_text(
        "💳 <b>PILIH METODE PEMBAYARAN</b>\n\n"
        f"🟡 QRIS pribadi: <b>Aktif</b>\n"
        f"⚡ Payment Gateway otomatis: <b>{auto_status}</b>\n"
        f"⭐ Mode utama owner: <b>{preferred}</b>\n\n"
        "Jika Payment Gateway otomatis belum siap, pembayaran manual tetap dapat digunakan.",
        reply_markup=kb.as_markup(),
        parse_mode="HTML"
    )
    await call.answer()



@router.callback_query(F.data.startswith("paywallet:"))
async def process_wallet_order(call: CallbackQuery, bot: Bot, state: FSMContext):
    if maintenance_enabled() and not is_owner(call.from_user.id):
        return await call.answer("Toko sedang maintenance. Silakan coba kembali nanti.", show_alert=True)
    async with purchase_lock(call.from_user.id):
        _, variant_id, qty = call.data.split(":")
        variant_id, qty = int(variant_id), max(1, int(qty))

        allowed, reason = anti_abuse_checkout(call.from_user.id, "WALLET")
        if not allowed:
            return await call.answer(reason, show_alert=True)

        checkout_data = await state.get_data()
        checkout_note = get_checkout_note_from_state(checkout_data)

        conn = db()
        conn.execute("BEGIN IMMEDIATE")

        duplicate = recent_duplicate_checkout(
            conn, call.from_user.id, variant_id, qty, "WALLET"
        )
        if duplicate:
            conn.rollback()
            conn.close()
            return await call.answer(
                "Pesanan yang sama baru saja diproses. Cek Pesanan Saya.",
                show_alert=True
            )

        variant = conn.execute(
            "SELECT * FROM product_variants WHERE id=? AND active=1",
            (variant_id,)
        ).fetchone()
        product = conn.execute(
            "SELECT * FROM products WHERE id=? AND active=1",
            (variant["product_id"],)
        ).fetchone() if variant else None

        if not variant or not product or available_stock(variant) < qty:
            conn.rollback()
            conn.close()
            return await call.answer("Stok tidak mencukupi.", show_alert=True)

        wallet = conn.execute(
            "SELECT balance FROM wallets WHERE user_id=?",
            (call.from_user.id,)
        ).fetchone()
        balance = int(wallet["balance"]) if wallet else 0

        unit = effective_unit_price(variant, qty)
        subtotal = unit * qty
        voucher_code, discount_amount = checkout_discount_from_state(
            checkout_data, call.from_user.id, product["id"], variant_id, subtotal
        )
        total = max(0, subtotal - discount_amount)

        if balance < total:
            conn.rollback()
            conn.close()
            return await call.answer(
                f"Saldo tidak cukup. Saldo Kamu {rupiah(balance)}.",
                show_alert=True
            )

        if not reserve_stock_for_order(conn, variant_id, qty):
            conn.rollback()
            conn.close()
            return await call.answer("Stok baru saja berubah. Silakan coba lagi.", show_alert=True)

        cur = conn.execute(
            """INSERT INTO orders
               (user_id, username, product_id, variant_id, qty, unit_price, total,
                status, payment_method, payment_status, note, unique_code,
                payment_total, stock_reserved, reserved_until,
                fulfillment_status, created_at, voucher_code, discount_amount)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                call.from_user.id,
                call.from_user.username or "",
                product["id"],
                variant_id,
                qty,
                unit,
                subtotal,
                "paid_pending_delivery",
                "WALLET",
                "paid",
                checkout_note,
                0,
                total,
                1,
                "",
                "pending",
                datetime.now().isoformat(timespec="seconds"),
                voucher_code,
                discount_amount
            )
        )
        order_id = cur.lastrowid
        ref = invoice(order_id)
        new_balance = balance - total

        conn.execute(
            """INSERT OR IGNORE INTO wallets(user_id, balance, updated_at)
               VALUES(?,?,?)""",
            (call.from_user.id, balance, datetime.now().isoformat(timespec="seconds"))
        )
        conn.execute(
            "UPDATE wallets SET balance=?, updated_at=? WHERE user_id=?",
            (new_balance, datetime.now().isoformat(timespec="seconds"), call.from_user.id)
        )
        conn.execute(
            """INSERT INTO wallet_ledger
               (user_id, type, amount, balance_after, reference, note, created_at)
               VALUES(?,?,?,?,?,?,?)""",
            (
                call.from_user.id, "PURCHASE", -total, new_balance, ref,
                f"Pembelian {product['name']} - {variant['name']}",
                datetime.now().isoformat(timespec="seconds")
            )
        )
        conn.commit()
        conn.close()

        record_voucher_usage(voucher_code, call.from_user.id, order_id, discount_amount)

        delivered = await fulfill_order(order_id, bot)

        if delivered:
            text = (
                "✅ <b>PEMBAYARAN SALDO BERHASIL</b>\n\n"
                f"🧾 Invoice: <b>{ref}</b>\n"
                f"📦 Produk: {product['name']} — {variant['name']}\n"
                f"💰 Subtotal: <b>{rupiah(subtotal)}</b>\n"
                + (f"🎟️ Voucher: <b>-{rupiah(discount_amount)}</b>\n" if discount_amount else "")
                + f"💰 Total: <b>{rupiah(total)}</b>\n"
                f"💵 Sisa saldo: <b>{rupiah(new_balance)}</b>\n\n"
                "🎁 Data akun premium sudah dikirim otomatis."
            )
        else:
            text = (
                "🟡 <b>PEMBAYARAN SALDO BERHASIL</b>\n\n"
                f"🧾 Invoice: <b>{ref}</b>\n"
                f"💰 Total: <b>{rupiah(total)}</b>\n"
                f"💵 Sisa saldo: <b>{rupiah(new_balance)}</b>\n\n"
                "Pembayaran sudah tercatat. Akun premium sedang disiapkan dan akan dikirim otomatis."
            )

        await call.message.edit_text(
            text + f"\n\n<i>{STORE_FOOTER}</i>",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🧾 Pesanan Saya", callback_data="my_orders")],
                [InlineKeyboardButton(text="🏠 Menu Utama", callback_data="home")]
            ]),
            parse_mode="HTML"
        )
        await state.clear()
        await call.answer("Pembayaran berhasil.")



@router.callback_query(F.data.startswith("checkoutvoucher:"))
async def checkout_voucher_prompt(call: CallbackQuery, state: FSMContext):
    _, variant_id, qty = call.data.split(":")
    await state.update_data(
        checkout_variant_id=int(variant_id),
        checkout_qty=int(qty)
    )
    await state.set_state(CheckoutState.waiting_voucher)
    await call.message.edit_text(
        "🎟️ <b>PAKAI VOUCHER</b>\n\n"
        "Kirim kode voucher.\n"
        "Contoh: <code>HEMAT10</code>\n\n"
        "Kirim <code>RESET</code> untuk melepas voucher.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="⬅️ Kembali",
                callback_data=f"checkoutnote:skip:{variant_id}:{qty}"
            )]
        ]),
        parse_mode="HTML"
    )
    await call.answer()


@router.message(CheckoutState.waiting_voucher)
async def checkout_voucher_input(message: Message, state: FSMContext):
    data = await state.get_data()
    variant_id = int(data.get("checkout_variant_id", 0))
    qty = max(1, int(data.get("checkout_qty", 1)))
    code = (message.text or "").strip().upper()

    if code == "RESET":
        await state.update_data(checkout_voucher_code="")
        await state.set_state(None)
        return await message.answer(
            "✅ Voucher dilepas.",
            reply_markup=payment_method_keyboard(variant_id, qty)
        )

    conn = db()
    variant = conn.execute("SELECT * FROM product_variants WHERE id=?", (variant_id,)).fetchone()
    product = conn.execute(
        "SELECT * FROM products WHERE id=?",
        (variant["product_id"],)
    ).fetchone() if variant else None
    conn.close()

    if not variant or not product:
        await state.set_state(None)
        return await message.answer("❌ Produk tidak tersedia.")

    subtotal = effective_unit_price(variant, qty) * qty
    voucher, discount, error = voucher_validate(
        code, message.from_user.id, product["id"], variant_id, subtotal
    )
    if not voucher:
        return await message.answer(f"❌ {error}\n\nKirim kode lain atau RESET.")

    await state.update_data(checkout_voucher_code=code)
    await state.set_state(None)

    await message.answer(
        "✅ <b>VOUCHER DITERAPKAN</b>\n\n"
        f"Kode: <b>{html.escape(code)}</b>\n"
        f"Subtotal: <b>{rupiah(subtotal)}</b>\n"
        f"Diskon: <b>-{rupiah(discount)}</b>\n"
        f"Total setelah voucher: <b>{rupiah(max(0, subtotal-discount))}</b>\n\n"
        "Silakan pilih metode pembayaran:",
        reply_markup=payment_method_keyboard(variant_id, qty),
        parse_mode="HTML"
    )


@router.callback_query(F.data.startswith("process:"))
async def process_order(call: CallbackQuery, bot: Bot, state: FSMContext):
    if maintenance_enabled() and not is_owner(call.from_user.id):
        return await call.answer("Toko sedang maintenance. Silakan coba kembali nanti.", show_alert=True)
    async with purchase_lock(call.from_user.id):
        _, variant_id, qty = call.data.split(":")
        variant_id, qty = int(variant_id), max(1, int(qty))

        allowed, reason = anti_abuse_checkout(call.from_user.id, "QRIS")
        if not allowed:
            return await call.answer(reason, show_alert=True)

        checkout_data = await state.get_data()
        checkout_note = get_checkout_note_from_state(checkout_data)

        conn = db()
        conn.execute("BEGIN IMMEDIATE")

        duplicate = recent_duplicate_checkout(
            conn, call.from_user.id, variant_id, qty, "QRIS"
        )
        if duplicate:
            conn.rollback()
            conn.close()
            return await call.answer(
                "Pesanan QRIS yang sama baru saja dibuat. Cek Pesanan Saya.",
                show_alert=True
            )
        variant = conn.execute(
            "SELECT * FROM product_variants WHERE id=?",
            (variant_id,)
        ).fetchone()
        product = conn.execute(
            "SELECT * FROM products WHERE id=?",
            (variant["product_id"],)
        ).fetchone() if variant else None

        if not variant or not product or not product["active"] or available_stock(variant) < qty:
            conn.rollback()
            conn.close()
            return await call.answer("Stok tidak mencukupi / produk tidak aktif.", show_alert=True)

        unit = effective_unit_price(variant, qty)
        subtotal = unit * qty
        voucher_code, discount_amount = checkout_discount_from_state(
            checkout_data, call.from_user.id, product["id"], variant_id, subtotal
        )
        total = subtotal
        unique_code = unique_code_for_order()
        payment_total = max(0, subtotal - discount_amount) + unique_code

        if not reserve_stock_for_order(conn, variant_id, qty):
            conn.rollback()
            conn.close()
            return await call.answer("Stok baru saja berubah. Silakan coba lagi.", show_alert=True)

        cur = conn.execute(
            """INSERT INTO orders
               (user_id, username, product_id, variant_id, qty, unit_price, total,
                status, payment_method, payment_status, note, unique_code,
                payment_total, stock_reserved, reserved_until, created_at,
                voucher_code, discount_amount)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                call.from_user.id,
                call.from_user.username or "",
                product["id"],
                variant_id,
                qty,
                unit,
                total,
                "pending",
                "QRIS",
                "unpaid",
                checkout_note,
                unique_code,
                payment_total,
                1,
                reservation_expiry_iso(),
                datetime.now().isoformat(timespec="seconds"),
                voucher_code,
                discount_amount
            )
        )
        order_id = cur.lastrowid
        conn.commit()
        conn.close()

        inv = invoice(order_id)
        kb = InlineKeyboardBuilder()
        if ADMIN_USERNAME:
            kb.button(text="💬 Hubungi Owner", url=f"https://t.me/{ADMIN_USERNAME}")
        kb.button(text="🧾 Pesanan Saya", callback_data="my_orders")
        kb.button(text="🏠 Menu Utama", callback_data="home")
        kb.adjust(1)

        payment_note = get_setting("payment_note", DEFAULT_PAYMENT_NOTE)
        qris_file_id = get_setting("qris_file_id", "")
        unique_text = f"🔢 Kode unik: <b>+{unique_code}</b>\n" if unique_code > 0 else ""

        note_text = (
            f"📝 Catatan: <blockquote>{html.escape(checkout_note)}</blockquote>\n"
            if checkout_note else "📝 Catatan: <i>Tidak ada</i>\n"
        )

        voucher_text = (
            f"🎟️ Voucher {html.escape(voucher_code)}: <b>-{rupiah(discount_amount)}</b>\n"
            if discount_amount else ""
        )

        payment_text = (
            "💳 <b>TRANSAKSI PENDING</b>\n\n"
            f"🧾 Invoice: <b>{inv}</b>\n"
            "💠 Pembayaran: <b>QRIS Manual</b>\n"
            f"📦 Produk: {product['name']} — {variant['name']}\n"
            f"🔢 Jumlah: <b>{qty}</b>\n"
            f"💰 Subtotal: <b>{rupiah(subtotal)}</b>\n"
            f"{voucher_text}"
            f"{unique_text}"
            f"💵 <b>TOTAL TRANSFER: {rupiah(payment_total)}</b>\n"
            f"{note_text}\n"
            f"⏳ Stok direservasi selama <b>{ORDER_RESERVATION_MINUTES} menit</b>.\n"
            "⚠️ Transfer harus sesuai total hingga kode unik.\n"
            f"📝 {payment_note}\n\n"
            "Setelah pembayaran, owner akan memverifikasi transaksi.\n\n"
            f"<i>{STORE_FOOTER}</i>"
        )

        if qris_file_id:
            try:
                await call.message.delete()
                await bot.send_photo(
                    call.from_user.id,
                    photo=qris_file_id,
                    caption=payment_text,
                    reply_markup=kb.as_markup(),
                    parse_mode="HTML"
                )
            except Exception:
                await bot.send_message(
                    call.from_user.id,
                    payment_text + "\n\n⚠️ QRIS belum dapat dimuat. Hubungi owner.",
                    reply_markup=kb.as_markup(),
                    parse_mode="HTML"
                )
        else:
            await call.message.edit_text(
                payment_text + "\n\n⚠️ Owner belum memasang gambar QRIS.",
                reply_markup=kb.as_markup(),
                parse_mode="HTML"
            )

        if ADMIN_ID:
            try:
                user = f"@{call.from_user.username}" if call.from_user.username else str(call.from_user.id)
                owner_voucher_text = (
                    f"🎟️ Voucher: {voucher_code} (-{rupiah(discount_amount)})\n"
                    if discount_amount else ""
                )
                await bot.send_message(
                    ADMIN_ID,
                    "🔔 <b>ORDER BARU / MENUNGGU BAYAR</b>\n\n"
                    f"🧾 {inv}\n"
                    f"👤 {user}\n"
                    f"📦 {product['name']} — {variant['name']}\n"
                    f"🔢 Qty: {qty}\n"
                    f"💰 Subtotal: {rupiah(subtotal)}\n"
                    f"{owner_voucher_text}"
                    f"🔢 Kode unik: +{unique_code}\n"
                    f"💵 Transfer: {rupiah(payment_total)}\n"
                    f"📝 Catatan: {checkout_note or '-'}\n"
                    f"⏳ Reservasi: {ORDER_RESERVATION_MINUTES} menit\n\n"
                    "Buka /owner → ✅ Verifikasi Bayar setelah pembayaran valid.",
                    parse_mode="HTML"
                )
            except Exception:
                pass

        await state.clear()
        await call.answer("Pesanan dibuat dan stok direservasi.")


@router.callback_query(F.data.startswith("processauto:"))
async def process_auto_order(call: CallbackQuery, bot: Bot, state: FSMContext):
    if maintenance_enabled() and not is_owner(call.from_user.id):
        return await call.answer("Toko sedang maintenance. Silakan coba kembali nanti.", show_alert=True)
    if not shopeepay_ready():
        return await call.answer(
            "QRIS otomatis belum dikonfigurasi lengkap.",
            show_alert=True
        )

    async with purchase_lock(call.from_user.id):
        _, variant_id, qty = call.data.split(":")
        variant_id, qty = int(variant_id), max(1, int(qty))

        allowed, reason = anti_abuse_checkout(call.from_user.id, "AUTO_QRIS")
        if not allowed:
            return await call.answer(reason, show_alert=True)

        checkout_data = await state.get_data()
        checkout_note = get_checkout_note_from_state(checkout_data)

        conn = db()
        conn.execute("BEGIN IMMEDIATE")

        duplicate = recent_duplicate_checkout(
            conn, call.from_user.id, variant_id, qty, "AUTO_QRIS"
        )
        if duplicate:
            conn.rollback()
            conn.close()
            return await call.answer(
                "QR pembayaran yang sama baru saja dibuat. Cek Pesanan Saya.",
                show_alert=True
            )
        variant = conn.execute(
            "SELECT * FROM product_variants WHERE id=?",
            (variant_id,)
        ).fetchone()
        product = conn.execute(
            "SELECT * FROM products WHERE id=?",
            (variant["product_id"],)
        ).fetchone() if variant else None

        if not variant or not product or not product["active"] or available_stock(variant) < qty:
            conn.rollback()
            conn.close()
            return await call.answer("Stok tidak mencukupi.", show_alert=True)

        unit = effective_unit_price(variant, qty)
        subtotal = unit * qty
        voucher_code, discount_amount = checkout_discount_from_state(
            checkout_data, call.from_user.id, product["id"], variant_id, subtotal
        )
        total = max(0, subtotal - discount_amount)

        if not reserve_stock_for_order(conn, variant_id, qty):
            conn.rollback()
            conn.close()
            return await call.answer("Stok baru saja berubah. Silakan coba lagi.", show_alert=True)

        cur = conn.execute(
            """INSERT INTO orders
               (user_id, username, product_id, variant_id, qty, unit_price, total,
                status, payment_method, payment_status, note, unique_code,
                payment_total, provider_reference, provider_qr_url,
                stock_reserved, reserved_until, created_at,
                voucher_code, discount_amount)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                call.from_user.id,
                call.from_user.username or "",
                product["id"],
                variant_id,
                qty,
                unit,
                subtotal,
                "pending",
                "AUTO_QRIS",
                "unpaid",
                checkout_note,
                0,
                total,
                "",
                "",
                1,
                reservation_expiry_iso(),
                datetime.now().isoformat(timespec="seconds"),
                voucher_code,
                discount_amount
            )
        )
        order_id = cur.lastrowid
        conn.commit()
        conn.close()

        try:
            qr = await shopeepay_generate_qr(order_id, total)
        except Exception as e:
            conn = db()
            conn.execute("BEGIN IMMEDIATE")
            order = conn.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
            release_order_reservation(conn, order)
            conn.execute(
                "UPDATE orders SET status='payment_error', payment_status='error', note=? WHERE id=?",
                (str(e)[:250], order_id)
            )
            conn.commit()
            conn.close()

            return await call.message.edit_text(
                "❌ <b>QRIS OTOMATIS BELUM BERHASIL DIBUAT</b>\n\n"
                "Stok reservasi sudah dilepas otomatis.\n"
                "Silakan gunakan QRIS manual sementara.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(
                        text="🟡 Gunakan QRIS Manual",
                        callback_data=f"process:{variant_id}:{qty}"
                    )],
                    [InlineKeyboardButton(
                        text="⬅️ Kembali",
                        callback_data=f"variant:{variant_id}"
                    )]
                ]),
                parse_mode="HTML"
            )

        conn = db()
        conn.execute(
            """UPDATE orders
               SET provider_reference=?, provider_qr_url=?
               WHERE id=?""",
            (qr["partner_reference"], qr["qr_url"], order_id)
        )
        conn.commit()
        conn.close()

        note_text = (
            f"📝 Catatan: <blockquote>{html.escape(checkout_note)}</blockquote>\n"
            if checkout_note else "📝 Catatan: <i>Tidak ada</i>\n"
        )

        caption = (
            "⚡ <b>QRIS OTOMATIS</b>\n\n"
            f"🧾 Invoice: <b>{invoice(order_id)}</b>\n"
            f"📦 {product['name']} — {variant['name']}\n"
            f"🔢 Qty: <b>{qty}</b>\n"
            f"💵 Total: <b>{rupiah(total)}</b>\n"
            f"{note_text}"
            f"⏳ Stok direservasi <b>{ORDER_RESERVATION_MINUTES} menit</b>.\n\n"
            "Setelah pembayaran sukses dan callback tervalidasi, status order berubah otomatis.\n\n"
            f"<i>{STORE_FOOTER}</i>"
        )

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🧾 Pesanan Saya", callback_data="my_orders")],
            [InlineKeyboardButton(text="🏠 Menu Utama", callback_data="home")]
        ])

        if qr["qr_url"]:
            try:
                await call.message.delete()
                await bot.send_photo(
                    call.from_user.id,
                    qr["qr_url"],
                    caption=caption,
                    reply_markup=kb,
                    parse_mode="HTML"
                )
            except Exception:
                await bot.send_message(
                    call.from_user.id,
                    caption + f"\n\nQR URL:\n{qr['qr_url']}",
                    reply_markup=kb,
                    parse_mode="HTML"
                )
        else:
            await call.message.edit_text(
                caption + "\n\nQR image URL tidak tersedia.",
                reply_markup=kb,
                parse_mode="HTML"
            )

        await state.clear()
        await call.answer("QR otomatis berhasil dibuat.")


@router.callback_query(F.data == "my_orders")
async def my_orders(call: CallbackQuery):
    conn = db()
    rows = conn.execute("""
        SELECT o.*, p.name AS product_name, v.name AS variant_name
        FROM orders o
        JOIN products p ON p.id=o.product_id
        LEFT JOIN product_variants v ON v.id=o.variant_id
        WHERE o.user_id=?
        ORDER BY o.id DESC
        LIMIT 10
    """, (call.from_user.id,)).fetchall()
    conn.close()

    if not rows:
        text = f"🧾 <b>PESANAN SAYA</b>\n\nBelum ada pesanan.\n\n<i>{STORE_FOOTER}</i>"
    else:
        lines = ["🧾 <b>PESANAN SAYA</b>\n"]
        for row in rows:
            status_icons = {
                "completed": "✅",
                "pending": "🟡",
                "expired": "⌛",
                "cancelled": "❌",
                "payment_error": "⚠️",
            }
            icon = status_icons.get(row["status"], "🔵")
            lines.append(
                f"{icon} <b>{invoice(row['id'])}</b>\n"
                f"   {row['product_name']} — {row['variant_name'] or 'Standard'}\n"
                f"   Qty {row['qty']} • {rupiah(row['total'])}\n"
                f"   Status: {row['status'].title()}\n"
            )
        lines.append(f"<i>{STORE_FOOTER}</i>")
        text = "\n".join(lines)

    kb = InlineKeyboardBuilder()
    has_delivery = any((row["delivery_text"] or "").strip() for row in rows) if rows else False
    if has_delivery:
        kb.button(text="📩 Kirim Ulang Akun Terakhir", callback_data="resend:last")
    kb.button(text="⬅️ Menu Utama", callback_data="home")
    kb.adjust(1)

    await call.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")
    await call.answer()


@router.callback_query(F.data == "resend:last")
async def resend_last_delivery(call: CallbackQuery, bot: Bot):
    conn = db()
    order = conn.execute(
        """SELECT * FROM orders
           WHERE user_id=?
             AND delivery_text!=''
           ORDER BY id DESC
           LIMIT 1""",
        (call.from_user.id,)
    ).fetchone()
    conn.close()

    if not order:
        return await call.answer("Belum ada akun yang bisa dikirim ulang.", show_alert=True)

    try:
        await send_delivery_payload(
            bot,
            call.from_user.id,
            order["id"],
            order["delivery_text"]
        )
        await call.answer("✅ Akun dikirim ulang.")
    except Exception:
        await call.answer(
            "Pengiriman ulang gagal. Silakan coba lagi beberapa saat.",
            show_alert=True
        )


@router.callback_query(F.data == "stock_report")
async def stock_report(call: CallbackQuery):
    conn = db()
    rows = conn.execute("""
        SELECT p.name AS product_name, v.name AS variant_name, v.stock, v.reserved_stock
        FROM product_variants v
        JOIN products p ON p.id=v.product_id
        WHERE p.active=1 AND v.active=1
        ORDER BY p.id, v.id
    """).fetchall()
    conn.close()

    lines = ["📁 <b>LAPORAN STOK</b>\n"]
    for row in rows:
        available = max(0, int(row["stock"]) - int(row["reserved_stock"] or 0))
        icon = "✅" if available > 0 else "❌"
        lines.append(f"{icon} {row['product_name']} — {row['variant_name']}: <b>{available}</b>")
    lines.append(f"\n<i>{STORE_FOOTER}</i>")

    await call.message.edit_text("\n".join(lines), reply_markup=back_home(), parse_mode="HTML")
    await call.answer()


@router.callback_query(F.data == "voucher_info")
async def voucher_info(call: CallbackQuery):
    conn = db()
    rows = conn.execute(
        """SELECT * FROM vouchers
           WHERE active=1
           ORDER BY id DESC LIMIT 15"""
    ).fetchall()
    conn.close()

    lines = ["🎁 <b>VOUCHER AKTIF</b>", ""]
    if not rows:
        lines.append("Belum ada voucher aktif.")
    else:
        for row in rows:
            quota = (
                f"{max(0, int(row['usage_limit'])-int(row['used']))} tersisa"
                if int(row["usage_limit"] or 0) > 0 else "tanpa batas"
            )
            lines.append(
                f"🎟️ <code>{html.escape(row['code'])}</code>\n"
                f"Diskon {rupiah(row['discount'])}"
                + (f" • Min {rupiah(row['min_spend'])}" if int(row["min_spend"] or 0) else "")
                + f" • {quota}"
            )

    lines.append("\nGunakan tombol 🎟️ Pakai Voucher saat checkout.")

    await call.message.edit_text(
        "\n\n".join(lines) + f"\n\n<i>{STORE_FOOTER}</i>",
        reply_markup=back_home(),
        parse_mode="HTML"
    )
    await call.answer()

# =========================
# WALLET USER
# =========================
@router.callback_query(F.data == "wallet")
async def wallet_home(call: CallbackQuery, state: FSMContext):
    await state.clear()
    balance = get_balance(call.from_user.id)
    loyalty, lifetime_spend = loyalty_status(call.from_user.id)
    conn = db()
    topup_total = conn.execute(
        "SELECT COALESCE(SUM(amount),0) AS n FROM wallet_ledger WHERE user_id=? AND type='TOPUP'",
        (call.from_user.id,)
    ).fetchone()["n"]
    spend_total = conn.execute(
        "SELECT COALESCE(SUM(ABS(amount)),0) AS n FROM wallet_ledger WHERE user_id=? AND type='PURCHASE'",
        (call.from_user.id,)
    ).fetchone()["n"]
    conn.close()

    await safe_edit_or_answer(
        call,
        "💰 <b>SALDO KAMU</b>\n\n"
        f"Saldo tersedia: <b>{rupiah(balance)}</b>\n"
        f"🏅 Level member: <b>{loyalty}</b>\n"
        f"🛍️ Total belanja selesai: <b>{rupiah(lifetime_spend)}</b>\n"
        f"Total top up: <b>{rupiah(topup_total)}</b>\n"
        f"Total digunakan: <b>{rupiah(spend_total)}</b>\n"
        f"Minimum top up: <b>{rupiah(get_min_topup())}</b>\n\n"
        f"<i>{STORE_FOOTER}</i>",
        reply_markup=wallet_menu(),
        parse_mode="HTML"
    )
    await call.answer()


@router.callback_query(F.data == "wallet:history")
async def wallet_history(call: CallbackQuery):
    conn = db()
    rows = conn.execute(
        """SELECT * FROM wallet_ledger
           WHERE user_id=?
           ORDER BY id DESC
           LIMIT 15""",
        (call.from_user.id,)
    ).fetchall()
    conn.close()

    lines = ["📑 <b>RIWAYAT SALDO</b>\n"]
    if not rows:
        lines.append("Belum ada transaksi saldo.")
    else:
        for row in rows:
            sign = "+" if row["amount"] > 0 else "-"
            lines.append(
                f"{'🟢' if row['amount'] > 0 else '🔴'} "
                f"{row['type']} {sign}{rupiah(abs(row['amount']))}\n"
                f"   Saldo: {rupiah(row['balance_after'])}\n"
                f"   Ref: {row['reference'] or '-'}"
            )
    lines.append(f"\n<i>{STORE_FOOTER}</i>")

    await call.message.edit_text(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Saldo Kamu", callback_data="wallet")]
        ]),
        parse_mode="HTML"
    )
    await call.answer()


@router.callback_query(F.data == "wallet:topup")
async def wallet_topup(call: CallbackQuery, state: FSMContext):
    await state.clear()
    minimum = get_min_topup()

    await call.message.edit_text(
        "➕ <b>ISI SALDO</b>\n\n"
        f"Saldo minimum: <b>{rupiah(minimum)}</b>\n\n"
        "Pilih nominal cepat, gunakan tombol tambah/kurang, "
        "atau masukkan nominal custom.",
        reply_markup=topup_amount_keyboard(minimum),
        parse_mode="HTML"
    )
    await call.answer()


@router.callback_query(F.data.startswith("topup:set:"))
async def wallet_topup_set(call: CallbackQuery, state: FSMContext):
    await state.clear()

    try:
        amount = int(call.data.split(":")[2])
    except Exception:
        return await call.answer("Nominal tidak valid.", show_alert=True)

    amount = max(get_min_topup(), amount)

    await call.message.edit_text(
        "➕ <b>ISI SALDO</b>\n\n"
        f"Nominal dipilih: <b>{rupiah(amount)}</b>\n"
        f"Minimum: <b>{rupiah(get_min_topup())}</b>\n\n"
        "Atur nominal lalu lanjutkan ke pembayaran.",
        reply_markup=topup_amount_keyboard(amount),
        parse_mode="HTML"
    )
    await call.answer()


@router.callback_query(F.data == "topup:custom")
async def wallet_topup_custom(call: CallbackQuery, state: FSMContext):
    await state.set_state(OwnerState.topup_amount)

    await call.message.edit_text(
        "✏️ <b>NOMINAL CUSTOM</b>\n\n"
        f"Minimum isi saldo: <b>{rupiah(get_min_topup())}</b>\n\n"
        "Kirim nominal dalam angka.\n"
        "Contoh: <code>75000</code>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Kembali", callback_data="wallet:topup")]
        ]),
        parse_mode="HTML"
    )
    await call.answer()


@router.message(OwnerState.topup_amount)
async def wallet_topup_custom_input(message: Message, state: FSMContext):
    try:
        raw = (message.text or "").replace(".", "").replace(",", "").strip()
        amount = int(raw)
        if amount < get_min_topup():
            raise ValueError
    except Exception:
        return await message.answer(
            f"❌ Nominal tidak valid. Minimum isi saldo adalah {rupiah(get_min_topup())}."
        )

    await state.clear()

    await message.answer(
        "✅ <b>NOMINAL DIPILIH</b>\n\n"
        f"Isi saldo: <b>{rupiah(amount)}</b>\n\n"
        "Periksa nominal sebelum membuat invoice.",
        reply_markup=topup_confirm_keyboard(amount),
        parse_mode="HTML"
    )


@router.callback_query(F.data.startswith("topup:confirm:"))
async def wallet_topup_confirm(call: CallbackQuery, state: FSMContext):
    await state.clear()

    try:
        amount = int(call.data.split(":")[2])
    except Exception:
        return await call.answer("Nominal tidak valid.", show_alert=True)

    if amount < get_min_topup():
        return await call.answer(
            f"Minimum isi saldo {rupiah(get_min_topup())}.",
            show_alert=True
        )

    balance = get_balance(call.from_user.id)

    await call.message.edit_text(
        "🧾 <b>KONFIRMASI ISI SALDO</b>\n\n"
        f"Saldo sekarang: <b>{rupiah(balance)}</b>\n"
        f"Nominal isi saldo: <b>{rupiah(amount)}</b>\n"
        f"Perkiraan saldo setelah berhasil: <b>{rupiah(balance + amount)}</b>\n\n"
        "Invoice baru dibuat setelah Anda menekan tombol pembayaran.",
        reply_markup=topup_confirm_keyboard(amount),
        parse_mode="HTML"
    )
    await call.answer()


@router.callback_query(F.data.startswith("topup:pay:"))
async def wallet_topup_pay(call: CallbackQuery, state: FSMContext, bot: Bot):
    await state.clear()

    try:
        amount = int(call.data.split(":")[2])
    except Exception:
        return await call.answer("Nominal tidak valid.", show_alert=True)

    if amount < get_min_topup():
        return await call.answer(
            f"Minimum isi saldo {rupiah(get_min_topup())}.",
            show_alert=True
        )

    # Anti double-click: reuse/reject a same pending topup created very recently.
    conn = db()
    recent = conn.execute(
        """SELECT * FROM topups
           WHERE user_id=? AND amount=? AND status='pending'
           ORDER BY id DESC
           LIMIT 1""",
        (call.from_user.id, amount)
    ).fetchone()

    if recent:
        try:
            created = datetime.fromisoformat(recent["created_at"])
            now = datetime.now(created.tzinfo) if created.tzinfo else datetime.now()
            age = (now - created).total_seconds()
        except Exception:
            age = 999

        if 0 <= age <= 30:
            conn.close()
            return await call.answer(
                f"Invoice {topup_invoice(recent['id'])} baru saja dibuat. Jangan buat dua kali.",
                show_alert=True
            )

    code = unique_code_for_order()
    payment_total = amount + code

    cur = conn.execute(
        """INSERT INTO topups
           (user_id, username, amount, unique_code, payment_total,
            payment_method, status, created_at)
           VALUES(?,?,?,?,?,?,?,?)""",
        (
            call.from_user.id,
            call.from_user.username or "",
            amount,
            code,
            payment_total,
            "QRIS_MANUAL",
            "pending",
            datetime.now().isoformat(timespec="seconds")
        )
    )
    topup_id = cur.lastrowid
    conn.commit()
    conn.close()

    qris_file_id = get_setting("qris_file_id", "")
    payment_note = get_setting("payment_note", DEFAULT_PAYMENT_NOTE)

    caption = (
        "💰 <b>INVOICE ISI SALDO</b>\n\n"
        f"🧾 Invoice: <b>{topup_invoice(topup_id)}</b>\n"
        f"💵 Isi saldo: <b>{rupiah(amount)}</b>\n"
        f"🔢 Kode unik: <b>+{code}</b>\n"
        f"💳 TOTAL TRANSFER: <b>{rupiah(payment_total)}</b>\n\n"
        "⚠️ Transfer harus sesuai total sampai kode unik.\n"
        f"📝 {payment_note}\n\n"
        "Setelah pembayaran diterima dan diverifikasi owner, "
        "saldo akan masuk ke Saldo Kamu."
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 Saldo Kamu", callback_data="wallet")],
        [InlineKeyboardButton(text="📑 Riwayat Saldo", callback_data="wallet:history")]
    ])

    if qris_file_id:
        try:
            await call.message.delete()
        except Exception:
            pass

        await bot.send_photo(
            call.from_user.id,
            qris_file_id,
            caption=caption,
            reply_markup=kb,
            parse_mode="HTML"
        )
    else:
        await call.message.edit_text(
            caption + "\n\n⚠️ QRIS belum dipasang owner.",
            reply_markup=kb,
            parse_mode="HTML"
        )

    if ADMIN_ID:
        try:
            user = (
                f"@{call.from_user.username}"
                if call.from_user.username
                else str(call.from_user.id)
            )
            await bot.send_message(
                ADMIN_ID,
                "💰 <b>ISI SALDO BARU</b>\n\n"
                f"🧾 {topup_invoice(topup_id)}\n"
                f"👤 {user}\n"
                f"💵 Saldo: {rupiah(amount)}\n"
                f"🔢 Kode unik: +{code}\n"
                f"💳 Transfer: {rupiah(payment_total)}\n\n"
                "Buka /owner → 💰 Manajemen Saldo → ✅ Verifikasi Top Up.",
                parse_mode="HTML"
            )
        except Exception:
            pass

    await call.answer("Invoice isi saldo berhasil dibuat.")




@router.callback_query(F.data == "owner:wallet")
async def owner_wallet(call: CallbackQuery, state: FSMContext):
    if not is_owner(call.from_user.id):
        return await call.answer("Akses ditolak.", show_alert=True)

    await state.clear()
    conn = db()
    total_balance = conn.execute("SELECT COALESCE(SUM(balance),0) AS n FROM wallets").fetchone()["n"]
    users = conn.execute("SELECT COUNT(*) AS n FROM wallets WHERE balance>0").fetchone()["n"]
    pending = conn.execute("SELECT COUNT(*) AS n FROM topups WHERE status='pending'").fetchone()["n"]
    conn.close()

    await call.message.edit_text(
        "💰 <b>MANAJEMEN SALDO</b>\n\n"
        f"👤 User dengan saldo: <b>{users}</b>\n"
        f"💵 Total saldo tersimpan: <b>{rupiah(total_balance)}</b>\n"
        f"⏳ Top up pending: <b>{pending}</b>\n\n"
        "Pilih menu:",
        reply_markup=owner_wallet_menu(),
        parse_mode="HTML"
    )
    await call.answer()


@router.callback_query(F.data == "owner:wallet_add")
async def owner_wallet_add(call: CallbackQuery, state: FSMContext):
    if not is_owner(call.from_user.id):
        return await call.answer("Akses ditolak.", show_alert=True)
    await state.set_state(OwnerState.owner_wallet_add)
    await call.message.edit_text(
        "➕ <b>TAMBAH SALDO USER</b>\n\n"
        "Kirim:\n<code>USER_ID | NOMINAL | CATATAN</code>\n\n"
        "Contoh:\n<code>123456789 | 50000 | Bonus saldo</code>",
        reply_markup=back_owner(),
        parse_mode="HTML"
    )
    await call.answer()


@router.message(OwnerState.owner_wallet_add)
async def owner_wallet_add_input(message: Message, state: FSMContext):
    if not is_owner(message.from_user.id):
        return
    try:
        uid, amount, note = [x.strip() for x in message.text.split("|", 2)]
        uid, amount = int(uid), int(amount)
        if amount <= 0:
            raise ValueError
        ref = f"ADMINADD-{int(time.time())}"
        balance = wallet_change(uid, amount, "ADMIN_ADJUST", ref, note)
        await state.clear()
        await message.answer(
            f"✅ Saldo ditambahkan.\nSaldo user sekarang: {rupiah(balance)}",
            reply_markup=owner_wallet_menu()
        )
    except Exception:
        await message.answer("❌ Format salah. Contoh: 123456789 | 50000 | Bonus saldo")


@router.callback_query(F.data == "owner:wallet_sub")
async def owner_wallet_sub(call: CallbackQuery, state: FSMContext):
    if not is_owner(call.from_user.id):
        return await call.answer("Akses ditolak.", show_alert=True)
    await state.set_state(OwnerState.owner_wallet_subtract)
    await call.message.edit_text(
        "➖ <b>KURANGI SALDO USER</b>\n\n"
        "Kirim:\n<code>USER_ID | NOMINAL | CATATAN</code>",
        reply_markup=back_owner(),
        parse_mode="HTML"
    )
    await call.answer()


@router.message(OwnerState.owner_wallet_subtract)
async def owner_wallet_sub_input(message: Message, state: FSMContext):
    if not is_owner(message.from_user.id):
        return
    try:
        uid, amount, note = [x.strip() for x in message.text.split("|", 2)]
        uid, amount = int(uid), int(amount)
        if amount <= 0:
            raise ValueError
        ref = f"ADMINSUB-{int(time.time())}"
        balance = wallet_change(uid, -amount, "ADMIN_ADJUST", ref, note)
        await state.clear()
        await message.answer(
            f"✅ Saldo dikurangi.\nSaldo user sekarang: {rupiah(balance)}",
            reply_markup=owner_wallet_menu()
        )
    except ValueError as e:
        await message.answer(f"❌ {str(e) or 'Saldo tidak mencukupi.'}")
    except Exception:
        await message.answer("❌ Format salah.")


@router.callback_query(F.data == "owner:wallet_verify")
async def owner_wallet_verify(call: CallbackQuery, state: FSMContext):
    if not is_owner(call.from_user.id):
        return await call.answer("Akses ditolak.", show_alert=True)

    await state.clear()
    conn = db()
    rows = conn.execute(
        "SELECT * FROM topups WHERE status='pending' ORDER BY id DESC LIMIT 20"
    ).fetchall()
    conn.close()

    kb = InlineKeyboardBuilder()
    for row in rows:
        kb.button(
            text=f"✅ {topup_invoice(row['id'])} • {rupiah(row['payment_total'])}",
            callback_data=f"topupverify:{row['id']}"
        )
    kb.button(text="⬅️ Kembali", callback_data="owner:wallet")
    kb.adjust(1)

    await call.message.edit_text(
        "✅ <b>VERIFIKASI TOP UP</b>\n\n"
        "Pilih invoice yang sudah benar-benar dibayar:",
        reply_markup=kb.as_markup(),
        parse_mode="HTML"
    )
    await call.answer()


@router.callback_query(F.data.startswith("topupverify:"))
async def owner_wallet_verify_button(call: CallbackQuery, bot: Bot):
    if not is_owner(call.from_user.id):
        return await call.answer("Akses ditolak.", show_alert=True)

    topup_id = int(call.data.split(":")[1])

    conn = db()
    row = conn.execute(
        "SELECT * FROM topups WHERE id=? AND status='pending'",
        (topup_id,)
    ).fetchone()
    conn.close()

    if not row:
        return await call.answer("Top up sudah diproses / tidak ditemukan.", show_alert=True)

    balance = wallet_change(
        row["user_id"],
        row["amount"],
        "TOPUP",
        topup_invoice(topup_id),
        "Top up saldo terverifikasi."
    )

    conn = db()
    conn.execute(
        """UPDATE topups
           SET status='completed', verified_at=?, verified_by=?
           WHERE id=? AND status='pending'""",
        (datetime.now().isoformat(timespec="seconds"), call.from_user.id, topup_id)
    )
    conn.commit()
    conn.close()

    try:
        await bot.send_message(
            row["user_id"],
            "✅ <b>TOP UP BERHASIL</b>\n\n"
            f"🧾 {topup_invoice(topup_id)}\n"
            f"💰 Saldo masuk: <b>{rupiah(row['amount'])}</b>\n"
            f"💵 Saldo sekarang: <b>{rupiah(balance)}</b>",
            parse_mode="HTML"
        )
    except Exception:
        pass

    await call.answer("Top up berhasil diverifikasi.", show_alert=True)
    await call.message.edit_text("✅ Top up selesai diproses.", reply_markup=owner_wallet_menu())



@router.callback_query(F.data == "owner:min_topup")
async def owner_min_topup(call: CallbackQuery, state: FSMContext):
    if not is_owner(call.from_user.id):
        return await call.answer("Akses ditolak.", show_alert=True)

    await state.set_state(OwnerState.owner_min_topup)
    await call.message.edit_text(
        "⚙️ <b>MINIMUM TOP UP</b>\n\n"
        f"Minimum saat ini: <b>{rupiah(get_min_topup())}</b>\n\n"
        "Kirim nominal minimum baru.\n"
        "Contoh: <code>5000</code>",
        reply_markup=back_owner(),
        parse_mode="HTML"
    )
    await call.answer()


@router.message(OwnerState.owner_min_topup)
async def owner_min_topup_input(message: Message, state: FSMContext):
    if not is_owner(message.from_user.id):
        return

    try:
        amount = int((message.text or "").strip())
        if amount < 1000:
            raise ValueError
    except Exception:
        return await message.answer("❌ Minimum top up paling rendah Rp1.000.")

    set_setting("min_topup", amount)
    await state.clear()
    await message.answer(
        f"✅ Minimum top up diubah menjadi {rupiah(amount)}.",
        reply_markup=owner_wallet_menu()
    )


@router.callback_query(F.data == "owner:wallet_history")
async def owner_wallet_history(call: CallbackQuery):
    if not is_owner(call.from_user.id):
        return await call.answer("Akses ditolak.", show_alert=True)

    conn = db()
    rows = conn.execute(
        "SELECT * FROM wallet_ledger ORDER BY id DESC LIMIT 20"
    ).fetchall()
    conn.close()

    lines = ["📑 <b>RIWAYAT SALDO TERBARU</b>\n"]
    if not rows:
        lines.append("Belum ada transaksi saldo.")
    else:
        for row in rows:
            lines.append(
                f"👤 {row['user_id']} • {row['type']}\n"
                f"{rupiah(row['amount'])} → {rupiah(row['balance_after'])}\n"
                f"Ref: {row['reference'] or '-'}"
            )

    await call.message.edit_text(
        "\n\n".join(lines),
        reply_markup=owner_wallet_menu(),
        parse_mode="HTML"
    )
    await call.answer()


@router.callback_query(F.data == "owner:qris_settings")
async def owner_qris_settings(call: CallbackQuery, state: FSMContext):
    if not is_owner(call.from_user.id):
        return await call.answer("Akses ditolak.", show_alert=True)

    await state.clear()
    enabled = get_setting("unique_code_enabled", "1") == "1"
    low = get_setting("unique_code_min", "1")
    high = get_setting("unique_code_max", "999")
    qris_status = "✅ Sudah dipasang" if get_setting("qris_file_id", "") else "❌ Belum dipasang"
    auto_status = "✅ Siap" if shopeepay_ready() else "⚪ Belum siap"
    mode = get_setting("payment_mode", "manual")

    await call.message.edit_text(
        "💳 <b>PENGATURAN PEMBAYARAN</b>\n\n"
        f"🖼️ QRIS manual: <b>{qris_status}</b>\n"
        f"🔢 Kode unik: <b>{'AKTIF' if enabled else 'NONAKTIF'}</b>\n"
        f"⚙️ Rentang: <b>{low} - {high}</b>\n"
        f"⚡ Payment Gateway: <b>{auto_status}</b>\n"
        f"⭐ Mode utama: <b>{'AUTO' if mode == 'auto' else 'MANUAL'}</b>\n"
        f"📝 Catatan: {get_setting('payment_note', DEFAULT_PAYMENT_NOTE)}\n\n"
        "QRIS manual tetap menjadi fallback jika pembayaran otomatis belum siap.",
        reply_markup=qris_settings_menu(),
        parse_mode="HTML"
    )
    await call.answer()



@router.callback_query(F.data == "owner:qris_toggle_mode")
async def owner_qris_toggle_mode(call: CallbackQuery):
    if not is_owner(call.from_user.id):
        return await call.answer("Akses ditolak.", show_alert=True)

    current = get_setting("payment_mode", "manual")
    target = "auto" if current == "manual" else "manual"

    if target == "auto" and not shopeepay_ready():
        return await call.answer(
            "QRIS otomatis belum siap. Lengkapi credential Railway dulu.",
            show_alert=True
        )

    set_setting("payment_mode", target)
    await call.answer(
        f"Mode pembayaran utama: {target.upper()}",
        show_alert=True
    )

    enabled = get_setting("unique_code_enabled", "1") == "1"
    low = get_setting("unique_code_min", "1")
    high = get_setting("unique_code_max", "999")
    qris_status = "✅ Sudah dipasang" if get_setting("qris_file_id", "") else "❌ Belum dipasang"
    auto_status = "✅ Siap" if shopeepay_ready() else "⚪ Belum siap"

    await call.message.edit_text(
        "💳 <b>PENGATURAN PEMBAYARAN</b>\n\n"
        f"🖼️ QRIS manual: <b>{qris_status}</b>\n"
        f"🔢 Kode unik: <b>{'AKTIF' if enabled else 'NONAKTIF'}</b>\n"
        f"⚙️ Rentang: <b>{low} - {high}</b>\n"
        f"⚡ Payment Gateway: <b>{auto_status}</b>\n"
        f"⭐ Mode utama: <b>{target.upper()}</b>\n"
        f"📝 Catatan: {get_setting('payment_note', DEFAULT_PAYMENT_NOTE)}",
        reply_markup=qris_settings_menu(),
        parse_mode="HTML"
    )


@router.callback_query(F.data == "owner:shopeepay_status")
async def owner_shopeepay_status(call: CallbackQuery):
    if not is_owner(call.from_user.id):
        return await call.answer("Akses ditolak.", show_alert=True)

    checks = {
        "SHOPEEPAY_ENABLED": SHOPEEPAY_ENABLED,
        "BASE_URL": bool(SHOPEEPAY_BASE_URL),
        "CLIENT_ID": bool(SHOPEEPAY_CLIENT_ID),
        "CLIENT_SECRET": bool(SHOPEEPAY_CLIENT_SECRET),
        "MERCHANT_ID": bool(SHOPEEPAY_MERCHANT_ID),
        "STORE_ID": bool(SHOPEEPAY_STORE_ID),
        "PRIVATE_KEY": bool(SHOPEEPAY_PRIVATE_KEY),
        "PUBLIC_KEY": bool(SHOPEEPAY_PUBLIC_KEY),
        "PUBLIC_BASE_URL": bool(PUBLIC_BASE_URL),
    }

    lines = ["🔌 <b>STATUS PAYMENT GATEWAY</b>\n"]
    for name, ok in checks.items():
        lines.append(f"{'✅' if ok else '❌'} {name}")

    lines.append(
        "\nCredential rahasia tidak ditampilkan di Telegram.\n"
        "Semua credential diisi melalui Railway Variables."
    )

    await call.message.edit_text(
        "\n".join(lines),
        reply_markup=back_owner(),
        parse_mode="HTML"
    )
    await call.answer()


@router.callback_query(F.data == "owner:qris_set")
async def owner_qris_set(call: CallbackQuery, state: FSMContext):
    if not is_owner(call.from_user.id):
        return await call.answer("Akses ditolak.", show_alert=True)

    await state.set_state(OwnerState.set_qris)
    await call.message.edit_text(
        "🖼️ <b>GANTI QRIS</b>\n\n"
        "Silakan kirim <b>foto QRIS pribadi</b> ke chat ini.\n\n"
        "Bot akan menyimpan Telegram file_id, jadi QRIS tidak perlu di-upload ke GitHub.",
        reply_markup=back_owner(),
        parse_mode="HTML"
    )
    await call.answer()


@router.message(OwnerState.set_qris, F.photo)
async def owner_qris_photo(message: Message, state: FSMContext):
    if not is_owner(message.from_user.id):
        return

    file_id = message.photo[-1].file_id
    set_setting("qris_file_id", file_id)
    await state.clear()
    await message.answer(
        "✅ QRIS berhasil diperbarui.\n\n"
        "QRIS baru akan langsung digunakan pada checkout berikutnya.",
        reply_markup=owner_menu()
    )


@router.message(OwnerState.set_qris)
async def owner_qris_invalid(message: Message):
    if not is_owner(message.from_user.id):
        return
    await message.answer("❌ Kirim sebagai <b>foto</b>, bukan teks atau file lain.", parse_mode="HTML")


@router.callback_query(F.data == "owner:qris_note")
async def owner_qris_note(call: CallbackQuery, state: FSMContext):
    if not is_owner(call.from_user.id):
        return await call.answer("Akses ditolak.", show_alert=True)

    await state.set_state(OwnerState.set_payment_note)
    await call.message.edit_text(
        "📝 <b>EDIT CATATAN PEMBAYARAN</b>\n\n"
        "Kirim catatan yang ingin tampil di bawah QRIS.\n\n"
        "Contoh:\n"
        "<code>QRIS Maboyy Digital • Transfer sesuai nominal</code>",
        reply_markup=back_owner(),
        parse_mode="HTML"
    )
    await call.answer()


@router.message(OwnerState.set_payment_note)
async def owner_qris_note_input(message: Message, state: FSMContext):
    if not is_owner(message.from_user.id):
        return

    note = (message.text or "").strip()
    if not note:
        return await message.answer("❌ Catatan tidak boleh kosong.")

    set_setting("payment_note", note[:300])
    await state.clear()
    await message.answer("✅ Catatan pembayaran diperbarui.", reply_markup=owner_menu())


@router.callback_query(F.data == "owner:qris_toggle_unique")
async def owner_qris_toggle_unique(call: CallbackQuery):
    if not is_owner(call.from_user.id):
        return await call.answer("Akses ditolak.", show_alert=True)

    current = get_setting("unique_code_enabled", "1") == "1"
    set_setting("unique_code_enabled", "0" if current else "1")
    await call.answer(
        "Kode unik dinonaktifkan." if current else "Kode unik diaktifkan.",
        show_alert=True
    )

    enabled = not current
    low = get_setting("unique_code_min", "1")
    high = get_setting("unique_code_max", "999")
    qris_status = "✅ Sudah dipasang" if get_setting("qris_file_id", "") else "❌ Belum dipasang"

    await call.message.edit_text(
        "💳 <b>PENGATURAN QRIS</b>\n\n"
        f"🖼️ QRIS: <b>{qris_status}</b>\n"
        f"🔢 Kode unik: <b>{'AKTIF' if enabled else 'NONAKTIF'}</b>\n"
        f"⚙️ Rentang: <b>{low} - {high}</b>\n"
        f"📝 Catatan: {get_setting('payment_note', DEFAULT_PAYMENT_NOTE)}",
        reply_markup=qris_settings_menu(),
        parse_mode="HTML"
    )


@router.callback_query(F.data == "owner:qris_range")
async def owner_qris_range(call: CallbackQuery, state: FSMContext):
    if not is_owner(call.from_user.id):
        return await call.answer("Akses ditolak.", show_alert=True)

    await state.set_state(OwnerState.set_unique_range)
    await call.message.edit_text(
        "⚙️ <b>RENTANG KODE UNIK</b>\n\n"
        "Kirim format:\n"
        "<code>MIN | MAX</code>\n\n"
        "Contoh:\n"
        "<code>1 | 999</code>\n\n"
        "Untuk nominal kecil, rentang <b>1-99</b> biasanya lebih nyaman.",
        reply_markup=back_owner(),
        parse_mode="HTML"
    )
    await call.answer()


@router.message(OwnerState.set_unique_range)
async def owner_qris_range_input(message: Message, state: FSMContext):
    if not is_owner(message.from_user.id):
        return

    try:
        low, high = [int(x.strip()) for x in message.text.split("|", 1)]
        if low < 1 or high < low or high > 9999:
            raise ValueError

        set_setting("unique_code_min", low)
        set_setting("unique_code_max", high)
        await state.clear()
        await message.answer(
            f"✅ Rentang kode unik diubah menjadi {low} - {high}.",
            reply_markup=owner_menu()
        )
    except Exception:
        await message.answer("❌ Format salah. Contoh: 1 | 999")


@router.callback_query(F.data == "owner:qris_preview")
async def owner_qris_preview(call: CallbackQuery, bot: Bot):
    if not is_owner(call.from_user.id):
        return await call.answer("Akses ditolak.", show_alert=True)

    qris_file_id = get_setting("qris_file_id", "")
    if not qris_file_id:
        return await call.answer("QRIS belum dipasang.", show_alert=True)

    await bot.send_photo(
        call.from_user.id,
        qris_file_id,
        caption=(
            "👁️ <b>PREVIEW QRIS</b>\n\n"
            f"📝 {get_setting('payment_note', DEFAULT_PAYMENT_NOTE)}\n"
            f"🔢 Kode unik: {'ON' if get_setting('unique_code_enabled', '1') == '1' else 'OFF'}"
        ),
        parse_mode="HTML"
    )
    await call.answer("Preview dikirim.")



@router.callback_query(F.data == "owner:health")
async def owner_health(call: CallbackQuery):
    if not is_owner(call.from_user.id):
        return await call.answer("Akses ditolak.", show_alert=True)

    snap = system_health_snapshot()

    status = "✅ Normal"
    if (
        snap["send_failed"] > 0
        or snap["stock_mismatch"] > 0
        or not snap["db_exists"]
    ):
        status = "⚠️ Perlu Dicek"

    text = (
        "🩺 <b>CEK SISTEM</b>\n\n"
        f"Status: <b>{status}</b>\n\n"
        f"📦 Produk aktif: <b>{snap['active_products']}</b>\n"
        f"🧩 Variasi aktif: <b>{snap['active_variants']}</b>\n"
        f"👥 User terverifikasi: <b>{snap['verified_users']}</b>\n"
        f"🟡 Order pending: <b>{snap['pending_orders']}</b>\n"
        f"💳 Paid/pending delivery: <b>{snap['paid_pending']}</b>\n"
        f"⚠️ Send failed: <b>{snap['send_failed']}</b>\n"
        f"🔒 Akun allocated: <b>{snap['allocated_items']}</b>\n"
        f"✅ Akun available: <b>{snap['available_items']}</b>\n"
        f"🧮 Stock mismatch: <b>{snap['stock_mismatch']}</b>\n"
        f"💾 Database: <b>{'OK' if snap['db_exists'] else 'TIDAK DITEMUKAN'}</b>\n"
        f"🗄️ Backup terakhir: <b>{snap['last_backup_name']}</b>\n\n"
        "Gunakan ♻️ Recovery Order jika ada paid pending/send failed.",
    )

    await call.message.edit_text(
        text,
        reply_markup=back_owner(),
        parse_mode="HTML"
    )
    await call.answer()


@router.callback_query(F.data == "owner:recover_orders")
async def owner_recover_orders(call: CallbackQuery, bot: Bot):
    if not is_owner(call.from_user.id):
        return await call.answer("Akses ditolak.", show_alert=True)

    await call.answer("Memeriksa order...", show_alert=False)
    recovered, pending = await recover_stuck_orders(bot)

    await call.message.edit_text(
        "♻️ <b>RECOVERY ORDER SELESAI</b>\n\n"
        f"✅ Berhasil dipulihkan/dikirim: <b>{recovered}</b>\n"
        f"🟡 Masih menunggu stok / gagal kirim: <b>{pending}</b>\n\n"
        "Recovery tidak melakukan charge baru dan tidak membuat invoice baru.",
        reply_markup=back_owner(),
        parse_mode="HTML"
    )


def owner_resend_orders_keyboard():
    conn = db()
    rows = conn.execute(
        """SELECT id, user_id, status, fulfillment_status
           FROM orders
           WHERE payment_status='paid'
             AND delivery_text!=''
           ORDER BY id DESC
           LIMIT 20"""
    ).fetchall()
    conn.close()

    kb = InlineKeyboardBuilder()
    for row in rows:
        kb.button(
            text=f"📨 {invoice(row['id'])} • {row['fulfillment_status']}",
            callback_data=f"ownerresend:{row['id']}"
        )
    kb.button(text="⬅️ Kembali", callback_data="owner:panel")
    kb.adjust(1)
    return kb.as_markup()


@router.callback_query(F.data == "owner:resend_order")
async def owner_resend_order(call: CallbackQuery):
    if not is_owner(call.from_user.id):
        return await call.answer("Akses ditolak.", show_alert=True)

    await call.message.edit_text(
        "📨 <b>KIRIM ULANG AKUN</b>\n\n"
        "Pilih invoice. Bot akan mengirim ulang credential yang sudah tersimpan pada order yang sama.",
        reply_markup=owner_resend_orders_keyboard(),
        parse_mode="HTML"
    )
    await call.answer()


@router.callback_query(F.data.startswith("ownerresend:"))
async def owner_resend_selected(call: CallbackQuery, bot: Bot):
    if not is_owner(call.from_user.id):
        return await call.answer("Akses ditolak.", show_alert=True)

    order_id = int(call.data.split(":")[1])

    conn = db()
    order = conn.execute(
        "SELECT * FROM orders WHERE id=?",
        (order_id,)
    ).fetchone()
    conn.close()

    if not order or not (order["delivery_text"] or "").strip():
        return await call.answer("Data akun order tidak tersedia.", show_alert=True)

    try:
        await send_delivery_payload(
            bot,
            order["user_id"],
            order_id,
            order["delivery_text"]
        )
        await call.answer("✅ Akun dikirim ulang ke user.", show_alert=True)
    except Exception:
        await call.answer(
            "❌ Pengiriman ulang gagal. Coba lagi setelah koneksi normal.",
            show_alert=True
        )


def owner_cancel_orders_keyboard():
    conn = db()
    rows = conn.execute(
        """SELECT id, user_id, status
           FROM orders
           WHERE payment_status!='paid'
             AND status='pending'
           ORDER BY id DESC
           LIMIT 20"""
    ).fetchall()
    conn.close()

    kb = InlineKeyboardBuilder()
    for row in rows:
        kb.button(
            text=f"❌ {invoice(row['id'])}",
            callback_data=f"ownercancel:select:{row['id']}"
        )
    kb.button(text="⬅️ Kembali", callback_data="owner:panel")
    kb.adjust(1)
    return kb.as_markup()


@router.callback_query(F.data == "owner:cancel_order")
async def owner_cancel_order(call: CallbackQuery):
    if not is_owner(call.from_user.id):
        return await call.answer("Akses ditolak.", show_alert=True)

    await call.message.edit_text(
        "❌ <b>BATALKAN ORDER</b>\n\n"
        "Hanya order pending yang belum dibayar yang dapat dibatalkan.",
        reply_markup=owner_cancel_orders_keyboard(),
        parse_mode="HTML"
    )
    await call.answer()


@router.callback_query(F.data.startswith("ownercancel:select:"))
async def owner_cancel_select(call: CallbackQuery):
    if not is_owner(call.from_user.id):
        return await call.answer("Akses ditolak.", show_alert=True)

    order_id = int(call.data.split(":")[2])

    conn = db()
    order = conn.execute(
        "SELECT * FROM orders WHERE id=?",
        (order_id,)
    ).fetchone()
    conn.close()

    if not order:
        return await call.answer("Order tidak ditemukan.", show_alert=True)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="✅ Ya, Batalkan",
                callback_data=f"ownercancel:confirm:{order_id}"
            )
        ],
        [
            InlineKeyboardButton(
                text="⬅️ Batal",
                callback_data="owner:cancel_order"
            )
        ]
    ])

    await call.message.edit_text(
        "⚠️ <b>KONFIRMASI BATAL ORDER</b>\n\n"
        f"Invoice: <b>{invoice(order_id)}</b>\n"
        f"Status: <b>{order['status']}</b>\n"
        f"Pembayaran: <b>{order['payment_status']}</b>\n\n"
        "Jika dibatalkan, stok reservasi akan dilepas kembali.",
        reply_markup=kb,
        parse_mode="HTML"
    )
    await call.answer()


@router.callback_query(F.data.startswith("ownercancel:confirm:"))
async def owner_cancel_confirm(call: CallbackQuery, bot: Bot):
    if not is_owner(call.from_user.id):
        return await call.answer("Akses ditolak.", show_alert=True)

    order_id = int(call.data.split(":")[2])
    ok, message = await cancel_pending_order(order_id, bot)

    if ok:
        await call.message.edit_text(
            "✅ <b>ORDER DIBATALKAN</b>\n\n"
            f"Invoice: <b>{invoice(order_id)}</b>\n"
            "Reservasi stok sudah dilepas.",
            reply_markup=back_owner(),
            parse_mode="HTML"
        )
        await call.answer("Order dibatalkan.", show_alert=True)
    else:
        await call.answer(message, show_alert=True)


@router.callback_query(F.data == "owner:backup_now")
async def owner_backup_now(call: CallbackQuery, bot: Bot):
    if not is_owner(call.from_user.id):
        return await call.answer("Akses ditolak.", show_alert=True)

    try:
        backup_path = create_database_backup()
        await send_backup(bot, backup_path)
        await call.answer("✅ Backup berhasil dibuat.", show_alert=True)
    except Exception as exc:
        await call.answer(f"❌ Backup gagal: {str(exc)[:100]}", show_alert=True)


@router.callback_query(F.data == "owner:sync_stock")
async def owner_sync_stock(call: CallbackQuery, bot: Bot):
    if not is_owner(call.from_user.id):
        return await call.answer("Akses ditolak.", show_alert=True)

    if not STOCK_CHANNEL_ID:
        return await call.answer(
            "STOCK_CHANNEL_ID belum diisi di Railway.",
            show_alert=True
        )

    await sync_stock_channel(bot)
    await call.answer("✅ Stok channel disinkronkan.", show_alert=True)


@router.callback_query(F.data == "owner:stats")
async def owner_stats(call: CallbackQuery):
    if not is_owner(call.from_user.id):
        return await call.answer("Akses ditolak.", show_alert=True)

    conn = db()
    today = datetime.now().date().isoformat()

    products = conn.execute(
        "SELECT COUNT(*) AS n FROM products WHERE active=1"
    ).fetchone()["n"]
    variants = conn.execute(
        "SELECT COUNT(*) AS n FROM product_variants WHERE active=1"
    ).fetchone()["n"]
    stock = conn.execute(
        """SELECT COUNT(*) AS n FROM inventory_items WHERE status='available'"""
    ).fetchone()["n"]
    orders = conn.execute("SELECT COUNT(*) AS n FROM orders").fetchone()["n"]
    completed = conn.execute(
        "SELECT COUNT(*) AS n FROM orders WHERE status='completed'"
    ).fetchone()["n"]
    pending = conn.execute(
        "SELECT COUNT(*) AS n FROM orders WHERE status='pending'"
    ).fetchone()["n"]
    paid_pending = conn.execute(
        "SELECT COUNT(*) AS n FROM orders WHERE status='paid_pending_delivery'"
    ).fetchone()["n"]
    revenue = conn.execute(
        """SELECT COALESCE(SUM(payment_total),0) AS n
           FROM orders WHERE status='completed'"""
    ).fetchone()["n"]
    today_orders = conn.execute(
        """SELECT COUNT(*) AS n FROM orders
           WHERE substr(created_at,1,10)=?""",
        (today,)
    ).fetchone()["n"]
    today_revenue = conn.execute(
        """SELECT COALESCE(SUM(payment_total),0) AS n FROM orders
           WHERE status='completed' AND substr(completed_at,1,10)=?""",
        (today,)
    ).fetchone()["n"]
    users = conn.execute(
        "SELECT COUNT(*) AS n FROM verified_users WHERE active=1"
    ).fetchone()["n"]
    wallet_total = conn.execute(
        "SELECT COALESCE(SUM(balance),0) AS n FROM wallets"
    ).fetchone()["n"]
    reviews = conn.execute(
        "SELECT COUNT(*) AS n FROM reviews"
    ).fetchone()["n"]
    top_product = conn.execute(
        """SELECT name, sold FROM products
           WHERE active=1 ORDER BY sold DESC LIMIT 1"""
    ).fetchone()
    conn.close()

    await call.message.edit_text(
        "📊 <b>DASHBOARD OWNER</b>\n\n"
        "📅 <b>Hari Ini</b>\n"
        f"🧾 Order: <b>{today_orders}</b>\n"
        f"💰 Omzet: <b>{rupiah(today_revenue)}</b>\n\n"
        "📈 <b>Keseluruhan</b>\n"
        f"💰 Omzet: <b>{rupiah(revenue)}</b>\n"
        f"🧾 Total order: <b>{orders}</b>\n"
        f"✅ Selesai: <b>{completed}</b>\n"
        f"⏳ Pending bayar: <b>{pending}</b>\n"
        f"⚠️ Pending delivery: <b>{paid_pending}</b>\n\n"
        "📦 <b>Inventori</b>\n"
        f"Produk aktif: <b>{products}</b>\n"
        f"Variasi aktif: <b>{variants}</b>\n"
        f"Akun siap jual: <b>{stock}</b>\n"
        f"🔥 Terlaris: <b>{html.escape(top_product['name']) if top_product else '-'}</b>\n\n"
        "👥 <b>User & Saldo</b>\n"
        f"User terverifikasi: <b>{users}</b>\n"
        f"Total Saldo Kamu: <b>{rupiah(wallet_total)}</b>\n"
        f"⭐ Total ulasan: <b>{reviews}</b>\n\n"
        f"<i>{STORE_FOOTER}</i>",
        reply_markup=back_owner(),
        parse_mode="HTML"
    )
    await call.answer()

@router.callback_query(F.data == "owner:orders")
async def owner_orders(call: CallbackQuery):
    if not is_owner(call.from_user.id):
        return await call.answer("Akses ditolak.", show_alert=True)

    conn = db()
    rows = conn.execute("""
        SELECT o.*, p.name AS product_name, v.name AS variant_name
        FROM orders o
        JOIN products p ON p.id=o.product_id
        LEFT JOIN product_variants v ON v.id=o.variant_id
        ORDER BY o.id DESC
        LIMIT 15
    """).fetchall()
    conn.close()

    if not rows:
        text = f"🧾 <b>PESANAN</b>\n\nBelum ada order.\n\n<i>{STORE_FOOTER}</i>"
    else:
        lines = ["🧾 <b>PESANAN TERBARU</b>\n"]
        for row in rows:
            user = f"@{row['username']}" if row["username"] else str(row["user_id"])
            lines.append(
                f"<b>{invoice(row['id'])}</b> • {row['status'].upper()}\n"
                f"👤 {user}\n"
                f"📦 {row['product_name']} — {row['variant_name'] or 'Standard'}\n"
                f"🔢 {row['qty']} • 💰 {rupiah(row['total'])}\n"
                f"💳 Transfer: {rupiah(row['payment_total'] or row['total'])}\n"
            )
        lines.append(f"<i>{STORE_FOOTER}</i>")
        text = "\n".join(lines)

    await call.message.edit_text(text, reply_markup=back_owner(), parse_mode="HTML")
    await call.answer()


async def prompt_state(call, state, target_state, text):
    if not is_owner(call.from_user.id):
        return await call.answer("Akses ditolak.", show_alert=True)
    await state.set_state(target_state)
    await call.message.edit_text(text, reply_markup=back_owner(), parse_mode="HTML")
    await call.answer()


@router.callback_query(F.data == "owner:add_product")
async def owner_add_product(call: CallbackQuery, state: FSMContext):
    await prompt_state(
        call, state, OwnerState.add_product,
        "➕ <b>TAMBAH PRODUK</b>\n\n"
        "Kirim:\n<code>Nama | Harga Dasar | Stok | Deskripsi</code>\n\n"
        "Contoh:\n<code>Alight Motion | 5000 | 10 | Private akun</code>"
    )


@router.message(OwnerState.add_product)
async def owner_add_product_input(message: Message, state: FSMContext):
    if not is_owner(message.from_user.id):
        return
    try:
        name, price, stock, desc = [p.strip() for p in message.text.split("|", 3)]
        price, stock = int(price), int(stock)
        conn = db()
        cur = conn.execute(
            "INSERT INTO products(name, price, stock, description) VALUES(?,?,?,?)",
            (name, price, stock, desc)
        )
        pid = cur.lastrowid
        conn.execute(
            """INSERT INTO product_variants
               (product_id, name, code, price, stock)
               VALUES(?,?,?,?,?)""",
            (pid, "Standard", f"P{pid}", price, stock)
        )
        conn.commit()
        conn.close()
        await state.clear()
        await message.answer("✅ Produk berhasil ditambahkan.", reply_markup=owner_menu())
    except Exception:
        await message.answer("❌ Format salah. Gunakan: Nama | Harga | Stok | Deskripsi")


@router.callback_query(F.data == "owner:add_variant")
async def owner_add_variant(call: CallbackQuery, state: FSMContext):
    await prompt_state(
        call, state, OwnerState.add_variant,
        "🧩 <b>TAMBAH VARIASI</b>\n\n"
        "Kirim:\n"
        "<code>ID Produk | Nama Variasi | Kode | Harga | Stok | Grosir10 | Grosir20</code>\n\n"
        "Isi 0 jika tidak ada harga grosir.\n"
        "Contoh:\n<code>1 | Durasi 1 Tahun | am1th | 500 | 416 | 400 | 300</code>"
    )


@router.message(OwnerState.add_variant)
async def owner_add_variant_input(message: Message, state: FSMContext):
    if not is_owner(message.from_user.id):
        return
    try:
        pid, name, code, price, stock, g10, g20 = [p.strip() for p in message.text.split("|")]
        conn = db()
        conn.execute(
            """INSERT INTO product_variants
               (product_id, name, code, price, stock, wholesale10, wholesale20)
               VALUES(?,?,?,?,?,?,?)""",
            (int(pid), name, code, int(price), int(stock), int(g10), int(g20))
        )
        conn.commit()
        conn.close()
        await state.clear()
        await message.answer("✅ Variasi berhasil ditambahkan.", reply_markup=owner_menu())
    except Exception:
        await message.answer("❌ Format variasi tidak valid.")


def owner_stock_products_keyboard():
    conn = db()
    rows = conn.execute(
        "SELECT id, name FROM products WHERE active=1 ORDER BY id"
    ).fetchall()
    conn.close()

    kb = InlineKeyboardBuilder()
    for row in rows:
        kb.button(
            text=f"📦 {row['name']}",
            callback_data=f"ownerstock:product:{row['id']}"
        )
    kb.button(text="⬅️ Kembali", callback_data="owner:panel")
    kb.adjust(1)
    return kb.as_markup()


def owner_stock_variants_keyboard(product_id: int):
    conn = db()
    product = conn.execute("SELECT * FROM products WHERE id=?", (product_id,)).fetchone()
    rows = conn.execute(
        """SELECT * FROM product_variants
           WHERE product_id=? AND active=1
           ORDER BY id""",
        (product_id,)
    ).fetchall()
    conn.close()

    kb = InlineKeyboardBuilder()
    for row in rows:
        kb.button(
            text=f"{row['name']} • stok {available_stock(row)}",
            callback_data=f"ownerstock:variant:{row['id']}"
        )
    kb.button(text="⬅️ Pilih Produk", callback_data="owner:set_stock")
    kb.adjust(1)
    return (product, kb.as_markup())


def owner_stock_variant_actions(variant_id: int):
    kb = InlineKeyboardBuilder()
    kb.button(text="➕ Tambah Akun", callback_data=f"ownerstock:add:{variant_id}")
    kb.button(text="📣 Broadcast Restock", callback_data=f"ownerstock:broadcast:{variant_id}")
    kb.button(text="📤 Kirim Pending", callback_data=f"ownerstock:fulfill:{variant_id}")
    kb.button(text="⬅️ Kembali", callback_data=f"ownerstock:backvariant:{variant_id}")
    kb.adjust(1)
    return kb.as_markup()


@router.callback_query(F.data == "owner:set_stock")
async def owner_set_stock(call: CallbackQuery, state: FSMContext):
    if not is_owner(call.from_user.id):
        return await call.answer("Akses ditolak.", show_alert=True)
    await state.clear()
    await call.message.edit_text(
        "📦 <b>ATUR STOK</b>\n\n"
        "Pilih produk yang ingin diatur.\n"
        "Tidak perlu mengetik ID produk/variasi.",
        reply_markup=owner_stock_products_keyboard(),
        parse_mode="HTML"
    )
    await call.answer()


@router.callback_query(F.data.startswith("ownerstock:product:"))
async def owner_stock_product(call: CallbackQuery):
    if not is_owner(call.from_user.id):
        return await call.answer("Akses ditolak.", show_alert=True)

    product_id = int(call.data.split(":")[2])
    product, markup = owner_stock_variants_keyboard(product_id)

    if not product:
        return await call.answer("Produk tidak ditemukan.", show_alert=True)

    await call.message.edit_text(
        f"📦 <b>{product['name']}</b>\n\nPilih variasi:",
        reply_markup=markup,
        parse_mode="HTML"
    )
    await call.answer()


@router.callback_query(F.data.startswith("ownerstock:variant:"))
async def owner_stock_variant(call: CallbackQuery):
    if not is_owner(call.from_user.id):
        return await call.answer("Akses ditolak.", show_alert=True)

    variant_id = int(call.data.split(":")[2])
    conn = db()
    variant = conn.execute(
        """SELECT v.*, p.name AS product_name
           FROM product_variants v
           JOIN products p ON p.id=v.product_id
           WHERE v.id=?""",
        (variant_id,)
    ).fetchone()
    counts = inventory_counts(conn, variant_id) if variant else {"available": 0, "sold": 0}
    conn.close()

    if not variant:
        return await call.answer("Variasi tidak ditemukan.", show_alert=True)

    await call.message.edit_text(
        "📦 <b>DETAIL STOK</b>\n\n"
        f"Produk: <b>{variant['product_name']}</b>\n"
        f"Variasi: <b>{variant['name']}</b>\n"
        f"Stok tersedia: <b>{available_stock(variant)}</b>\n"
        f"Akun siap kirim: <b>{counts['available']}</b>\n"
        f"Akun sudah terjual: <b>{counts['sold']}</b>\n\n"
        "Gunakan <b>➕ Tambah Akun</b>. Jumlah stok mengikuti jumlah akun yang benar-benar tersedia.",
        reply_markup=owner_stock_variant_actions(variant_id),
        parse_mode="HTML"
    )
    await call.answer()


@router.callback_query(F.data.startswith("ownerstock:backvariant:"))
async def owner_stock_back_variant(call: CallbackQuery):
    variant_id = int(call.data.split(":")[2])
    conn = db()
    row = conn.execute("SELECT product_id FROM product_variants WHERE id=?", (variant_id,)).fetchone()
    conn.close()
    if not row:
        return await call.answer("Variasi tidak ditemukan.", show_alert=True)
    call.data = f"ownerstock:product:{row['product_id']}"
    await owner_stock_product(call)


@router.callback_query(F.data.startswith("ownerstock:add:"))
async def owner_stock_add(call: CallbackQuery, state: FSMContext):
    if not is_owner(call.from_user.id):
        return await call.answer("Akses ditolak.", show_alert=True)

    variant_id = int(call.data.split(":")[2])
    await state.update_data(stock_variant_id=variant_id)
    await state.set_state(OwnerState.stock_add_items)

    await call.message.edit_text(
        "➕ <b>TAMBAH AKUN PREMIUM</b>\n\n"
        "Kirim <b>1 akun per baris</b>.\n\n"
        "Contoh:\n"
        "<code>email1@gmail.com | password1\n"
        "email2@gmail.com | password2\n"
        "email3@gmail.com | password3</code>\n\n"
        "Setiap baris akan dianggap sebagai 1 stok yang dapat dikirim otomatis.",
        reply_markup=back_owner(),
        parse_mode="HTML"
    )
    await call.answer()


@router.message(OwnerState.stock_add_items)
async def owner_stock_add_input(message: Message, state: FSMContext, bot: Bot):
    if not is_owner(message.from_user.id):
        return

    data = await state.get_data()
    variant_id = int(data.get("stock_variant_id", 0))
    items = [line.strip() for line in (message.text or "").splitlines() if line.strip()]

    if not variant_id or not items:
        return await message.answer("❌ Tidak ada akun yang dapat ditambahkan.")

    conn = db()
    conn.execute("BEGIN IMMEDIATE")
    variant = conn.execute(
        "SELECT * FROM product_variants WHERE id=?",
        (variant_id,)
    ).fetchone()

    if not variant:
        conn.rollback()
        conn.close()
        await state.clear()
        return await message.answer("❌ Variasi tidak ditemukan.", reply_markup=owner_menu())

    old_available = available_stock(variant)
    product_id = int(variant["product_id"])

    now = datetime.now().isoformat(timespec="seconds")
    added = 0
    for content in items:
        # Prevent accidental exact duplicate credentials in the same variant.
        exists = conn.execute(
            """SELECT id FROM inventory_items
               WHERE variant_id=? AND content=?""",
            (variant_id, content)
        ).fetchone()
        if exists:
            continue

        conn.execute(
            """INSERT INTO inventory_items
               (variant_id, content, status, created_at)
               VALUES(?,?,'available',?)""",
            (variant_id, content, now)
        )
        added += 1

    sync_variant_stock_from_inventory(conn, variant_id)
    conn.commit()
    conn.close()

    await state.clear()
    await fulfill_pending_for_variant(variant_id, bot)

    conn = db()
    variant_after = conn.execute("SELECT * FROM product_variants WHERE id=?", (variant_id,)).fetchone()
    conn.close()

    new_available = available_stock(variant_after)

    if added > 0:
        inventory_log(variant_id, "RESTOCK", added, "OWNER", "Tambah akun stok")

    if added > 0 and old_available <= 0 and new_available > 0:
        asyncio.create_task(
            broadcast_restock_to_verified(
                bot,
                product_id,
                variant_id,
                new_available
            )
        )

    await message.answer(
        "✅ <b>STOK AKUN BERHASIL DITAMBAHKAN</b>\n\n"
        f"Ditambahkan: <b>{added}</b> akun\n"
        f"Stok tersedia sekarang: <b>{new_available}</b>\n\n"
        + (
            "📣 Restock Alert dikirim ke semua user terverifikasi karena stok berubah dari 0 menjadi tersedia.\n"
            if added > 0 and old_available <= 0 and new_available > 0
            else "ℹ️ Restock Alert tidak dikirim karena stok sebelumnya masih tersedia.\n"
        )
        + "Pesanan yang sudah dibayar tetapi menunggu akun juga sudah dicek otomatis.",
        reply_markup=owner_menu(),
        parse_mode="HTML"
    )


@router.callback_query(F.data.startswith("ownerstock:number:"))
async def owner_stock_number(call: CallbackQuery, state: FSMContext):
    if not is_owner(call.from_user.id):
        return await call.answer("Akses ditolak.", show_alert=True)

    await state.clear()
    await call.answer(
        "Set stok angka dinonaktifkan untuk mencegah stok tanpa akun. Gunakan ➕ Tambah Akun.",
        show_alert=True
    )


@router.callback_query(F.data.startswith("ownerstock:broadcast:"))
async def owner_stock_broadcast(call: CallbackQuery, bot: Bot):
    if not is_owner(call.from_user.id):
        return await call.answer("Akses ditolak.", show_alert=True)

    variant_id = int(call.data.split(":")[2])
    conn = db()
    variant = conn.execute(
        "SELECT * FROM product_variants WHERE id=? AND active=1",
        (variant_id,)
    ).fetchone()
    conn.close()

    if not variant:
        return await call.answer("Variasi tidak ditemukan.", show_alert=True)

    current_stock = available_stock(variant)
    if current_stock <= 0:
        return await call.answer(
            "Stok masih 0, broadcast restock tidak dikirim.",
            show_alert=True
        )

    await call.answer("📣 Broadcast restock dimulai.", show_alert=True)
    asyncio.create_task(
        broadcast_restock_to_verified(
            bot,
            int(variant["product_id"]),
            variant_id,
            current_stock
        )
    )


@router.callback_query(F.data.startswith("ownerstock:fulfill:"))
async def owner_stock_fulfill_pending(call: CallbackQuery, bot: Bot):
    if not is_owner(call.from_user.id):
        return await call.answer("Akses ditolak.", show_alert=True)

    variant_id = int(call.data.split(":")[2])
    await fulfill_pending_for_variant(variant_id, bot)
    await call.answer("✅ Pesanan pending sudah dicek.", show_alert=True)


def owner_variant_button_products_keyboard():
    conn = db()
    rows = conn.execute(
        "SELECT id, name FROM products WHERE active=1 ORDER BY id"
    ).fetchall()
    conn.close()

    kb = InlineKeyboardBuilder()
    for row in rows:
        kb.button(
            text=f"📦 {row['name']}",
            callback_data=f"ownerbtnname:product:{row['id']}"
        )
    kb.button(text="⬅️ Kembali", callback_data="owner:panel")
    kb.adjust(1)
    return kb.as_markup()


@router.callback_query(F.data == "owner:variant_button_name")
async def owner_variant_button_name(call: CallbackQuery, state: FSMContext):
    if not is_owner(call.from_user.id):
        return await call.answer("Akses ditolak.", show_alert=True)

    await state.clear()
    await call.message.edit_text(
        "🏷️ <b>NAMA TOMBOL VARIASI</b>\n\n"
        "Pilih produk.\n\n"
        "Nama ini hanya mengubah tulisan pada tombol variasi. "
        "Stok tetap ditampilkan otomatis dari database.",
        reply_markup=owner_variant_button_products_keyboard(),
        parse_mode="HTML"
    )
    await call.answer()


@router.callback_query(F.data.startswith("ownerbtnname:product:"))
async def owner_variant_button_product(call: CallbackQuery):
    if not is_owner(call.from_user.id):
        return await call.answer("Akses ditolak.", show_alert=True)

    product_id = int(call.data.split(":")[2])
    conn = db()
    product = conn.execute(
        "SELECT * FROM products WHERE id=? AND active=1",
        (product_id,)
    ).fetchone()
    rows = conn.execute(
        """SELECT * FROM product_variants
           WHERE product_id=? AND active=1
           ORDER BY id""",
        (product_id,)
    ).fetchall()
    conn.close()

    if not product:
        return await call.answer("Produk tidak ditemukan.", show_alert=True)

    kb = InlineKeyboardBuilder()
    for row in rows:
        label = variant_button_label(row)
        kb.button(
            text=f"🏷️ {label} ({available_stock(row)})",
            callback_data=f"ownerbtnname:variant:{row['id']}"
        )
    kb.button(text="⬅️ Pilih Produk", callback_data="owner:variant_button_name")
    kb.adjust(1)

    await call.message.edit_text(
        f"🏷️ <b>{product['name']}</b>\n\n"
        "Pilih variasi yang nama tombolnya ingin diubah:",
        reply_markup=kb.as_markup(),
        parse_mode="HTML"
    )
    await call.answer()


@router.callback_query(F.data.startswith("ownerbtnname:variant:"))
async def owner_variant_button_variant(call: CallbackQuery, state: FSMContext):
    if not is_owner(call.from_user.id):
        return await call.answer("Akses ditolak.", show_alert=True)

    variant_id = int(call.data.split(":")[2])
    conn = db()
    variant = conn.execute(
        """SELECT v.*, p.name AS product_name
           FROM product_variants v
           JOIN products p ON p.id=v.product_id
           WHERE v.id=?""",
        (variant_id,)
    ).fetchone()
    conn.close()

    if not variant:
        return await call.answer("Variasi tidak ditemukan.", show_alert=True)

    await state.update_data(button_name_variant_id=variant_id)
    await state.set_state(OwnerState.variant_button_name)

    current = variant_button_label(variant)
    await call.message.edit_text(
        "🏷️ <b>UBAH NAMA TOMBOL VARIASI</b>\n\n"
        f"Produk: <b>{variant['product_name']}</b>\n"
        f"Nama variasi asli: <b>{variant['name']}</b>\n"
        f"Nama tombol saat ini: <b>{html.escape(current)}</b>\n"
        f"Stok otomatis: <b>{available_stock(variant)}</b>\n\n"
        "Kirim nama tombol baru.\n"
        "Contoh: <code>1 Bulan</code>, <code>Private</code>, atau <code>Sharing 1P2U</code>.\n\n"
        "Kirim <code>RESET</code> untuk memakai nama variasi asli.",
        reply_markup=back_owner(),
        parse_mode="HTML"
    )
    await call.answer()


@router.message(OwnerState.variant_button_name)
async def owner_variant_button_name_input(message: Message, state: FSMContext):
    if not is_owner(message.from_user.id):
        return

    data = await state.get_data()
    variant_id = int(data.get("button_name_variant_id", 0))
    value = (message.text or "").strip()

    if not variant_id:
        await state.clear()
        return await message.answer(
            "❌ Variasi tidak ditemukan.",
            reply_markup=owner_menu()
        )

    if not value:
        return await message.answer("❌ Nama tombol tidak boleh kosong.")

    if len(value) > 40:
        return await message.answer(
            "❌ Nama tombol terlalu panjang. Maksimal 40 karakter."
        )

    button_label = "" if value.upper() == "RESET" else value

    conn = db()
    variant = conn.execute(
        "SELECT * FROM product_variants WHERE id=?",
        (variant_id,)
    ).fetchone()

    if not variant:
        conn.close()
        await state.clear()
        return await message.answer(
            "❌ Variasi tidak ditemukan.",
            reply_markup=owner_menu()
        )

    conn.execute(
        "UPDATE product_variants SET button_label=? WHERE id=?",
        (button_label, variant_id)
    )
    conn.commit()

    updated = conn.execute(
        "SELECT * FROM product_variants WHERE id=?",
        (variant_id,)
    ).fetchone()
    conn.close()

    await state.clear()

    await message.answer(
        "✅ <b>NAMA TOMBOL BERHASIL DIPERBARUI</b>\n\n"
        f"Nama tombol: <b>{html.escape(variant_button_label(updated))}</b>\n"
        f"Stok otomatis: <b>{available_stock(updated)}</b>\n\n"
        "Tombol user akan tampil seperti:\n"
        f"<code>{html.escape(variant_button_label(updated))} ({available_stock(updated)})</code>",
        reply_markup=owner_menu(),
        parse_mode="HTML"
    )


@router.callback_query(F.data == "owner:set_price")
async def owner_set_price(call: CallbackQuery, state: FSMContext):
    await prompt_state(
        call, state, OwnerState.set_price,
        "💰 <b>ATUR HARGA VARIASI</b>\n\n"
        "Kirim:\n<code>ID VARIASI | HARGA | GROSIR10 | GROSIR20</code>\n\n"
        "Contoh: <code>1 | 500 | 400 | 300</code>"
    )


@router.message(OwnerState.set_price)
async def owner_set_price_input(message: Message, state: FSMContext):
    if not is_owner(message.from_user.id):
        return
    try:
        vid, price, g10, g20 = [x.strip() for x in message.text.split("|")]
        conn = db()
        conn.execute(
            """UPDATE product_variants
               SET price=?, wholesale10=?, wholesale20=?
               WHERE id=?""",
            (int(price), int(g10), int(g20), int(vid))
        )
        conn.commit()
        conn.close()
        await state.clear()
        await message.answer("✅ Harga berhasil diperbarui.", reply_markup=owner_menu())
    except Exception:
        await message.answer("❌ Format salah.")


def owner_delete_products_keyboard():
    conn = db()
    rows = conn.execute(
        """SELECT p.id, p.name,
                  COUNT(v.id) AS variant_count
           FROM products p
           LEFT JOIN product_variants v
             ON v.product_id=p.id AND v.active=1
           WHERE p.active=1
           GROUP BY p.id, p.name
           ORDER BY p.id"""
    ).fetchall()
    conn.close()

    kb = InlineKeyboardBuilder()
    for row in rows:
        kb.button(
            text=f"🗑️ {row['name']} • {row['variant_count']} varian",
            callback_data=f"ownerdelete:select:{row['id']}"
        )
    kb.button(text="⬅️ Kembali", callback_data="owner:panel")
    kb.adjust(1)
    return kb.as_markup()


@router.callback_query(F.data == "owner:delete_product")
async def owner_delete_product(call: CallbackQuery, state: FSMContext):
    if not is_owner(call.from_user.id):
        return await call.answer("Akses ditolak.", show_alert=True)

    await state.clear()

    conn = db()
    total = conn.execute(
        "SELECT COUNT(*) AS n FROM products WHERE active=1"
    ).fetchone()["n"]
    conn.close()

    if int(total or 0) == 0:
        await call.message.edit_text(
            "🗑️ <b>HAPUS PRODUK</b>\n\nBelum ada produk aktif.",
            reply_markup=back_owner(),
            parse_mode="HTML"
        )
        return await call.answer()

    await call.message.edit_text(
        "🗑️ <b>HAPUS PRODUK</b>\n\n"
        "Pilih produk yang ingin dihapus dari toko.\n\n"
        "Produk menggunakan soft delete agar riwayat order lama tetap aman.",
        reply_markup=owner_delete_products_keyboard(),
        parse_mode="HTML"
    )
    await call.answer()


@router.callback_query(F.data.startswith("ownerdelete:select:"))
async def owner_delete_select(call: CallbackQuery):
    if not is_owner(call.from_user.id):
        return await call.answer("Akses ditolak.", show_alert=True)

    product_id = int(call.data.split(":")[2])
    conn = db()

    product = conn.execute(
        "SELECT * FROM products WHERE id=? AND active=1",
        (product_id,)
    ).fetchone()

    if not product:
        conn.close()
        return await call.answer("Produk tidak ditemukan.", show_alert=True)

    variants = conn.execute(
        """SELECT id, name, stock, reserved_stock
           FROM product_variants
           WHERE product_id=? AND active=1
           ORDER BY id""",
        (product_id,)
    ).fetchall()

    active_orders = conn.execute(
        """SELECT COUNT(*) AS n
           FROM orders
           WHERE product_id=?
             AND status IN ('pending','paid_pending_delivery')""",
        (product_id,)
    ).fetchone()["n"]

    inventory_left = conn.execute(
        """SELECT COUNT(*) AS n
           FROM inventory_items i
           JOIN product_variants v ON v.id=i.variant_id
           WHERE v.product_id=?
             AND i.status IN ('available','allocated')""",
        (product_id,)
    ).fetchone()["n"]

    conn.close()

    total_available = sum(
        max(0, int(v["stock"]) - int(v["reserved_stock"] or 0))
        for v in variants
    )

    warnings = []
    if int(active_orders or 0) > 0:
        warnings.append(f"⚠️ Order aktif/pending: <b>{active_orders}</b>")
    if int(inventory_left or 0) > 0:
        warnings.append(f"📦 Akun inventory tersisa: <b>{inventory_left}</b>")

    warning_text = "\n".join(warnings)
    if warning_text:
        warning_text = "\n" + warning_text + "\n"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="✅ Ya, Hapus Produk",
                callback_data=f"ownerdelete:confirm:{product_id}"
            )
        ],
        [
            InlineKeyboardButton(
                text="⬅️ Batal",
                callback_data="owner:delete_product"
            )
        ]
    ])

    await call.message.edit_text(
        "⚠️ <b>KONFIRMASI HAPUS PRODUK</b>\n\n"
        f"Produk: <b>{product['name']}</b>\n"
        f"Variasi aktif: <b>{len(variants)}</b>\n"
        f"Stok tersedia: <b>{total_available}</b>"
        f"{warning_text}\n"
        "Produk akan hilang dari menu user, tetapi riwayat order lama tetap tersimpan.",
        reply_markup=kb,
        parse_mode="HTML"
    )
    await call.answer()


@router.callback_query(F.data.startswith("ownerdelete:confirm:"))
async def owner_delete_confirm(call: CallbackQuery):
    if not is_owner(call.from_user.id):
        return await call.answer("Akses ditolak.", show_alert=True)

    product_id = int(call.data.split(":")[2])
    conn = db()
    conn.execute("BEGIN IMMEDIATE")

    product = conn.execute(
        "SELECT * FROM products WHERE id=? AND active=1",
        (product_id,)
    ).fetchone()

    if not product:
        conn.rollback()
        conn.close()
        return await call.answer(
            "Produk sudah tidak aktif atau tidak ditemukan.",
            show_alert=True
        )

    active_orders = conn.execute(
        """SELECT COUNT(*) AS n
           FROM orders
           WHERE product_id=?
             AND status IN ('pending','paid_pending_delivery')""",
        (product_id,)
    ).fetchone()["n"]

    if int(active_orders or 0) > 0:
        conn.rollback()
        conn.close()
        return await call.answer(
            f"Tidak bisa dihapus. Masih ada {active_orders} order aktif/pending.",
            show_alert=True
        )

    conn.execute(
        "UPDATE products SET active=0 WHERE id=?",
        (product_id,)
    )
    conn.execute(
        "UPDATE product_variants SET active=0 WHERE product_id=?",
        (product_id,)
    )
    conn.commit()
    conn.close()

    await call.message.edit_text(
        "✅ <b>PRODUK BERHASIL DIHAPUS DARI TOKO</b>\n\n"
        f"Produk: <b>{product['name']}</b>\n\n"
        "Produk dan semua variasinya sekarang nonaktif.\n"
        "Riwayat order dan data lama tetap aman.",
        reply_markup=back_owner(),
        parse_mode="HTML"
    )
    await call.answer("Produk berhasil dihapus dari toko.")


@router.callback_query(F.data == "owner:mark_popular")
async def owner_mark_popular(call: CallbackQuery, state: FSMContext):
    await prompt_state(
        call, state, OwnerState.mark_popular,
        "🔥 <b>PRODUK POPULER</b>\n\n"
        "Kirim:\n<code>ID PRODUK | 1/0</code>\n\n"
        "1 = tampilkan sebagai populer\n0 = matikan"
    )


@router.message(OwnerState.mark_popular)
async def owner_mark_popular_input(message: Message, state: FSMContext):
    if not is_owner(message.from_user.id):
        return
    try:
        pid, value = [x.strip() for x in message.text.split("|", 1)]
        conn = db()
        conn.execute("UPDATE products SET is_popular=? WHERE id=?", (1 if int(value) else 0, int(pid)))
        conn.commit()
        conn.close()
        await state.clear()
        await message.answer("✅ Status produk populer diperbarui.", reply_markup=owner_menu())
    except Exception:
        await message.answer("❌ Format salah. Contoh: 1 | 1")


@router.callback_query(F.data == "owner:mark_flash")
async def owner_mark_flash(call: CallbackQuery, state: FSMContext):
    await prompt_state(
        call, state, OwnerState.mark_flash,
        "⚡ <b>FLASH SALE</b>\n\n"
        "Kirim:\n<code>ID PRODUK | 1/0</code>\n\n"
        "1 = masuk Flash Sale\n0 = keluarkan"
    )


@router.message(OwnerState.mark_flash)
async def owner_mark_flash_input(message: Message, state: FSMContext):
    if not is_owner(message.from_user.id):
        return
    try:
        pid, value = [x.strip() for x in message.text.split("|", 1)]
        conn = db()
        conn.execute("UPDATE products SET is_flash_sale=? WHERE id=?", (1 if int(value) else 0, int(pid)))
        conn.commit()
        conn.close()
        await state.clear()
        await message.answer("✅ Status Flash Sale diperbarui.", reply_markup=owner_menu())
    except Exception:
        await message.answer("❌ Format salah. Contoh: 1 | 1")


@router.callback_query(F.data == "owner:add_voucher")
async def owner_add_voucher(call: CallbackQuery, state: FSMContext):
    if not is_owner(call.from_user.id):
        return await call.answer("Akses ditolak.", show_alert=True)

    await state.clear()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💵 Rp5.000", callback_data="vbuild:discount:5000"),
         InlineKeyboardButton(text="💵 Rp10.000", callback_data="vbuild:discount:10000")],
        [InlineKeyboardButton(text="💵 Rp20.000", callback_data="vbuild:discount:20000"),
         InlineKeyboardButton(text="💵 Rp50.000", callback_data="vbuild:discount:50000")],
        [InlineKeyboardButton(text="✏️ Nominal Lain", callback_data="vbuild:discount:custom")],
        [InlineKeyboardButton(text="⬅️ Kembali", callback_data="owner:panel")]
    ])
    await state.set_state(OwnerState.voucher_code)
    await call.message.edit_text(
        "🎁 <b>BUAT VOUCHER</b>\n\n"
        "Langkah 1 dari 7\n"
        "Kirim <b>kode voucher</b> terlebih dahulu.\n\n"
        "Contoh: <code>HEMAT10</code>\n\n"
        "Setelah kode dikirim, semua pengaturan berikutnya dipilih lewat tombol.",
        reply_markup=kb,
        parse_mode="HTML"
    )
    await call.answer()


@router.message(OwnerState.voucher_code)
async def voucher_code_input(message: Message, state: FSMContext):
    if not is_owner(message.from_user.id):
        return

    code = (message.text or "").strip().upper()
    if not code or len(code) > 30 or " " in code:
        return await message.answer("❌ Kode voucher tidak valid. Gunakan huruf/angka tanpa spasi.")

    conn = db()
    exists = conn.execute("SELECT id FROM vouchers WHERE code=?", (code,)).fetchone()
    conn.close()
    if exists:
        return await message.answer("❌ Kode voucher sudah ada.")

    await state.update_data(voucher_code=code)
    await state.set_state(None)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Rp5.000", callback_data="vbuild:discount:5000"),
         InlineKeyboardButton(text="Rp10.000", callback_data="vbuild:discount:10000")],
        [InlineKeyboardButton(text="Rp20.000", callback_data="vbuild:discount:20000"),
         InlineKeyboardButton(text="Rp50.000", callback_data="vbuild:discount:50000")],
        [InlineKeyboardButton(text="✏️ Nominal Lain", callback_data="vbuild:discount:custom")],
        [InlineKeyboardButton(text="❌ Batal", callback_data="owner:panel")]
    ])
    await message.answer(
        f"✅ Kode: <b>{html.escape(code)}</b>\n\n"
        "Langkah 2 dari 7\n"
        "Pilih nominal diskon:",
        reply_markup=kb,
        parse_mode="HTML"
    )


@router.callback_query(F.data.startswith("vbuild:discount:"))
async def voucher_build_discount(call: CallbackQuery, state: FSMContext):
    value = call.data.split(":")[2]
    if value == "custom":
        await state.set_state(OwnerState.voucher_discount)
        await call.message.edit_text(
            "✏️ <b>DISKON CUSTOM</b>\n\nKirim nominal diskon dalam angka.\nContoh: <code>15000</code>",
            reply_markup=back_owner(),
            parse_mode="HTML"
        )
        return await call.answer()

    await state.update_data(voucher_discount=int(value))
    await state.set_state(None)
    await voucher_minimum_menu(call, state)


@router.message(OwnerState.voucher_discount)
async def voucher_discount_input(message: Message, state: FSMContext):
    if not is_owner(message.from_user.id):
        return
    try:
        value = int((message.text or "").replace(".", "").strip())
        if value <= 0:
            raise ValueError
    except Exception:
        return await message.answer("❌ Nominal diskon tidak valid.")

    await state.update_data(voucher_discount=value)
    await state.set_state(None)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Tanpa Minimum", callback_data="vbuild:min:0")],
        [InlineKeyboardButton(text="Rp25.000", callback_data="vbuild:min:25000"),
         InlineKeyboardButton(text="Rp50.000", callback_data="vbuild:min:50000")],
        [InlineKeyboardButton(text="Rp100.000", callback_data="vbuild:min:100000"),
         InlineKeyboardButton(text="Rp200.000", callback_data="vbuild:min:200000")],
        [InlineKeyboardButton(text="✏️ Minimum Lain", callback_data="vbuild:min:custom")]
    ])
    await message.answer(
        "Langkah 3 dari 7\nPilih minimum transaksi:",
        reply_markup=kb
    )


async def voucher_minimum_menu(call: CallbackQuery, state: FSMContext):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Tanpa Minimum", callback_data="vbuild:min:0")],
        [InlineKeyboardButton(text="Rp25.000", callback_data="vbuild:min:25000"),
         InlineKeyboardButton(text="Rp50.000", callback_data="vbuild:min:50000")],
        [InlineKeyboardButton(text="Rp100.000", callback_data="vbuild:min:100000"),
         InlineKeyboardButton(text="Rp200.000", callback_data="vbuild:min:200000")],
        [InlineKeyboardButton(text="✏️ Minimum Lain", callback_data="vbuild:min:custom")]
    ])
    await call.message.edit_text(
        "Langkah 3 dari 7\nPilih minimum transaksi:",
        reply_markup=kb
    )
    await call.answer()


@router.callback_query(F.data.startswith("vbuild:min:"))
async def voucher_build_min(call: CallbackQuery, state: FSMContext):
    value = call.data.split(":")[2]
    if value == "custom":
        await state.set_state(OwnerState.voucher_min_spend)
        await call.message.edit_text(
            "✏️ <b>MINIMUM TRANSAKSI</b>\n\nKirim nominal minimum.",
            reply_markup=back_owner(),
            parse_mode="HTML"
        )
        return await call.answer()

    await state.update_data(voucher_min_spend=int(value))
    await state.set_state(None)
    await voucher_quota_menu(call, state)


@router.message(OwnerState.voucher_min_spend)
async def voucher_min_input(message: Message, state: FSMContext):
    if not is_owner(message.from_user.id):
        return
    try:
        value = max(0, int((message.text or "").replace(".", "").strip()))
    except Exception:
        return await message.answer("❌ Nominal tidak valid.")

    await state.update_data(voucher_min_spend=value)
    await state.set_state(None)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Tanpa Batas", callback_data="vbuild:quota:0")],
        [InlineKeyboardButton(text="10x", callback_data="vbuild:quota:10"),
         InlineKeyboardButton(text="25x", callback_data="vbuild:quota:25")],
        [InlineKeyboardButton(text="50x", callback_data="vbuild:quota:50"),
         InlineKeyboardButton(text="100x", callback_data="vbuild:quota:100")],
        [InlineKeyboardButton(text="✏️ Kuota Lain", callback_data="vbuild:quota:custom")]
    ])
    await message.answer("Langkah 4 dari 7\nPilih kuota voucher:", reply_markup=kb)


async def voucher_quota_menu(call: CallbackQuery, state: FSMContext):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Tanpa Batas", callback_data="vbuild:quota:0")],
        [InlineKeyboardButton(text="10x", callback_data="vbuild:quota:10"),
         InlineKeyboardButton(text="25x", callback_data="vbuild:quota:25")],
        [InlineKeyboardButton(text="50x", callback_data="vbuild:quota:50"),
         InlineKeyboardButton(text="100x", callback_data="vbuild:quota:100")],
        [InlineKeyboardButton(text="✏️ Kuota Lain", callback_data="vbuild:quota:custom")]
    ])
    await call.message.edit_text("Langkah 4 dari 7\nPilih kuota voucher:", reply_markup=kb)
    await call.answer()


@router.callback_query(F.data.startswith("vbuild:quota:"))
async def voucher_build_quota(call: CallbackQuery, state: FSMContext):
    value = call.data.split(":")[2]
    if value == "custom":
        await state.set_state(OwnerState.voucher_quota)
        await call.message.edit_text("Kirim jumlah kuota voucher.", reply_markup=back_owner())
        return await call.answer()

    await state.update_data(voucher_quota=int(value))
    await state.set_state(None)
    await voucher_peruser_menu(call, state)


@router.message(OwnerState.voucher_quota)
async def voucher_quota_input(message: Message, state: FSMContext):
    if not is_owner(message.from_user.id):
        return
    try:
        value = max(0, int((message.text or "").strip()))
    except Exception:
        return await message.answer("❌ Kuota tidak valid.")

    await state.update_data(voucher_quota=value)
    await state.set_state(None)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="1x / User", callback_data="vbuild:peruser:1"),
         InlineKeyboardButton(text="2x / User", callback_data="vbuild:peruser:2")],
        [InlineKeyboardButton(text="3x / User", callback_data="vbuild:peruser:3"),
         InlineKeyboardButton(text="5x / User", callback_data="vbuild:peruser:5")]
    ])
    await message.answer("Langkah 5 dari 7\nPilih limit per user:", reply_markup=kb)


async def voucher_peruser_menu(call: CallbackQuery, state: FSMContext):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="1x / User", callback_data="vbuild:peruser:1"),
         InlineKeyboardButton(text="2x / User", callback_data="vbuild:peruser:2")],
        [InlineKeyboardButton(text="3x / User", callback_data="vbuild:peruser:3"),
         InlineKeyboardButton(text="5x / User", callback_data="vbuild:peruser:5")]
    ])
    await call.message.edit_text("Langkah 5 dari 7\nPilih limit per user:", reply_markup=kb)
    await call.answer()


@router.callback_query(F.data.startswith("vbuild:peruser:"))
async def voucher_build_peruser(call: CallbackQuery, state: FSMContext):
    value = int(call.data.split(":")[2])
    await state.update_data(voucher_per_user=value)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="7 Hari", callback_data="vbuild:days:7"),
         InlineKeyboardButton(text="30 Hari", callback_data="vbuild:days:30")],
        [InlineKeyboardButton(text="90 Hari", callback_data="vbuild:days:90"),
         InlineKeyboardButton(text="Tanpa Kedaluwarsa", callback_data="vbuild:days:0")]
    ])
    await call.message.edit_text("Langkah 6 dari 7\nPilih masa aktif voucher:", reply_markup=kb)
    await call.answer()


@router.callback_query(F.data.startswith("vbuild:days:"))
async def voucher_build_days(call: CallbackQuery, state: FSMContext):
    days = int(call.data.split(":")[2])
    await state.update_data(voucher_days=days)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👥 Semua Pelanggan", callback_data="vbuild:new:0")],
        [InlineKeyboardButton(text="🆕 Pelanggan Baru Saja", callback_data="vbuild:new:1")],
    ])
    await call.message.edit_text(
        "Langkah 7 dari 7\nPilih target pelanggan:",
        reply_markup=kb
    )
    await call.answer()


@router.callback_query(F.data.startswith("vbuild:new:"))
async def voucher_build_finish(call: CallbackQuery, state: FSMContext):
    new_only = int(call.data.split(":")[2])
    data = await state.get_data()

    code = data.get("voucher_code")
    discount = int(data.get("voucher_discount", 0))
    min_spend = int(data.get("voucher_min_spend", 0))
    quota = int(data.get("voucher_quota", 0))
    per_user = int(data.get("voucher_per_user", 1))
    days = int(data.get("voucher_days", 0))

    if not code or discount <= 0:
        await state.clear()
        return await call.answer("Data voucher tidak lengkap.", show_alert=True)

    expires_at = ""
    if days > 0:
        expires_at = (datetime.now() + timedelta(days=days)).isoformat(timespec="seconds")

    conn = db()
    try:
        conn.execute(
            """INSERT INTO vouchers
               (code, discount, min_spend, max_discount, usage_limit,
                per_user_limit, expires_at, active, product_id, variant_id,
                new_user_only)
               VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (
                code, discount, min_spend, 0, quota,
                per_user, expires_at, 1, 0, 0, new_only
            )
        )
        conn.commit()
    except sqlite3.IntegrityError:
        conn.rollback()
        conn.close()
        await state.clear()
        return await call.answer("Kode voucher sudah ada.", show_alert=True)
    conn.close()
    await state.clear()

    await call.message.edit_text(
        "✅ <b>VOUCHER BERHASIL DIBUAT</b>\n\n"
        f"Kode: <b>{html.escape(code)}</b>\n"
        f"Diskon: <b>{rupiah(discount)}</b>\n"
        f"Minimum: <b>{rupiah(min_spend)}</b>\n"
        f"Kuota: <b>{quota or 'Tanpa batas'}</b>\n"
        f"Per user: <b>{per_user}x</b>\n"
        f"Masa aktif: <b>{days or 'Tanpa kedaluwarsa'}</b>\n"
        f"Target: <b>{'Pelanggan baru' if new_only else 'Semua pelanggan'}</b>",
        reply_markup=owner_menu(),
        parse_mode="HTML"
    )
    await call.answer("Voucher dibuat.")


@router.callback_query(F.data == "owner:complete_order")
async def owner_complete_order(call: CallbackQuery, state: FSMContext):
    await prompt_state(
        call, state, OwnerState.complete_order,
        "✅ <b>VERIFIKASI PEMBAYARAN</b>\n\n"
        "Kirim ID order / nomor invoice.\n"
        "Contoh MBY-000001 → <code>1</code>"
    )


@router.message(OwnerState.complete_order)
async def owner_complete_order_input(message: Message, state: FSMContext, bot: Bot):
    if not is_owner(message.from_user.id):
        return

    try:
        raw = message.text.strip().upper().replace("MBY-", "")
        order_id = int(raw)
    except Exception:
        return await message.answer("❌ ID order tidak valid.")

    conn = db()
    order = conn.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
    conn.close()

    if not order:
        return await message.answer("❌ Order tidak ditemukan.")

    if order["status"] == "completed" and order["fulfillment_status"] == "delivered":
        await state.clear()
        return await message.answer("ℹ️ Order sudah selesai dan akun sudah dikirim.", reply_markup=owner_menu())

    if order["status"] == "cancelled":
        await state.clear()
        return await message.answer(
            "❌ Order sudah dibatalkan dan tidak dapat diverifikasi.",
            reply_markup=owner_menu()
        )

    ok = await mark_order_paid(
        order_id,
        bot,
        int(order["payment_total"] or order["total"])
    )

    await state.clear()
    if ok:
        await message.answer(
            f"✅ {invoice(order_id)} berhasil diverifikasi.\n"
            "Stok dan status transaksi sudah diperbarui.",
            reply_markup=owner_menu()
        )
    else:
        await message.answer(
            "❌ Order gagal diselesaikan. Periksa stok/status transaksi.",
            reply_markup=owner_menu()
        )



# =========================
# PERSISTENT USER MENU
# =========================
@router.message(F.text == "🏷️ List Produk")
async def reply_menu_products(message: Message, bot: Bot):
    if not await is_channel_member(bot, message.from_user.id):
        return await send_join_required(message)

    mark_user_verified(message.from_user.id, message.from_user.username or "")

    conn = db()
    rows = conn.execute(
        "SELECT * FROM products WHERE active=1 ORDER BY id"
    ).fetchall()
    conn.close()

    if not rows:
        return await message.answer(
            f"🏷️ <b>LIST PRODUK</b>\n\nBelum ada produk aktif.\n\n<i>{STORE_FOOTER}</i>",
            reply_markup=user_reply_menu(),
            parse_mode="HTML"
        )

    lines = ["🏷️ <b>LIST PRODUK</b>", ""]
    for i, row in enumerate(rows, 1):
        lines.append(f"{i}. {html.escape(row['name'])}")
    lines.append("\nTekan nomor produk di keyboard bawah atau pilih tombol produk berikut.")

    await message.answer(
        "\n".join(lines),
        reply_markup=products_keyboard(""),
        parse_mode="HTML"
    )


@router.message(F.text == "🔥 Produk Populer")
async def reply_menu_popular(message: Message, bot: Bot):
    if not await is_channel_member(bot, message.from_user.id):
        return await send_join_required(message)

    conn = db()
    rows = conn.execute(
        "SELECT * FROM products WHERE active=1 AND is_popular=1 ORDER BY sold DESC, id"
    ).fetchall()
    conn.close()

    if not rows:
        return await message.answer(
            "🔥 <b>PRODUK POPULER</b>\n\nBelum ada produk populer.",
            reply_markup=user_reply_menu(),
            parse_mode="HTML"
        )

    kb = InlineKeyboardBuilder()
    lines = ["🔥 <b>PRODUK POPULER</b>", ""]
    for i, row in enumerate(rows, 1):
        lines.append(f"{i}. {html.escape(row['name'])}")
        kb.button(text=row["name"], callback_data=f"product:{row['id']}")
    kb.adjust(1)

    await message.answer("\n".join(lines), reply_markup=kb.as_markup(), parse_mode="HTML")


@router.message(F.text == "⚡ Flash Sale")
async def reply_menu_flash(message: Message, bot: Bot):
    if not await is_channel_member(bot, message.from_user.id):
        return await send_join_required(message)

    conn = db()
    rows = conn.execute(
        "SELECT * FROM products WHERE active=1 AND is_flash_sale=1 ORDER BY id"
    ).fetchall()
    conn.close()

    if not rows:
        return await message.answer(
            "⚡ <b>FLASH SALE</b>\n\nBelum ada produk Flash Sale.",
            reply_markup=user_reply_menu(),
            parse_mode="HTML"
        )

    kb = InlineKeyboardBuilder()
    lines = ["⚡ <b>FLASH SALE</b>", ""]
    for i, row in enumerate(rows, 1):
        lines.append(f"{i}. {html.escape(row['name'])}")
        kb.button(text=row["name"], callback_data=f"product:{row['id']}")
    kb.adjust(1)

    await message.answer("\n".join(lines), reply_markup=kb.as_markup(), parse_mode="HTML")


@router.message(F.text == "🎁 Voucher")
async def reply_menu_voucher(message: Message, bot: Bot):
    if not await is_channel_member(bot, message.from_user.id):
        return await send_join_required(message)

    await message.answer(
        "🎁 <b>VOUCHER</b>\n\n"
        "Voucher dapat digunakan saat checkout jika tersedia.\n"
        "Pilih produk terlebih dahulu untuk memulai pesanan.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🏷️ Lihat Produk", callback_data="products")]
        ]),
        parse_mode="HTML"
    )


@router.message(F.text == "📁 Laporan Stok")
async def reply_menu_stock(message: Message, bot: Bot):
    if not await is_channel_member(bot, message.from_user.id):
        return await send_join_required(message)

    conn = db()
    rows = conn.execute(
        """SELECT p.name AS product_name, v.name AS variant_name,
                  v.stock, v.reserved_stock
           FROM product_variants v
           JOIN products p ON p.id=v.product_id
           WHERE p.active=1 AND v.active=1
           ORDER BY p.id, v.id"""
    ).fetchall()
    conn.close()

    lines = ["📁 <b>LAPORAN STOK</b>", ""]
    if not rows:
        lines.append("Belum ada stok aktif.")
    else:
        for row in rows:
            stock = max(0, int(row["stock"]) - int(row["reserved_stock"] or 0))
            icon = "✅" if stock > 0 else "❌"
            lines.append(
                f"{icon} {html.escape(row['product_name'])} — "
                f"{html.escape(row['variant_name'])}: <b>{stock}</b>"
            )

    await message.answer(
        "\n".join(lines),
        reply_markup=user_reply_menu(),
        parse_mode="HTML"
    )


@router.message(F.text == "🧾 Pesanan Saya")
async def reply_menu_orders(message: Message, bot: Bot):
    if not await is_channel_member(bot, message.from_user.id):
        return await send_join_required(message)

    conn = db()
    rows = conn.execute(
        """SELECT * FROM orders
           WHERE user_id=?
           ORDER BY id DESC
           LIMIT 10""",
        (message.from_user.id,)
    ).fetchall()
    conn.close()

    if not rows:
        return await message.answer(
            "🧾 <b>PESANAN SAYA</b>\n\nBelum ada pesanan.",
            reply_markup=user_reply_menu(),
            parse_mode="HTML"
        )

    lines = ["🧾 <b>PESANAN SAYA</b>", ""]
    for row in rows:
        icon = "✅" if row["status"] == "completed" else "🟡"
        lines.append(
            f"{icon} <b>{invoice(row['id'])}</b>\n"
            f"   Status: {html.escape(row['status'])}\n"
            f"   Total: {rupiah(row['payment_total'] or row['total'])}"
        )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📩 Kirim Ulang Akun Terakhir", callback_data="resend:last")]
    ])

    await message.answer("\n\n".join(lines), reply_markup=kb, parse_mode="HTML")


@router.message(F.text == "💰 Isi Saldo")
async def reply_menu_wallet(message: Message, bot: Bot):
    if not await is_channel_member(bot, message.from_user.id):
        return await send_join_required(message)

    mark_user_verified(
        message.from_user.id,
        message.from_user.username or ""
    )

    balance = get_balance(message.from_user.id)
    minimum = get_min_topup()

    await message.answer(
        "💰 <b>ISI SALDO</b>\n\n"
        f"Saldo Kamu: <b>{rupiah(balance)}</b>\n"
        f"Minimum isi saldo: <b>{rupiah(minimum)}</b>\n\n"
        "Pilih nominal cepat atau atur nominal sendiri:",
        reply_markup=topup_amount_keyboard(minimum),
        parse_mode="HTML"
    )


@router.message(F.text.regexp(r"^\d{1,2}$"))
async def reply_menu_product_number(message: Message, bot: Bot):
    if not await is_channel_member(bot, message.from_user.id):
        return await send_join_required(message)

    mark_user_verified(
        message.from_user.id,
        message.from_user.username or ""
    )

    try:
        index = int((message.text or "").strip())
    except Exception:
        return

    if index < 1:
        return await message.answer(
            "❌ Nomor produk tidak valid.",
            reply_markup=user_reply_menu()
        )

    conn = db()
    products = conn.execute(
        "SELECT id, name FROM products WHERE active=1 ORDER BY id LIMIT 25"
    ).fetchall()

    if index > len(products):
        conn.close()
        return await message.answer(
            "❌ Nomor produk tidak tersedia. Tekan 🏷️ List Produk untuk melihat daftar terbaru.",
            reply_markup=user_reply_menu()
        )

    product_id = int(products[index - 1]["id"])
    product = conn.execute(
        "SELECT * FROM products WHERE id=? AND active=1",
        (product_id,)
    ).fetchone()
    variants = conn.execute(
        """SELECT *
           FROM product_variants
           WHERE product_id=? AND active=1
           ORDER BY id""",
        (product_id,)
    ).fetchall()
    conn.close()

    if not product:
        return await message.answer(
            "❌ Produk sudah tidak tersedia.",
            reply_markup=user_reply_menu()
        )

    text = (
        "╭────────────────────╮\n"
        f"• <b>Produk:</b> {html.escape(product['name'])}\n"
        f"• <b>Terjual:</b> {int(product['sold'] or 0)}\n"
        f"• <b>Deskripsi:</b> {html.escape(product['description'] or '-')}\n"
        "╰────────────────────╯\n\n"
        "╭────────────────────╮\n"
        "📦 <b>VARIASI • HARGA • STOK</b>\n"
    )

    kb = InlineKeyboardBuilder()

    if variants:
        for idx, variant in enumerate(variants, start=1):
            stock = available_stock(variant)
            icon = "✅" if stock > 0 else "❌"
            text += (
                f"\n{idx}. <b>{html.escape(variant['name'])}</b>\n"
                f"   💰 Harga: <b>{rupiah(variant['price'])}</b>\n"
                f"   {icon} Stok: <b>{stock}</b>\n"
            )

            kb.button(
                text=f"{variant_button_label(variant)} ({stock})",
                callback_data=f"variant:{variant['id']}"
            )
    else:
        text += "\n<i>Belum ada variasi aktif.</i>\n"

    text += (
        "\n╰────────────────────╯\n\n"
        f"<i>{STORE_FOOTER}</i>\n\n"
        "Pilih variasi:"
    )

    kb.adjust(1)

    await message.answer(
        text,
        reply_markup=kb.as_markup(),
        parse_mode="HTML"
    )


@router.message(F.text == "❓ Cara Order")
async def reply_menu_howto(message: Message):
    await message.answer(
        "❓ <b>CARA ORDER</b>\n\n"
        "1. Pilih List Produk.\n"
        "2. Pilih produk dan variasi.\n"
        "3. Tentukan jumlah.\n"
        "4. Isi catatan jika diperlukan.\n"
        "5. Pilih metode pembayaran.\n"
        "6. Selesaikan pembayaran.\n"
        "7. Setelah pembayaran valid, akun premium dikirim otomatis.\n\n"
        f"<i>{STORE_FOOTER}</i>",
        reply_markup=user_reply_menu(),
        parse_mode="HTML"
    )


@router.message(F.text == "💬 Hubungi Owner")
async def reply_menu_owner_contact(message: Message):
    if ADMIN_USERNAME:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="💬 Chat Owner",
                    url=f"https://t.me/{ADMIN_USERNAME}"
                )
            ]
        ])
        await message.answer(
            "💬 <b>HUBUNGI OWNER</b>\n\n"
            "Tekan tombol di bawah untuk menghubungi owner.",
            reply_markup=kb,
            parse_mode="HTML"
        )
    else:
        await message.answer(
            "💬 Username owner belum dikonfigurasi.",
            reply_markup=user_reply_menu()
        )



@router.callback_query(F.data.startswith("rate:"))
async def submit_rating(call: CallbackQuery):
    try:
        _, order_id, stars = call.data.split(":")
        order_id, stars = int(order_id), int(stars)
    except Exception:
        return await call.answer("Rating tidak valid.", show_alert=True)

    if stars < 1 or stars > 5:
        return await call.answer("Rating tidak valid.", show_alert=True)

    conn = db()
    order = conn.execute(
        "SELECT * FROM orders WHERE id=? AND user_id=? AND status='completed'",
        (order_id, call.from_user.id)
    ).fetchone()
    if not order:
        conn.close()
        return await call.answer("Pesanan tidak ditemukan.", show_alert=True)

    exists = conn.execute(
        "SELECT id FROM reviews WHERE order_id=?",
        (order_id,)
    ).fetchone()
    if exists:
        conn.close()
        return await call.answer("Pesanan ini sudah dinilai.", show_alert=True)

    conn.execute(
        """INSERT INTO reviews(order_id,user_id,product_id,rating,comment,created_at)
           VALUES(?,?,?,?,?,?)""",
        (
            order_id, call.from_user.id, order["product_id"], stars, "",
            datetime.now().isoformat(timespec="seconds")
        )
    )
    stats = conn.execute(
        "SELECT AVG(rating) AS avg_rating, COUNT(*) AS n FROM reviews WHERE product_id=?",
        (order["product_id"],)
    ).fetchone()
    conn.execute(
        "UPDATE products SET rating=?, rating_count=? WHERE id=?",
        (float(stats["avg_rating"] or 0), int(stats["n"] or 0), order["product_id"])
    )
    conn.commit()
    conn.close()

    await call.message.edit_text(
        f"⭐ <b>Terima kasih!</b>\n\nPenilaian Anda: <b>{stars}/5</b>",
        parse_mode="HTML"
    )
    await call.answer("Rating tersimpan.")


@router.callback_query(F.data == "owner:low_stock")
async def owner_low_stock(call: CallbackQuery, state: FSMContext):
    if not is_owner(call.from_user.id):
        return await call.answer("Akses ditolak.", show_alert=True)
    current = low_stock_threshold()
    await state.set_state(OwnerState.low_stock_threshold)
    await call.message.edit_text(
        "🔔 <b>ALERT STOK MENIPIS</b>\n\n"
        f"Batas saat ini: <b>{current}</b>\n\n"
        "Kirim angka batas stok.\n"
        "Contoh: <code>5</code>\n"
        "Kirim <code>0</code> untuk menonaktifkan alert.",
        reply_markup=back_owner(),
        parse_mode="HTML"
    )
    await call.answer()


@router.message(OwnerState.low_stock_threshold)
async def owner_low_stock_input(message: Message, state: FSMContext):
    if not is_owner(message.from_user.id):
        return
    try:
        value = int((message.text or "").strip())
        if value < 0 or value > 999:
            raise ValueError
    except Exception:
        return await message.answer("❌ Masukkan angka 0–999.")

    set_setting("low_stock_threshold", str(value))
    await state.clear()
    await message.answer(
        f"✅ Alert stok menipis diset ke <b>{value}</b>.",
        reply_markup=owner_menu(),
        parse_mode="HTML"
    )


@router.callback_query(F.data == "owner:inventory_log")
async def owner_inventory_log(call: CallbackQuery):
    if not is_owner(call.from_user.id):
        return await call.answer("Akses ditolak.", show_alert=True)

    conn = db()
    rows = conn.execute(
        """SELECT l.*, v.name AS variant_name, p.name AS product_name
           FROM inventory_logs l
           JOIN product_variants v ON v.id=l.variant_id
           JOIN products p ON p.id=v.product_id
           ORDER BY l.id DESC LIMIT 25"""
    ).fetchall()
    conn.close()

    lines = ["📚 <b>RIWAYAT STOK</b>", ""]
    if not rows:
        lines.append("Belum ada log stok.")
    else:
        for row in rows:
            sign = "+" if int(row["qty"]) > 0 else ""
            lines.append(
                f"{row['created_at'][:16]} • {html.escape(row['action'])}\n"
                f"{html.escape(row['product_name'])} — {html.escape(row['variant_name'])}\n"
                f"{sign}{row['qty']} • {html.escape(row['reference'] or '-')}"
            )

    await call.message.edit_text(
        "\n\n".join(lines),
        reply_markup=back_owner(),
        parse_mode="HTML"
    )
    await call.answer()


@router.callback_query(F.data == "owner:security")
async def owner_security(call: CallbackQuery, state: FSMContext):
    if not is_owner(call.from_user.id):
        return await call.answer("Akses ditolak.", show_alert=True)

    await state.clear()
    conn = db()
    rows = conn.execute(
        """SELECT u.user_id, u.risk_score, u.blocked, u.last_reason,
                  v.username
           FROM user_security u
           LEFT JOIN verified_users v ON v.user_id=u.user_id
           ORDER BY u.blocked DESC, u.risk_score DESC
           LIMIT 25"""
    ).fetchall()
    conn.close()

    kb = InlineKeyboardBuilder()
    for row in rows:
        label = row["username"] or str(row["user_id"])
        icon = "🚫" if int(row["blocked"] or 0) else "⚠️"
        kb.button(
            text=f"{icon} {label} • Risk {row['risk_score']}",
            callback_data=f"securityuser:{row['user_id']}"
        )
    kb.button(text="⬅️ Kembali", callback_data="owner:panel")
    kb.adjust(1)

    await call.message.edit_text(
        "🛡️ <b>ANTI-FRAUD</b>\n\n"
        f"Max invoice pending: <b>{setting_int('fraud_pending_limit',3)}</b>\n"
        f"Cooldown checkout: <b>{setting_int('fraud_cooldown_seconds',8)} detik</b>\n\n"
        "Pilih user untuk block/unblock:",
        reply_markup=kb.as_markup(),
        parse_mode="HTML"
    )
    await call.answer()


@router.callback_query(F.data.startswith("securityuser:"))
async def owner_security_user_toggle(call: CallbackQuery):
    if not is_owner(call.from_user.id):
        return await call.answer("Akses ditolak.", show_alert=True)

    user_id = int(call.data.split(":")[1])
    now = datetime.now().isoformat(timespec="seconds")

    conn = db()
    row = conn.execute("SELECT * FROM user_security WHERE user_id=?", (user_id,)).fetchone()
    new_blocked = 0 if row and int(row["blocked"] or 0) else 1
    conn.execute(
        """INSERT INTO user_security(user_id,blocked,risk_score,strikes,last_reason,updated_at)
           VALUES(?,?,?,?,?,?)
           ON CONFLICT(user_id) DO UPDATE SET
             blocked=excluded.blocked,
             last_reason=excluded.last_reason,
             updated_at=excluded.updated_at""",
        (
            user_id, new_blocked,
            int(row["risk_score"] or 0) if row else 0,
            int(row["strikes"] or 0) if row else 0,
            "Manual owner block" if new_blocked else "Manual owner unblock",
            now
        )
    )
    conn.commit()
    conn.close()

    await call.answer(
        "🚫 User diblokir." if new_blocked else "✅ User dibuka kembali.",
        show_alert=True
    )
    await call.message.edit_text("✅ Status user diperbarui.", reply_markup=owner_menu())


@router.callback_query(F.data == "owner:reviews")
async def owner_reviews(call: CallbackQuery):
    if not is_owner(call.from_user.id):
        return await call.answer("Akses ditolak.", show_alert=True)

    conn = db()
    rows = conn.execute(
        """SELECT r.*, p.name AS product_name
           FROM reviews r
           JOIN products p ON p.id=r.product_id
           ORDER BY r.id DESC LIMIT 20"""
    ).fetchall()
    conn.close()

    lines = ["⭐ <b>ULASAN TERBARU</b>", ""]
    if not rows:
        lines.append("Belum ada ulasan.")
    else:
        for row in rows:
            lines.append(
                f"{'⭐' * int(row['rating'])} • {html.escape(row['product_name'])}\n"
                f"Order {invoice(row['order_id'])} • User <code>{row['user_id']}</code>"
            )

    await call.message.edit_text(
        "\n\n".join(lines),
        reply_markup=back_owner(),
        parse_mode="HTML"
    )
    await call.answer()



@router.callback_query(F.data == "owner:wallet_reject")
async def owner_wallet_reject(call: CallbackQuery, state: FSMContext):
    if not is_owner(call.from_user.id):
        return await call.answer("Akses ditolak.", show_alert=True)

    await state.clear()
    conn = db()
    rows = conn.execute(
        "SELECT * FROM topups WHERE status='pending' ORDER BY id DESC LIMIT 20"
    ).fetchall()
    conn.close()

    kb = InlineKeyboardBuilder()
    for row in rows:
        kb.button(
            text=f"❌ {topup_invoice(row['id'])} • {rupiah(row['payment_total'])}",
            callback_data=f"topupreject:{row['id']}"
        )
    kb.button(text="⬅️ Kembali", callback_data="owner:wallet")
    kb.adjust(1)

    await call.message.edit_text(
        "❌ <b>TOLAK TOP UP</b>\n\nPilih invoice:",
        reply_markup=kb.as_markup(),
        parse_mode="HTML"
    )
    await call.answer()


@router.callback_query(F.data.startswith("topupreject:"))
async def owner_wallet_reject_choose(call: CallbackQuery):
    if not is_owner(call.from_user.id):
        return await call.answer("Akses ditolak.", show_alert=True)

    topup_id = int(call.data.split(":")[1])
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Bukti Tidak Valid", callback_data=f"topuprejectreason:{topup_id}:invalid")],
        [InlineKeyboardButton(text="Nominal Tidak Sesuai", callback_data=f"topuprejectreason:{topup_id}:amount")],
        [InlineKeyboardButton(text="Pembayaran Tidak Ditemukan", callback_data=f"topuprejectreason:{topup_id}:notfound")],
        [InlineKeyboardButton(text="Dibatalkan Owner", callback_data=f"topuprejectreason:{topup_id}:owner")],
        [InlineKeyboardButton(text="⬅️ Kembali", callback_data="owner:wallet_reject")]
    ])
    await call.message.edit_text(
        "Pilih alasan penolakan:",
        reply_markup=kb
    )
    await call.answer()


@router.callback_query(F.data.startswith("topuprejectreason:"))
async def owner_wallet_reject_reason(call: CallbackQuery, bot: Bot):
    if not is_owner(call.from_user.id):
        return await call.answer("Akses ditolak.", show_alert=True)

    _, topup_id, reason_code = call.data.split(":")
    topup_id = int(topup_id)
    reasons = {
        "invalid": "Bukti pembayaran tidak valid",
        "amount": "Nominal pembayaran tidak sesuai",
        "notfound": "Pembayaran tidak ditemukan",
        "owner": "Dibatalkan oleh owner",
    }
    reason = reasons.get(reason_code, "Top up ditolak")

    conn = db()
    row = conn.execute(
        "SELECT * FROM topups WHERE id=? AND status='pending'",
        (topup_id,)
    ).fetchone()
    if not row:
        conn.close()
        return await call.answer("Top up sudah diproses / tidak ditemukan.", show_alert=True)

    conn.execute(
        """UPDATE topups
           SET status='rejected', reject_reason=?, verified_at=?, verified_by=?
           WHERE id=? AND status='pending'""",
        (
            reason,
            datetime.now().isoformat(timespec="seconds"),
            call.from_user.id,
            topup_id
        )
    )
    conn.commit()
    conn.close()

    try:
        await bot.send_message(
            row["user_id"],
            "❌ <b>TOP UP DITOLAK</b>\n\n"
            f"🧾 {topup_invoice(topup_id)}\n"
            f"Alasan: <b>{html.escape(reason)}</b>\n\n"
            "Saldo tidak berubah.",
            parse_mode="HTML"
        )
    except Exception:
        pass

    await call.answer("Top up ditolak.", show_alert=True)
    await call.message.edit_text("✅ Top up selesai diproses.", reply_markup=owner_wallet_menu())



@router.callback_query(F.data == "owner:selftest")
async def owner_selftest(call: CallbackQuery, bot: Bot):
    if not is_owner(call.from_user.id):
        return await call.answer("Akses ditolak.", show_alert=True)

    results = await run_system_self_test(bot)
    lines=["🧪 <b>TEST SISTEM</b>",""]
    for name, ok, detail in results:
        lines.append(f"{'✅' if ok else '❌'} <b>{html.escape(name)}</b>: {html.escape(str(detail))}")

    await call.message.edit_text(
        "\n".join(lines),
        reply_markup=back_owner(),
        parse_mode="HTML"
    )
    await call.answer()


@router.callback_query(F.data == "owner:maintenance")
async def owner_maintenance(call: CallbackQuery):
    if not is_owner(call.from_user.id):
        return await call.answer("Akses ditolak.", show_alert=True)

    new_value = "0" if maintenance_enabled() else "1"
    set_setting("maintenance_mode", new_value)
    status = "ON" if new_value == "1" else "OFF"

    await call.message.edit_text(
        "🔧 <b>MAINTENANCE MODE</b>\n\n"
        f"Status sekarang: <b>{status}</b>\n\n"
        "Saat ON, menu tetap dapat dilihat tetapi checkout baru ditahan.",
        reply_markup=owner_menu(),
        parse_mode="HTML"
    )
    await call.answer(f"Maintenance {status}")


@router.callback_query(F.data == "owner:segments")
async def owner_segments(call: CallbackQuery):
    if not is_owner(call.from_user.id):
        return await call.answer("Akses ditolak.", show_alert=True)

    counts = {}
    for key in ["new","buyers","returning","vip","inactive","all"]:
        counts[key]=len(segment_user_ids(key))

    await call.message.edit_text(
        "👥 <b>SEGMENTASI USER</b>\n\n"
        f"🆕 User baru: <b>{counts['new']}</b>\n"
        f"🛍️ Pernah belanja: <b>{counts['buyers']}</b>\n"
        f"🔁 Returning: <b>{counts['returning']}</b>\n"
        f"👑 VIP: <b>{counts['vip']}</b>\n"
        f"💤 Inaktif ≥30 hari: <b>{counts['inactive']}</b>\n"
        f"👥 Semua user aktif: <b>{counts['all']}</b>",
        reply_markup=back_owner(),
        parse_mode="HTML"
    )
    await call.answer()


@router.callback_query(F.data == "owner:broadcast")
async def owner_broadcast(call: CallbackQuery):
    if not is_owner(call.from_user.id):
        return await call.answer("Akses ditolak.", show_alert=True)

    kb=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👥 Semua User",callback_data="broadcastseg:all")],
        [InlineKeyboardButton(text="🛍️ Pernah Belanja",callback_data="broadcastseg:buyers")],
        [InlineKeyboardButton(text="🔁 Returning Buyer",callback_data="broadcastseg:returning")],
        [InlineKeyboardButton(text="👑 VIP",callback_data="broadcastseg:vip")],
        [InlineKeyboardButton(text="💤 Inaktif",callback_data="broadcastseg:inactive")],
        [InlineKeyboardButton(text="🆕 User Baru",callback_data="broadcastseg:new")],
        [InlineKeyboardButton(text="⬅️ Kembali",callback_data="owner:panel")],
    ])
    await call.message.edit_text(
        "📣 <b>BROADCAST</b>\n\nPilih target penerima:",
        reply_markup=kb,
        parse_mode="HTML"
    )
    await call.answer()


@router.callback_query(F.data.startswith("broadcastseg:"))
async def owner_broadcast_segment(call: CallbackQuery, state: FSMContext):
    if not is_owner(call.from_user.id):
        return await call.answer("Akses ditolak.", show_alert=True)
    segment=call.data.split(":")[1]
    await state.update_data(broadcast_segment=segment)
    await state.set_state(BroadcastState.waiting_message)
    await call.message.edit_text(
        "📣 <b>ISI BROADCAST</b>\n\n"
        "Kirim pesan yang ingin dikirim ke segmen terpilih.\n"
        "Ini satu-satunya bagian yang perlu diketik karena isi pesan bersifat bebas.",
        reply_markup=back_owner(),
        parse_mode="HTML"
    )
    await call.answer()


@router.message(BroadcastState.waiting_message)
async def owner_broadcast_message(message: Message, state: FSMContext, bot: Bot):
    if not is_owner(message.from_user.id):
        return
    data=await state.get_data()
    segment=data.get("broadcast_segment","all")
    content=(message.text or "").strip()
    if not content:
        return await message.answer("❌ Pesan kosong.")

    ids=segment_user_ids(segment)
    sent=failed=0
    for uid in ids:
        if uid==ADMIN_ID:
            continue
        try:
            await bot.send_message(
                uid,
                "📣 <b>MABOYY DIGITAL</b>\n\n"+html.escape(content)+"\n\n"+f"<i>{STORE_FOOTER}</i>",
                parse_mode="HTML"
            )
            sent+=1
        except TelegramRetryAfter as exc:
            await asyncio.sleep(float(exc.retry_after))
            try:
                await bot.send_message(uid, html.escape(content), parse_mode="HTML")
                sent+=1
            except Exception:
                failed+=1
        except TelegramForbiddenError:
            failed+=1
            conn=db()
            conn.execute("UPDATE verified_users SET active=0 WHERE user_id=?",(uid,))
            conn.commit(); conn.close()
        except Exception:
            failed+=1

    conn=db()
    conn.execute(
        """INSERT INTO broadcast_log(segment,sent_count,failed_count,message_preview,created_at)
           VALUES(?,?,?,?,?)""",
        (segment,sent,failed,content[:150],datetime.now().isoformat(timespec="seconds"))
    )
    conn.commit(); conn.close()
    await state.clear()
    await message.answer(
        f"✅ Broadcast selesai.\nTerkirim: {sent}\nGagal: {failed}",
        reply_markup=owner_menu()
    )


@router.callback_query(F.data == "owner:auto_promo")
async def owner_auto_promo(call: CallbackQuery):
    if not is_owner(call.from_user.id):
        return await call.answer("Akses ditolak.", show_alert=True)

    current=setting_int("cashback_percent",0)
    kb=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="OFF",callback_data="cashback:0"),
         InlineKeyboardButton(text="2%",callback_data="cashback:2"),
         InlineKeyboardButton(text="5%",callback_data="cashback:5"),
         InlineKeyboardButton(text="10%",callback_data="cashback:10")],
        [InlineKeyboardButton(text="⬅️ Kembali",callback_data="owner:panel")]
    ])
    await call.message.edit_text(
        "🎯 <b>PROMO OTOMATIS</b>\n\n"
        f"Cashback order selesai saat ini: <b>{current}%</b>\n\n"
        "Pilih persentase cashback otomatis ke Saldo Kamu:",
        reply_markup=kb,
        parse_mode="HTML"
    )
    await call.answer()


@router.callback_query(F.data.startswith("cashback:"))
async def owner_cashback_set(call: CallbackQuery):
    if not is_owner(call.from_user.id):
        return await call.answer("Akses ditolak.",show_alert=True)
    value=max(0,min(50,int(call.data.split(":")[1])))
    set_setting("cashback_percent",str(value))
    await call.answer(f"Cashback {value}% aktif." if value else "Cashback dimatikan.",show_alert=True)
    await call.message.edit_text(
        f"🎯 Cashback otomatis: <b>{value}%</b>",
        reply_markup=owner_menu(),
        parse_mode="HTML"
    )


@router.callback_query(F.data == "owner:daily_report")
async def owner_daily_report(call: CallbackQuery, bot: Bot):
    if not is_owner(call.from_user.id):
        return await call.answer("Akses ditolak.",show_alert=True)

    enabled=get_setting("daily_report_enabled","1")=="1"
    kb=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=("🔕 Matikan Laporan" if enabled else "🔔 Aktifkan Laporan"),
            callback_data="dailyreport:toggle"
        )],
        [InlineKeyboardButton(text="📨 Kirim Laporan Sekarang",callback_data="dailyreport:send")],
        [InlineKeyboardButton(text="⬅️ Kembali",callback_data="owner:panel")]
    ])
    await call.message.edit_text(
        "📅 <b>LAPORAN HARIAN</b>\n\n"
        f"Status: <b>{'ON' if enabled else 'OFF'}</b>\n"
        f"Jam laporan: sekitar <b>{setting_int('daily_report_hour',20):02d}:00</b>",
        reply_markup=kb,
        parse_mode="HTML"
    )
    await call.answer()


@router.callback_query(F.data == "dailyreport:toggle")
async def owner_daily_report_toggle(call: CallbackQuery):
    enabled=get_setting("daily_report_enabled","1")=="1"
    set_setting("daily_report_enabled","0" if enabled else "1")
    await call.answer("Pengaturan laporan diperbarui.",show_alert=True)
    await call.message.edit_text("✅ Pengaturan laporan harian diperbarui.",reply_markup=owner_menu())


@router.callback_query(F.data == "dailyreport:send")
async def owner_daily_report_send(call: CallbackQuery, bot: Bot):
    await send_daily_owner_report(bot)
    await call.answer("Laporan dikirim ke PM owner.",show_alert=True)



@router.callback_query(F.data == "owner:bundles")
async def owner_bundles(call: CallbackQuery):
    if not is_owner(call.from_user.id):
        return await call.answer("Akses ditolak.",show_alert=True)

    conn=db()
    rows=conn.execute("SELECT * FROM products WHERE active=1 ORDER BY id LIMIT 30").fetchall()
    conn.close()
    kb=InlineKeyboardBuilder()
    for row in rows:
        kb.button(text=f"1️⃣ {row['name']}",callback_data=f"bundlefirst:{row['id']}")
    kb.button(text="⬅️ Kembali",callback_data="owner:panel")
    kb.adjust(1)
    await call.message.edit_text(
        "🎁 <b>BUAT PAKET</b>\n\nPilih produk pertama:",
        reply_markup=kb.as_markup(),
        parse_mode="HTML"
    )
    await call.answer()


@router.callback_query(F.data.startswith("bundlefirst:"))
async def owner_bundle_first(call: CallbackQuery, state: FSMContext):
    first=int(call.data.split(":")[1])
    await state.update_data(bundle_first=first)
    conn=db()
    rows=conn.execute("SELECT * FROM products WHERE active=1 AND id!=? ORDER BY id LIMIT 30",(first,)).fetchall()
    conn.close()
    kb=InlineKeyboardBuilder()
    for row in rows:
        kb.button(text=f"2️⃣ {row['name']}",callback_data=f"bundlesecond:{row['id']}")
    kb.button(text="⬅️ Kembali",callback_data="owner:bundles")
    kb.adjust(1)
    await call.message.edit_text("Pilih produk kedua:",reply_markup=kb.as_markup())
    await call.answer()


@router.callback_query(F.data.startswith("bundlesecond:"))
async def owner_bundle_second(call: CallbackQuery, state: FSMContext):
    second=int(call.data.split(":")[1])
    data=await state.get_data()
    first=int(data.get("bundle_first",0))
    if not first:
        return await call.answer("Produk pertama belum dipilih.",show_alert=True)

    conn=db()
    p1=conn.execute("SELECT name FROM products WHERE id=?",(first,)).fetchone()
    p2=conn.execute("SELECT name FROM products WHERE id=?",(second,)).fetchone()
    if not p1 or not p2:
        conn.close()
        return await call.answer("Produk tidak ditemukan.",show_alert=True)
    name=f"{p1['name']} + {p2['name']}"
    conn.execute(
        """INSERT INTO bundle_offers(name,product_a,product_b,active,created_at)
           VALUES(?,?,?,?,?)""",
        (name,first,second,1,datetime.now().isoformat(timespec="seconds"))
    )
    conn.commit(); conn.close()
    await state.clear()

    await call.message.edit_text(
        f"✅ Paket dibuat:\n<b>{html.escape(name)}</b>\n\n"
        "User dapat menambahkan paket ini ke keranjang dari List Produk → Paket Hemat.",
        reply_markup=owner_menu(),
        parse_mode="HTML"
    )
    await call.answer("Paket dibuat.")



@router.callback_query()
async def stale_callback_recovery(call: CallbackQuery, state: FSMContext):
    """
    Last-resort for stale inline buttons from older bot messages.
    Specific callback handlers above always get first chance.
    """
    data = call.data or ""

    # Old owner/navigation buttons should never remain unresponsive.
    if is_owner(call.from_user.id) and data.startswith("owner:"):
        await state.clear()
        await safe_edit_or_answer(
            call,
            f"🛠️ <b>PANEL OWNER • {STORE_NAME}</b>\n\n"
            "Menu lama sudah diperbarui. Silakan pilih pengaturan dari panel terbaru.\n\n"
            f"<i>{STORE_FOOTER}</i>",
            reply_markup=owner_menu(),
            parse_mode="HTML"
        )
        return await call.answer("Menu diperbarui.")

    # User-facing stale navigation falls back to home rather than silently doing nothing.
    if data in {"back", "menu", "main_menu", "start"}:
        await state.clear()
        await safe_edit_or_answer(
            call,
            f"🛍️ <b>{STORE_NAME}</b>\n\nSilakan pilih menu:",
            reply_markup=main_menu(),
            parse_mode="HTML"
        )
        return await call.answer("Menu diperbarui.")

    await call.answer("Tombol ini sudah kedaluwarsa. Buka menu terbaru.", show_alert=True)


# =========================
# FALLBACK
# =========================
@router.message()
async def fallback(message: Message):
    if message.text and message.text.startswith("/"):
        await message.answer(
            "ℹ️ Command yang tersedia hanya:\n"
            "/start — Menu utama\n"
            "/owner — Panel owner\n"
            "/ping — Status bot"
        )



async def shopeepay_callback(request: web.Request):
    raw_body = await request.read()
    timestamp = request.headers.get("X-TIMESTAMP", "")
    signature = request.headers.get("X-SIGNATURE", "")

    if not SHOPEEPAY_PUBLIC_KEY or not PUBLIC_BASE_URL:
        return web.json_response(
            {"responseCode": "5005600", "responseMessage": "Merchant not configured"},
            status=500
        )

    callback_url = PUBLIC_BASE_URL + "/shopeepay/callback"
    body_hash = hashlib.sha256(raw_body).hexdigest().lower()
    string_to_sign = f"POST:{callback_url}:{body_hash}:{timestamp}"

    if not rsa_sha256_verify(SHOPEEPAY_PUBLIC_KEY, string_to_sign, signature):
        return web.json_response(
            {"responseCode": "4015600", "responseMessage": "Invalid Signature"},
            status=401
        )

    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except Exception:
        return web.json_response(
            {"responseCode": "4005600", "responseMessage": "Invalid Body"},
            status=400
        )

    partner_ref = payload.get("originalPartnerReferenceNo", "")
    latest_status = payload.get("latestTransactionStatus", "")
    amount_obj = payload.get("amount") or {}
    amount_value = amount_obj.get("value", "0")

    try:
        paid_amount = int(Decimal(str(amount_value)))
    except (InvalidOperation, ValueError, TypeError):
        paid_amount = 0

    # Expected reference format MBY-000001
    try:
        order_id = int(str(partner_ref).replace("MBY-", ""))
    except Exception:
        return web.json_response(
            {"responseCode": "4005600", "responseMessage": "Invalid Reference"},
            status=400
        )

    conn = db()
    order = conn.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
    conn.close()

    if not order:
        return web.json_response(
            {"responseCode": "4045600", "responseMessage": "Order Not Found"},
            status=404
        )

    expected_amount = int(order["payment_total"] or order["total"])
    expected_ref = order["provider_reference"] or invoice(order_id)

    # Validate reference + amount before marking paid
    if partner_ref != expected_ref or paid_amount != expected_amount:
        return web.json_response(
            {"responseCode": "4005600", "responseMessage": "Reference/Amount Mismatch"},
            status=400
        )

    # Payment Gateway status "00" is successful for notify flow
    if latest_status == "00":
        bot = request.app["bot"]
        ok = await mark_order_paid(order_id, bot, paid_amount)
        if not ok:
            logging.warning(
                "Payment confirmed but order %s needs manual review/fulfillment.",
                order_id
            )

    return web.json_response(
        {"responseCode": "2005600", "responseMessage": "Successful"}
    )


async def health(request: web.Request):
    return web.json_response({
        "status": "ok",
        "service": STORE_NAME,
        "shopeepay_ready": shopeepay_ready()
    })


async def start_web_server(bot: Bot):
    app = web.Application()
    app["bot"] = bot
    app.router.add_get("/", health)
    app.router.add_get("/health", health)
    app.router.add_post("/shopeepay/callback", shopeepay_callback)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    return runner




async def silent_recovery_loop(bot: Bot):
    # One recovery pass after startup/redeploy.
    # It never charges or creates new orders.
    await asyncio.sleep(20)
    try:
        await recover_stuck_orders(bot)
    except Exception as exc:
        logging.exception("Startup order recovery failed: %s", exc)


async def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN belum diisi.")

    init_db()
    bot = Bot(BOT_TOKEN)
    dp = Dispatcher()
    dp.include_router(router)

    # Railway web endpoint for health check + payment callback.
    runner = await start_web_server(bot)

    backup_task = asyncio.create_task(backup_loop(bot))
    cleanup_task = asyncio.create_task(cleanup_expired_orders(bot))
    recovery_task = asyncio.create_task(silent_recovery_loop(bot))
    operations_task = asyncio.create_task(periodic_operations_loop(bot))

    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    finally:
        backup_task.cancel()
        cleanup_task.cancel()
        recovery_task.cancel()
        operations_task.cancel()
        await runner.cleanup()


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
