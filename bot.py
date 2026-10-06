from collections.abc import Mapping
import os
import traceback
from contextlib import asynccontextmanager
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
import tempfile
from pathlib import Path
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from decimal import Decimal, InvalidOperation

from aiohttp import web, ClientSession
from Crypto.PublicKey import RSA
from Crypto.Signature import pkcs1_15
from Crypto.Hash import SHA256

from aiogram import BaseMiddleware, Bot, Dispatcher, F, Router
from aiogram.exceptions import TelegramRetryAfter, TelegramNetworkError, TelegramBadRequest
from aiogram.utils.backoff import BackoffConfig
from aiogram.filters import Command
from aiogram.types import (
    ErrorEvent,
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile,
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import BaseStorage, StorageKey
from aiogram.fsm.storage.memory import SimpleEventIsolation
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from dotenv import load_dotenv
try:
    from PIL import Image, ImageDraw, ImageFont
    PIL_AVAILABLE = True
except ImportError:
    Image = ImageDraw = ImageFont = None
    PIL_AVAILABLE = False

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

BOT_VERSION = "10.8"
BOT_CHANGELOG = [
    "Invoice pembayaran berhasil sekarang dikirim sebagai gambar profesional.",
    "Detail akun premium digabung dalam invoice gambar agar chat lebih ringkas.",
    "Fallback otomatis ke format teks jika render gambar gagal.",
    "Flow pengiriman akun tetap aman dan tetap final setelah Telegram sukses mengirim.",
    "Tidak mengubah alur menu awal maupun checkout user."
]

STORE_NAME = "Maboyy Produk Digital"
STORE_FOOTER = "Aplikasi Premium • Since 2020"


logging.basicConfig(level=logging.INFO)
router = Router()
START_TIME = time.time()

LAST_CALLBACK_TRACE = {
    "at": "",
    "data": "",
    "user_id": 0,
    "elapsed_ms": 0,
    "status": "none",
}



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
    conn = sqlite3.connect(
        DB_PATH,
        timeout=10.0,
        check_same_thread=False
    )
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=10000")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA synchronous=NORMAL")
    except Exception:
        pass
    return conn

class SQLiteFSMStorage(BaseStorage):
    """
    Persistent Aiogram FSM storage backed by the same SQLite database.
    This replaces Dispatcher()'s default MemoryStorage so wizard state
    survives Railway restarts/redeploys.
    """

    def __init__(self, db_path: str):
        self.db_path=db_path

    @staticmethod
    def _storage_key(key: StorageKey) -> str:
        parts = {
            "bot_id": getattr(key, "bot_id", 0),
            "chat_id": getattr(key, "chat_id", 0),
            "user_id": getattr(key, "user_id", 0),
            "thread_id": getattr(key, "thread_id", None),
            "business_connection_id": getattr(key, "business_connection_id", None),
            "destiny": getattr(key, "destiny", "default"),
        }
        return json.dumps(parts, sort_keys=True, separators=(",", ":"))

    def _connect(self):
        conn=sqlite3.connect(self.db_path)
        conn.row_factory=sqlite3.Row
        return conn

    async def set_state(self, key: StorageKey, state=None) -> None:
        state_value = state.state if isinstance(state, State) else (state or "")
        skey=self._storage_key(key)
        conn=self._connect()
        try:
            conn.execute(
                """INSERT INTO fsm_storage(storage_key,state,data,updated_at)
                   VALUES(?,?,?,?)
                   ON CONFLICT(storage_key) DO UPDATE SET
                     state=excluded.state,
                     updated_at=excluded.updated_at""",
                (
                    skey,
                    str(state_value),
                    "{}",
                    datetime.now().isoformat(timespec="seconds")
                )
            )
            conn.commit()
        finally:
            conn.close()

    async def get_state(self, key: StorageKey):
        skey=self._storage_key(key)
        conn=self._connect()
        try:
            row=conn.execute(
                "SELECT state FROM fsm_storage WHERE storage_key=?",
                (skey,)
            ).fetchone()
            if not row or not row["state"]:
                return None
            return str(row["state"])
        finally:
            conn.close()

    async def set_data(self, key: StorageKey, data: Mapping) -> None:
        if not isinstance(data, Mapping):
            raise TypeError("FSM data must be mapping-like.")

        skey=self._storage_key(key)
        payload=json.dumps(dict(data), ensure_ascii=False, default=str)
        conn=self._connect()
        try:
            conn.execute(
                """INSERT INTO fsm_storage(storage_key,state,data,updated_at)
                   VALUES(?,?,?,?)
                   ON CONFLICT(storage_key) DO UPDATE SET
                     data=excluded.data,
                     updated_at=excluded.updated_at""",
                (
                    skey,
                    "",
                    payload,
                    datetime.now().isoformat(timespec="seconds")
                )
            )
            conn.commit()
        finally:
            conn.close()

    async def get_data(self, key: StorageKey) -> dict:
        skey=self._storage_key(key)
        conn=self._connect()
        try:
            row=conn.execute(
                "SELECT data FROM fsm_storage WHERE storage_key=?",
                (skey,)
            ).fetchone()
            if not row or not row["data"]:
                return {}
            try:
                value=json.loads(row["data"])
                return value if isinstance(value, dict) else {}
            except Exception:
                return {}
        finally:
            conn.close()

    async def close(self) -> None:
        # Connections are short-lived per operation.
        return None





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


    cur.execute("""
        CREATE TABLE IF NOT EXISTS payment_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entity_type TEXT NOT NULL,
            entity_id INTEGER NOT NULL,
            event_type TEXT NOT NULL,
            amount INTEGER NOT NULL DEFAULT 0,
            actor_id INTEGER NOT NULL DEFAULT 0,
            detail TEXT DEFAULT '',
            created_at TEXT NOT NULL,
            UNIQUE(entity_type, entity_id, event_type)
        )
    """)


    cur.execute("""
        CREATE TABLE IF NOT EXISTS system_errors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            module TEXT NOT NULL,
            severity TEXT NOT NULL DEFAULT 'warning',
            reference TEXT DEFAULT '',
            error_text TEXT NOT NULL,
            recovered INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS integrity_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT NOT NULL,
            reference TEXT DEFAULT '',
            before_value TEXT DEFAULT '',
            after_value TEXT DEFAULT '',
            detail TEXT DEFAULT '',
            created_at TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS fsm_storage (
            storage_key TEXT PRIMARY KEY,
            state TEXT DEFAULT '',
            data TEXT DEFAULT '{}',
            updated_at TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS owner_input_sessions (
            user_id INTEGER PRIMARY KEY,
            flow TEXT NOT NULL,
            payload TEXT DEFAULT '{}',
            created_at TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS payment_proof_sessions (
            user_id INTEGER PRIMARY KEY,
            entity_type TEXT NOT NULL,
            entity_id INTEGER NOT NULL,
            created_at TEXT NOT NULL
        )
    """)

    # migrations from previous versions
    add_column_if_missing(conn, "products", "created_at", "TEXT DEFAULT ''")
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
    add_column_if_missing(conn, "system_errors", "update_id", "INTEGER DEFAULT 0")
    add_column_if_missing(conn, "system_errors", "event_type", "TEXT DEFAULT ''")
    add_column_if_missing(conn, "system_errors", "callback_data", "TEXT DEFAULT ''")
    add_column_if_missing(conn, "system_errors", "user_id", "INTEGER DEFAULT 0")
    add_column_if_missing(conn, "system_errors", "state_name", "TEXT DEFAULT ''")
    add_column_if_missing(conn, "system_errors", "exception_type", "TEXT DEFAULT ''")
    add_column_if_missing(conn, "system_errors", "traceback_text", "TEXT DEFAULT ''")
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
    add_column_if_missing(conn, "topups", "expires_at", "TEXT DEFAULT ''")
    add_column_if_missing(conn, "orders", "cashback_applied", "INTEGER NOT NULL DEFAULT 0")
    add_column_if_missing(conn, "orders", "payment_verified_at", "TEXT DEFAULT ''")
    add_column_if_missing(conn, "orders", "payment_verified_by", "INTEGER NOT NULL DEFAULT 0")
    add_column_if_missing(conn, "orders", "payment_error", "TEXT DEFAULT ''")
    add_column_if_missing(conn, "orders", "payment_proof_file_id", "TEXT DEFAULT ''")
    add_column_if_missing(conn, "orders", "payment_proof_type", "TEXT DEFAULT ''")
    add_column_if_missing(conn, "orders", "payment_proof_submitted_at", "TEXT DEFAULT ''")
    add_column_if_missing(conn, "orders", "payment_reject_reason", "TEXT DEFAULT ''")

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
        "invoice_history_retention_days": "7",
        "expired_invoice_hide_minutes": "60",
        "safe_mode": "0",
        "system_error_pm_enabled": "1",
        "auto_repair_inventory": "1",
        "auto_recovery_enabled": "1",
        "qris_upload_pending": "0",
        "bank_name": "",
        "bank_account": "",
        "bank_holder": "",
    }
    for k, v in defaults.items():
        cur.execute("INSERT OR IGNORE INTO settings(key, value) VALUES(?,?)", (k, v))
    cur.execute(
        "UPDATE settings SET value='1' WHERE key='unique_code_enabled'"
    )

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




def format_uptime_detail(seconds: int) -> str:
    seconds=max(0,int(seconds))
    days, rem=divmod(seconds,86400)
    hours, rem=divmod(rem,3600)
    minutes, secs=divmod(rem,60)

    parts=[]
    if days:
        parts.append(f"{days} hari")
    if hours or days:
        parts.append(f"{hours} jam")
    if minutes or hours or days:
        parts.append(f"{minutes} menit")
    parts.append(f"{secs} detik")
    return " ".join(parts)


def jakarta_now():
    return datetime.now(JAKARTA_TZ)


def bot_started_at_jakarta():
    return datetime.fromtimestamp(START_TIME, tz=JAKARTA_TZ)


def owner_access_denied_text() -> str:
    return (
        "⛔ <b>AKSES DITOLAK</b>\n\n"
        "Command / fitur ini <b>khusus owner</b> dan tidak dapat digunakan oleh user.\n"
        "Silakan gunakan /start untuk kembali ke menu toko."
    )


async def deny_owner_callback(call: CallbackQuery):
    try:
        await call.answer(
            "⛔ Fitur ini khusus owner.",
            show_alert=True
        )
    except Exception:
        pass




def parse_rupiah_input(text: str):
    """
    Menerima format:
    15000
    15.000
    15,000
    Rp15.000
    rp 15 000
    """
    raw=(text or "").strip().lower()
    if not raw:
        return None

    raw=raw.replace("rp","").replace("idr","").strip()
    digits=re.sub(r"[^0-9]","",raw)

    if not digits:
        return None

    try:
        value=int(digits)
    except Exception:
        return None

    return value if value > 0 else None




async def check_channel_membership(bot: Bot, user_id: int):
    """
    Returns (joined: bool, reason: str, detail: str).

    reason:
    - disabled
    - joined
    - not_member
    - bot_not_admin
    - invalid_channel
    - telegram_error
    """
    if not REQUIRED_CHANNEL_ID:
        return True, "disabled", "Verifikasi channel tidak diwajibkan."

    raw_target = str(REQUIRED_CHANNEL_ID).strip()
    target = int(raw_target) if raw_target.lstrip("-").isdigit() else raw_target

    try:
        # First make sure the bot itself can access the required channel.
        me = await bot.get_me()
        bot_member = await bot.get_chat_member(target, me.id)
        bot_status_obj = getattr(bot_member, "status", "")
        bot_status = str(getattr(bot_status_obj, "value", bot_status_obj)).lower()

        # Telegram getChatMember for OTHER users in channels is reliable
        # when the bot is an administrator.
        if bot_status not in {"administrator", "creator", "owner"}:
            return (
                False,
                "bot_not_admin",
                "Bot belum menjadi admin di channel wajib."
            )

        member = await bot.get_chat_member(target, user_id)
        status_obj = getattr(member, "status", "")
        status = str(getattr(status_obj, "value", status_obj)).lower()

        if status in {"member", "administrator", "creator", "owner"}:
            return True, "joined", status

        if status == "restricted":
            is_member_flag = getattr(member, "is_member", None)
            if bool(is_member_flag):
                return True, "joined", "restricted-member"

        return False, "not_member", status or "not_member"

    except Exception as exc:
        error_text = str(exc)
        lower = error_text.lower()

        if (
            "chat not found" in lower
            or "chat_id_invalid" in lower
            or "peer_id_invalid" in lower
        ):
            return False, "invalid_channel", error_text[:300]

        if (
            "administrator" in lower
            or "not enough rights" in lower
            or "member list is inaccessible" in lower
        ):
            return False, "bot_not_admin", error_text[:300]

        if (
            "user not participant" in lower
            or "participant_id_invalid" in lower
        ):
            return False, "not_member", error_text[:300]

        logging.warning(
            "Required channel verification failed target=%r user_id=%s error=%s",
            target,
            user_id,
            exc
        )
        return False, "telegram_error", error_text[:300]


async def is_channel_member(bot: Bot, user_id: int) -> bool:
    joined, _reason, _detail = await check_channel_membership(bot, user_id)
    return joined




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



async def notify_restock_subscribers(
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
    subscribers = conn.execute(
        """SELECT user_id
           FROM restock_subscriptions
           WHERE product_id=? AND variant_id=?
           ORDER BY id""",
        (product_id, variant_id)
    ).fetchall()
    conn.close()

    if not product or not variant or stock_after <= 0:
        return {"sent": 0, "failed": 0, "subscribers": 0}

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="🛒 Lihat Produk",
                callback_data=f"variant:{variant_id}"
            )
        ],
        [
            InlineKeyboardButton(
                text="🔕 Matikan Notif Restock",
                callback_data=f"restock:{variant_id}"
            )
        ]
    ])

    text = (
        "🔔 <b>RESTOCK TERSEDIA</b>\n\n"
        f"📦 Produk: <b>{html.escape(product['name'])}</b>\n"
        f"🧩 Variasi: <b>{html.escape(variant['name'])}</b>\n"
        f"✅ Stok sekarang: <b>{stock_after}</b>\n"
        f"💰 Harga: <b>{rupiah(variant['price'])}</b>\n\n"
        "Stok sudah tersedia kembali. Silakan order sebelum habis.\n\n"
        f"<i>{STORE_FOOTER}</i>"
    )

    sent = 0
    failed = 0

    for row in subscribers:
        user_id = int(row["user_id"])

        # Owner summary is sent separately below.
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
        except Exception as exc:
            failed += 1
            logging.warning(
                "Restock subscriber PM failed for user %s: %s",
                user_id,
                exc
            )

    # One-shot subscription: once stock is available and PM attempted,
    # clear subscriptions so the button can be activated again later.
    conn = db()
    conn.execute(
        """DELETE FROM restock_subscriptions
           WHERE product_id=? AND variant_id=?""",
        (product_id, variant_id)
    )
    conn.commit()
    conn.close()

    if ADMIN_ID and owner_alert_allowed(f"restock-summary:{variant_id}:{stock_after}", 120):
        try:
            await bot.send_message(
                ADMIN_ID,
                "📬 <b>RESTOCK PM SELESAI</b>\n\n"
                f"📦 {html.escape(product['name'])} — {html.escape(variant['name'])}\n"
                f"👥 Subscriber: <b>{len(subscribers)}</b>\n"
                f"✅ Terkirim: <b>{sent}</b>\n"
                f"❌ Gagal: <b>{failed}</b>\n"
                f"📊 Stok sekarang: <b>{stock_after}</b>",
                parse_mode="HTML"
            )
        except Exception:
            pass

    return {
        "sent": sent,
        "failed": failed,
        "subscribers": len(subscribers)
    }


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



async def force_refresh_user_keyboard(message: Message):
    """
    Force Telegram clients (Android/iOS) to discard an old persistent
    reply keyboard, then send the current keyboard again.
    """
    try:
        remove_msg = await message.answer(
            "🔄 Memperbarui keyboard...",
            reply_markup=ReplyKeyboardRemove()
        )
    except Exception:
        remove_msg = None

    # Small message boundary helps Telegram clients apply removal before re-send.
    await asyncio.sleep(0.15)

    await message.answer(
        "✅ <b>KEYBOARD DIPERBARUI</b>\n\n"
        "Keyboard menu terbaru sudah dimuat.",
        reply_markup=user_reply_menu(),
        parse_mode="HTML"
    )

    if remove_msg:
        try:
            await remove_msg.delete()
        except Exception:
            pass


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
    temp_paths = []

    # 1) Send professional PAID invoice image.
    try:
        temp_paths = create_success_invoice_images(order_id, delivery_text)
        if temp_paths:
            await bot.send_photo(
                user_id,
                FSInputFile(str(temp_paths[0])),
                caption=(
                    "✅ <b>PEMBAYARAN BERHASIL</b>\n"
                    f"🧾 Invoice: <b>{invoice(order_id)}</b>\n\n"
                    "Invoice pembayaran berhasil terlampir."
                ),
                parse_mode="HTML"
            )
    except Exception as exc:
        logging.exception("Invoice image render failed for order %s: %s", order_id, exc)
        try:
            await bot.send_message(
                user_id,
                professional_invoice_for_order(order_id)
                + "\n\n✅ <b>Pembayaran berhasil.</b>",
                parse_mode="HTML"
            )
        except Exception:
            pass
    finally:
        for path in temp_paths:
            try:
                os.remove(path)
            except Exception:
                pass

    # 2) Send account data separately as text.
    chunks = split_delivery_text(delivery_text)

    await bot.send_message(
        user_id,
        "🎁 <b>DETAIL AKUN PREMIUM</b>\n\n"
        f"🧾 Invoice: <b>{invoice(order_id)}</b>\n"
        f"📦 Total data: <b>{len([line for line in (delivery_text or '').splitlines() if line.strip()])}</b>\n\n"
        "Data akun dikirim terpisah dari invoice:",
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
        "🔒 Simpan akun dengan aman dan jangan membagikannya kepada orang lain.\n\n"
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
            except Exception as owner_alert_exc:
                logging.exception(
                    "Failed to notify owner about delivery failure for order %s: %s",
                    order_id,
                    owner_alert_exc
                )
                log_system_error(
                    "DELIVERY_OWNER_ALERT",
                    str(owner_alert_exc),
                    reference=f"order:{order_id}",
                    severity="warning",
                    recovered=False
                )
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


def topup_expiry_iso(minutes: int = 30) -> str:
    return (
        datetime.now(timezone.utc).astimezone()
        + timedelta(minutes=max(5, int(minutes)))
    ).isoformat(timespec="seconds")


def invoice_retention_cutoff_iso(days: int | None = None) -> str:
    if days is None:
        days = setting_int("invoice_history_retention_days", 7)
    days = max(1, int(days))
    return (
        datetime.now(timezone.utc).astimezone()
        - timedelta(days=days)
    ).isoformat(timespec="seconds")


def expired_invoice_hide_cutoff_iso(minutes: int | None = None) -> str:
    if minutes is None:
        minutes = setting_int("expired_invoice_hide_minutes", 60)
    minutes = max(1, int(minutes))
    return (
        datetime.now(timezone.utc).astimezone()
        - timedelta(minutes=minutes)
    ).isoformat(timespec="seconds")


def format_expiry_time(value: str) -> str:
    if not value:
        return "-"
    try:
        dt = datetime.fromisoformat(value)
        jakarta = dt.astimezone(ZoneInfo("Asia/Jakarta"))
        return jakarta.strftime("%d-%m-%Y %H:%M WIB")
    except Exception:
        return value


def order_expiry_text(order) -> str:
    if not order:
        return ""
    expiry = order["reserved_until"] if "reserved_until" in order.keys() else ""
    if expiry:
        return f"⏳ Kedaluwarsa: <b>{format_expiry_time(expiry)}</b>\n"
    return ""


def topup_expiry_text(topup) -> str:
    if not topup:
        return ""
    expiry = topup["expires_at"] if "expires_at" in topup.keys() else ""
    if expiry:
        return f"⏳ Kedaluwarsa: <b>{format_expiry_time(expiry)}</b>\n"
    return ""




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




_action_locks = {}


@asynccontextmanager
async def action_lock(key: str):
    lock = _action_locks.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _action_locks[key] = lock

    if lock.locked():
        yield False
        return

    await lock.acquire()
    try:
        yield True
    finally:
        lock.release()


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

    if bank_transfer_ready():
        rows.append([
            InlineKeyboardButton(
                text="🏦 Transfer Rekening",
                callback_data=f"processbank:{variant_id}:{qty}"
            )
        ])

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



async def purge_stale_invoice_data():
    """
    Hard-delete only stale unpaid/expired/cancelled transaction data.
    Paid/completed records are intentionally preserved for audit/accounting.
    """
    cutoff = invoice_retention_cutoff_iso()

    conn = db()
    conn.execute("BEGIN IMMEDIATE")

    # Remove dependent records first where needed.
    stale_order_ids = [
        int(r["id"]) for r in conn.execute(
            """SELECT id FROM orders
               WHERE created_at < ?
                 AND status IN ('expired','cancelled')
                 AND payment_status!='paid'""",
            (cutoff,)
        ).fetchall()
    ]

    if stale_order_ids:
        placeholders = ",".join("?" for _ in stale_order_ids)
        conn.execute(
            f"DELETE FROM voucher_usage WHERE order_id IN ({placeholders})",
            stale_order_ids
        )
        conn.execute(
            f"DELETE FROM payment_events WHERE entity_type='order' AND entity_id IN ({placeholders})",
            stale_order_ids
        )
        conn.execute(
            f"DELETE FROM orders WHERE id IN ({placeholders})",
            stale_order_ids
        )

    stale_topup_ids = [
        int(r["id"]) for r in conn.execute(
            """SELECT id FROM topups
               WHERE created_at < ?
                 AND status IN ('expired','rejected','cancelled')""",
            (cutoff,)
        ).fetchall()
    ]

    if stale_topup_ids:
        placeholders = ",".join("?" for _ in stale_topup_ids)
        conn.execute(
            f"DELETE FROM payment_events WHERE entity_type='topup' AND entity_id IN ({placeholders})",
            stale_topup_ids
        )
        conn.execute(
            f"DELETE FROM topups WHERE id IN ({placeholders})",
            stale_topup_ids
        )

    conn.commit()
    conn.close()
    return len(stale_order_ids), len(stale_topup_ids)


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

            notify_orders = []
            for order in rows:
                release_order_reservation(conn, order)
                conn.execute(
                    """UPDATE orders
                       SET status='expired', payment_status='expired'
                       WHERE id=?""",
                    (order["id"],)
                )
                notify_orders.append((order["user_id"], order["id"]))

            stale_topups = conn.execute(
                """SELECT * FROM topups
                   WHERE status='pending'
                     AND expires_at!=''
                     AND expires_at < ?""",
                (now_iso,)
            ).fetchall()

            for row in stale_topups:
                conn.execute(
                    "UPDATE topups SET status='expired' WHERE id=? AND status='pending'",
                    (row["id"],)
                )

            conn.commit()
            conn.close()

            for user_id, order_id in notify_orders:
                record_payment_event(
                    "order", order_id, "expired", 0, 0, "Reservation expired"
                )
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

            for row in stale_topups:
                record_payment_event(
                    "topup", row["id"], "expired", 0, 0, "Topup expired"
                )
                try:
                    await bot.send_message(
                        row["user_id"],
                        "⌛ <b>TOP UP KADALUARSA</b>\n\n"
                        f"🧾 {topup_invoice(row['id'])}\n"
                        "Waktu pembayaran telah habis. Silakan buat top up baru.",
                        parse_mode="HTML"
                    )
                except Exception:
                    pass

            try:
                await purge_stale_invoice_data()
            except Exception as purge_exc:
                logging.exception("Invoice purge failed: %s", purge_exc)

        except Exception as exc:
            logging.exception("Expired payment cleanup failed: %s", exc)


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
        if not owner_alert_allowed(f"lowstock:{variant_id}:{stock}", 900):
            return
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





def order_bundle(order_id: int):
    conn = db()
    order = conn.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
    if not order:
        conn.close()
        return None

    product = conn.execute(
        "SELECT * FROM products WHERE id=?",
        (order["product_id"],)
    ).fetchone()
    variant = conn.execute(
        "SELECT * FROM product_variants WHERE id=?",
        (order["variant_id"],)
    ).fetchone()
    conn.close()
    return {
        "order": order,
        "product": product,
        "variant": variant,
    }


def invoice_success_datetime(order) -> str:
    raw = (
        order["completed_at"]
        or order["delivery_sent_at"]
        or order["payment_verified_at"]
        or order["created_at"]
        or ""
    )
    if not raw:
        return "-"
    try:
        dt = datetime.fromisoformat(str(raw))
        return dt.strftime("%d %b %Y • %H:%M")
    except Exception:
        return str(raw)


def invoice_image_font(size: int, bold: bool = False):
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        "/Library/Fonts/Arial.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size=size)
        except Exception:
            continue
    return ImageFont.load_default()


def wrap_pixels(draw, text: str, font, max_width: int):
    text = str(text or "").replace("\r", "")
    pieces = []
    for paragraph in text.split("\n"):
        paragraph = paragraph.rstrip()
        if not paragraph:
            pieces.append("")
            continue

        words = paragraph.split()
        current = ""
        for word in words:
            probe = word if not current else f"{current} {word}"
            box = draw.textbbox((0, 0), probe, font=font)
            if (box[2] - box[0]) <= max_width:
                current = probe
            else:
                if current:
                    pieces.append(current)
                    current = word
                else:
                    # hard split long word
                    buff = ""
                    for ch in word:
                        probe2 = buff + ch
                        box2 = draw.textbbox((0, 0), probe2, font=font)
                        if (box2[2] - box2[0]) <= max_width:
                            buff = probe2
                        else:
                            if buff:
                                pieces.append(buff)
                            buff = ch
                    current = buff
        if current:
            pieces.append(current)
    return pieces or [""]


def count_wrapped_lines(draw, text: str, font, max_width: int) -> int:
    return len(wrap_pixels(draw, text, font, max_width))


def draw_wrapped(draw, text: str, xy, font, fill, max_width: int, line_gap: int = 8):
    x, y = xy
    lines = wrap_pixels(draw, text, font, max_width)
    box = draw.textbbox((0, 0), "Ag", font=font)
    line_height = (box[3] - box[1]) + line_gap
    for line in lines:
        draw.text((x, y), line, font=font, fill=fill)
        y += line_height
    return y


def create_success_invoice_images(order_id: int, delivery_text: str):
    if not PIL_AVAILABLE:
        raise RuntimeError("Pillow belum terpasang; gunakan fallback invoice teks.")

    """
    Invoice image only.
    Account credentials are intentionally NOT rendered into the image.
    """
    bundle = order_bundle(order_id)
    if not bundle:
        raise ValueError("Order tidak ditemukan.")

    order = bundle["order"]
    product = bundle["product"]
    variant = bundle["variant"]

    product_name = product["name"] if product else "-"
    variant_name = variant["name"] if variant else "-"
    qty = int(order["qty"] or 0)
    subtotal = int(order["total"] or 0)
    discount = int(order["discount_amount"] or 0)
    payment_total = int(order["payment_total"] or max(0, subtotal - discount))
    note_text = (order["note"] or "").strip() or "-"
    payment_method = order["payment_method"] or "-"
    date_text = invoice_success_datetime(order)
    voucher_code = (order["voucher_code"] or "").strip()

    dummy = Image.new("RGB", (10, 10), "white")
    d = ImageDraw.Draw(dummy)

    font_title = invoice_image_font(46, bold=True)
    font_sub = invoice_image_font(22, bold=False)
    font_h2 = invoice_image_font(28, bold=True)
    font_label = invoice_image_font(21, bold=True)
    font_text = invoice_image_font(21, bold=False)
    font_small = invoice_image_font(18, bold=False)

    card_width = 1080
    margin = 50
    inner = card_width - margin * 2

    note_lines = count_wrapped_lines(d, note_text, font_text, inner - 48)
    detail_rows = 8 + (1 if discount > 0 else 0) + (1 if voucher_code else 0)
    detail_height = 40 + (detail_rows * 40)
    note_height = 70 + max(1, note_lines) * 30
    total_height = max(980, 140 + 100 + detail_height + 26 + note_height + 120)

    bg = "#0B1220"
    card = "#111B2F"
    accent = "#2D7FF9"
    text_primary = "#F8FAFC"
    text_muted = "#B7C4D8"
    text_soft = "#DDE7F5"
    success = "#22C55E"
    line_color = "#20304D"

    img = Image.new("RGB", (card_width, total_height), bg)
    draw = ImageDraw.Draw(img)

    # Header
    draw.rounded_rectangle((margin, 40, card_width - margin, 170), radius=28, fill=card)
    draw.rounded_rectangle((margin + 28, 68, margin + 198, 112), radius=18, fill=success)
    draw.text((margin + 48, 78), "PAID", font=font_label, fill="white")
    draw.text((margin + 230, 66), "Maboyy Digital", font=font_title, fill=text_primary)
    draw.text((margin + 230, 120), "Invoice Pembayaran Berhasil", font=font_sub, fill=text_muted)

    y = 205

    # Detail card
    detail_bottom = y + detail_height
    draw.rounded_rectangle((margin, y, card_width - margin, detail_bottom), radius=28, fill=card)
    draw.text((margin + 24, y + 18), "Ringkasan Pembayaran", font=font_h2, fill=text_primary)

    items = [
        ("Invoice", invoice(order["id"])),
        ("Tanggal", date_text),
        ("Produk", product_name),
        ("Variasi", variant_name),
        ("Qty", str(qty)),
        ("Subtotal", rupiah(subtotal)),
    ]
    if discount > 0:
        items.append(("Diskon", f"-{rupiah(discount)}"))
    if voucher_code:
        items.append(("Voucher", voucher_code))
    items.extend([
        ("Total Dibayar", rupiah(payment_total)),
        ("Metode", payment_method.upper()),
    ])

    row_y = y + 64
    for label, value in items:
        draw.text((margin + 28, row_y), label, font=font_label, fill=text_muted)
        wrapped = wrap_pixels(draw, str(value), font_text, 520)
        draw.text((margin + 340, row_y), wrapped[0], font=font_text, fill=text_soft)
        if len(wrapped) > 1:
            extra_y = row_y + 26
            for extra in wrapped[1:]:
                draw.text((margin + 340, extra_y), extra, font=font_text, fill=text_soft)
                extra_y += 26
            row_y = extra_y + 8
        else:
            row_y += 40

    y = detail_bottom + 24

    # Note card
    note_bottom = y + note_height
    draw.rounded_rectangle((margin, y, card_width - margin, note_bottom), radius=28, fill=card)
    draw.text((margin + 24, y + 18), "Catatan Pembeli", font=font_h2, fill=text_primary)
    draw_wrapped(draw, note_text, (margin + 28, y + 62), font_text, text_soft, inner - 48, line_gap=7)

    footer_y = total_height - 72
    draw.line((margin + 10, footer_y - 18, card_width - margin - 10, footer_y - 18), fill=line_color, width=2)
    draw.text(
        (margin, footer_y),
        "Pembayaran berhasil • Maboyy Digital • Since 2020",
        font=font_small,
        fill=text_muted
    )

    out = Path(tempfile.gettempdir()) / f"maboyy_invoice_{order_id}.png"
    img.save(out, format="PNG", optimize=True)
    return [out]




async def send_delivery_payload_text(bot: Bot, user_id: int, order_id: int, delivery_text: str):
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
        schema_ok, schema_problems = validate_system_schema()
        results.append((
            "Schema DB",
            schema_ok,
            "Lengkap" if schema_ok else "; ".join(schema_problems)[:200]
        ))
    except Exception as exc:
        results.append(("Schema DB", False, str(exc)[:100]))

    try:
        conn=db()
        journal=conn.execute("PRAGMA journal_mode").fetchone()[0]
        busy=conn.execute("PRAGMA busy_timeout").fetchone()[0]
        conn.close()
        results.append((
            "SQLite WAL",
            str(journal).lower()=="wal",
            f"journal={journal} busy_timeout={busy}ms"
        ))
    except Exception as exc:
        results.append(("SQLite WAL",False,str(exc)[:100]))

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

    results.append((
        "Invoice Image",
        PIL_AVAILABLE,
        "Pillow aktif" if PIL_AVAILABLE else "Fallback teks aktif"
    ))

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



async def payment_health_report():
    conn = db()
    data = {
        "pending_manual": conn.execute(
            "SELECT COUNT(*) AS n FROM orders WHERE payment_method IN ('QRIS','BANK_TRANSFER') AND payment_status='unpaid' AND status='pending'"
        ).fetchone()["n"],
        "paid_pending": conn.execute(
            "SELECT COUNT(*) AS n FROM orders WHERE payment_status='paid' AND fulfillment_status!='delivered'"
        ).fetchone()["n"],
        "topup_pending": conn.execute(
            "SELECT COUNT(*) AS n FROM topups WHERE status='pending'"
        ).fetchone()["n"],
        "topup_processing": conn.execute(
            "SELECT COUNT(*) AS n FROM topups WHERE status='processing'"
        ).fetchone()["n"],
        "topup_expired": conn.execute(
            "SELECT COUNT(*) AS n FROM topups WHERE status='expired'"
        ).fetchone()["n"],
        "wallet_negative": conn.execute(
            "SELECT COUNT(*) AS n FROM wallets WHERE balance<0"
        ).fetchone()["n"],
        "duplicate_paid_events": conn.execute(
            """SELECT COUNT(*) AS n FROM (
                 SELECT entity_id, COUNT(*) c
                 FROM payment_events
                 WHERE entity_type='order' AND event_type='paid'
                 GROUP BY entity_id HAVING c>1
               )"""
        ).fetchone()["n"],
        "stale_expired_orders": conn.execute(
            """SELECT COUNT(*) AS n FROM orders
               WHERE status IN ('expired','cancelled')
                 AND payment_status!='paid'
                 AND created_at < ?""",
            (invoice_retention_cutoff_iso(),)
        ).fetchone()["n"],
    }
    conn.close()
    return data


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

            if get_setting("auto_repair_inventory","1") == "1":
                inventory_integrity_report(auto_repair=True)

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
            await notify_owner_system_error(
                bot,
                "PERIODIC_OPERATIONS",
                str(exc),
                recovered=False
            )

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



def record_payment_event(
    entity_type: str,
    entity_id: int,
    event_type: str,
    amount: int = 0,
    actor_id: int = 0,
    detail: str = "",
):
    conn = db()
    try:
        conn.execute(
            """INSERT OR IGNORE INTO payment_events
               (entity_type, entity_id, event_type, amount, actor_id, detail, created_at)
               VALUES(?,?,?,?,?,?,?)""",
            (
                entity_type, int(entity_id), event_type, int(amount or 0),
                int(actor_id or 0), detail[:500],
                datetime.now().isoformat(timespec="seconds")
            )
        )
        conn.commit()
    finally:
        conn.close()


def verify_topup_atomic(topup_id: int, actor_id: int):
    """
    Idempotent top-up verification.
    Only the transaction that changes pending -> processing may credit the wallet.
    """
    conn = db()
    conn.execute("BEGIN IMMEDIATE")
    row = conn.execute("SELECT * FROM topups WHERE id=?", (topup_id,)).fetchone()

    if not row:
        conn.rollback()
        conn.close()
        return None, "not_found"

    if row["status"] == "completed":
        wallet = conn.execute(
            "SELECT balance FROM wallets WHERE user_id=?",
            (row["user_id"],)
        ).fetchone()
        balance = int(wallet["balance"] or 0) if wallet else 0
        conn.rollback()
        conn.close()
        return (row, balance), "already_completed"

    if row["status"] not in {"pending", "expired"}:
        conn.rollback()
        conn.close()
        return None, f"invalid_status:{row['status']}"

    now = datetime.now().isoformat(timespec="seconds")
    updated = conn.execute(
        """UPDATE topups
           SET status='processing', verified_at=?, verified_by=?
           WHERE id=? AND status IN ('pending','expired')""",
        (now, actor_id, topup_id)
    ).rowcount

    if updated != 1:
        conn.rollback()
        conn.close()
        return None, "race_lost"

    wallet = conn.execute(
        "SELECT balance FROM wallets WHERE user_id=?",
        (row["user_id"],)
    ).fetchone()
    balance = int(wallet["balance"] or 0) if wallet else 0
    new_balance = balance + int(row["amount"])

    conn.execute(
        """INSERT INTO wallets(user_id,balance,updated_at)
           VALUES(?,?,?)
           ON CONFLICT(user_id) DO UPDATE SET
             balance=excluded.balance,
             updated_at=excluded.updated_at""",
        (row["user_id"], new_balance, now)
    )

    # Unique ledger key prevents duplicate credit if code is replayed.
    conn.execute(
        """INSERT OR IGNORE INTO wallet_ledger
           (user_id,type,amount,balance_after,reference,note,created_at)
           VALUES(?,?,?,?,?,?,?)""",
        (
            row["user_id"], "TOPUP", int(row["amount"]), new_balance,
            topup_invoice(topup_id), "Top up saldo terverifikasi.", now
        )
    )

    conn.execute(
        """UPDATE topups
           SET status='completed'
           WHERE id=? AND status='processing'""",
        (topup_id,)
    )

    conn.commit()
    conn.close()

    record_payment_event(
        "topup", topup_id, "verified",
        int(row["amount"]), actor_id, "Topup credited atomically"
    )
    return (row, new_balance), "completed"


def order_payment_state_ok(order) -> tuple[bool, str]:
    if not order:
        return False, "Order tidak ditemukan."
    if order["status"] == "cancelled":
        return False, "Order sudah dibatalkan."
    if order["payment_status"] == "paid":
        return True, "already_paid"
    if order["payment_status"] not in {"unpaid", "expired"}:
        return False, f"Status pembayaran tidak valid: {order['payment_status']}"
    return True, "ready"



def bank_transfer_ready() -> bool:
    return bool(
        get_setting("bank_name", "").strip()
        and get_setting("bank_account", "").strip()
        and get_setting("bank_holder", "").strip()
    )


def bank_transfer_text() -> str:
    bank = html.escape(get_setting("bank_name", "-"))
    account = html.escape(get_setting("bank_account", "-"))
    holder = html.escape(get_setting("bank_holder", "-"))
    return (
        f"🏦 Bank: <b>{bank}</b>\n"
        f"💳 No. Rekening: <code>{account}</code>\n"
        f"👤 Atas Nama: <b>{holder}</b>"
    )


def topup_payment_method_keyboard(amount: int):
    rows = [
        [InlineKeyboardButton(
            text="🟡 QRIS Manual",
            callback_data=f"topupmethod:qris:{amount}"
        )]
    ]
    if bank_transfer_ready():
        rows.append([
            InlineKeyboardButton(
                text="🏦 Transfer Rekening",
                callback_data=f"topupmethod:bank:{amount}"
            )
        ])
    rows.append([
        InlineKeyboardButton(
            text="⬅️ Ubah Nominal",
            callback_data=f"topup:set:{amount}"
        )
    ])
    rows.append([
        InlineKeyboardButton(
            text="❌ Batal",
            callback_data="wallet"
        )
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)





_owner_alert_cache = {}


def owner_alert_allowed(key: str, seconds: int = 120) -> bool:
    now = time.time()
    last = _owner_alert_cache.get(key, 0)
    if now - last < seconds:
        return False
    _owner_alert_cache[key] = now

    # Keep memory bounded.
    if len(_owner_alert_cache) > 500:
        cutoff = now - 3600
        for old_key in list(_owner_alert_cache.keys()):
            if _owner_alert_cache.get(old_key, 0) < cutoff:
                _owner_alert_cache.pop(old_key, None)
    return True


_recent_actions = {}


def recent_action_allowed(key: str, seconds: int = 3) -> bool:
    now = time.time()
    last = _recent_actions.get(key, 0)
    if now - last < seconds:
        return False
    _recent_actions[key] = now
    return True


def safe_mode_enabled() -> bool:
    return get_setting("safe_mode", "0") == "1"


def set_safe_mode(enabled: bool):
    set_setting("safe_mode", "1" if enabled else "0")



def log_detailed_error(
    module: str,
    exc: Exception,
    reference: str = "",
    update_id: int = 0,
    event_type: str = "",
    callback_data: str = "",
    user_id: int = 0,
    state_name: str = "",
    recovered: bool = False,
):
    exc_type=type(exc).__name__
    tb="".join(traceback.format_exception(type(exc), exc, exc.__traceback__))[-4000:]

    conn=db()
    try:
        conn.execute(
            """INSERT INTO system_errors(
                module,severity,reference,error_text,recovered,created_at,
                update_id,event_type,callback_data,user_id,state_name,
                exception_type,traceback_text
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                module[:60],
                "error",
                reference[:250],
                str(exc)[:1500],
                1 if recovered else 0,
                datetime.now().isoformat(timespec="seconds"),
                int(update_id or 0),
                event_type[:80],
                callback_data[:500],
                int(user_id or 0),
                state_name[:200],
                exc_type[:120],
                tb,
            )
        )
        conn.commit()
    finally:
        conn.close()


def latest_error_diagnostics(limit: int = 5):
    conn=db()
    try:
        return conn.execute(
            """SELECT id,module,reference,error_text,recovered,created_at,
                      update_id,event_type,callback_data,user_id,state_name,
                      exception_type
               FROM system_errors
               ORDER BY id DESC LIMIT ?""",
            (max(1,min(int(limit),20)),)
        ).fetchall()
    finally:
        conn.close()


def log_system_error(
    module: str,
    error_text: str,
    reference: str = "",
    severity: str = "warning",
    recovered: bool = False,
):
    conn = db()
    try:
        conn.execute(
            """INSERT INTO system_errors
               (module,severity,reference,error_text,recovered,created_at)
               VALUES(?,?,?,?,?,?)""",
            (
                module[:60],
                severity[:20],
                reference[:120],
                error_text[:1000],
                1 if recovered else 0,
                datetime.now().isoformat(timespec="seconds")
            )
        )
        conn.commit()
    finally:
        conn.close()


def record_integrity_event(
    event_type: str,
    reference: str = "",
    before_value: str = "",
    after_value: str = "",
    detail: str = "",
):
    conn = db()
    try:
        conn.execute(
            """INSERT INTO integrity_events
               (event_type,reference,before_value,after_value,detail,created_at)
               VALUES(?,?,?,?,?,?)""",
            (
                event_type[:60],
                reference[:120],
                str(before_value)[:500],
                str(after_value)[:500],
                detail[:1000],
                datetime.now().isoformat(timespec="seconds")
            )
        )
        conn.commit()
    finally:
        conn.close()


async def notify_owner_system_error(
    bot: Bot,
    module: str,
    error_text: str,
    reference: str = "",
    recovered: bool = False,
):
    log_system_error(
        module,
        error_text,
        reference=reference,
        severity="error",
        recovered=recovered
    )

    if not ADMIN_ID or get_setting("system_error_pm_enabled", "1") != "1":
        return

    alert_key = f"system:{module}:{reference}:{str(error_text)[:120]}"
    if not owner_alert_allowed(alert_key, 300):
        return

    try:
        await bot.send_message(
            ADMIN_ID,
            "⚠️ <b>SYSTEM ERROR</b>\n\n"
            f"Module: <b>{html.escape(module)}</b>\n"
            + (f"Reference: <b>{html.escape(reference)}</b>\n" if reference else "")
            + f"Status: <b>{'Recovered' if recovered else 'Needs attention'}</b>\n"
            f"Error: <code>{html.escape(str(error_text)[:700])}</code>",
            parse_mode="HTML"
        )
    except Exception:
        pass


def allowed_order_transition(old_status: str, new_status: str) -> bool:
    allowed = {
        "pending": {"paid_pending_delivery", "expired", "cancelled"},
        "expired": {"paid_pending_delivery", "cancelled"},
        "paid_pending_delivery": {"completed", "cancelled"},
        "completed": set(),
        "cancelled": set(),
    }
    return new_status in allowed.get(old_status, set())


def transition_order_status(conn, order_id: int, new_status: str) -> bool:
    row = conn.execute(
        "SELECT status FROM orders WHERE id=?",
        (order_id,)
    ).fetchone()
    if not row:
        return False

    old = row["status"]
    if old == new_status:
        return True

    if not allowed_order_transition(old, new_status):
        return False

    conn.execute(
        "UPDATE orders SET status=? WHERE id=?",
        (new_status, order_id)
    )
    return True


def wallet_integrity_snapshot(user_id: int):
    conn = db()
    wallet = conn.execute(
        "SELECT balance FROM wallets WHERE user_id=?",
        (user_id,)
    ).fetchone()
    balance = int(wallet["balance"] or 0) if wallet else 0

    ledger = conn.execute(
        "SELECT COALESCE(SUM(amount),0) AS n FROM wallet_ledger WHERE user_id=?",
        (user_id,)
    ).fetchone()
    ledger_total = int(ledger["n"] or 0)
    conn.close()

    return {
        "balance": balance,
        "ledger_total": ledger_total,
        "match": balance == ledger_total,
    }


def inventory_integrity_report(auto_repair: bool = False):
    conn = db()
    conn.execute("BEGIN IMMEDIATE")
    rows = conn.execute(
        "SELECT id, stock, reserved_stock FROM product_variants WHERE active=1"
    ).fetchall()

    mismatches = []
    repaired = 0

    for row in rows:
        available = conn.execute(
            """SELECT COUNT(*) AS n FROM inventory_items
               WHERE variant_id=? AND status='available'""",
            (row["id"],)
        ).fetchone()["n"]

        current_stock = int(row["stock"] or 0)
        if current_stock != int(available or 0):
            mismatches.append({
                "variant_id": int(row["id"]),
                "stock": current_stock,
                "available": int(available or 0),
            })

            if auto_repair:
                conn.execute(
                    "UPDATE product_variants SET stock=? WHERE id=?",
                    (int(available or 0), row["id"])
                )
                repaired += 1

    conn.commit()
    conn.close()

    for item in mismatches:
        record_integrity_event(
            "inventory_mismatch",
            reference=f"variant:{item['variant_id']}",
            before_value=item["stock"],
            after_value=item["available"],
            detail="Auto-repaired" if auto_repair else "Detected"
        )

    return mismatches, repaired



async def auto_recovery_cycle(bot: Bot, source: str = "periodic"):
    """
    Safe self-healing cycle.
    Never edits source code and never deletes paid/completed transactions.
    """
    report = {
        "source": source,
        "recovered_orders": 0,
        "pending_paid": 0,
        "inventory_mismatch": 0,
        "inventory_repaired": 0,
        "topups_reset": 0,
        "proof_sessions_cleaned": 0,
        "owner_input_sessions_cleaned": 0,
        "fsm_rows_cleaned": 0,
        "safe_mode_triggered": False,
        "errors": [],
    }

    try:
        # 1) Recover paid orders that were not delivered.
        if get_setting("auto_recovery_enabled", "1") == "1":
            recovered, pending = await recover_stuck_orders(bot)
            report["recovered_orders"] = recovered
            report["pending_paid"] = pending

        # 2) Repair inventory counters from inventory_items.
        if get_setting("auto_repair_inventory", "1") == "1":
            mismatches, repaired = inventory_integrity_report(auto_repair=True)
            report["inventory_mismatch"] = len(mismatches)
            report["inventory_repaired"] = repaired

        # 3) Reset topups stuck in processing.
        conn = db()
        stuck = conn.execute(
            "SELECT id FROM topups WHERE status='processing'"
        ).fetchall()
        for row in stuck:
            conn.execute(
                "UPDATE topups SET status='pending' WHERE id=? AND status='processing'",
                (row["id"],)
            )
        conn.commit()
        conn.close()
        report["topups_reset"] = len(stuck)

        # 4) Clean proof sessions that point to missing/already finished entities.
        conn = db()
        sessions = conn.execute(
            "SELECT user_id,entity_type,entity_id FROM payment_proof_sessions"
        ).fetchall()

        stale_user_ids = []
        for row in sessions:
            entity = row["entity_type"]
            entity_id = int(row["entity_id"] or 0)
            stale = False

            if entity == "order":
                item = conn.execute(
                    "SELECT payment_status,status FROM orders WHERE id=?",
                    (entity_id,)
                ).fetchone()
                stale = (
                    item is None
                    or item["payment_status"] == "paid"
                    or item["status"] in {"completed","cancelled","expired"}
                )
            elif entity == "topup":
                item = conn.execute(
                    "SELECT status FROM topups WHERE id=?",
                    (entity_id,)
                ).fetchone()
                stale = (
                    item is None
                    or item["status"] in {"completed","paid","rejected","cancelled","expired"}
                )
            else:
                stale = True

            if stale:
                stale_user_ids.append(int(row["user_id"]))

        for user_id in stale_user_ids:
            conn.execute(
                "DELETE FROM payment_proof_sessions WHERE user_id=?",
                (user_id,)
            )

        conn.commit()
        conn.close()
        report["proof_sessions_cleaned"] = len(stale_user_ids)

        # 5) Clear abandoned owner input sessions older than 24h.
        conn=db()
        cutoff=(datetime.now() - timedelta(hours=24)).isoformat(timespec="seconds")
        cur=conn.execute(
            "DELETE FROM owner_input_sessions WHERE created_at<?",
            (cutoff,)
        )
        conn.commit()
        conn.close()
        report["owner_input_sessions_cleaned"]=max(0,int(cur.rowcount or 0))

        # 6) Clean old empty FSM rows only; active wizard states are preserved.
        conn=db()
        cutoff=(datetime.now() - timedelta(days=7)).isoformat(timespec="seconds")
        cur=conn.execute(
            """DELETE FROM fsm_storage
               WHERE (state IS NULL OR state='')
                 AND updated_at<?""",
            (cutoff,)
        )
        conn.commit()
        conn.close()
        report["fsm_rows_cleaned"]=max(0,int(cur.rowcount or 0))

        # 7) DB integrity check.
        conn = db()
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        conn.close()

        if str(integrity).lower() != "ok":
            raise RuntimeError(f"SQLite integrity_check: {integrity}")

        # If recovery is healthy, do not force-disable Safe Mode automatically.
        # Owner controls when Safe Mode should be turned off.

    except Exception as exc:
        report["errors"].append(str(exc)[:500])
        report["safe_mode_triggered"] = True

        try:
            set_safe_mode(True)
        except Exception:
            pass

        try:
            log_system_error(
                "AUTO_RECOVERY",
                str(exc),
                reference=source,
                severity="critical",
                recovered=False
            )
        except Exception:
            pass

        try:
            await notify_owner_system_error(
                bot,
                "AUTO_RECOVERY",
                str(exc),
                reference=source,
                recovered=False
            )
        except Exception:
            pass

    return report


async def periodic_auto_recovery(bot: Bot):
    """
    Lightweight periodic recovery every 10 minutes.
    """
    await asyncio.sleep(120)

    while True:
        try:
            report = await auto_recovery_cycle(bot, source="periodic")

            # Only notify owner when something meaningful happened.
            if ADMIN_ID and (
                report["recovered_orders"]
                or report["inventory_repaired"]
                or report["topups_reset"]
                or report["proof_sessions_cleaned"]
                or report["safe_mode_triggered"]
            ):
                lines = [
                    "♻️ <b>AUTO RECOVERY</b>",
                    "",
                    f"✅ Order recovered: <b>{report['recovered_orders']}</b>",
                    f"📦 Paid belum terkirim: <b>{report['pending_paid']}</b>",
                    f"🧹 Inventory repaired: <b>{report['inventory_repaired']}</b>",
                    f"💰 Topup reset: <b>{report['topups_reset']}</b>",
                    f"📎 Proof session cleaned: <b>{report['proof_sessions_cleaned']}</b>",
                    f"🛟 Safe Mode: <b>{'ON' if report['safe_mode_triggered'] else 'tidak berubah'}</b>",
                ]
                try:
                    await bot.send_message(
                        ADMIN_ID,
                        "\n".join(lines),
                        parse_mode="HTML"
                    )
                except Exception:
                    pass

        except Exception as exc:
            logging.exception("Periodic auto recovery crashed: %s", exc)

        await asyncio.sleep(600)


async def startup_recovery_audit(bot: Bot):
    report = await auto_recovery_cycle(bot, source="startup")

    return {
        "recovered_orders": report["recovered_orders"],
        "pending_orders": report["pending_paid"],
        "inventory_mismatch": report["inventory_mismatch"],
        "inventory_repaired": report["inventory_repaired"],
        "processing_topups_reset": report["topups_reset"],
        "proof_sessions_cleaned": report["proof_sessions_cleaned"],
        "safe_mode_triggered": report["safe_mode_triggered"],
    }


    try:
        recovered, pending = await recover_stuck_orders(bot)
        results["recovered_orders"] = recovered
        results["pending_orders"] = pending

        mismatches, repaired = inventory_integrity_report(
            auto_repair=get_setting("auto_repair_inventory","1") == "1"
        )
        results["inventory_mismatch"] = len(mismatches)
        results["inventory_repaired"] = repaired

        # Reset topups stuck in 'processing' back to pending after restart.
        conn = db()
        stuck = conn.execute(
            "SELECT id FROM topups WHERE status='processing'"
        ).fetchall()
        for row in stuck:
            conn.execute(
                "UPDATE topups SET status='pending' WHERE id=? AND status='processing'",
                (row["id"],)
            )
        conn.commit()
        conn.close()
        results["processing_topups_reset"] = len(stuck)

    except Exception as exc:
        set_safe_mode(True)
        await notify_owner_system_error(
            bot,
            "STARTUP_RECOVERY",
            str(exc),
            recovered=False
        )

    return results


async def transaction_self_test():
    checks = []

    # DB
    try:
        conn = db()
        conn.execute("SELECT 1").fetchone()
        conn.close()
        checks.append(("Database", True, "OK"))
    except Exception as exc:
        checks.append(("Database", False, str(exc)[:100]))

    # Unique code simulation (read only)
    try:
        conn = db()
        max_order = conn.execute("SELECT COALESCE(MAX(unique_code),0) AS n FROM orders").fetchone()["n"]
        max_topup = conn.execute("SELECT COALESCE(MAX(unique_code),0) AS n FROM topups").fetchone()["n"]
        conn.close()
        checks.append(("Kode Unik", True, f"last={max(int(max_order or 0), int(max_topup or 0))}"))
    except Exception as exc:
        checks.append(("Kode Unik", False, str(exc)[:100]))

    # Inventory
    try:
        mismatches, _ = inventory_integrity_report(auto_repair=False)
        checks.append(("Inventory", len(mismatches)==0, f"{len(mismatches)} mismatch"))
    except Exception as exc:
        checks.append(("Inventory", False, str(exc)[:100]))

    # Wallet negatives
    try:
        conn = db()
        negative = conn.execute("SELECT COUNT(*) AS n FROM wallets WHERE balance<0").fetchone()["n"]
        conn.close()
        checks.append(("Wallet", int(negative)==0, f"{negative} negative"))
    except Exception as exc:
        checks.append(("Wallet", False, str(exc)[:100]))

    # Payment config
    checks.append(("QRIS", bool(get_setting("qris_file_id","")), "configured" if get_setting("qris_file_id","") else "not set"))
    checks.append(("Rekening", bank_transfer_ready(), "configured" if bank_transfer_ready() else "not set"))

    return checks


def system_health_score():
    score = 100
    notes = []

    try:
        conn = db()
        negatives = int(conn.execute("SELECT COUNT(*) AS n FROM wallets WHERE balance<0").fetchone()["n"] or 0)
        pending_paid = int(conn.execute(
            "SELECT COUNT(*) AS n FROM orders WHERE payment_status='paid' AND fulfillment_status!='delivered'"
        ).fetchone()["n"] or 0)
        stuck_processing = int(conn.execute(
            "SELECT COUNT(*) AS n FROM topups WHERE status='processing'"
        ).fetchone()["n"] or 0)
        conn.close()

        mismatches, _ = inventory_integrity_report(auto_repair=False)

        if negatives:
            score -= min(30, negatives * 10)
            notes.append(f"{negatives} wallet negatif")
        if pending_paid:
            score -= min(25, pending_paid * 5)
            notes.append(f"{pending_paid} paid pending")
        if stuck_processing:
            score -= min(20, stuck_processing * 10)
            notes.append(f"{stuck_processing} topup processing")
        if mismatches:
            score -= min(25, len(mismatches) * 5)
            notes.append(f"{len(mismatches)} inventory mismatch")
        if safe_mode_enabled():
            score -= 30
            notes.append("safe mode aktif")

    except Exception as exc:
        return 0, [f"health error: {exc}"]

    return max(0, score), notes




async def launch_readiness_report(bot: Bot):
    checks = []

    # Database
    try:
        conn = db()
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        checks.append(("Database", integrity == "ok", integrity))
        conn.close()
    except Exception as exc:
        checks.append(("Database", False, str(exc)[:120]))

    # Telegram bot
    try:
        me = await bot.get_me()
        checks.append(("Telegram Bot", True, f"@{me.username or me.id}"))
    except Exception as exc:
        checks.append(("Telegram Bot", False, str(exc)[:120]))

    # Owner PM
    if not ADMIN_ID:
        checks.append(("PM Owner", False, "ADMIN_ID kosong"))
    else:
        try:
            chat = await bot.get_chat(ADMIN_ID)
            checks.append(("PM Owner", True, f"ID {chat.id}"))
        except Exception as exc:
            checks.append(("PM Owner", False, str(exc)[:120]))

    # Required channel
    if not REQUIRED_CHANNEL_ID:
        checks.append(("Required Channel", True, "Tidak diwajibkan"))
    else:
        raw_target = str(REQUIRED_CHANNEL_ID).strip()
        target = int(raw_target) if raw_target.lstrip("-").isdigit() else raw_target
        try:
            chat = await bot.get_chat(target)
            me = await bot.get_me()
            bot_member = await bot.get_chat_member(target, me.id)
            bot_status_obj = getattr(bot_member, "status", "")
            bot_status = str(
                getattr(bot_status_obj, "value", bot_status_obj)
            ).lower()
            bot_admin = bot_status in {"administrator", "creator", "owner"}

            channel_name = (
                getattr(chat, "title", "")
                or getattr(chat, "username", "")
                or str(target)
            )
            checks.append((
                "Required Channel",
                bot_admin,
                f"{channel_name} • bot={bot_status}"
            ))
        except Exception as exc:
            checks.append(("Required Channel", False, str(exc)[:120]))

    # Storage
    try:
        db_path = Path(DB_PATH)
        backup_path = Path(BACKUP_DIR)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        backup_path.mkdir(parents=True, exist_ok=True)
        writable = os.access(db_path.parent, os.W_OK) and os.access(backup_path, os.W_OK)
        checks.append(("Storage", writable, f"{db_path.parent} / {backup_path}"))
    except Exception as exc:
        checks.append(("Storage", False, str(exc)[:120]))

    # Inventory integrity
    try:
        mismatches, _ = inventory_integrity_report(auto_repair=False)
        checks.append(("Inventory", len(mismatches) == 0, f"{len(mismatches)} mismatch"))
    except Exception as exc:
        checks.append(("Inventory", False, str(exc)[:120]))

    # Wallet integrity basics
    try:
        conn = db()
        negative = int(conn.execute(
            "SELECT COUNT(*) AS n FROM wallets WHERE balance<0"
        ).fetchone()["n"] or 0)
        checks.append(("Wallet", negative == 0, f"{negative} saldo negatif"))
        conn.close()
    except Exception as exc:
        checks.append(("Wallet", False, str(exc)[:120]))

    # Stuck paid orders
    try:
        conn = db()
        paid_pending = int(conn.execute(
            """SELECT COUNT(*) AS n FROM orders
               WHERE payment_status='paid'
                 AND fulfillment_status!='delivered'"""
        ).fetchone()["n"] or 0)
        send_failed = int(conn.execute(
            """SELECT COUNT(*) AS n FROM orders
               WHERE fulfillment_status='send_failed'"""
        ).fetchone()["n"] or 0)
        conn.close()
        checks.append((
            "Fulfillment",
            paid_pending == 0 and send_failed == 0,
            f"paid pending={paid_pending}, send failed={send_failed}"
        ))
    except Exception as exc:
        checks.append(("Fulfillment", False, str(exc)[:120]))

    # Payment configuration
    qris_ready = bool(get_setting("qris_file_id", ""))
    bank_ready = bank_transfer_ready()
    auto_ready = shopeepay_ready()
    payment_ok = qris_ready or bank_ready or auto_ready
    methods = []
    if qris_ready:
        methods.append("QRIS")
    if bank_ready:
        methods.append("Rekening")
    if auto_ready:
        methods.append("Gateway")
    checks.append((
        "Pembayaran",
        payment_ok,
        ", ".join(methods) if methods else "Belum ada metode aktif"
    ))

    # Invoice image renderer is optional because fallback text exists.
    checks.append((
        "Invoice",
        True,
        "Gambar aktif" if PIL_AVAILABLE else "Fallback teks aktif"
    ))

    # Safe mode / maintenance are launch blockers by design.
    checks.append((
        "Safe Mode",
        not safe_mode_enabled(),
        "OFF" if not safe_mode_enabled() else "ON"
    ))
    checks.append((
        "Maintenance",
        not maintenance_enabled(),
        "OFF" if not maintenance_enabled() else "ON"
    ))

    blockers = [name for name, ok, _ in checks if not ok]
    ready = len(blockers) == 0
    return ready, checks, blockers





def set_owner_input_session(user_id: int, flow: str, payload: dict):
    conn=db()
    conn.execute(
        """INSERT INTO owner_input_sessions(user_id,flow,payload,created_at)
           VALUES(?,?,?,?)
           ON CONFLICT(user_id) DO UPDATE SET
             flow=excluded.flow,
             payload=excluded.payload,
             created_at=excluded.created_at""",
        (
            int(user_id),
            str(flow),
            json.dumps(payload, ensure_ascii=False),
            datetime.now().isoformat(timespec="seconds")
        )
    )
    conn.commit()
    conn.close()


def get_owner_input_session(user_id: int):
    conn=db()
    row=conn.execute(
        "SELECT * FROM owner_input_sessions WHERE user_id=?",
        (int(user_id),)
    ).fetchone()
    conn.close()

    if not row:
        return None

    try:
        payload=json.loads(row["payload"] or "{}")
    except Exception:
        payload={}

    return {
        "flow": row["flow"],
        "payload": payload,
        "created_at": row["created_at"],
    }


def clear_owner_input_session(user_id: int):
    conn=db()
    conn.execute(
        "DELETE FROM owner_input_sessions WHERE user_id=?",
        (int(user_id),)
    )
    conn.commit()
    conn.close()


def set_payment_proof_session(user_id: int, entity: str, entity_id: int):
    conn = db()
    conn.execute(
        """INSERT INTO payment_proof_sessions(user_id,entity_type,entity_id,created_at)
           VALUES(?,?,?,?)
           ON CONFLICT(user_id) DO UPDATE SET
             entity_type=excluded.entity_type,
             entity_id=excluded.entity_id,
             created_at=excluded.created_at""",
        (
            int(user_id),
            str(entity),
            int(entity_id),
            datetime.now().isoformat(timespec="seconds")
        )
    )
    conn.commit()
    conn.close()


def get_payment_proof_session(user_id: int):
    conn = db()
    row = conn.execute(
        "SELECT * FROM payment_proof_sessions WHERE user_id=?",
        (int(user_id),)
    ).fetchone()
    conn.close()
    return row


def clear_payment_proof_session(user_id: int):
    conn = db()
    conn.execute(
        "DELETE FROM payment_proof_sessions WHERE user_id=?",
        (int(user_id),)
    )
    conn.commit()
    conn.close()


async def forward_payment_proof_to_owner(
    bot: Bot,
    message: Message,
    entity: str,
    entity_id: int,
    row,
) -> tuple[bool, str]:
    if not ADMIN_ID:
        logging.error(
            "PAYMENT_PROOF_FORWARD failed: ADMIN_ID is empty for %s:%s",
            entity,
            entity_id
        )
        return False, "ADMIN_ID belum dikonfigurasi."

    caption = payment_proof_caption(entity, row)
    keyboard = owner_payment_proof_keyboard(entity, entity_id)

    # Preferred path: copy the exact user evidence, then send action controls.
    # This is more reliable than re-sending a Telegram file_id after restarts.
    try:
        await bot.copy_message(
            chat_id=ADMIN_ID,
            from_chat_id=message.chat.id,
            message_id=message.message_id
        )
        await bot.send_message(
            ADMIN_ID,
            caption,
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        return True, ""
    except Exception as copy_exc:
        logging.warning(
            "Payment proof copy_message failed for %s:%s: %s",
            entity,
            entity_id,
            copy_exc
        )

    # Fallback: re-send by file_id.
    try:
        if message.photo:
            await bot.send_photo(
                ADMIN_ID,
                photo=message.photo[-1].file_id,
                caption=caption,
                reply_markup=keyboard,
                parse_mode="HTML"
            )
        elif message.document:
            await bot.send_document(
                ADMIN_ID,
                document=message.document.file_id,
                caption=caption,
                reply_markup=keyboard,
                parse_mode="HTML"
            )
        else:
            return False, "Bukti bukan foto/file gambar."
        return True, ""
    except Exception as send_exc:
        logging.exception(
            "PAYMENT_PROOF_FORWARD failed for %s:%s: %s",
            entity,
            entity_id,
            send_exc
        )
        return False, str(send_exc)[:300]


async def process_payment_proof_message(
    message: Message,
    state: FSMContext,
    bot: Bot,
    entity: str,
    entity_id: int,
):
    if entity not in {"order", "topup"} or not entity_id:
        return False, "Data invoice tidak valid."

    if not message.photo and not message.document:
        return False, "Bukti harus berupa foto atau file gambar."

    proof_type = "photo" if message.photo else "document"
    file_id = (
        message.photo[-1].file_id
        if message.photo
        else message.document.file_id
    )
    now = datetime.now().isoformat(timespec="seconds")

    conn = db()
    if entity == "order":
        row = conn.execute(
            "SELECT * FROM orders WHERE id=? AND user_id=?",
            (entity_id, message.from_user.id)
        ).fetchone()

        if not row:
            conn.close()
            return False, "Invoice tidak ditemukan."

        if row["payment_status"] == "paid":
            conn.close()
            clear_payment_proof_session(message.from_user.id)
            await state.clear()
            return False, "Order ini sudah diverifikasi."

        conn.execute(
            """UPDATE orders
               SET payment_proof_file_id=?,
                   payment_proof_type=?,
                   payment_proof_submitted_at=?,
                   payment_reject_reason=''
               WHERE id=?""",
            (file_id, proof_type, now, entity_id)
        )
    else:
        row = conn.execute(
            "SELECT * FROM topups WHERE id=? AND user_id=?",
            (entity_id, message.from_user.id)
        ).fetchone()

        if not row:
            conn.close()
            return False, "Invoice top up tidak ditemukan."

        if row["status"] == "completed":
            conn.close()
            clear_payment_proof_session(message.from_user.id)
            await state.clear()
            return False, "Top up ini sudah selesai."

        conn.execute(
            """UPDATE topups
               SET payment_proof_file_id=?,
                   payment_proof_type=?,
                   payment_proof_submitted_at=?,
                   payment_reject_reason=''
               WHERE id=?""",
            (file_id, proof_type, now, entity_id)
        )

    conn.commit()
    conn.close()

    forwarded, error = await forward_payment_proof_to_owner(
        bot,
        message,
        entity,
        entity_id,
        row
    )

    if forwarded:
        clear_payment_proof_session(message.from_user.id)
        await state.clear()
        return True, ""

    # Keep persistent session active so the user can retry after owner PM is fixed.
    set_payment_proof_session(message.from_user.id, entity, entity_id)
    return False, error or "Gagal meneruskan bukti ke owner."


def payment_proof_keyboard(entity: str, entity_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="📤 Kirim Bukti Pembayaran",
                callback_data=f"proofsubmit:{entity}:{entity_id}"
            )
        ],
        [
            InlineKeyboardButton(text="🧾 Pesanan Saya", callback_data="my_orders"),
            InlineKeyboardButton(text="🏠 Menu Utama", callback_data="home")
        ]
    ])


def owner_payment_proof_keyboard(entity: str, entity_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="✅ Konfirmasi",
                callback_data=f"proofapprove:{entity}:{entity_id}"
            ),
            InlineKeyboardButton(
                text="❌ Tolak",
                callback_data=f"proofreject:{entity}:{entity_id}"
            )
        ],
        [
            InlineKeyboardButton(
                text="⏳ Tandai Pending",
                callback_data=f"proofpending:{entity}:{entity_id}"
            )
        ]
    ])


def payment_proof_caption(entity: str, row) -> str:
    if entity == "order":
        return (
            "🧾 <b>BUKTI PEMBAYARAN ORDER</b>\n\n"
            f"Invoice: <b>{invoice(row['id'])}</b>\n"
            f"User ID: <code>{row['user_id']}</code>\n"
            f"Metode: <b>{html.escape(row['payment_method'])}</b>\n"
            f"Total: <b>{rupiah(row['payment_total'] or row['total'])}</b>\n"
            f"Kode unik: <b>+{int(row['unique_code'] or 0)}</b>\n"
            f"Catatan: <b>{html.escape(row['note'] or '-')}</b>\n\n"
            "Periksa bukti sebelum konfirmasi."
        )

    return (
        "💰 <b>BUKTI PEMBAYARAN TOP UP</b>\n\n"
        f"Invoice: <b>{topup_invoice(row['id'])}</b>\n"
        f"User ID: <code>{row['user_id']}</code>\n"
        f"Metode: <b>{html.escape(row['payment_method'])}</b>\n"
        f"Saldo masuk: <b>{rupiah(row['amount'])}</b>\n"
        f"Total transfer: <b>{rupiah(row['payment_total'])}</b>\n"
        f"Kode unik: <b>+{int(row['unique_code'] or 0)}</b>\n\n"
        "Periksa bukti sebelum konfirmasi."
    )


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


def unique_code_for_order(conn=None):
    """
    Kode unik pembayaran wajib:
    - selalu > 0
    - tidak random
    - tidak pernah memakai ulang kode yang sudah pernah tersimpan
    - aman terhadap race ketika dipanggil di dalam BEGIN IMMEDIATE
    """
    own_conn = conn is None
    if own_conn:
        conn = db()
        conn.execute("BEGIN IMMEDIATE")

    try:
        max_order = conn.execute(
            "SELECT COALESCE(MAX(unique_code),0) AS n FROM orders"
        ).fetchone()["n"]
        max_topup = conn.execute(
            "SELECT COALESCE(MAX(unique_code),0) AS n FROM topups"
        ).fetchone()["n"]

        last_setting = 0
        try:
            row = conn.execute(
                "SELECT value FROM settings WHERE key='last_unique_code'"
            ).fetchone()
            last_setting = int(row["value"]) if row and row["value"] else 0
        except Exception:
            last_setting = 0

        code = max(
            int(max_order or 0),
            int(max_topup or 0),
            int(last_setting or 0),
            0
        ) + 1

        conn.execute(
            """INSERT INTO settings(key,value)
               VALUES('last_unique_code',?)
               ON CONFLICT(key) DO UPDATE SET value=excluded.value""",
            (str(code),)
        )

        if own_conn:
            conn.commit()

        return code
    except Exception:
        if own_conn:
            conn.rollback()
        raise
    finally:
        if own_conn:
            conn.close()




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


async def mark_order_paid(
    order_id: int,
    bot: Bot,
    paid_amount: int | None = None,
    verified_by: int = 0,
):
    conn = db()
    conn.execute("BEGIN IMMEDIATE")
    order = conn.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()

    if not order:
        conn.rollback()
        conn.close()
        return False

    if order["status"] == "cancelled":
        conn.rollback()
        conn.close()
        return False

    now = datetime.now().isoformat(timespec="seconds")
    first_payment = order["payment_status"] != "paid"

    if first_payment:
        updated = conn.execute(
            """UPDATE orders
               SET payment_status='paid',
                   status='paid_pending_delivery',
                   payment_verified_at=?,
                   payment_verified_by=?,
                   payment_error=''
               WHERE id=?
                 AND payment_status!='paid'
                 AND status!='cancelled'""",
            (now, int(verified_by or 0), order_id)
        ).rowcount

        if updated != 1:
            conn.rollback()
            conn.close()
            return False

    conn.commit()
    conn.close()

    if first_payment:
        record_payment_event(
            "order", order_id, "paid",
            int(paid_amount or order["payment_total"] or order["total"]),
            verified_by,
            f"method={order['payment_method']}"
        )

        # Voucher is consumed only on the first successful payment transition.
        record_voucher_usage(
            order["voucher_code"] or "",
            order["user_id"],
            order_id,
            int(order["discount_amount"] or 0)
        )

    delivered = await fulfill_order(order_id, bot)

    return True


# =========================
# FSM
# =========================
class CheckoutState(StatesGroup):
    waiting_note = State()
    waiting_voucher = State()
    waiting_payment_proof = State()


class ShopToolsState(StatesGroup):
    search_product = State()


class BroadcastState(StatesGroup):
    waiting_message = State()

class BundleState(StatesGroup):
    choose_second = State()



class OwnerState(StatesGroup):
    add_product = State()
    add_product_variant_price = State()
    add_product_variant_name = State()
    add_product_description = State()
    add_product_name = State()
    add_variant = State()
    add_variant_price = State()
    add_variant_name = State()
    stock_add_items = State()
    set_price = State()
    mark_popular = State()
    mark_flash = State()
    set_qris = State()
    set_payment_note = State()
    topup_amount = State()
    owner_wallet_add = State()
    owner_wallet_subtract = State()
    owner_min_topup = State()
    variant_button_name = State()
    low_stock_threshold = State()
    voucher_code = State()
    voucher_discount = State()
    voucher_min_spend = State()
    voucher_quota = State()
    set_bank_name = State()
    set_bank_account = State()
    set_bank_holder = State()




async def show_loading_sequence(message: Message, final_text: str, reply_markup=None, parse_mode: str = "HTML"):
    """
    Lightweight Telegram loading animation.
    Uses one message and edits it a few times to avoid chat spam.
    """
    msg = await message.answer("⏳ <b>Memuat •</b>", parse_mode="HTML")

    for text in (
        "⏳ <b>Memuat ••</b>",
        "⏳ <b>Memuat •••</b>",
        "✅ <b>Selesai</b>"
    ):
        try:
            await asyncio.sleep(0.35)
            await msg.edit_text(text, parse_mode="HTML")
        except Exception:
            pass

    await asyncio.sleep(0.25)

    try:
        await msg.edit_text(
            final_text,
            reply_markup=reply_markup,
            parse_mode=parse_mode
        )
    except Exception:
        await message.answer(
            final_text,
            reply_markup=reply_markup,
            parse_mode=parse_mode
        )


async def show_loading_from_callback(call: CallbackQuery, final_text: str, reply_markup=None, parse_mode: str = "HTML"):
    """
    Loading animation for callback-based verification flow.
    """
    try:
        await call.message.edit_text("⏳ <b>Memuat •</b>", parse_mode="HTML")
    except Exception:
        return await show_loading_sequence(
            call.message,
            final_text,
            reply_markup=reply_markup,
            parse_mode=parse_mode
        )

    for text in (
        "⏳ <b>Memuat ••</b>",
        "⏳ <b>Memuat •••</b>",
        "✅ <b>Verifikasi berhasil</b>"
    ):
        try:
            await asyncio.sleep(0.35)
            await call.message.edit_text(text, parse_mode="HTML")
        except Exception:
            pass

    await asyncio.sleep(0.25)

    try:
        await call.message.edit_text(
            final_text,
            reply_markup=reply_markup,
            parse_mode=parse_mode
        )
    except Exception:
        await call.message.answer(
            final_text,
            reply_markup=reply_markup,
            parse_mode=parse_mode
        )


async def safe_edit_or_answer(call: CallbackQuery, text: str, reply_markup=None, parse_mode: str = "HTML"):
    """
    Reliable callback renderer:
    - text message -> edit_text
    - media/caption -> edit_caption
    - stale/non-editable message -> send new message
    - "message is not modified" -> treat as success, not an error
    """
    try:
        await call.message.edit_text(
            text,
            reply_markup=reply_markup,
            parse_mode=parse_mode
        )
        return True
    except Exception as exc:
        if "message is not modified" in str(exc).lower():
            return True

    try:
        if getattr(call.message, "caption", None) is not None:
            await call.message.edit_caption(
                caption=text,
                reply_markup=reply_markup,
                parse_mode=parse_mode
            )
            return True
    except Exception as exc:
        if "message is not modified" in str(exc).lower():
            return True

    try:
        await call.message.answer(
            text,
            reply_markup=reply_markup,
            parse_mode=parse_mode
        )
        return True
    except Exception:
        return False


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
    kb.button(text="📦 Produk & Stok", callback_data="owner:menu_products")
    kb.button(text="🧾 Order & Pembayaran", callback_data="owner:menu_orders")
    kb.button(text="👥 Pelanggan & Promo", callback_data="owner:menu_customers")
    kb.button(text="⚙️ Sistem", callback_data="owner:menu_system")
    kb.button(text="📊 Dashboard", callback_data="owner:stats")
    kb.button(text="🏠 Menu User", callback_data="home")
    kb.adjust(2, 2, 2)
    return kb.as_markup()





async def owner_product_error_view(call: CallbackQuery, feature: str, exc: Exception):
    logging.exception("Owner product feature failed [%s]: %s", feature, exc)
    try:
        log_system_error(
            "OWNER_PRODUCT",
            str(exc),
            reference=feature,
            severity="error",
            recovered=False
        )
    except Exception:
        pass

    await safe_edit_or_answer(
        call,
        "❌ <b>FITUR PRODUK ERROR</b>\n\n"
        f"Fitur: <b>{html.escape(feature)}</b>\n"
        f"Error: <code>{html.escape(str(exc)[:500])}</code>\n\n"
        "Menu Produk & Stok tetap dapat digunakan.",
        reply_markup=owner_products_menu(),
        parse_mode="HTML"
    )
    await safe_callback_notice(call)



def owner_delete_products_keyboard():
    conn=db()
    rows=conn.execute(
        "SELECT id,name FROM products WHERE active=1 ORDER BY id"
    ).fetchall()
    conn.close()

    kb=InlineKeyboardBuilder()
    for row in rows:
        kb.button(
            text=f"🗑️ {row['name']}",
            callback_data=f"ownerdelete:{row['id']}"
        )
    kb.button(text="⬅️ Kembali", callback_data="owner:back_products")
    kb.adjust(1)
    return kb.as_markup()


def owner_stock_products_keyboard():
    conn=db()
    rows=conn.execute(
        "SELECT id,name FROM products WHERE active=1 ORDER BY id"
    ).fetchall()
    conn.close()

    kb=InlineKeyboardBuilder()
    for row in rows:
        kb.button(
            text=f"📦 {row['name']}",
            callback_data=f"ownerstock:{row['id']}"
        )
    kb.button(text="⬅️ Kembali", callback_data="owner:back_products")
    kb.adjust(1)
    return kb.as_markup()


def owner_stock_variants_keyboard(product_id: int):
    conn=db()
    rows=conn.execute(
        """SELECT id,name,stock,reserved_stock
           FROM product_variants
           WHERE product_id=? AND active=1
           ORDER BY id""",
        (int(product_id),)
    ).fetchall()
    conn.close()

    kb=InlineKeyboardBuilder()
    for row in rows:
        available=max(0, int(row["stock"] or 0)-int(row["reserved_stock"] or 0))
        kb.button(
            text=f"🧩 {row['name']} • {available}",
            callback_data=f"ownerstockvar:{row['id']}"
        )
    kb.button(text="⬅️ Kembali", callback_data="owner:set_stock")
    kb.adjust(1)
    return kb.as_markup()

def owner_stock_variant_actions(variant_id: int):
    conn=db()
    row=conn.execute(
        """SELECT v.id,v.name,v.stock,v.reserved_stock,p.id AS product_id,p.name AS product_name
           FROM product_variants v
           JOIN products p ON p.id=v.product_id
           WHERE v.id=? AND v.active=1 AND p.active=1""",
        (int(variant_id),)
    ).fetchone()
    conn.close()

    kb=InlineKeyboardBuilder()

    if not row:
        kb.button(text="⬅️ Kembali", callback_data="owner:set_stock")
        kb.adjust(1)
        return kb.as_markup()

    kb.button(
        text="➕ Tambah Akun",
        callback_data=f"ownerstockadd:{variant_id}"
    )
    kb.button(
        text="📚 Riwayat Stok",
        callback_data="owner:inventory_log"
    )
    kb.button(
        text="⬅️ Kembali",
        callback_data=f"ownerstock:{row['product_id']}"
    )
    kb.adjust(1)
    return kb.as_markup()





def owner_products_menu():
    kb = InlineKeyboardBuilder()
    kb.button(text="➕ Tambah Produk", callback_data="owner:add_product")
    kb.button(text="📦 Atur Stok", callback_data="owner:set_stock")
    kb.button(text="🔔 Alert Stok", callback_data="owner:low_stock")
    kb.button(text="📚 Riwayat Stok", callback_data="owner:inventory_log")
    kb.button(text="🏷️ Nama Tombol Variasi", callback_data="owner:variant_button_name")
    kb.button(text="💰 Atur Harga", callback_data="owner:set_price")
    kb.button(text="🗑️ Hapus Produk", callback_data="owner:delete_product")
    kb.button(text="🔥 Produk Populer", callback_data="owner:mark_popular")
    kb.button(text="⚡ Flash Sale", callback_data="owner:mark_flash")
    kb.button(text="🎁 Paket / Bundle", callback_data="owner:bundles")
    kb.button(text="⬅️ Kembali", callback_data="owner:panel")
    kb.adjust(2, 2, 2, 2, 1, 1)
    return kb.as_markup()


def owner_orders_menu():
    kb = InlineKeyboardBuilder()
    kb.button(text="🧾 Pesanan", callback_data="owner:orders")
    kb.button(text="📥 Verifikasi via Bukti PM", callback_data="owner:proof_info")
    kb.button(text="💳 Pengaturan Pembayaran", callback_data="owner:qris_settings")
    kb.button(text="💰 Manajemen Saldo", callback_data="owner:wallet")
    kb.button(text="♻️ Recovery Order", callback_data="owner:recover_orders")
    kb.button(text="📨 Kirim Ulang Akun", callback_data="owner:resend_order")
    kb.button(text="❌ Batalkan Order", callback_data="owner:cancel_order")
    kb.button(text="⬅️ Kembali", callback_data="owner:panel")
    kb.adjust(2, 2, 2, 1, 1)
    return kb.as_markup()


def owner_customers_menu():
    kb = InlineKeyboardBuilder()
    kb.button(text="🎁 Voucher", callback_data="owner:add_voucher")
    kb.button(text="📣 Broadcast", callback_data="owner:broadcast")
    kb.button(text="👥 Segmentasi", callback_data="owner:segments")
    kb.button(text="🎯 Promo Otomatis", callback_data="owner:auto_promo")
    kb.button(text="⭐ Ulasan", callback_data="owner:reviews")
    kb.button(text="🛡️ Anti-Fraud", callback_data="owner:security")
    kb.button(text="⬅️ Kembali", callback_data="owner:panel")
    kb.adjust(2, 2, 2, 1)
    return kb.as_markup()


async def owner_system_error_view(call: CallbackQuery, feature: str, exc: Exception):
    logging.exception("Owner system feature failed [%s]: %s", feature, exc)
    try:
        log_system_error(
            "OWNER_SYSTEM",
            str(exc),
            reference=feature,
            severity="error",
            recovered=False
        )
    except Exception:
        logging.exception("Failed to write owner system error log.")

    await safe_edit_or_answer(
        call,
        "❌ <b>FITUR SISTEM ERROR</b>\n\n"
        f"Fitur: <b>{html.escape(feature)}</b>\n"
        f"Error: <code>{html.escape(str(exc)[:600])}</code>\n\n"
        "Fitur lain tetap dapat digunakan.",
        reply_markup=owner_system_menu(),
        parse_mode="HTML"
    )


async def safe_callback_notice(call: CallbackQuery, text: str = ""):
    try:
        await call.answer(text)
    except Exception:
        pass




def validate_system_schema():
    required = {
        "orders": {
            "id","user_id","status","payment_status","fulfillment_status",
            "variant_id","qty","stock_reserved","reserved_until","created_at"
        },
        "topups": {"id","user_id","status","expires_at","created_at"},
        "product_variants": {"id","stock","reserved_stock","active"},
        "inventory_items": {"id","variant_id","status","order_id"},
        "settings": {"key","value"},
        "system_errors": {"id","error_text","created_at"},
        "payment_proof_sessions": {"user_id","entity_type","entity_id"},
    }

    conn=db()
    problems=[]
    try:
        for table, columns in required.items():
            exists=conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                (table,)
            ).fetchone()
            if not exists:
                problems.append(f"table {table} tidak ada")
                continue

            real={
                row["name"]
                for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
            }
            missing=sorted(columns-real)
            if missing:
                problems.append(f"{table}: kolom kurang {', '.join(missing)}")
    finally:
        conn.close()

    return len(problems)==0, problems


def cleanup_data_counts():
    conn = db()
    now = datetime.now().isoformat(timespec="seconds")

    def count(sql, params=()):
        row=conn.execute(sql, params).fetchone()
        return int(row["n"] or 0)

    try:
        return {
            "pending_orders": count(
                """SELECT COUNT(*) AS n FROM orders
                   WHERE payment_status!='paid'
                     AND status IN ('pending','pending_payment','waiting_payment')"""
            ),
            "expired_orders": count(
                """SELECT COUNT(*) AS n FROM orders
                   WHERE payment_status!='paid'
                     AND status NOT IN ('completed','cancelled')
                     AND (
                        (reserved_until IS NOT NULL AND reserved_until!='' AND reserved_until<=?)
                        OR status='expired'
                     )""",
                (now,)
            ),
            "expired_topups": count(
                """SELECT COUNT(*) AS n FROM topups
                   WHERE status NOT IN ('completed','paid')
                     AND (
                        (expires_at IS NOT NULL AND expires_at!='' AND expires_at<=?)
                        OR status='expired'
                     )""",
                (now,)
            ),
            "proof_sessions": count(
                "SELECT COUNT(*) AS n FROM payment_proof_sessions"
            ),
            "system_errors": count(
                "SELECT COUNT(*) AS n FROM system_errors"
            ),
        }
    finally:
        conn.close()




def cleanup_data_keyboard():
    counts=cleanup_data_counts()
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"🧾 Order Expired ({counts['expired_orders']})",
            callback_data="cleanup:preview:orders"
        )],
        [InlineKeyboardButton(
            text=f"⏳ Pesanan Pending ({counts['pending_orders']})",
            callback_data="cleanup:preview:pending"
        )],
        [InlineKeyboardButton(
            text=f"💰 Top Up Expired ({counts['expired_topups']})",
            callback_data="cleanup:preview:topups"
        )],
        [InlineKeyboardButton(
            text=f"📎 Session Bukti ({counts['proof_sessions']})",
            callback_data="cleanup:preview:proofs"
        )],
        [InlineKeyboardButton(
            text=f"🧯 Log Error ({counts['system_errors']})",
            callback_data="cleanup:preview:errors"
        )],
        [InlineKeyboardButton(
            text="🧹 Bersihkan Data Aman",
            callback_data="cleanup:preview:safe"
        )],
        [InlineKeyboardButton(
            text="⬅️ Kembali",
            callback_data="owner:back_system"
        )]
    ])


def cleanup_preview_text(kind: str):
    counts=cleanup_data_counts()
    mapping={
        "pending": (
            "⏳ PESANAN PENDING BELUM BAYAR",
            counts["pending_orders"],
            "Pesanan pending yang BELUM dibayar. Reservasi stok akan dilepas sebelum order dihapus. Order paid tidak termasuk."
        ),
        "orders": (
            "🧾 ORDER EXPIRED",
            counts["expired_orders"],
            "Order belum dibayar yang sudah expired. Reservasi stok akan dilepas sebelum order dihapus."
        ),
        "topups": (
            "💰 TOP UP EXPIRED",
            counts["expired_topups"],
            "Top up yang belum selesai dan sudah expired."
        ),
        "proofs": (
            "📎 SESSION BUKTI PEMBAYARAN",
            counts["proof_sessions"],
            "Session bukti pembayaran yang tersimpan. Bukti pada transaksi tidak ikut dihapus."
        ),
        "errors": (
            "🧯 LOG ERROR SISTEM",
            counts["system_errors"],
            "Riwayat log error sistem. Transaksi user tidak ikut dihapus."
        ),
        "safe": (
            "🧹 PEMBERSIHAN DATA AMAN",
            counts["expired_orders"] + counts["expired_topups"] + counts["proof_sessions"],
            "Order expired belum bayar, top up expired, dan session bukti akan dibersihkan sekaligus."
        ),
    }
    return mapping.get(kind)


def cleanup_confirm_keyboard(kind: str):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="✅ Ya, Hapus",
            callback_data=f"cleanup:confirm:{kind}"
        )],
        [InlineKeyboardButton(
            text="❌ Batal",
            callback_data="owner:cleanup_data"
        )]
    ])


def cleanup_execute(kind: str):
    conn=db()
    now=datetime.now().isoformat(timespec="seconds")
    result={"orders":0,"topups":0,"proofs":0,"errors":0}

    try:
        conn.execute("BEGIN IMMEDIATE")


        if kind=="pending":
            rows=conn.execute(
                """SELECT id,variant_id,qty,stock_reserved
                   FROM orders
                   WHERE payment_status!='paid'
                     AND status IN ('pending','pending_payment','waiting_payment')"""
            ).fetchall()

            for row in rows:
                if int(row["stock_reserved"] or 0)==1:
                    conn.execute(
                        """UPDATE product_variants
                           SET reserved_stock=MAX(0,reserved_stock-?)
                           WHERE id=?""",
                        (int(row["qty"] or 0), row["variant_id"])
                    )

            ids=[int(r["id"]) for r in rows]
            if ids:
                marks=",".join("?" for _ in ids)
                conn.execute(f"DELETE FROM orders WHERE id IN ({marks})", ids)
            result["orders"]=len(ids)

        if kind in {"orders","safe"}:
            rows=conn.execute(
                """SELECT id,variant_id,qty,stock_reserved
                   FROM orders
                   WHERE payment_status!='paid'
                     AND status NOT IN ('completed','cancelled')
                     AND (
                        (reserved_until IS NOT NULL AND reserved_until!='' AND reserved_until<=?)
                        OR status='expired'
                     )""",
                (now,)
            ).fetchall()

            for row in rows:
                if int(row["stock_reserved"] or 0)==1:
                    conn.execute(
                        """UPDATE product_variants
                           SET reserved_stock=MAX(0,reserved_stock-?)
                           WHERE id=?""",
                        (int(row["qty"] or 0), row["variant_id"])
                    )

            ids=[int(r["id"]) for r in rows]
            if ids:
                marks=",".join("?" for _ in ids)
                conn.execute(f"DELETE FROM orders WHERE id IN ({marks})", ids)
            result["orders"]=len(ids)

        if kind in {"topups","safe"}:
            rows=conn.execute(
                """SELECT id FROM topups
                   WHERE status NOT IN ('completed','paid')
                     AND (
                        (expires_at IS NOT NULL AND expires_at!='' AND expires_at<=?)
                        OR status='expired'
                     )""",
                (now,)
            ).fetchall()
            ids=[int(r["id"]) for r in rows]
            if ids:
                marks=",".join("?" for _ in ids)
                conn.execute(f"DELETE FROM topups WHERE id IN ({marks})", ids)
            result["topups"]=len(ids)

        if kind in {"proofs","safe"}:
            cur=conn.execute("DELETE FROM payment_proof_sessions")
            result["proofs"]=max(0,int(cur.rowcount or 0))

        if kind=="errors":
            cur=conn.execute("DELETE FROM system_errors")
            result["errors"]=max(0,int(cur.rowcount or 0))

        conn.commit()
        return result
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def owner_system_menu():
    kb = InlineKeyboardBuilder()
    kb.button(text="🩺 Diagnostik Sistem", callback_data="owner:diagnostics")
    kb.button(text="📨 Test PM Owner", callback_data="owner:test_pm")
    kb.button(text="📢 Test Channel", callback_data="owner:test_channel")
    kb.button(text="🛟 Safe Mode", callback_data="owner:safe_mode")
    kb.button(text="🧹 Repair Inventory", callback_data="owner:repair_inventory")
    kb.button(text="♻️ Auto Recovery", callback_data="owner:auto_recovery_now")
    kb.button(text="🔧 Maintenance", callback_data="owner:maintenance")
    kb.button(text="🗄️ Backup Sekarang", callback_data="owner:backup_now")
    kb.button(text="📢 Sinkron Stok Channel", callback_data="owner:sync_stock")
    kb.button(text="📅 Laporan Harian", callback_data="owner:daily_report")
    kb.button(text="🗑️ Hapus Data", callback_data="owner:cleanup_data")
    kb.button(text="⬅️ Kembali", callback_data="owner:panel")
    kb.adjust(2, 2, 2, 2, 1)
    return kb.as_markup()



def back_home():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Menu Utama", callback_data="home")]
    ])


def back_owner(target: str = "owner:panel"):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Kembali", callback_data=target)]
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
            callback_data=("noop" if value == amount else f"topup:set:{value}")
        )

    if presets:
        kb.adjust(2)

    kb.row(
        InlineKeyboardButton(
            text="✏️ Nominal Custom",
            callback_data="topup:custom"
        )
    )
    kb.row(
        InlineKeyboardButton(
            text=f"✅ Lanjut Pembayaran • {rupiah(amount)}",
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
    return topup_payment_method_keyboard(amount)


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
    kb.button(text="📑 Riwayat Saldo", callback_data="owner:wallet_history")
    kb.button(text="⚙️ Minimum Top Up", callback_data="owner:min_topup")
    kb.button(text="⬅️ Kembali", callback_data="owner:panel")
    kb.adjust(2, 2, 1)
    return kb.as_markup()



def bank_settings_menu():
    ready = bank_transfer_ready()
    kb = InlineKeyboardBuilder()
    kb.button(text="🏦 Nama Bank", callback_data="owner:bank_name")
    kb.button(text="💳 No. Rekening", callback_data="owner:bank_account")
    kb.button(text="👤 Atas Nama", callback_data="owner:bank_holder")
    kb.button(
        text=("✅ Status: AKTIF" if ready else "⚠️ Status: BELUM LENGKAP"),
        callback_data="owner:bank_preview"
    )
    kb.button(text="⬅️ Kembali", callback_data="owner:qris_settings")
    kb.adjust(2, 1, 1, 1)
    return kb.as_markup()



async def save_owner_qris_photo(message: Message, state: FSMContext, file_id: str):
    set_setting("qris_file_id", file_id)
    set_setting("qris_upload_pending", "0")
    await state.clear()

    await message.answer_photo(
        photo=file_id,
        caption=(
            "✅ <b>QRIS BERHASIL DISIMPAN</b>\n\n"
            "QRIS baru sudah aktif untuk pembayaran manual.\n"
            "Gunakan tombol Preview QRIS untuk memastikan gambar tampil dengan benar."
        ),
        reply_markup=qris_settings_menu(),
        parse_mode="HTML"
    )


def qris_settings_menu():
    mode = get_setting("payment_mode", "manual")
    kb = InlineKeyboardBuilder()
    kb.button(text="🖼️ Ganti QRIS Manual", callback_data="owner:qris_set")
    kb.button(text="🏦 Rekening Transfer", callback_data="owner:bank_settings")
    kb.button(text="📝 Edit Catatan", callback_data="owner:qris_note")
    kb.button(text="🔢 Kode Unik: WAJIB", callback_data="owner:unique_info")
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

    # Pilih jumlah langsung dari menu angka.
    quick_max = min(stock, 20)
    for number in range(1, quick_max + 1):
        prefix = "✅ " if number == qty else ""
        kb.button(
            text=f"{prefix}{number}",
            callback_data=("noop" if number == qty else f"qty:{variant_id}:{number}")
        )

    if quick_max > 0:
        kb.adjust(5)

    if stock > 20:
        kb.row(
            InlineKeyboardButton(
                text=f"📦 MAX {stock}",
                callback_data=("noop" if qty == stock else f"qty:{variant_id}:{stock}")
            )
        )

    if stock > 0:
        kb.row(
            InlineKeyboardButton(
                text=f"🛒 Lanjut Beli • Qty {qty}",
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

class CallbackTraceMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        started=time.monotonic()
        callback_data=str(getattr(event,"data","") or "")
        user_id=int(getattr(getattr(event,"from_user",None),"id",0) or 0)

        LAST_CALLBACK_TRACE.update({
            "at": datetime.now().isoformat(timespec="seconds"),
            "data": callback_data[:250],
            "user_id": user_id,
            "elapsed_ms": 0,
            "status": "received",
        })

        try:
            result=await handler(event,data)
            LAST_CALLBACK_TRACE["status"]="handled"
            return result
        except Exception:
            LAST_CALLBACK_TRACE["status"]="error"
            raise
        finally:
            LAST_CALLBACK_TRACE["elapsed_ms"]=int(
                (time.monotonic()-started)*1000
            )


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
    await safe_edit_or_answer(call, 
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

    await safe_edit_or_answer(call, 
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
    await safe_edit_or_answer(call, 
        "⭐ <b>PRODUK FAVORIT</b>\n\n"+(f"{len(rows)} produk tersimpan." if rows else "Belum ada favorit."),
        reply_markup=kb.as_markup(),
        parse_mode="HTML"
    )
    await call.answer()



@router.callback_query(F.data == "cartcheckout:wallet")
async def cart_checkout_wallet(call: CallbackQuery, bot: Bot):
    if safe_mode_enabled() and not is_owner(call.from_user.id):
        return await call.answer(
            "Sistem sedang Safe Mode. Pembayaran sementara ditahan.",
            show_alert=True
        )
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

    await safe_edit_or_answer(call, 
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

    await safe_edit_or_answer(call, 
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

    await safe_edit_or_answer(call, 
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
    await safe_edit_or_answer(call, "\n".join(lines),reply_markup=kb.as_markup(),parse_mode="HTML")
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



@router.callback_query(F.data.startswith("proofsubmit:"))
async def payment_proof_start(call: CallbackQuery, state: FSMContext):
    try:
        _, entity, raw_id = call.data.split(":")
        entity_id = int(raw_id)
    except Exception:
        return await call.answer("Data invoice tidak valid.", show_alert=True)

    if entity not in {"order", "topup"}:
        return await call.answer("Jenis transaksi tidak valid.", show_alert=True)

    conn = db()
    if entity == "order":
        row = conn.execute(
            "SELECT * FROM orders WHERE id=? AND user_id=?",
            (entity_id, call.from_user.id)
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT * FROM topups WHERE id=? AND user_id=?",
            (entity_id, call.from_user.id)
        ).fetchone()
    conn.close()

    if not row:
        return await call.answer("Invoice tidak ditemukan.", show_alert=True)

    if entity == "order" and row["payment_status"] == "paid":
        return await call.answer("Order ini sudah diverifikasi.", show_alert=True)
    if entity == "topup" and row["status"] == "completed":
        return await call.answer("Top up ini sudah selesai.", show_alert=True)

    set_payment_proof_session(call.from_user.id, entity, entity_id)

    await state.update_data(
        proof_entity=entity,
        proof_entity_id=entity_id
    )
    await state.set_state(CheckoutState.waiting_payment_proof)

    await safe_edit_or_answer(
        call,
        "📤 <b>KIRIM BUKTI PEMBAYARAN</b>\n\n"
        "Kirim <b>foto/screenshot bukti transfer</b> ke chat ini.\n\n"
        "Bukti akan diteruskan ke owner untuk diperiksa.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Batal", callback_data="my_orders")]
        ]),
        parse_mode="HTML"
    )
    await call.answer()


@router.message(CheckoutState.waiting_payment_proof, F.photo)
async def payment_proof_photo(message: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    entity = data.get("proof_entity")
    entity_id = int(data.get("proof_entity_id") or 0)

    if entity not in {"order", "topup"} or not entity_id:
        session = get_payment_proof_session(message.from_user.id)
        if session:
            entity = session["entity_type"]
            entity_id = int(session["entity_id"])

    ok, error = await process_payment_proof_message(
        message,
        state,
        bot,
        entity,
        entity_id
    )

    if not ok:
        return await message.answer(
            "❌ <b>BUKTI BELUM TERKIRIM KE OWNER</b>\n\n"
            f"{html.escape(error)}\n\n"
            "Silakan coba kirim ulang. Jika tetap gagal, owner perlu membuka/start chat bot terlebih dahulu.",
            parse_mode="HTML"
        )

    await message.answer(
        "✅ <b>BUKTI PEMBAYARAN TERKIRIM</b>\n\n"
        "Bukti sudah benar-benar diteruskan ke PM owner.\n"
        "Owner akan memeriksa dan mengonfirmasi pembayaran.",
        reply_markup=main_menu(),
        parse_mode="HTML"
    )



@router.message(CheckoutState.waiting_payment_proof, F.document)
async def payment_proof_document(message: Message, state: FSMContext, bot: Bot):
    document = message.document
    mime = (document.mime_type or "").lower() if document else ""
    if not document or not mime.startswith("image/"):
        return await message.answer(
            "❌ Bukti harus berupa foto/screenshot atau file gambar."
        )

    data = await state.get_data()
    entity = data.get("proof_entity")
    entity_id = int(data.get("proof_entity_id") or 0)

    if entity not in {"order", "topup"} or not entity_id:
        session = get_payment_proof_session(message.from_user.id)
        if session:
            entity = session["entity_type"]
            entity_id = int(session["entity_id"])

    ok, error = await process_payment_proof_message(
        message,
        state,
        bot,
        entity,
        entity_id
    )

    if not ok:
        return await message.answer(
            "❌ <b>BUKTI BELUM TERKIRIM KE OWNER</b>\n\n"
            f"{html.escape(error)}\n\n"
            "Silakan coba kirim ulang. Jika tetap gagal, owner perlu membuka/start chat bot terlebih dahulu.",
            parse_mode="HTML"
        )

    await message.answer(
        "✅ <b>BUKTI PEMBAYARAN TERKIRIM</b>\n\n"
        "Bukti sudah benar-benar diteruskan ke PM owner.",
        reply_markup=main_menu(),
        parse_mode="HTML"
    )



@router.message(CheckoutState.waiting_payment_proof)
async def payment_proof_invalid(message: Message):
    await message.answer(
        "❌ Kirim bukti pembayaran sebagai foto/screenshot atau file gambar."
    )


@router.message(Command("owner"))
async def owner(message: Message, state: FSMContext):
    await state.clear()
    if not is_owner(message.from_user.id):
        return await message.answer(owner_access_denied_text(), parse_mode="HTML")

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
        await safe_edit_or_answer(call, 
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



@router.callback_query(F.data == "owner:back_products")
async def owner_back_products(call: CallbackQuery, state: FSMContext):
    if not is_owner(call.from_user.id):
        return await call.answer("Akses ditolak.", show_alert=True)
    await state.clear()
    await safe_edit_or_answer(
        call,
        "📦 <b>PRODUK & STOK</b>\n\nPilih pengaturan:",
        reply_markup=owner_products_menu(),
        parse_mode="HTML"
    )
    await call.answer()


@router.callback_query(F.data == "owner:back_orders")
async def owner_back_orders(call: CallbackQuery, state: FSMContext):
    if not is_owner(call.from_user.id):
        return await call.answer("Akses ditolak.", show_alert=True)
    await state.clear()
    await safe_edit_or_answer(
        call,
        "🧾 <b>ORDER & PEMBAYARAN</b>\n\nPilih pengaturan:",
        reply_markup=owner_orders_menu(),
        parse_mode="HTML"
    )
    await call.answer()


@router.callback_query(F.data == "owner:back_customers")
async def owner_back_customers(call: CallbackQuery, state: FSMContext):
    if not is_owner(call.from_user.id):
        return await call.answer("Akses ditolak.", show_alert=True)
    await state.clear()
    await safe_edit_or_answer(
        call,
        "👥 <b>PELANGGAN & PROMO</b>\n\nPilih pengaturan:",
        reply_markup=owner_customers_menu(),
        parse_mode="HTML"
    )
    await call.answer()


@router.callback_query(F.data == "owner:back_system")
async def owner_back_system(call: CallbackQuery, state: FSMContext):
    if not is_owner(call.from_user.id):
        return await deny_owner_callback(call)

    try:
        await state.clear()
        await safe_edit_or_answer(
            call,
            "⚙️ <b>SISTEM</b>\n\nPilih fitur sistem:",
            reply_markup=owner_system_menu(),
            parse_mode="HTML"
        )
        await safe_callback_notice(call)
    except Exception as exc:
        await owner_system_error_view(call, "Menu Sistem", exc)



@router.callback_query(F.data == "owner:menu_products")
async def owner_menu_products(call: CallbackQuery, state: FSMContext):
    if not is_owner(call.from_user.id):
        return await deny_owner_callback(call)

    try:
        await state.clear()
        await safe_edit_or_answer(
            call,
            "📦 <b>PRODUK & STOK</b>\n\nPilih pengaturan:",
            reply_markup=owner_products_menu(),
            parse_mode="HTML"
        )
        await safe_callback_notice(call)
    except Exception as exc:
        await owner_product_error_view(call, "Menu Produk & Stok", exc)



@router.callback_query(F.data == "owner:menu_orders")
async def owner_menu_orders(call: CallbackQuery, state: FSMContext):
    if not is_owner(call.from_user.id):
        return await call.answer("Akses ditolak.", show_alert=True)
    await state.clear()
    await safe_edit_or_answer(
        call,
        "🧾 <b>ORDER & PEMBAYARAN</b>\n\nPilih pengaturan:",
        reply_markup=owner_orders_menu(),
        parse_mode="HTML"
    )
    await call.answer()


@router.callback_query(F.data == "owner:menu_customers")
async def owner_menu_customers(call: CallbackQuery, state: FSMContext):
    if not is_owner(call.from_user.id):
        return await call.answer("Akses ditolak.", show_alert=True)
    await state.clear()
    await safe_edit_or_answer(
        call,
        "👥 <b>PELANGGAN & PROMO</b>\n\nPilih pengaturan:",
        reply_markup=owner_customers_menu(),
        parse_mode="HTML"
    )
    await call.answer()


@router.callback_query(F.data == "owner:menu_system")
async def owner_menu_system(call: CallbackQuery, state: FSMContext):
    if not is_owner(call.from_user.id):
        return await deny_owner_callback(call)

    try:
        await state.clear()
        await safe_edit_or_answer(
            call,
            "⚙️ <b>SISTEM</b>\n\nPilih fitur sistem:",
            reply_markup=owner_system_menu(),
            parse_mode="HTML"
        )
        await safe_callback_notice(call)
    except Exception as exc:
        await owner_system_error_view(call, "Menu Sistem", exc)



@router.message(Command("ping"))
async def ping(message: Message, bot: Bot):
    if not is_owner(message.from_user.id):
        return await message.answer(
            "⛔ <b>AKSES DITOLAK</b>\n\n"
            "Command <code>/ping</code> khusus owner.",
            parse_mode="HTML"
        )

    ready, checks, blockers = await launch_readiness_report(bot)

    now = jakarta_now()
    uptime_seconds = int(time.time() - START_TIME)
    uptime_text = format_uptime_detail(uptime_seconds)

    hari_indonesia = {
        "Monday": "Senin",
        "Tuesday": "Selasa",
        "Wednesday": "Rabu",
        "Thursday": "Kamis",
        "Friday": "Jumat",
        "Saturday": "Sabtu",
        "Sunday": "Minggu",
    }

    bulan_indonesia = {
        1: "Januari", 2: "Februari", 3: "Maret", 4: "April",
        5: "Mei", 6: "Juni", 7: "Juli", 8: "Agustus",
        9: "September", 10: "Oktober", 11: "November", 12: "Desember"
    }

    day_name = hari_indonesia.get(now.strftime("%A"), now.strftime("%A"))
    now_date = f"{day_name}, {now.day} {bulan_indonesia[now.month]} {now.year}"
    now_time = now.strftime("%H:%M:%S WIB")


    lines = [
        ("🟢" if ready else "🔴")
        + f" <b>STATUS BOT: {'SIAP' if ready else 'PERLU DICEK'}</b>",
        "",
        "🤖 <b>INFORMASI BOT</b>",
        f"• Versi: <b>v{BOT_VERSION}</b>",
        f"• Tanggal: <b>{now_date}</b>",
        f"• Jam: <b>{now_time}</b>",
        f"• Runtime: <b>{uptime_text}</b>",
        "",
        "🩺 <b>STATUS SISTEM</b>",
    ]

    for name, ok, detail in checks:
        lines.append(
            f"{'✅' if ok else '❌'} <b>{html.escape(name)}</b>: "
            f"{html.escape(str(detail))}"
        )

    if blockers:
        lines += [
            "",
            "⚠️ <b>Yang perlu diperbaiki:</b>",
            *[f"• {html.escape(name)}" for name in blockers]
        ]
    else:
        lines += [
            "",
            "✅ <b>Tidak ada blocker utama terdeteksi.</b>"
        ]

    await message.answer(
        "\n".join(lines),
        parse_mode="HTML"
    )



# =========================
# USER FLOW
# =========================

@router.callback_query(F.data == "verify_join")
async def verify_join(call: CallbackQuery, bot: Bot, state: FSMContext):
    joined, reason, detail = await check_channel_membership(
        bot,
        call.from_user.id
    )

    check_time = datetime.now().strftime("%H:%M:%S")

    if joined:
        mark_user_verified(
            call.from_user.id,
            call.from_user.username or ""
        )
        await state.clear()

        try:
            await call.answer("✅ Verifikasi berhasil!", show_alert=True)
        except Exception:
            pass

        success_text = (
            f"🛍️ <b>{STORE_NAME}</b>\n\n"
            "✅ <b>VERIFIKASI BERHASIL</b>\n"
            f"Dicek: <b>{check_time} WIB</b>\n\n"
            "Silakan pilih menu:"
        )

        edited = await safe_edit_or_answer(
            call,
            success_text,
            reply_markup=main_menu(),
            parse_mode="HTML"
        )

        try:
            await call.message.answer(
                "✅ Menu cepat sudah aktif.",
                reply_markup=user_reply_menu()
            )
        except Exception:
            if not edited:
                await call.message.answer(
                    success_text,
                    reply_markup=main_menu(),
                    parse_mode="HTML"
                )
        return

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
            text=f"🔄 Cek Lagi • {check_time}",
            callback_data="verify_join"
        )
    ])

    if reason == "not_member":
        title = "❌ <b>BELUM TERDETEKSI JOIN</b>"
        explanation = (
            "Telegram masih membaca akun Anda sebagai belum menjadi member.\n\n"
            "Pastikan Anda join menggunakan akun Telegram yang sama dengan akun yang memakai bot."
        )
        alert = "Belum terdeteksi sebagai member."
    elif reason == "bot_not_admin":
        title = "⚠️ <b>VERIFIKASI CHANNEL BELUM SIAP</b>"
        explanation = (
            "Bot belum memiliki akses yang cukup untuk memeriksa member channel.\n\n"
            "Owner perlu menjadikan bot sebagai <b>admin channel</b> agar verifikasi user dapat bekerja."
        )
        alert = "Bot belum menjadi admin channel."
    elif reason == "invalid_channel":
        title = "⚠️ <b>KONFIGURASI CHANNEL SALAH</b>"
        explanation = (
            "Channel wajib tidak dapat ditemukan.\n\n"
            "Owner perlu memeriksa <code>REQUIRED_CHANNEL_ID</code> di Railway."
        )
        alert = "REQUIRED_CHANNEL_ID perlu diperiksa."
    else:
        title = "⚠️ <b>VERIFIKASI SEMENTARA GAGAL</b>"
        explanation = (
            "Telegram tidak dapat menyelesaikan pengecekan membership saat ini.\n"
            "Silakan coba lagi beberapa saat."
        )
        alert = "Pengecekan Telegram gagal."

    try:
        await call.answer(
            f"{alert}\nCek: {check_time} WIB",
            show_alert=True
        )
    except Exception:
        pass

    await safe_edit_or_answer(
        call,
        f"{title}\n\n"
        f"{explanation}\n\n"
        f"🕒 Pemeriksaan terakhir: <b>{check_time} WIB</b>\n"
        f"📢 Channel: <b>{html.escape(REQUIRED_CHANNEL_NAME)}</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
        parse_mode="HTML"
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

    await safe_edit_or_answer(call, 
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
    await safe_callback_notice(call)
    await show_product_list(call, "🏷️ <b>LIST PRODUK</b>")


@router.callback_query(F.data == "popular")
async def popular(call: CallbackQuery):
    await safe_callback_notice(call)
    await show_product_list(call, "🔥 <b>PRODUK POPULER</b>", "AND is_popular=1")


@router.callback_query(F.data == "flash")
async def flash(call: CallbackQuery):
    await safe_callback_notice(call)
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

    await safe_edit_or_answer(call, 
        variant_card(product, variant, qty),
        reply_markup=qty_keyboard(variant_id, qty),
        parse_mode="HTML"
    )


@router.callback_query(F.data.startswith("restock:"))
async def restock(call: CallbackQuery, bot: Bot):
    variant_id = int(call.data.split(":")[1])

    conn = db()
    variant = conn.execute(
        """SELECT v.*, p.name AS product_name
           FROM product_variants v
           JOIN products p ON p.id=v.product_id
           WHERE v.id=?""",
        (variant_id,)
    ).fetchone()

    if not variant:
        conn.close()
        return await call.answer("Variasi tidak ditemukan.", show_alert=True)

    existing = conn.execute(
        """SELECT id FROM restock_subscriptions
           WHERE user_id=? AND product_id=? AND variant_id=?""",
        (call.from_user.id, variant["product_id"], variant_id)
    ).fetchone()

    if existing:
        conn.execute(
            """DELETE FROM restock_subscriptions
               WHERE user_id=? AND product_id=? AND variant_id=?""",
            (call.from_user.id, variant["product_id"], variant_id)
        )
        conn.commit()
        conn.close()

        await call.answer("🔕 Notifikasi restock dinonaktifkan.", show_alert=True)
        return

    conn.execute(
        """INSERT INTO restock_subscriptions
           (user_id, product_id, variant_id, created_at)
           VALUES(?,?,?,?)""",
        (
            call.from_user.id,
            variant["product_id"],
            variant_id,
            datetime.now().isoformat(timespec="seconds")
        )
    )
    conn.commit()
    conn.close()

    await call.answer("🔔 Notifikasi restock diaktifkan.", show_alert=True)

    # Owner gets PM when someone subscribes.
    if ADMIN_ID and call.from_user.id != ADMIN_ID:
        try:
            user = (
                f"@{call.from_user.username}"
                if call.from_user.username
                else f"ID {call.from_user.id}"
            )
            await bot.send_message(
                ADMIN_ID,
                "🔔 <b>RESTOCK SUBSCRIPTION ON</b>\n\n"
                f"👤 {html.escape(user)}\n"
                f"📦 {html.escape(variant['product_name'])}\n"
                f"🧩 {html.escape(variant['name'])}\n\n"
                "User akan menerima PM saat stok tersedia kembali.",
                parse_mode="HTML"
            )
        except Exception:
            pass

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

    await safe_edit_or_answer(call, 
        "🧾 <b>KONFIRMASI PESANAN</b>\n\n"
        f"📦 Produk: <b>{product['name']}</b>\n"
        f"🧩 Variasi: <b>{variant['name']}</b>\n"
        f"🔢 Jumlah: <b>{qty}</b>\n"
        f"💰 Harga/unit: <b>{rupiah(unit)}</b>\n"
        f"💵 Total: <b>{rupiah(total)}</b>\n\n"
        "Sebelum lanjut ke pembayaran, Anda bisa menambahkan catatan untuk pesanan ini.\n"
        "Contoh: instruksi khusus dari pembeli atau keterangan tambahan untuk order.",
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

    await safe_edit_or_answer(call, 
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

    await safe_edit_or_answer(call, 
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

    await safe_edit_or_answer(call, 
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
    if safe_mode_enabled() and not is_owner(call.from_user.id):
        return await call.answer(
            "Sistem sedang Safe Mode. Pembayaran sementara ditahan.",
            show_alert=True
        )
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

        record_payment_event(
            "order", order_id, "paid",
            total, call.from_user.id, "method=WALLET"
        )
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

        await safe_edit_or_answer(call, 
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
    await safe_edit_or_answer(call, 
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



@router.callback_query(F.data.startswith("processbank:"))
async def process_bank_order(call: CallbackQuery, bot: Bot, state: FSMContext):
    if safe_mode_enabled() and not is_owner(call.from_user.id):
        return await call.answer(
            "Sistem sedang Safe Mode. Pembayaran sementara ditahan.",
            show_alert=True
        )
    if maintenance_enabled() and not is_owner(call.from_user.id):
        return await call.answer(
            "Toko sedang maintenance. Silakan coba kembali nanti.",
            show_alert=True
        )

    if not bank_transfer_ready():
        return await call.answer(
            "Transfer rekening belum dikonfigurasi owner.",
            show_alert=True
        )

    async with purchase_lock(call.from_user.id):
        _, variant_id, qty = call.data.split(":")
        variant_id, qty = int(variant_id), max(1, int(qty))

        allowed, reason = anti_abuse_checkout(call.from_user.id, "BANK_TRANSFER")
        if not allowed:
            return await call.answer(reason, show_alert=True)

        checkout_data = await state.get_data()
        checkout_note = get_checkout_note_from_state(checkout_data)

        conn = db()
        conn.execute("BEGIN IMMEDIATE")

        duplicate = recent_duplicate_checkout(
            conn, call.from_user.id, variant_id, qty, "BANK_TRANSFER"
        )
        if duplicate:
            conn.rollback()
            conn.close()
            return await call.answer(
                "Pesanan transfer yang sama baru saja dibuat. Cek Pesanan Saya.",
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
            return await call.answer(
                "Stok tidak mencukupi / produk tidak aktif.",
                show_alert=True
            )

        unit = effective_unit_price(variant, qty)
        subtotal = unit * qty
        voucher_code, discount_amount = checkout_discount_from_state(
            checkout_data,
            call.from_user.id,
            product["id"],
            variant_id,
            subtotal
        )

        total = subtotal
        unique_code = unique_code_for_order(conn)
        payment_total = max(0, subtotal - discount_amount) + unique_code

        if not reserve_stock_for_order(conn, variant_id, qty):
            conn.rollback()
            conn.close()
            return await call.answer(
                "Stok baru saja berubah. Silakan coba lagi.",
                show_alert=True
            )

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
                "BANK_TRANSFER",
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

        conn = db()
        saved_order = conn.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
        conn.close()
        inv = invoice(order_id)
        expiry_text = order_expiry_text(saved_order)
        voucher_text = (
            f"🎟️ Voucher {html.escape(voucher_code)}: <b>-{rupiah(discount_amount)}</b>\n"
            if discount_amount else ""
        )
        note_text = (
            f"📝 Catatan: <blockquote>{html.escape(checkout_note)}</blockquote>\n"
            if checkout_note else "📝 Catatan: <i>Tidak ada</i>\n"
        )

        text = (
            "🏦 <b>TRANSAKSI PENDING • TRANSFER REKENING</b>\n\n"
            f"🧾 Invoice: <b>{inv}</b>\n"
            f"📦 Produk: {html.escape(product['name'])} — {html.escape(variant['name'])}\n"
            f"🔢 Jumlah: <b>{qty}</b>\n"
            f"💰 Subtotal: <b>{rupiah(subtotal)}</b>\n"
            f"{voucher_text}"
            f"🔢 Kode unik: <b>+{unique_code}</b>\n"
            f"💵 <b>TOTAL TRANSFER: {rupiah(payment_total)}</b>\n"
            f"{note_text}\n"
            + bank_transfer_text()
            + f"\n\n{expiry_text}"
              f"⏳ Stok direservasi selama <b>{ORDER_RESERVATION_MINUTES} menit</b>.\n"
              "⚠️ Transfer harus sesuai total hingga kode unik.\n"
              "Setelah pembayaran, kirim bukti pembayaran melalui tombol di bawah.\n\n"
            f"<i>{STORE_FOOTER}</i>"
        )

        kb = InlineKeyboardBuilder()
        if ADMIN_USERNAME:
            kb.button(text="💬 Hubungi Owner", url=f"https://t.me/{ADMIN_USERNAME}")
        kb.button(text="📤 Kirim Bukti Pembayaran", callback_data=f"proofsubmit:order:{order_id}")
        kb.button(text="🧾 Pesanan Saya", callback_data="my_orders")
        kb.button(text="🏠 Menu Utama", callback_data="home")
        kb.adjust(1)

        await safe_edit_or_answer(
            call,
            text,
            reply_markup=kb.as_markup(),
            parse_mode="HTML"
        )

        if ADMIN_ID:
            try:
                user = (
                    f"@{call.from_user.username}"
                    if call.from_user.username
                    else f"ID {call.from_user.id}"
                )
                owner_voucher_text = (
                    f"🎟️ Voucher: -{rupiah(discount_amount)}\n"
                    if discount_amount else ""
                )
                await bot.send_message(
                    ADMIN_ID,
                    "🏦 <b>ORDER BARU • TRANSFER REKENING</b>\n\n"
                    f"🧾 {inv}\n"
                    f"👤 {html.escape(user)}\n"
                    f"📦 {html.escape(product['name'])} — {html.escape(variant['name'])}\n"
                    f"🔢 Qty: {qty}\n"
                    f"💰 Subtotal: {rupiah(subtotal)}\n"
                    f"{owner_voucher_text}"
                    f"🔢 Kode unik: +{unique_code}\n"
                    f"💵 Transfer: {rupiah(payment_total)}\n"
                    f"⏳ Reservasi: {ORDER_RESERVATION_MINUTES} menit",
                    parse_mode="HTML"
                )
            except Exception:
                pass

        await state.clear()
        await call.answer("Pesanan transfer rekening dibuat.")


@router.callback_query(F.data.startswith("process:"))
async def process_order(call: CallbackQuery, bot: Bot, state: FSMContext):
    if safe_mode_enabled() and not is_owner(call.from_user.id):
        return await call.answer(
            "Sistem sedang Safe Mode. Pembayaran sementara ditahan.",
            show_alert=True
        )
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
        unique_code = unique_code_for_order(conn)
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
        kb.button(text="📤 Kirim Bukti Pembayaran", callback_data=f"proofsubmit:order:{order_id}")
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
            f"{expiry_text}"
            f"⏳ Stok direservasi selama <b>{ORDER_RESERVATION_MINUTES} menit</b>.\n"
            "⚠️ Transfer harus sesuai total hingga kode unik.\n"
            f"📝 {payment_note}\n\n"
            "Setelah pembayaran, kirim bukti pembayaran melalui tombol di bawah.\n\n"
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
            await safe_edit_or_answer(call, 
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
    if safe_mode_enabled() and not is_owner(call.from_user.id):
        return await call.answer(
            "Sistem sedang Safe Mode. Pembayaran sementara ditahan.",
            show_alert=True
        )
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

            return await safe_edit_or_answer(call, 
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
            await safe_edit_or_answer(call, 
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

    await safe_edit_or_answer(call, text, reply_markup=kb.as_markup(), parse_mode="HTML")
    await call.answer()


@router.callback_query(F.data == "resend:last")
async def resend_last_delivery(call: CallbackQuery, bot: Bot):
    if not recent_action_allowed(f"resend:{call.from_user.id}", 3):
        return await call.answer("Sedang diproses. Jangan tekan dua kali.", show_alert=True)
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

    await safe_edit_or_answer(call, "\n".join(lines), reply_markup=back_home(), parse_mode="HTML")
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

    await safe_edit_or_answer(call, 
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

    await safe_edit_or_answer(call, 
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

    await safe_edit_or_answer(call, 
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

    await safe_edit_or_answer(call, 
        "➕ <b>ISI SALDO</b>\n\n"
        f"Nominal dipilih: <b>{rupiah(amount)}</b>\n"
        f"Minimum: <b>{rupiah(get_min_topup())}</b>\n\n"
        "Pilih nominal dari menu di bawah atau gunakan Nominal Custom.",
        reply_markup=topup_amount_keyboard(amount),
        parse_mode="HTML"
    )
    await call.answer()


@router.callback_query(F.data == "topup:custom")
async def wallet_topup_custom(call: CallbackQuery, state: FSMContext):
    await state.set_state(OwnerState.topup_amount)

    await safe_edit_or_answer(call, 
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

    await safe_edit_or_answer(call, 
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
async def wallet_topup_pay(call: CallbackQuery):
    amount = int(call.data.split(":")[2])
    minimum = get_min_topup()
    if amount < minimum:
        return await call.answer(
            f"Minimum top up {rupiah(minimum)}.",
            show_alert=True
        )

    await safe_edit_or_answer(call, 
        "💳 <b>PILIH METODE ISI SALDO</b>\n\n"
        f"Nominal saldo: <b>{rupiah(amount)}</b>\n\n"
        "Pilih metode pembayaran:",
        reply_markup=topup_payment_method_keyboard(amount),
        parse_mode="HTML"
    )
    await call.answer()


@router.callback_query(F.data.startswith("topupmethod:qris:"))
async def wallet_topup_method_qris(call: CallbackQuery):
    if safe_mode_enabled() and not is_owner(call.from_user.id):
        return await call.answer(
            "Sistem sedang Safe Mode. Pembayaran sementara ditahan.",
            show_alert=True
        )
    amount = int(call.data.split(":")[2])
    minimum = get_min_topup()
    if amount < minimum:
        return await call.answer(
            f"Minimum top up {rupiah(minimum)}.",
            show_alert=True
        )

    conn = db()
    conn.execute("BEGIN IMMEDIATE")
    recent = conn.execute(
        """SELECT * FROM topups
           WHERE user_id=? AND amount=? AND payment_method='QRIS_MANUAL'
             AND status='pending'
           ORDER BY id DESC LIMIT 1""",
        (call.from_user.id, amount)
    ).fetchone()

    if recent:
        try:
            created = datetime.fromisoformat(recent["created_at"])
            now = datetime.now(created.tzinfo) if created.tzinfo else datetime.now()
            if (now - created).total_seconds() < 30:
                conn.rollback()
                conn.close()
                return await call.answer(
                    f"Top up {topup_invoice(recent['id'])} masih pending.",
                    show_alert=True
                )
        except Exception:
            pass

    unique_code = unique_code_for_order(conn)
    payment_total = amount + unique_code
    cur = conn.execute(
        """INSERT INTO topups
           (user_id, username, amount, unique_code, payment_total,
            payment_method, status, created_at, expires_at)
           VALUES(?,?,?,?,?,'QRIS_MANUAL','pending',?,?)""",
        (
            call.from_user.id,
            call.from_user.username or "",
            amount,
            unique_code,
            payment_total,
            datetime.now().isoformat(timespec="seconds"),
            topup_expiry_iso()
        )
    )
    topup_id = cur.lastrowid
    conn.commit()
    conn.close()

    conn = db()
    saved_topup = conn.execute("SELECT * FROM topups WHERE id=?", (topup_id,)).fetchone()
    conn.close()
    topup_expiry = topup_expiry_text(saved_topup)

    qris_file_id = get_setting("qris_file_id", "")
    payment_note = get_setting("payment_note", DEFAULT_PAYMENT_NOTE)
    unique_text = f"🔢 Kode unik: <b>+{unique_code}</b>\n" if unique_code > 0 else ""

    text = (
        "💰 <b>ISI SALDO • QRIS MANUAL</b>\n\n"
        f"🧾 Invoice: <b>{topup_invoice(topup_id)}</b>\n"
        f"💵 Saldo masuk: <b>{rupiah(amount)}</b>\n"
        f"{unique_text}"
        f"💳 Total transfer: <b>{rupiah(payment_total)}</b>\n"
        f"{topup_expiry}\n"
        f"📝 {html.escape(payment_note)}\n\n"
        "⏳ Invoice berlaku 30 menit. Setelah transfer, kirim bukti pembayaran ke bot."
    )

    if qris_file_id:
        try:
            await call.message.delete()
            await call.bot.send_photo(
                call.from_user.id,
                photo=qris_file_id,
                caption=text,
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="📤 Kirim Bukti Pembayaran", callback_data=f"proofsubmit:topup:{topup_id}")],
                    [InlineKeyboardButton(text="💬 Hubungi Owner", url=f"https://t.me/{ADMIN_USERNAME}")]
                ]) if ADMIN_USERNAME else payment_proof_keyboard("topup", topup_id),
                parse_mode="HTML"
            )
        except Exception:
            await call.bot.send_message(
                call.from_user.id,
                text + "\n\n⚠️ QRIS tidak dapat dimuat.",
                parse_mode="HTML"
            )
    else:
        await safe_edit_or_answer(call, 
            text + "\n\n⚠️ QRIS belum dipasang owner.",
            reply_markup=wallet_menu(),
            parse_mode="HTML"
        )

    if ADMIN_ID:
        try:
            user = (
                f"@{call.from_user.username}"
                if call.from_user.username
                else f"ID {call.from_user.id}"
            )
            await call.bot.send_message(
                ADMIN_ID,
                "💰 <b>TOP UP BARU • QRIS</b>\n\n"
                f"🧾 {topup_invoice(topup_id)}\n"
                f"👤 {html.escape(user)}\n"
                f"💰 Saldo: <b>{rupiah(amount)}</b>\n"
                f"🔢 Kode unik: <b>+{unique_code}</b>\n"
                f"💳 Transfer: <b>{rupiah(payment_total)}</b>",
                parse_mode="HTML"
            )
        except Exception:
            pass

    await call.answer("Invoice top up QRIS dibuat.")


@router.callback_query(F.data.startswith("topupmethod:bank:"))
async def wallet_topup_method_bank(call: CallbackQuery):
    if safe_mode_enabled() and not is_owner(call.from_user.id):
        return await call.answer(
            "Sistem sedang Safe Mode. Pembayaran sementara ditahan.",
            show_alert=True
        )
    amount = int(call.data.split(":")[2])
    minimum = get_min_topup()

    if amount < minimum:
        return await call.answer(
            f"Minimum top up {rupiah(minimum)}.",
            show_alert=True
        )

    if not bank_transfer_ready():
        return await call.answer(
            "Transfer rekening belum dikonfigurasi owner.",
            show_alert=True
        )

    conn = db()
    conn.execute("BEGIN IMMEDIATE")
    recent = conn.execute(
        """SELECT * FROM topups
           WHERE user_id=? AND amount=? AND payment_method='BANK_TRANSFER'
             AND status='pending'
           ORDER BY id DESC LIMIT 1""",
        (call.from_user.id, amount)
    ).fetchone()

    if recent:
        try:
            created = datetime.fromisoformat(recent["created_at"])
            now = datetime.now(created.tzinfo) if created.tzinfo else datetime.now()
            if (now - created).total_seconds() < 30:
                conn.rollback()
                conn.close()
                return await call.answer(
                    f"Top up {topup_invoice(recent['id'])} masih pending.",
                    show_alert=True
                )
        except Exception:
            pass

    unique_code = unique_code_for_order(conn)
    payment_total = amount + unique_code

    cur = conn.execute(
        """INSERT INTO topups
           (user_id, username, amount, unique_code, payment_total,
            payment_method, status, created_at, expires_at)
           VALUES(?,?,?,?,?,'BANK_TRANSFER','pending',?,?)""",
        (
            call.from_user.id,
            call.from_user.username or "",
            amount,
            unique_code,
            payment_total,
            datetime.now().isoformat(timespec="seconds"),
            topup_expiry_iso()
        )
    )
    topup_id = cur.lastrowid
    conn.commit()
    conn.close()

    conn = db()
    saved_topup = conn.execute("SELECT * FROM topups WHERE id=?", (topup_id,)).fetchone()
    conn.close()
    topup_expiry = topup_expiry_text(saved_topup)

    unique_text = f"🔢 Kode unik: <b>+{unique_code}</b>\n" if unique_code > 0 else ""

    await safe_edit_or_answer(call, 
        "💰 <b>ISI SALDO • TRANSFER REKENING</b>\n\n"
        f"🧾 Invoice: <b>{topup_invoice(topup_id)}</b>\n"
        f"💵 Saldo masuk: <b>{rupiah(amount)}</b>\n"
        f"{unique_text}"
        f"💳 Total transfer: <b>{rupiah(payment_total)}</b>\n"
        f"{topup_expiry}\n"
        + bank_transfer_text()
        + "\n\n⚠️ Transfer sesuai nominal hingga kode unik.\n"
          "⏳ Invoice berlaku 30 menit. Setelah transfer, kirim bukti pembayaran ke bot.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📤 Kirim Bukti Pembayaran", callback_data=f"proofsubmit:topup:{topup_id}")],
            [InlineKeyboardButton(text="💬 Hubungi Owner", url=f"https://t.me/{ADMIN_USERNAME}")]
        ]) if ADMIN_USERNAME else payment_proof_keyboard("topup", topup_id),
        parse_mode="HTML"
    )

    if ADMIN_ID:
        try:
            user = f"@{call.from_user.username}" if call.from_user.username else f"ID {call.from_user.id}"
            await call.bot.send_message(
                ADMIN_ID,
                "🏦 <b>TOP UP BARU • TRANSFER REKENING</b>\n\n"
                f"🧾 {topup_invoice(topup_id)}\n"
                f"👤 {html.escape(user)}\n"
                f"💰 Saldo: <b>{rupiah(amount)}</b>\n"
                f"💳 Transfer: <b>{rupiah(payment_total)}</b>",
                parse_mode="HTML"
            )
        except Exception:
            pass

    await call.answer("Invoice transfer rekening dibuat.")



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

    await safe_edit_or_answer(call, 
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
    await safe_edit_or_answer(call, 
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
    await safe_edit_or_answer(call, 
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
        "SELECT * FROM topups WHERE status IN ('pending','expired') ORDER BY id DESC LIMIT 20"
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

    await safe_edit_or_answer(call, 
        "✅ <b>VERIFIKASI TOP UP</b>\n\n"
        "Pilih invoice yang sudah benar-benar dibayar:",
        reply_markup=kb.as_markup(),
        parse_mode="HTML"
    )
    await call.answer()


@router.callback_query(F.data.startswith("topupverify:"))
async def owner_wallet_verify_button(call: CallbackQuery, bot: Bot):
    if not recent_action_allowed(f"topupverify:{call.from_user.id}:{call.data}", 3):
        return await call.answer("Sedang diproses. Jangan tekan dua kali.", show_alert=True)
    if not is_owner(call.from_user.id):
        return await call.answer("Akses ditolak.", show_alert=True)

    try:
        topup_id = int(call.data.split(":")[1])
    except Exception:
        return await call.answer("Top up tidak valid.", show_alert=True)

    result, status = verify_topup_atomic(topup_id, call.from_user.id)

    if status == "not_found":
        return await call.answer("Top up tidak ditemukan.", show_alert=True)
    if status == "already_completed":
        row, balance = result
        return await call.answer(
            f"Top up sudah pernah diverifikasi. Saldo {rupiah(balance)}.",
            show_alert=True
        )
    if status != "completed":
        return await call.answer(
            "Top up sedang/sudah diproses. Tidak ada saldo tambahan kedua.",
            show_alert=True
        )

    row, balance = result

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
    await safe_edit_or_answer(call, 
        "✅ Top up selesai diproses.",
        reply_markup=owner_wallet_menu()
    )



@router.callback_query(F.data == "owner:min_topup")
async def owner_min_topup(call: CallbackQuery, state: FSMContext):
    if not is_owner(call.from_user.id):
        return await call.answer("Akses ditolak.", show_alert=True)

    await state.set_state(OwnerState.owner_min_topup)
    await safe_edit_or_answer(call, 
        "⚙️ <b>MINIMUM TOP UP</b>\n\n"
        f"Minimum saat ini: <b>{rupiah(get_min_topup())}</b>\n\n"
        "Kirim nominal minimum baru.\n"
        "Contoh: <code>5000</code>",
        reply_markup=back_owner("owner:back_orders"),
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

    await safe_edit_or_answer(call, 
        "\n\n".join(lines),
        reply_markup=owner_wallet_menu(),
        parse_mode="HTML"
    )
    await call.answer()



@router.callback_query(F.data == "owner:bank_settings")
async def owner_bank_settings(call: CallbackQuery, state: FSMContext):
    if not is_owner(call.from_user.id):
        return await call.answer("Akses ditolak.", show_alert=True)
    await state.clear()
    status = "AKTIF" if bank_transfer_ready() else "BELUM LENGKAP"
    await safe_edit_or_answer(
        call,
        "🏦 <b>PENGATURAN REKENING TRANSFER</b>\n\n"
        f"Status: <b>{status}</b>\n\n"
        + bank_transfer_text(),
        reply_markup=bank_settings_menu(),
        parse_mode="HTML"
    )
    await call.answer()


@router.callback_query(F.data == "owner:bank_name")
async def owner_bank_name(call: CallbackQuery, state: FSMContext):
    if not is_owner(call.from_user.id):
        return await call.answer("Akses ditolak.", show_alert=True)
    await state.set_state(OwnerState.set_bank_name)
    await safe_edit_or_answer(call, 
        "🏦 Kirim nama bank.\nContoh: <code>BCA</code>",
        reply_markup=back_owner(),
        parse_mode="HTML"
    )
    await call.answer()


@router.message(OwnerState.set_bank_name)
async def owner_bank_name_input(message: Message, state: FSMContext):
    if not is_owner(message.from_user.id):
        return
    value = (message.text or "").strip()
    if not value:
        return await message.answer("❌ Nama bank tidak boleh kosong.")
    set_setting("bank_name", value[:60])
    await state.clear()
    await message.answer("✅ Nama bank disimpan.", reply_markup=bank_settings_menu())


@router.callback_query(F.data == "owner:bank_account")
async def owner_bank_account(call: CallbackQuery, state: FSMContext):
    if not is_owner(call.from_user.id):
        return await call.answer("Akses ditolak.", show_alert=True)
    await state.set_state(OwnerState.set_bank_account)
    await safe_edit_or_answer(call, 
        "💳 Kirim nomor rekening.\nContoh: <code>1234567890</code>",
        reply_markup=back_owner(),
        parse_mode="HTML"
    )
    await call.answer()


@router.message(OwnerState.set_bank_account)
async def owner_bank_account_input(message: Message, state: FSMContext):
    if not is_owner(message.from_user.id):
        return
    value = (message.text or "").strip().replace(" ", "")
    if not value or len(value) > 40:
        return await message.answer("❌ Nomor rekening tidak valid.")
    set_setting("bank_account", value)
    await state.clear()
    await message.answer("✅ Nomor rekening disimpan.", reply_markup=bank_settings_menu())


@router.callback_query(F.data == "owner:bank_holder")
async def owner_bank_holder(call: CallbackQuery, state: FSMContext):
    if not is_owner(call.from_user.id):
        return await call.answer("Akses ditolak.", show_alert=True)
    await state.set_state(OwnerState.set_bank_holder)
    await safe_edit_or_answer(call, 
        "👤 Kirim nama pemilik rekening.",
        reply_markup=back_owner()
    )
    await call.answer()


@router.message(OwnerState.set_bank_holder)
async def owner_bank_holder_input(message: Message, state: FSMContext):
    if not is_owner(message.from_user.id):
        return
    value = (message.text or "").strip()
    if not value:
        return await message.answer("❌ Nama pemilik rekening tidak boleh kosong.")
    set_setting("bank_holder", value[:100])
    await state.clear()
    await message.answer("✅ Atas nama rekening disimpan.", reply_markup=bank_settings_menu())


@router.callback_query(F.data == "owner:bank_preview")
async def owner_bank_preview(call: CallbackQuery):
    if not is_owner(call.from_user.id):
        return await call.answer("Akses ditolak.", show_alert=True)
    await safe_edit_or_answer(
        call,
        "🏦 <b>PREVIEW TRANSFER REKENING</b>\n\n"
        + bank_transfer_text()
        + f"\n\nStatus: <b>{'AKTIF' if bank_transfer_ready() else 'BELUM LENGKAP'}</b>",
        reply_markup=bank_settings_menu(),
        parse_mode="HTML"
    )
    await call.answer()


@router.callback_query(F.data == "owner:unique_info")
async def owner_unique_info(call: CallbackQuery):
    if not is_owner(call.from_user.id):
        return await call.answer("Akses ditolak.", show_alert=True)

    conn = db()
    max_order = conn.execute(
        "SELECT COALESCE(MAX(unique_code),0) AS n FROM orders"
    ).fetchone()["n"]
    max_topup = conn.execute(
        "SELECT COALESCE(MAX(unique_code),0) AS n FROM topups"
    ).fetchone()["n"]
    conn.close()

    last_code = max(int(max_order or 0), int(max_topup or 0))
    await call.answer(
        f"Kode unik wajib aktif. Kode terakhir: +{last_code}. "
        "Transaksi berikutnya otomatis memakai kode baru.",
        show_alert=True
    )


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

    await safe_edit_or_answer(call, 
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

    await safe_edit_or_answer(call, 
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

    await safe_edit_or_answer(call, 
        "\n".join(lines),
        reply_markup=back_owner(),
        parse_mode="HTML"
    )
    await call.answer()


@router.callback_query(F.data == "owner:qris_set")
async def owner_qris_set(call: CallbackQuery, state: FSMContext):
    if not is_owner(call.from_user.id):
        return await deny_owner_callback(call)

    await state.clear()
    set_setting("qris_upload_pending", "1")
    await state.set_state(OwnerState.set_qris)

    await safe_edit_or_answer(
        call,
        "🖼️ <b>GANTI QRIS</b>\n\n"
        "Kirim gambar QRIS ke chat ini.\n"
        "Boleh sebagai <b>foto biasa</b> atau <b>file gambar JPG/PNG</b>.\n\n"
        "Setelah tersimpan, bot akan menampilkan konfirmasi dan QRIS langsung aktif.",
        reply_markup=back_owner("owner:back_orders"),
        parse_mode="HTML"
    )
    await call.answer()

@router.message(OwnerState.set_qris, F.photo)
async def owner_qris_upload_photo(message: Message, state: FSMContext):
    if not is_owner(message.from_user.id):
        return

    if not message.photo:
        return await message.answer("❌ Foto QRIS tidak terbaca.")

    await save_owner_qris_photo(
        message,
        state,
        message.photo[-1].file_id
    )


@router.message(OwnerState.set_qris, F.document)
async def owner_qris_upload_document(message: Message, state: FSMContext, bot: Bot):
    if not is_owner(message.from_user.id):
        return

    document = message.document
    mime = (document.mime_type or "").lower() if document else ""

    if not document or not mime.startswith("image/"):
        return await message.answer(
            "❌ File harus berupa gambar QRIS.\n"
            "Kirim sebagai foto atau file gambar JPG/PNG."
        )

    temp_path = None
    try:
        suffix = ".png" if "png" in mime else ".jpg"
        fd, temp_path = tempfile.mkstemp(prefix="qris_upload_", suffix=suffix)
        os.close(fd)

        await bot.download(document, destination=temp_path)

        normalized = await bot.send_photo(
            message.from_user.id,
            FSInputFile(temp_path),
            caption="🔄 Memproses gambar QRIS..."
        )

        if not normalized.photo:
            raise RuntimeError("Telegram tidak menghasilkan photo file_id.")

        await save_owner_qris_photo(
            message,
            state,
            normalized.photo[-1].file_id
        )

    except Exception as exc:
        logging.exception("QRIS document normalization failed: %s", exc)
        await message.answer(
            "❌ Gagal memproses file QRIS.\n"
            "Coba kirim ulang sebagai <b>foto biasa</b>.",
            parse_mode="HTML"
        )
    finally:
        if temp_path:
            try:
                os.remove(temp_path)
            except Exception:
                pass


@router.message(OwnerState.set_qris)
async def owner_qris_upload_invalid(message: Message):
    if not is_owner(message.from_user.id):
        return

    await message.answer(
        "❌ <b>FORMAT QRIS TIDAK VALID</b>\n\n"
        "Kirim QRIS sebagai <b>foto</b> atau <b>file gambar JPG/PNG</b>.",
        parse_mode="HTML"
    )

@router.message(F.photo)
async def payment_proof_photo_recovery(message: Message, state: FSMContext, bot: Bot):
    if is_owner(message.from_user.id):
        return

    session = get_payment_proof_session(message.from_user.id)
    if not session:
        return

    entity = session["entity_type"]
    entity_id = int(session["entity_id"])

    ok, error = await process_payment_proof_message(
        message,
        state,
        bot,
        entity,
        entity_id
    )

    if not ok:
        return await message.answer(
            "❌ <b>BUKTI BELUM TERKIRIM KE OWNER</b>\n\n"
            f"{html.escape(error)}\n\n"
            "Silakan kirim ulang bukti pembayaran.",
            parse_mode="HTML"
        )

    await message.answer(
        "✅ <b>BUKTI PEMBAYARAN TERKIRIM</b>\n\n"
        "Bukti sudah diteruskan ke PM owner.",
        reply_markup=main_menu(),
        parse_mode="HTML"
    )


@router.message(F.document)
async def payment_proof_document_recovery(message: Message, state: FSMContext, bot: Bot):
    if is_owner(message.from_user.id):
        return

    session = get_payment_proof_session(message.from_user.id)
    if not session:
        return

    document = message.document
    mime = (document.mime_type or "").lower() if document else ""
    if not document or not mime.startswith("image/"):
        return await message.answer(
            "❌ Bukti harus berupa foto/screenshot atau file gambar."
        )

    entity = session["entity_type"]
    entity_id = int(session["entity_id"])

    ok, error = await process_payment_proof_message(
        message,
        state,
        bot,
        entity,
        entity_id
    )

    if not ok:
        return await message.answer(
            "❌ <b>BUKTI BELUM TERKIRIM KE OWNER</b>\n\n"
            f"{html.escape(error)}\n\n"
            "Silakan kirim ulang bukti pembayaran.",
            parse_mode="HTML"
        )

    await message.answer(
        "✅ <b>BUKTI PEMBAYARAN TERKIRIM</b>\n\n"
        "Bukti sudah diteruskan ke PM owner.",
        reply_markup=main_menu(),
        parse_mode="HTML"
    )


@router.message(F.photo)
async def owner_qris_photo_recovery(message: Message, state: FSMContext):
    if not is_owner(message.from_user.id):
        return

    if get_setting("qris_upload_pending", "0") != "1":
        return

    if not message.photo:
        return

    await save_owner_qris_photo(
        message,
        state,
        message.photo[-1].file_id
    )


@router.message(F.document)
async def owner_qris_document_recovery(message: Message, state: FSMContext, bot: Bot):
    if not is_owner(message.from_user.id):
        return

    if get_setting("qris_upload_pending", "0") != "1":
        return

    document = message.document
    mime = (document.mime_type or "").lower() if document else ""
    if not document or not mime.startswith("image/"):
        return

    temp_path = None
    try:
        suffix = ".png" if "png" in mime else ".jpg"
        fd, temp_path = tempfile.mkstemp(prefix="qris_recovery_", suffix=suffix)
        os.close(fd)

        await bot.download(document, destination=temp_path)

        normalized = await bot.send_photo(
            message.from_user.id,
            FSInputFile(temp_path),
            caption="🔄 Memproses gambar QRIS..."
        )

        if not normalized.photo:
            raise RuntimeError("Telegram tidak menghasilkan photo file_id.")

        await save_owner_qris_photo(
            message,
            state,
            normalized.photo[-1].file_id
        )

    except Exception as exc:
        logging.exception("QRIS recovery normalization failed: %s", exc)
        await message.answer(
            "❌ Gagal memproses QRIS. Coba kirim sebagai foto biasa."
        )
    finally:
        if temp_path:
            try:
                os.remove(temp_path)
            except Exception:
                pass



@router.callback_query(F.data == "owner:qris_note")
async def owner_qris_note(call: CallbackQuery, state: FSMContext):
    if not is_owner(call.from_user.id):
        return await call.answer("Akses ditolak.", show_alert=True)

    await state.set_state(OwnerState.set_payment_note)
    await safe_edit_or_answer(call, 
        "📝 <b>EDIT CATATAN PEMBAYARAN</b>\n\n"
        "Kirim catatan yang ingin tampil di bawah QRIS.\n\n"
        "Contoh:\n"
        "<code>QRIS Maboyy Digital • Transfer sesuai nominal</code>",
        reply_markup=back_owner("owner:back_orders"),
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





@router.callback_query(F.data == "owner:qris_preview")
async def owner_qris_preview(call: CallbackQuery, bot: Bot):
    if not is_owner(call.from_user.id):
        return await deny_owner_callback(call)

    qris_file_id = get_setting("qris_file_id", "")
    if not qris_file_id:
        return await call.answer("QRIS belum dipasang.", show_alert=True)

    try:
        await bot.send_photo(
            call.from_user.id,
            qris_file_id,
            caption=(
                "👁️ <b>PREVIEW QRIS</b>\n\n"
                f"📝 {html.escape(get_setting('payment_note', DEFAULT_PAYMENT_NOTE))}\n"
                "🔢 Kode unik: <b>WAJIB</b>"
            ),
            parse_mode="HTML"
        )
        await call.answer("Preview dikirim.")
    except Exception as exc:
        logging.exception("QRIS preview failed: %s", exc)
        set_setting("qris_file_id", "")
        set_setting("qris_upload_pending", "1")
        await call.answer(
            "QRIS lama tidak valid. Kirim ulang gambar QRIS sekarang.",
            show_alert=True
        )

@router.callback_query(F.data == "owner:health")
async def owner_health(call: CallbackQuery, bot: Bot):
    if not is_owner(call.from_user.id):
        return await call.answer("Akses ditolak.", show_alert=True)
    await call.answer("Menu ini sudah digabung ke Diagnostik Sistem.")
    await render_owner_diagnostics(call, bot)


@router.callback_query(F.data == "owner:recover_orders")
async def owner_recover_orders(call: CallbackQuery, bot: Bot):
    if not is_owner(call.from_user.id):
        return await call.answer("Akses ditolak.", show_alert=True)

    await call.answer("Memeriksa order...", show_alert=False)
    recovered, pending = await recover_stuck_orders(bot)

    await safe_edit_or_answer(call, 
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

    await safe_edit_or_answer(call, 
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

    await safe_edit_or_answer(call, 
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

    await safe_edit_or_answer(call, 
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
    if not recent_action_allowed(f"cancel:{call.from_user.id}:{call.data}", 3):
        return await call.answer("Sedang diproses. Jangan tekan dua kali.", show_alert=True)
    if not is_owner(call.from_user.id):
        return await call.answer("Akses ditolak.", show_alert=True)

    order_id = int(call.data.split(":")[2])
    ok, message = await cancel_pending_order(order_id, bot)

    if ok:
        await safe_edit_or_answer(call, 
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
        return await deny_owner_callback(call)

    try:
        backup_path = create_database_backup()
        if not backup_path.exists():
            raise RuntimeError("File backup tidak berhasil dibuat.")

        if not ADMIN_ID:
            raise RuntimeError("ADMIN_ID belum dikonfigurasi.")

        await bot.send_document(
            ADMIN_ID,
            document=FSInputFile(str(backup_path)),
            caption=(
                "🗄️ <b>BACKUP MANUAL MABOYY DIGITAL</b>\n\n"
                f"📦 Versi bot: <b>v{BOT_VERSION}</b>\n"
                f"🕒 {datetime.now().strftime('%d-%m-%Y %H:%M:%S')}"
            ),
            parse_mode="HTML"
        )

        await safe_edit_or_answer(
            call,
            "✅ <b>BACKUP BERHASIL</b>\n\n"
            "Database berhasil dibuat dan dikirim ke PM owner.",
            reply_markup=owner_system_menu(),
            parse_mode="HTML"
        )
        await safe_callback_notice(call)
    except Exception as exc:
        await owner_system_error_view(call, "Backup Sekarang", exc)



@router.callback_query(F.data == "owner:sync_stock")
async def owner_sync_stock(call: CallbackQuery, bot: Bot):
    if not is_owner(call.from_user.id):
        return await deny_owner_callback(call)

    try:
        if not STOCK_CHANNEL_ID:
            raise RuntimeError("STOCK_CHANNEL_ID belum diisi di Railway.")

        target = channel_target(STOCK_CHANNEL_ID)
        if not target:
            raise RuntimeError("STOCK_CHANNEL_ID tidak valid.")

        text = build_stock_text()
        message_id_raw = get_setting("stock_channel_message_id", "")
        message_id = int(message_id_raw) if message_id_raw.isdigit() else None

        synced = False
        if message_id:
            try:
                await bot.edit_message_text(
                    chat_id=target,
                    message_id=message_id,
                    text=text,
                    parse_mode="HTML"
                )
                synced = True
            except Exception:
                synced = False

        if not synced:
            msg = await bot.send_message(target, text, parse_mode="HTML")
            set_setting("stock_channel_message_id", msg.message_id)

        await safe_edit_or_answer(
            call,
            "✅ <b>STOK CHANNEL TERSINKRON</b>",
            reply_markup=owner_system_menu(),
            parse_mode="HTML"
        )
        await safe_callback_notice(call)
    except Exception as exc:
        await owner_system_error_view(call, "Sinkron Stok Channel", exc)



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

    await safe_edit_or_answer(call, 
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

    await safe_edit_or_answer(call, text, reply_markup=back_owner(), parse_mode="HTML")
    await call.answer()


async def prompt_state(call, state, target_state, text):
    if not is_owner(call.from_user.id):
        return await call.answer("Akses ditolak.", show_alert=True)
    await state.set_state(target_state)
    await safe_edit_or_answer(call, text, reply_markup=back_owner(), parse_mode="HTML")
    await call.answer()


@router.callback_query(F.data == "owner:add_product")
async def owner_add_product(call: CallbackQuery, state: FSMContext):
    if not is_owner(call.from_user.id):
        return await deny_owner_callback(call)

    try:
        await state.clear()
        await state.set_state(OwnerState.add_product_name)

        await safe_edit_or_answer(
            call,
            "➕ <b>TAMBAH PRODUK</b>\n\n"
            "Langkah 1/4\n"
            "Kirim <b>nama produk</b>.\n\n"
            "Contoh: <code>Alight Motion</code>",
            reply_markup=back_owner("owner:back_products"),
            parse_mode="HTML"
        )
        await safe_callback_notice(call)
    except Exception as exc:
        await owner_product_error_view(call, "Tambah Produk", exc)



@router.message(OwnerState.add_product_name)
async def owner_add_product_name_input(message: Message, state: FSMContext):
    if not is_owner(message.from_user.id):
        return

    name=(message.text or "").strip()
    if not name:
        return await message.answer("❌ Nama produk tidak boleh kosong.")

    await state.update_data(product_name=name[:120])
    await state.set_state(OwnerState.add_product_description)

    await message.answer(
        "📝 <b>Langkah 2/4</b>\n\n"
        "Kirim <b>deskripsi produk</b>.\n"
        "Ketik <code>-</code> jika tidak ingin memakai deskripsi.",
        reply_markup=back_owner("owner:back_products"),
        parse_mode="HTML"
    )


@router.message(OwnerState.add_product_description)
async def owner_add_product_description_input(message: Message, state: FSMContext):
    if not is_owner(message.from_user.id):
        return

    description=(message.text or "").strip()
    if description == "-":
        description=""

    await state.update_data(product_description=description[:1000])
    await state.set_state(OwnerState.add_product_variant_name)

    await message.answer(
        "🧩 <b>Langkah 3/4</b>\n\n"
        "Kirim <b>nama variasi pertama</b>.\n\n"
        "Contoh: <code>1 Bulan</code>",
        reply_markup=back_owner("owner:back_products"),
        parse_mode="HTML"
    )


@router.message(OwnerState.add_product_variant_name)
async def owner_add_product_variant_name_input(message: Message, state: FSMContext):
    if not is_owner(message.from_user.id):
        return

    variant_name=(message.text or "").strip()
    if not variant_name:
        return await message.answer("❌ Nama variasi tidak boleh kosong.")

    await state.update_data(product_variant_name=variant_name[:120])
    await state.set_state(OwnerState.add_product_variant_price)

    kb=InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="5.000", callback_data="newprodprice:5000"),
            InlineKeyboardButton(text="10.000", callback_data="newprodprice:10000"),
        ],
        [
            InlineKeyboardButton(text="20.000", callback_data="newprodprice:20000"),
            InlineKeyboardButton(text="50.000", callback_data="newprodprice:50000"),
        ],
        [InlineKeyboardButton(text="✍️ Harga Lain", callback_data="newprodprice:custom")],
        [InlineKeyboardButton(text="⬅️ Kembali", callback_data="owner:back_products")]
    ])

    await message.answer(
        "💰 <b>Langkah 4/4</b>\n\n"
        "Pilih harga variasi pertama:",
        reply_markup=kb,
        parse_mode="HTML"
    )


async def create_product_from_wizard(state: FSMContext, owner_id: int, price: int):
    data=await state.get_data()
    name=(data.get("product_name") or "").strip()
    description=(data.get("product_description") or "").strip()
    variant_name=(data.get("product_variant_name") or "").strip()

    if not name or not variant_name or price <= 0:
        return None

    conn=db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        now=datetime.now().isoformat(timespec="seconds")

        product_columns={
            row["name"]
            for row in conn.execute("PRAGMA table_info(products)").fetchall()
        }

        if "created_at" in product_columns:
            cur=conn.execute(
                """INSERT INTO products(name,description,active,created_at)
                   VALUES(?,?,1,?)""",
                (name,description,now)
            )
        else:
            cur=conn.execute(
                """INSERT INTO products(name,description,active)
                   VALUES(?,?,1)""",
                (name,description)
            )

        product_id=cur.lastrowid
        code=f"P{product_id}"

        vcur=conn.execute(
            """INSERT INTO product_variants
               (product_id,name,code,price,stock,wholesale10,wholesale20,active,reserved_stock,button_label)
               VALUES(?,?,?,?,0,0,0,1,0,'')""",
            (product_id,variant_name,code,price)
        )
        variant_id=vcur.lastrowid

        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    await state.clear()
    return product_id,variant_id,name,variant_name,price



@router.callback_query(F.data.startswith("newprodprice:"))
async def owner_new_product_price_button(call: CallbackQuery, state: FSMContext):
    if not is_owner(call.from_user.id):
        return await deny_owner_callback(call)

    value=call.data.split(":")[1]

    if value=="custom":
        data=await state.get_data()
        set_owner_input_session(
            call.from_user.id,
            "product_custom_price",
            {
                "product_name": data.get("product_name",""),
                "product_description": data.get("product_description",""),
                "product_variant_name": data.get("product_variant_name",""),
            }
        )
        await state.set_state(OwnerState.add_product_variant_price)
        await safe_edit_or_answer(
            call,
            "💰 <b>HARGA CUSTOM</b>\n\n"
            "Kirim nominal harga. Format berikut diterima:\n"
            "<code>15000</code>\n"
            "<code>15.000</code>\n"
            "<code>Rp15.000</code>",
            reply_markup=back_owner("owner:back_products"),
            parse_mode="HTML"
        )
        await safe_callback_notice(call)
        return

    try:
        price=int(value)
        result=await create_product_from_wizard(
            state,
            call.from_user.id,
            price
        )
    except Exception as exc:
        logging.exception("Create product preset price failed: %s", exc)
        try:
            log_system_error(
                "PRODUCT_WIZARD",
                str(exc),
                reference=f"owner:{call.from_user.id}",
                severity="error",
                recovered=False
            )
        except Exception:
            pass

        await safe_edit_or_answer(
            call,
            "❌ <b>GAGAL MEMBUAT PRODUK</b>\n\n"
            f"Error: <code>{html.escape(str(exc)[:400])}</code>\n\n"
            "Data produk belum disimpan. Silakan coba lagi.",
            reply_markup=owner_products_menu(),
            parse_mode="HTML"
        )
        await safe_callback_notice(call)
        return

    if not result:
        await safe_edit_or_answer(
            call,
            "❌ <b>DATA PRODUK TIDAK LENGKAP</b>\n\n"
            "Ulangi Tambah Produk dari awal.",
            reply_markup=owner_products_menu(),
            parse_mode="HTML"
        )
        await safe_callback_notice(call)
        return

    product_id,variant_id,name,variant_name,price=result

    await safe_edit_or_answer(
        call,
        "✅ <b>PRODUK BERHASIL DIBUAT</b>\n\n"
        f"📦 {html.escape(name)}\n"
        f"🧩 {html.escape(variant_name)}\n"
        f"💰 {rupiah(price)}\n"
        "📊 Stok awal: <b>0</b>\n\n"
        "Selanjutnya tambahkan akun dari menu Atur Stok.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="➕ Tambah Variasi Lagi",
                callback_data=f"addvariantprod:{product_id}"
            )],
            [InlineKeyboardButton(
                text="📦 Atur Stok",
                callback_data="owner:set_stock"
            )],
            [InlineKeyboardButton(
                text="⬅️ Produk & Stok",
                callback_data="owner:back_products"
            )]
        ]),
        parse_mode="HTML"
    )
    await safe_callback_notice(call)



@router.message(OwnerState.add_product_variant_price)
async def owner_new_product_price_custom(message: Message, state: FSMContext):
    if not is_owner(message.from_user.id):
        return

    raw_text=(message.text or "").strip()

    if not raw_text:
        return await message.answer(
            "❌ <b>NOMINAL KOSONG</b>\n\n"
            "Kirim nominal harga, contoh <code>2500</code> atau <code>2.500</code>.",
            parse_mode="HTML"
        )

    price=parse_rupiah_input(raw_text)

    if not price:
        return await message.answer(
            "❌ <b>HARGA TIDAK VALID</b>\n\n"
            "Format yang diterima:\n"
            "<code>2500</code>\n"
            "<code>2.500</code>\n"
            "<code>2,500</code>\n"
            "<code>Rp2.500</code>",
            parse_mode="HTML"
        )

    if price > 100_000_000:
        return await message.answer(
            "❌ Harga terlalu besar. Maksimal Rp100.000.000."
        )

    try:
        result=await create_product_from_wizard(
            state,
            message.from_user.id,
            price
        )
    except Exception as exc:
        logging.exception("Create product custom price failed: %s", exc)
        try:
            log_system_error(
                "PRODUCT_WIZARD",
                str(exc),
                reference=f"owner:{message.from_user.id}",
                severity="error",
                recovered=False
            )
        except Exception:
            pass

        clear_owner_input_session(message.from_user.id)
        await state.clear()
        return await message.answer(
            "❌ <b>GAGAL MEMBUAT PRODUK</b>\n\n"
            f"Error: <code>{html.escape(str(exc)[:400])}</code>\n\n"
            "Silakan ulangi Tambah Produk.",
            reply_markup=owner_products_menu(),
            parse_mode="HTML"
        )

    if not result:
        await state.clear()
        return await message.answer(
            "❌ Data produk tidak lengkap. Silakan ulangi Tambah Produk.",
            reply_markup=owner_products_menu()
        )

    product_id,_,name,variant_name,price=result
    clear_owner_input_session(message.from_user.id)

    await message.answer(
        "✅ <b>PRODUK BERHASIL DIBUAT</b>\n\n"
        f"📦 {html.escape(name)}\n"
        f"🧩 {html.escape(variant_name)}\n"
        f"💰 {rupiah(price)}\n"
        "📊 Stok awal: <b>0</b>\n\n"
        "Tambahkan akun dari menu Atur Stok.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="➕ Tambah Variasi Lagi",
                callback_data=f"addvariantprod:{product_id}"
            )],
            [InlineKeyboardButton(
                text="📦 Atur Stok",
                callback_data="owner:set_stock"
            )],
            [InlineKeyboardButton(
                text="⬅️ Produk & Stok",
                callback_data="owner:back_products"
            )]
        ]),
        parse_mode="HTML"
    )



@router.callback_query(F.data == "owner:add_variant")
async def owner_add_variant(call: CallbackQuery, state: FSMContext):
    if not is_owner(call.from_user.id):
        return await deny_owner_callback(call)

    await state.clear()
    await safe_edit_or_answer(
        call,
        "ℹ️ <b>TAMBAH VARIASI SUDAH DIGABUNG</b>\n\n"
        "Sekarang variasi ditambahkan langsung setelah membuat produk.\n"
        "Gunakan menu <b>➕ Tambah Produk</b>.",
        reply_markup=owner_products_menu(),
        parse_mode="HTML"
    )
    await safe_callback_notice(call)



@router.callback_query(F.data.startswith("addvariantprod:"))
async def owner_add_variant_product(call: CallbackQuery, state: FSMContext):
    if not is_owner(call.from_user.id):
        return await deny_owner_callback(call)

    try:
        product_id=int(call.data.split(":")[1])
    except Exception:
        return await call.answer("Produk tidak valid.", show_alert=True)

    conn=db()
    product=conn.execute(
        "SELECT id,name FROM products WHERE id=? AND active=1",
        (product_id,)
    ).fetchone()
    conn.close()

    if not product:
        return await call.answer("Produk tidak ditemukan.", show_alert=True)

    await state.update_data(add_variant_product_id=product_id)
    await state.set_state(OwnerState.add_variant_name)

    await safe_edit_or_answer(
        call,
        "🧩 <b>TAMBAH VARIASI</b>\n\n"
        f"Produk: <b>{html.escape(product['name'])}</b>\n\n"
        "Langkah 2/3\n"
        "Kirim <b>nama variasi</b>.\n\n"
        "Contoh: <code>1 Bulan</code>",
        reply_markup=back_owner("owner:back_products"),
        parse_mode="HTML"
    )
    await safe_callback_notice(call)


@router.message(OwnerState.add_variant_name)
async def owner_add_variant_name_input(message: Message, state: FSMContext):
    if not is_owner(message.from_user.id):
        return

    name=(message.text or "").strip()
    if not name:
        return await message.answer("❌ Nama variasi tidak boleh kosong.")

    await state.update_data(add_variant_name=name[:120])
    await state.set_state(OwnerState.add_variant_price)

    kb=InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="5.000", callback_data="addvariantprice:5000"),
            InlineKeyboardButton(text="10.000", callback_data="addvariantprice:10000"),
        ],
        [
            InlineKeyboardButton(text="20.000", callback_data="addvariantprice:20000"),
            InlineKeyboardButton(text="50.000", callback_data="addvariantprice:50000"),
        ],
        [
            InlineKeyboardButton(text="100.000", callback_data="addvariantprice:100000"),
            InlineKeyboardButton(text="200.000", callback_data="addvariantprice:200000"),
        ],
        [
            InlineKeyboardButton(text="✏️ Harga Custom", callback_data="addvariantprice:custom")
        ],
        [
            InlineKeyboardButton(text="⬅️ Kembali", callback_data="owner:back_products")
        ]
    ])

    await message.answer(
        "💰 <b>TAMBAH VARIASI</b>\n\n"
        f"Nama variasi: <b>{html.escape(name)}</b>\n\n"
        "Langkah 3/3\n"
        "Pilih harga:",
        reply_markup=kb,
        parse_mode="HTML"
    )


async def create_variant_from_wizard(state: FSMContext, price: int):
    data=await state.get_data()
    product_id=int(data.get("add_variant_product_id") or 0)
    name=(data.get("add_variant_name") or "").strip()

    if not product_id or not name or price <= 0:
        return None

    conn=db()
    conn.execute("BEGIN IMMEDIATE")

    product=conn.execute(
        "SELECT id,name FROM products WHERE id=? AND active=1",
        (product_id,)
    ).fetchone()
    if not product:
        conn.rollback()
        conn.close()
        return None

    existing=conn.execute(
        """SELECT id FROM product_variants
           WHERE product_id=? AND LOWER(name)=LOWER(?)""",
        (product_id,name)
    ).fetchone()
    if existing:
        conn.rollback()
        conn.close()
        return "duplicate"

    code_base=re.sub(r"[^A-Za-z0-9]+","",name.upper())[:8] or "VAR"
    existing_count=conn.execute(
        "SELECT COUNT(*) AS n FROM product_variants WHERE product_id=?",
        (product_id,)
    ).fetchone()["n"]
    code=f"{code_base}{int(existing_count)+1}"

    cur=conn.execute(
        """INSERT INTO product_variants
           (product_id,name,code,price,stock,wholesale10,wholesale20,active,reserved_stock,button_label)
           VALUES(?,?,?,?,0,0,0,1,0,'')""",
        (product_id,name,code,price)
    )
    variant_id=cur.lastrowid
    conn.commit()
    conn.close()

    await state.clear()
    return {
        "product_id":product_id,
        "product_name":product["name"],
        "variant_id":variant_id,
        "variant_name":name,
        "price":price,
        "code":code,
    }


@router.callback_query(F.data.startswith("addvariantprice:"))
async def owner_add_variant_price_button(call: CallbackQuery, state: FSMContext):
    if not is_owner(call.from_user.id):
        return await deny_owner_callback(call)

    value=call.data.split(":")[1]

    if value=="custom":
        data=await state.get_data()
        set_owner_input_session(
            call.from_user.id,
            "variant_custom_price",
            {
                "add_variant_product_id": int(data.get("add_variant_product_id") or 0),
                "add_variant_name": data.get("add_variant_name",""),
            }
        )
        await state.set_state(OwnerState.add_variant_price)
        await safe_edit_or_answer(
            call,
            "💰 <b>HARGA CUSTOM</b>\n\n"
            "Kirim nominal harga. Format berikut diterima:\n"
            "<code>15000</code>\n"
            "<code>15.000</code>\n"
            "<code>15,000</code>\n"
            "<code>Rp15.000</code>",
            reply_markup=back_owner("owner:back_products"),
            parse_mode="HTML"
        )
        return await safe_callback_notice(call)

    result=await create_variant_from_wizard(state,int(value))

    if result=="duplicate":
        return await call.answer(
            "Variasi dengan nama yang sama sudah ada.",
            show_alert=True
        )
    if not result:
        return await call.answer(
            "Data variasi tidak lengkap.",
            show_alert=True
        )

    await safe_edit_or_answer(
        call,
        "✅ <b>VARIASI BERHASIL DITAMBAHKAN</b>\n\n"
        f"📦 Produk: <b>{html.escape(result['product_name'])}</b>\n"
        f"🧩 Variasi: <b>{html.escape(result['variant_name'])}</b>\n"
        f"💰 Harga: <b>{rupiah(result['price'])}</b>\n"
        f"🏷️ Kode: <code>{html.escape(result['code'])}</code>\n"
        "📊 Stok awal: <b>0</b>\n\n"
        "Tambahkan akun dari menu Atur Stok.",
        reply_markup=owner_products_menu(),
        parse_mode="HTML"
    )
    await safe_callback_notice(call)


@router.message(OwnerState.add_variant_price)
async def owner_add_variant_price_custom(message: Message, state: FSMContext):
    if not is_owner(message.from_user.id):
        return

    price=parse_rupiah_input(message.text or "")
    if not price:
        return await message.answer(
            "❌ <b>HARGA TIDAK VALID</b>\n\n"
            "Format yang diterima:\n"
            "<code>15000</code>\n"
            "<code>15.000</code>\n"
            "<code>15,000</code>\n"
            "<code>Rp15.000</code>",
            reply_markup=back_owner("owner:back_products"),
            parse_mode="HTML"
        )

    if price > 100_000_000:
        return await message.answer(
            "❌ Harga terlalu besar. Maksimal Rp100.000.000.",
            reply_markup=back_owner("owner:back_products")
        )

    try:
        result=await create_variant_from_wizard(state,price)
    except Exception as exc:
        logging.exception("Create variant custom price failed: %s", exc)
        return await message.answer(
            "❌ <b>GAGAL MENAMBAHKAN VARIASI</b>\n\n"
            f"<code>{html.escape(str(exc)[:300])}</code>",
            reply_markup=owner_products_menu(),
            parse_mode="HTML"
        )

    if result=="duplicate":
        await state.clear()
        return await message.answer(
            "❌ Variasi dengan nama yang sama sudah ada.",
            reply_markup=owner_products_menu()
        )

    if not result:
        await state.clear()
        return await message.answer(
            "❌ Data variasi tidak lengkap atau produk tidak aktif.",
            reply_markup=owner_products_menu()
        )

    clear_owner_input_session(message.from_user.id)
    await state.clear()

    await message.answer(
        "✅ <b>VARIASI BERHASIL DITAMBAHKAN</b>\n\n"
        f"📦 Produk: <b>{html.escape(result['product_name'])}</b>\n"
        f"🧩 Variasi: <b>{html.escape(result['variant_name'])}</b>\n"
        f"💰 Harga: <b>{rupiah(result['price'])}</b>\n"
        f"🏷️ Kode: <code>{html.escape(result['code'])}</code>\n"
        "📊 Stok awal: <b>0</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="➕ Tambah Variasi Lagi",
                callback_data=f"addvariantprod:{result['product_id']}"
            )],
            [InlineKeyboardButton(
                text="📦 Atur Stok",
                callback_data="owner:set_stock"
            )],
            [InlineKeyboardButton(
                text="⬅️ Produk & Stok",
                callback_data="owner:back_products"
            )]
        ]),
        parse_mode="HTML"
    )



@router.callback_query(F.data == "owner:set_stock")
async def owner_set_stock(call: CallbackQuery, state: FSMContext):
    if not is_owner(call.from_user.id):
        return await deny_owner_callback(call)

    try:
        await state.clear()
        keyboard=owner_stock_products_keyboard()
        await safe_edit_or_answer(
            call,
            "📦 <b>ATUR STOK</b>\n\n"
            "Pilih produk yang ingin diatur.",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        await safe_callback_notice(call)
    except Exception as exc:
        await owner_product_error_view(call, "Atur Stok", exc)



@router.callback_query(F.data.startswith("ownerstock:product:"))
async def owner_stock_product(call: CallbackQuery):
    if not is_owner(call.from_user.id):
        return await call.answer("Akses ditolak.", show_alert=True)

    product_id = int(call.data.split(":")[2])
    product, markup = owner_stock_variants_keyboard(product_id)

    if not product:
        return await call.answer("Produk tidak ditemukan.", show_alert=True)

    await safe_edit_or_answer(call, 
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

    await safe_edit_or_answer(call, 
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
    if not is_owner(call.from_user.id):
        return await deny_owner_callback(call)

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

    await safe_edit_or_answer(
        call,
        "➕ <b>TAMBAH AKUN</b>\n\n"
        "Kirim <b>teks akun bebas</b> dari owner.\n"
        "Semua isi pesan akan disimpan <b>utuh sebagai 1 akun / 1 stok</b>.\n\n"
        "Boleh banyak baris, boleh ada email, password, catatan, atau format apa pun.\n"
        "Tidak perlu tanda | dan tidak ada format khusus.",
        reply_markup=back_owner("owner:back_products"),
        parse_mode="HTML"
    )
    await call.answer()



@router.message(OwnerState.stock_add_items)
async def owner_stock_add_input(message: Message, state: FSMContext, bot: Bot):
    if not is_owner(message.from_user.id):
        return

    data = await state.get_data()
    variant_id = int(data.get("stock_variant_id", 0))

    # Free-form account text:
    # everything owner sends is preserved as ONE inventory item.
    content = (message.text or message.caption or "").strip()

    if not variant_id:
        await state.clear()
        return await message.answer(
            "❌ Variasi stok tidak ditemukan.",
            reply_markup=owner_products_menu()
        )

    if not content:
        return await message.answer(
            "❌ Teks akun kosong.\n"
            "Kirim teks akun bebas yang ingin disimpan."
        )

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
        return await message.answer(
            "❌ Variasi tidak ditemukan.",
            reply_markup=owner_products_menu()
        )

    old_available = available_stock(variant)
    product_id = int(variant["product_id"])

    # Prevent exact duplicate of the full free-form text.
    exists = conn.execute(
        """SELECT id FROM inventory_items
           WHERE variant_id=? AND content=?""",
        (variant_id, content)
    ).fetchone()

    if exists:
        conn.rollback()
        conn.close()
        await state.clear()
        return await message.answer(
            "ℹ️ Teks akun yang sama persis sudah tersimpan di variasi ini.",
            reply_markup=owner_products_menu()
        )

    now = datetime.now().isoformat(timespec="seconds")
    conn.execute(
        """INSERT INTO inventory_items
           (variant_id, content, status, created_at)
           VALUES(?,?,'available',?)""",
        (variant_id, content, now)
    )

    sync_variant_stock_from_inventory(conn, variant_id)
    conn.commit()
    conn.close()

    await state.clear()
    await fulfill_pending_for_variant(variant_id, bot)

    conn = db()
    variant_after = conn.execute(
        "SELECT * FROM product_variants WHERE id=?",
        (variant_id,)
    ).fetchone()
    conn.close()

    new_available = available_stock(variant_after)

    inventory_log(
        variant_id,
        "RESTOCK",
        1,
        "OWNER",
        "Tambah 1 akun teks bebas"
    )

    if old_available <= 0 and new_available > 0:
        asyncio.create_task(
            notify_restock_subscribers(
                bot,
                product_id,
                variant_id,
                new_available
            )
        )
        asyncio.create_task(
            broadcast_restock_to_verified(
                bot,
                product_id,
                variant_id,
                new_available
            )
        )

    preview = html.escape(content[:500])
    if len(content) > 500:
        preview += "…"

    await message.answer(
        "✅ <b>AKUN BERHASIL DITAMBAHKAN</b>\n\n"
        "Teks disimpan utuh sebagai <b>1 akun / 1 stok</b>.\n\n"
        f"<blockquote>{preview}</blockquote>\n"
        f"📦 Stok tersedia sekarang: <b>{new_available}</b>\n\n"
        "Untuk menambah akun berikutnya, buka lagi menu Tambah Akun.",
        reply_markup=owner_products_menu(),
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
        return await deny_owner_callback(call)

    try:
        await state.clear()
        await safe_edit_or_answer(
            call,
            "🏷️ <b>NAMA TOMBOL VARIASI</b>\n\n"
            "Pilih produk.\n\n"
            "Nama ini hanya mengubah tulisan tombol variasi.",
            reply_markup=owner_variant_button_products_keyboard(),
            parse_mode="HTML"
        )
        await safe_callback_notice(call)
    except Exception as exc:
        await owner_product_error_view(call, "Nama Tombol Variasi", exc)



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

    await safe_edit_or_answer(call, 
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
    await safe_edit_or_answer(call, 
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
    if not is_owner(call.from_user.id):
        return await deny_owner_callback(call)

    try:
        await state.clear()

        conn=db()
        products=conn.execute(
            "SELECT id,name FROM products WHERE active=1 ORDER BY id"
        ).fetchall()
        conn.close()

        if not products:
            await safe_edit_or_answer(
                call,
                "❌ <b>BELUM ADA PRODUK</b>\n\n"
                "Tambahkan produk terlebih dahulu.",
                reply_markup=owner_products_menu(),
                parse_mode="HTML"
            )
            return await safe_callback_notice(call)

        rows=[
            [InlineKeyboardButton(
                text=f"📦 {p['name']}",
                callback_data=f"setpriceprod:{p['id']}"
            )]
            for p in products
        ]
        rows.append([
            InlineKeyboardButton(
                text="⬅️ Kembali",
                callback_data="owner:back_products"
            )
        ])

        await safe_edit_or_answer(
            call,
            "💰 <b>ATUR HARGA VARIAN</b>\n\n"
            "Pilih produk:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
            parse_mode="HTML"
        )
        await safe_callback_notice(call)
    except Exception as exc:
        await owner_product_error_view(call, "Atur Harga", exc)



@router.message(OwnerState.set_price)
async def owner_set_price_input(message: Message, state: FSMContext):
    if not is_owner(message.from_user.id):
        return

    price=parse_rupiah_input(message.text or "")
    if not price:
        return await message.answer(
            "❌ <b>HARGA TIDAK VALID</b>\n\n"
            "Kirim nominal bebas, contoh:\n"
            "<code>2500</code>\n"
            "<code>2750</code>\n"
            "<code>12.500</code>\n"
            "<code>Rp18.750</code>",
            parse_mode="HTML"
        )

    if price > 1_000_000_000:
        return await message.answer(
            "❌ Harga terlalu besar. Maksimal Rp1.000.000.000."
        )

    data=await state.get_data()
    variant_id=int(data.get("set_price_variant_id") or 0)

    if not variant_id:
        await state.clear()
        return await message.answer(
            "❌ Sesi Atur Harga sudah terputus. Silakan buka menu Atur Harga lagi.",
            reply_markup=owner_products_menu()
        )

    conn=db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row=conn.execute(
            """SELECT v.id,v.name,p.name AS product_name
               FROM product_variants v
               JOIN products p ON p.id=v.product_id
               WHERE v.id=? AND v.active=1 AND p.active=1""",
            (variant_id,)
        ).fetchone()

        if not row:
            conn.rollback()
            conn.close()
            await state.clear()
            return await message.answer(
                "❌ Varian tidak ditemukan.",
                reply_markup=owner_products_menu()
            )

        conn.execute(
            "UPDATE product_variants SET price=? WHERE id=?",
            (price,variant_id)
        )
        conn.commit()
    except Exception as exc:
        conn.rollback()
        conn.close()
        logging.exception("Set variant price failed: %s", exc)
        return await message.answer(
            "❌ <b>GAGAL MENGUBAH HARGA</b>\n\n"
            f"<code>{html.escape(str(exc)[:300])}</code>",
            reply_markup=owner_products_menu(),
            parse_mode="HTML"
        )
    else:
        conn.close()

    await state.clear()

    await message.answer(
        "✅ <b>HARGA VARIAN DIPERBARUI</b>\n\n"
        f"📦 Produk: <b>{html.escape(row['product_name'])}</b>\n"
        f"🧩 Varian: <b>{html.escape(row['name'])}</b>\n"
        f"💰 Harga baru: <b>{rupiah(price)}</b>",
        reply_markup=owner_products_menu(),
        parse_mode="HTML"
    )



@router.callback_query(F.data == "owner:delete_product")
async def owner_delete_product(call: CallbackQuery, state: FSMContext):
    if not is_owner(call.from_user.id):
        return await deny_owner_callback(call)

    try:
        await state.clear()
        conn=db()
        total=conn.execute(
            "SELECT COUNT(*) AS n FROM products WHERE active=1"
        ).fetchone()["n"]
        conn.close()

        if int(total or 0)==0:
            await safe_edit_or_answer(
                call,
                "🗑️ <b>HAPUS PRODUK</b>\n\nBelum ada produk aktif.",
                reply_markup=back_owner("owner:back_products"),
                parse_mode="HTML"
            )
            return await safe_callback_notice(call)

        await safe_edit_or_answer(
            call,
            "🗑️ <b>HAPUS PRODUK</b>\n\n"
            "Pilih produk yang ingin dihapus dari toko.\n\n"
            "Produk menggunakan soft delete agar riwayat order lama tetap aman.",
            reply_markup=owner_delete_products_keyboard(),
            parse_mode="HTML"
        )
        await safe_callback_notice(call)
    except Exception as exc:
        await owner_product_error_view(call, "Hapus Produk", exc)



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

    await safe_edit_or_answer(call, 
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

    await safe_edit_or_answer(call, 
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
    if not is_owner(call.from_user.id):
        return await deny_owner_callback(call)

    try:
        await state.clear()
        conn=db()
        rows=conn.execute(
            "SELECT id,name,is_popular FROM products WHERE active=1 ORDER BY id"
        ).fetchall()
        conn.close()

        kb=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text=f"{'✅' if int(r['is_popular'] or 0) else '▫️'} {r['name']}",
                callback_data=f"popular:toggle:{r['id']}"
            )] for r in rows
        ] + [[InlineKeyboardButton(
            text="⬅️ Kembali",
            callback_data="owner:back_products"
        )]])

        await safe_edit_or_answer(
            call,
            "🔥 <b>PRODUK POPULER</b>\n\n"
            "Tekan produk untuk mengaktifkan / menonaktifkan status populer.",
            reply_markup=kb,
            parse_mode="HTML"
        )
        await safe_callback_notice(call)
    except Exception as exc:
        await owner_product_error_view(call, "Produk Populer", exc)



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
    if not is_owner(call.from_user.id):
        return await deny_owner_callback(call)

    try:
        await state.clear()
        conn=db()
        rows=conn.execute(
            "SELECT id,name,is_flash_sale FROM products WHERE active=1 ORDER BY id"
        ).fetchall()
        conn.close()

        kb=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text=f"{'✅' if int(r['is_flash_sale'] or 0) else '▫️'} {r['name']}",
                callback_data=f"flash:toggle:{r['id']}"
            )] for r in rows
        ] + [[InlineKeyboardButton(
            text="⬅️ Kembali",
            callback_data="owner:back_products"
        )]])

        await safe_edit_or_answer(
            call,
            "⚡ <b>FLASH SALE</b>\n\n"
            "Tekan produk untuk mengaktifkan / menonaktifkan Flash Sale.",
            reply_markup=kb,
            parse_mode="HTML"
        )
        await safe_callback_notice(call)
    except Exception as exc:
        await owner_product_error_view(call, "Flash Sale", exc)



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
    await safe_edit_or_answer(call, 
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
        await safe_edit_or_answer(call, 
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
        await safe_edit_or_answer(call, 
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
        await safe_edit_or_answer(call, "Kirim jumlah kuota voucher.", reply_markup=back_owner())
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
    await safe_edit_or_answer(call, "Langkah 6 dari 7\nPilih masa aktif voucher:", reply_markup=kb)
    await call.answer()


@router.callback_query(F.data.startswith("vbuild:days:"))
async def voucher_build_days(call: CallbackQuery, state: FSMContext):
    days = int(call.data.split(":")[2])
    await state.update_data(voucher_days=days)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👥 Semua Pelanggan", callback_data="vbuild:new:0")],
        [InlineKeyboardButton(text="🆕 Pelanggan Baru Saja", callback_data="vbuild:new:1")],
    ])
    await safe_edit_or_answer(call, 
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

    await safe_edit_or_answer(call, 
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
    if not is_owner(call.from_user.id):
        return await call.answer("Akses ditolak.", show_alert=True)

    await state.clear()
    conn = db()
    rows = conn.execute(
        """SELECT o.*, p.name AS product_name, v.name AS variant_name
           FROM orders o
           LEFT JOIN products p ON p.id=o.product_id
           LEFT JOIN product_variants v ON v.id=o.variant_id
           WHERE o.payment_method IN ('QRIS','BANK_TRANSFER')
             AND o.payment_status IN ('unpaid','expired')
             AND o.status NOT IN ('cancelled','completed')
           ORDER BY o.id DESC
           LIMIT 25"""
    ).fetchall()
    conn.close()

    kb = InlineKeyboardBuilder()
    for row in rows:
        kb.button(
            text=f"✅ {invoice(row['id'])} • {rupiah(row['payment_total'] or row['total'])}",
            callback_data=f"verifyorder:{row['id']}"
        )
    kb.button(text="⬅️ Kembali", callback_data="owner:menu_orders")
    kb.adjust(1)

    await safe_edit_or_answer(
        call,
        "✅ <b>VERIFIKASI PEMBAYARAN MANUAL</b>\n\n"
        "Pilih invoice yang sudah benar-benar masuk ke rekening/QRIS.\n"
        "Invoice kedaluwarsa tetap bisa diverifikasi jika pembayaran memang masuk.",
        reply_markup=kb.as_markup(),
        parse_mode="HTML"
    )
    await call.answer()


@router.callback_query(F.data.startswith("verifyorder:"))
async def owner_verify_order_button(call: CallbackQuery, bot: Bot):
    if not recent_action_allowed(f"verifyorder:{call.from_user.id}:{call.data}", 3):
        return await call.answer("Sedang diproses. Jangan tekan dua kali.", show_alert=True)
    if not is_owner(call.from_user.id):
        return await call.answer("Akses ditolak.", show_alert=True)

    try:
        order_id = int(call.data.split(":")[1])
    except Exception:
        return await call.answer("Invoice tidak valid.", show_alert=True)

    conn = db()
    order = conn.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
    conn.close()

    ok, state = order_payment_state_ok(order)
    if not ok:
        return await call.answer(state, show_alert=True)

    if state == "already_paid":
        await call.answer("Order sudah pernah dibayar.", show_alert=True)
        return await safe_edit_or_answer(call, 
            f"ℹ️ {invoice(order_id)} sudah berstatus dibayar.",
            reply_markup=owner_orders_menu()
        )

    success = await mark_order_paid(
        order_id,
        bot,
        int(order["payment_total"] or order["total"]),
        verified_by=call.from_user.id
    )

    if success:
        await call.answer("Pembayaran berhasil diverifikasi.", show_alert=True)
        await safe_edit_or_answer(call, 
            f"✅ <b>{invoice(order_id)} TERVERIFIKASI</b>\n\n"
            "Pembayaran dicatat sekali dan fulfillment diproses secara idempotent.",
            reply_markup=owner_orders_menu(),
            parse_mode="HTML"
        )
    else:
        await call.answer("Verifikasi gagal. Cek status order.", show_alert=True)


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
             AND NOT (
               status IN ('expired','cancelled')
               AND created_at < ?
             )
           ORDER BY id DESC
           LIMIT 10""",
        (message.from_user.id, expired_invoice_hide_cutoff_iso())
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
        expiry_line = ""
        if row["status"] == "pending" and row["reserved_until"]:
            expiry_line = f"\n   ⏳ {format_expiry_time(row['reserved_until'])}"
        lines.append(
            f"{icon} <b>{invoice(row['id'])}</b>\n"
            f"   Status: {html.escape(row['status'])}\n"
            f"   Total: {rupiah(row['payment_total'] or row['total'])}"
            f"{expiry_line}"
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

    await safe_edit_or_answer(call, 
        f"⭐ <b>Terima kasih!</b>\n\nPenilaian Anda: <b>{stars}/5</b>",
        parse_mode="HTML"
    )
    await call.answer("Rating tersimpan.")


@router.callback_query(F.data == "owner:low_stock")
async def owner_low_stock(call: CallbackQuery, state: FSMContext):
    if not is_owner(call.from_user.id):
        return await deny_owner_callback(call)

    try:
        current=low_stock_threshold()
        await state.set_state(OwnerState.low_stock_threshold)
        await safe_edit_or_answer(
            call,
            "🔔 <b>ALERT STOK MENIPIS</b>\n\n"
            f"Batas saat ini: <b>{current}</b>\n\n"
            "Kirim angka batas stok.\n"
            "Contoh: <code>5</code>\n"
            "Kirim <code>0</code> untuk menonaktifkan alert.",
            reply_markup=back_owner("owner:back_products"),
            parse_mode="HTML"
        )
        await safe_callback_notice(call)
    except Exception as exc:
        await owner_product_error_view(call, "Alert Stok", exc)



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
        return await deny_owner_callback(call)

    try:
        conn=db()
        rows=conn.execute(
            """SELECT l.*, v.name AS variant_name, p.name AS product_name
               FROM inventory_logs l
               LEFT JOIN product_variants v ON v.id=l.variant_id
               LEFT JOIN products p ON p.id=v.product_id
               ORDER BY l.id DESC LIMIT 25"""
        ).fetchall()
        conn.close()

        lines=["📚 <b>RIWAYAT STOK</b>",""]
        if not rows:
            lines.append("Belum ada log stok.")
        else:
            for row in rows:
                sign="+" if int(row["qty"] or 0)>0 else ""
                product_name=row["product_name"] or "Produk lama"
                variant_name=row["variant_name"] or "Varian lama"
                lines.append(
                    f"{str(row['created_at'] or '-')[:16]} • {html.escape(str(row['action'] or '-'))}\n"
                    f"{html.escape(product_name)} — {html.escape(variant_name)}\n"
                    f"{sign}{int(row['qty'] or 0)} • {html.escape(str(row['reference'] or '-'))}"
                )

        await safe_edit_or_answer(
            call,
            "\n\n".join(lines),
            reply_markup=back_owner("owner:back_products"),
            parse_mode="HTML"
        )
        await safe_callback_notice(call)
    except Exception as exc:
        await owner_product_error_view(call, "Riwayat Stok", exc)



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

    await safe_edit_or_answer(call, 
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
    await safe_edit_or_answer(call, "✅ Status user diperbarui.", reply_markup=owner_menu())


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

    await safe_edit_or_answer(call, 
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

    await safe_edit_or_answer(call, 
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
    await safe_edit_or_answer(call, 
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
    await safe_edit_or_answer(call, "✅ Top up selesai diproses.", reply_markup=owner_wallet_menu())



@router.callback_query(F.data == "owner:selftest")
async def owner_selftest(call: CallbackQuery, bot: Bot):
    if not is_owner(call.from_user.id):
        return await call.answer("Akses ditolak.", show_alert=True)
    await call.answer("Menu ini sudah digabung ke Diagnostik Sistem.")
    await render_owner_diagnostics(call, bot)


@router.callback_query(F.data == "owner:maintenance")
async def owner_maintenance(call: CallbackQuery):
    if not is_owner(call.from_user.id):
        return await deny_owner_callback(call)

    try:
        new_value = "0" if maintenance_enabled() else "1"
        set_setting("maintenance_mode", new_value)
        status = "ON" if new_value == "1" else "OFF"

        await safe_edit_or_answer(
            call,
            "🔧 <b>MAINTENANCE MODE</b>\n\n"
            f"Status sekarang: <b>{status}</b>\n\n"
            "Saat ON, checkout baru ditahan.",
            reply_markup=owner_system_menu(),
            parse_mode="HTML"
        )
        await safe_callback_notice(call)
    except Exception as exc:
        await owner_system_error_view(call, "Maintenance", exc)



@router.callback_query(F.data == "owner:segments")
async def owner_segments(call: CallbackQuery):
    if not is_owner(call.from_user.id):
        return await call.answer("Akses ditolak.", show_alert=True)

    counts = {}
    for key in ["new","buyers","returning","vip","inactive","all"]:
        counts[key]=len(segment_user_ids(key))

    await safe_edit_or_answer(call, 
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
    await safe_edit_or_answer(call, 
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
    await safe_edit_or_answer(call, 
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
    await safe_edit_or_answer(call, 
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
    await safe_edit_or_answer(call, 
        f"🎯 Cashback otomatis: <b>{value}%</b>",
        reply_markup=owner_menu(),
        parse_mode="HTML"
    )


@router.callback_query(F.data == "owner:daily_report")
async def owner_daily_report(call: CallbackQuery, bot: Bot):
    if not is_owner(call.from_user.id):
        return await deny_owner_callback(call)

    try:
        enabled = get_setting("daily_report_enabled","1") == "1"
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text=("🔕 Matikan Laporan" if enabled else "🔔 Aktifkan Laporan"),
                callback_data="dailyreport:toggle"
            )],
            [InlineKeyboardButton(
                text="📨 Kirim Laporan Sekarang",
                callback_data="dailyreport:send"
            )],
            [InlineKeyboardButton(
                text="⬅️ Kembali",
                callback_data="owner:back_system"
            )]
        ])

        await safe_edit_or_answer(
            call,
            "📅 <b>LAPORAN HARIAN</b>\n\n"
            f"Status: <b>{'ON' if enabled else 'OFF'}</b>\n"
            f"Jam laporan: sekitar <b>{setting_int('daily_report_hour',20):02d}:00</b>",
            reply_markup=kb,
            parse_mode="HTML"
        )
        await safe_callback_notice(call)
    except Exception as exc:
        await owner_system_error_view(call, "Laporan Harian", exc)



@router.callback_query(F.data == "dailyreport:toggle")
async def owner_daily_report_toggle(call: CallbackQuery):
    if not is_owner(call.from_user.id):
        return await deny_owner_callback(call)

    try:
        enabled = get_setting("daily_report_enabled","1") == "1"
        set_setting("daily_report_enabled","0" if enabled else "1")

        await safe_edit_or_answer(
            call,
            "✅ <b>PENGATURAN LAPORAN DIPERBARUI</b>\n\n"
            f"Status sekarang: <b>{'OFF' if enabled else 'ON'}</b>",
            reply_markup=owner_system_menu(),
            parse_mode="HTML"
        )
        await safe_callback_notice(call)
    except Exception as exc:
        await owner_system_error_view(call, "Toggle Laporan Harian", exc)



@router.callback_query(F.data == "dailyreport:send")
async def owner_daily_report_send(call: CallbackQuery, bot: Bot):
    if not is_owner(call.from_user.id):
        return await deny_owner_callback(call)

    try:
        await send_daily_owner_report(bot)
        await safe_edit_or_answer(
            call,
            "✅ <b>LAPORAN HARIAN DIKIRIM</b>\n\n"
            "Laporan sudah dikirim ke PM owner.",
            reply_markup=owner_system_menu(),
            parse_mode="HTML"
        )
        await safe_callback_notice(call)
    except Exception as exc:
        await owner_system_error_view(call, "Kirim Laporan Harian", exc)



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
    kb.button(text="⬅️ Kembali",callback_data="owner:back_products")
    kb.adjust(1)
    await safe_edit_or_answer(call, 
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
    await safe_edit_or_answer(call, "Pilih produk kedua:",reply_markup=kb.as_markup())
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

    await safe_edit_or_answer(call, 
        f"✅ Paket dibuat:\n<b>{html.escape(name)}</b>\n\n"
        "User dapat menambahkan paket ini ke keranjang dari List Produk → Paket Hemat.",
        reply_markup=owner_menu(),
        parse_mode="HTML"
    )
    await call.answer("Paket dibuat.")




@router.callback_query(F.data == "owner:payment_health")
async def owner_payment_health(call: CallbackQuery, bot: Bot):
    if not is_owner(call.from_user.id):
        return await call.answer("Akses ditolak.", show_alert=True)
    await call.answer("Menu ini sudah digabung ke Diagnostik Sistem.")
    await render_owner_diagnostics(call, bot)


@router.callback_query(F.data == "owner:transaction_test")
async def owner_transaction_test(call: CallbackQuery, bot: Bot):
    if not is_owner(call.from_user.id):
        return await call.answer("Akses ditolak.", show_alert=True)
    await call.answer("Menu ini sudah digabung ke Diagnostik Sistem.")
    await render_owner_diagnostics(call, bot)


@router.callback_query(F.data == "owner:health_score")
async def owner_health_score(call: CallbackQuery, bot: Bot):
    if not is_owner(call.from_user.id):
        return await call.answer("Akses ditolak.", show_alert=True)
    await call.answer("Menu ini sudah digabung ke Diagnostik Sistem.")
    await render_owner_diagnostics(call, bot)


@router.callback_query(F.data == "owner:safe_mode")
async def owner_safe_mode(call: CallbackQuery):
    if not is_owner(call.from_user.id):
        return await deny_owner_callback(call)

    try:
        enabled = not safe_mode_enabled()
        set_safe_mode(enabled)

        await safe_edit_or_answer(
            call,
            "🛟 <b>SAFE MODE</b>\n\n"
            f"Status: <b>{'ON' if enabled else 'OFF'}</b>\n\n"
            "Saat ON, checkout dan top up user ditahan sementara.",
            reply_markup=owner_system_menu(),
            parse_mode="HTML"
        )
        await safe_callback_notice(call)
    except Exception as exc:
        await owner_system_error_view(call, "Safe Mode", exc)



@router.callback_query(F.data == "owner:repair_inventory")
async def owner_repair_inventory(call: CallbackQuery):
    if not is_owner(call.from_user.id):
        return await deny_owner_callback(call)

    try:
        mismatches, repaired = inventory_integrity_report(auto_repair=True)
        await safe_edit_or_answer(
            call,
            "🧹 <b>REPAIR INVENTORY</b>\n\n"
            f"Mismatch ditemukan: <b>{len(mismatches)}</b>\n"
            f"Diperbaiki: <b>{repaired}</b>\n\n"
            "Stock counter disinkronkan ulang dari inventory_items.",
            reply_markup=owner_system_menu(),
            parse_mode="HTML"
        )
        await safe_callback_notice(call)
    except Exception as exc:
        await owner_system_error_view(call, "Repair Inventory", exc)



@router.errors()
async def global_error_handler(event: ErrorEvent):
    exc=event.exception
    update=event.update

    if isinstance(exc, TelegramRetryAfter):
        wait_seconds=max(1,int(getattr(exc,"retry_after",1) or 1))
        logging.warning("Telegram rate limit: retry_after=%s", wait_seconds)
        await asyncio.sleep(min(wait_seconds,30))
        return True

    if isinstance(exc, TelegramNetworkError):
        logging.warning("Telegram network error: %s", exc)
        return True


    update_id=int(getattr(update,"update_id",0) or 0)
    callback=getattr(update,"callback_query",None)
    message=getattr(update,"message",None)

    event_type="unknown"
    callback_data=""
    user_id=0
    reference=""
    state_name=""

    if callback:
        event_type="callback_query"
        callback_data=str(callback.data or "")
        user_id=int(callback.from_user.id or 0)
        reference=f"callback:{callback_data or '-'}"
    elif message:
        event_type="message"
        user_id=int(message.from_user.id or 0)
        msg_text=str(message.text or "")
        reference=f"message:{msg_text[:80]}" if msg_text else "message"

    logging.exception(
        "Unhandled bot error update_id=%s event=%s user=%s callback=%r: %s",
        update_id,event_type,user_id,callback_data,exc
    )

    try:
        log_detailed_error(
            "GLOBAL_HANDLER",
            exc,
            reference=reference,
            update_id=update_id,
            event_type=event_type,
            callback_data=callback_data,
            user_id=user_id,
            state_name=state_name,
            recovered=False
        )
    except Exception as log_exc:
        logging.exception("Detailed error log failed: %s",log_exc)

    bot=getattr(event,"bot",None)

    if callback:
        try:
            if is_owner(user_id):
                await callback.answer(
                    f"{type(exc).__name__} • {callback_data or 'callback'}",
                    show_alert=True
                )
            else:
                await callback.answer(
                    "Terjadi gangguan sementara. Sistem mencoba recovery otomatis.",
                    show_alert=True
                )
        except Exception:
            pass

    if bot:
        try:
            await notify_owner_system_error(
                bot,
                "UNHANDLED",
                f"{type(exc).__name__}: {exc}",
                reference=reference,
                recovered=False
            )
        except Exception:
            pass

        try:
            await auto_recovery_cycle(bot,source=reference or f"update:{update_id}")
        except Exception:
            pass

    return True



@router.callback_query(F.data.startswith("proofapprove:"))
async def owner_proof_approve(call: CallbackQuery, bot: Bot):
    if not is_owner(call.from_user.id):
        return await call.answer("Akses ditolak.", show_alert=True)

    _, entity, raw_id = call.data.split(":")
    entity_id = int(raw_id)

    if not recent_action_allowed(f"proofapprove:{entity}:{entity_id}", 3):
        return await call.answer("Sedang diproses. Jangan tekan dua kali.", show_alert=True)

    if entity == "order":
        conn = db()
        row = conn.execute("SELECT * FROM orders WHERE id=?", (entity_id,)).fetchone()
        conn.close()

        if not row:
            return await call.answer("Order tidak ditemukan.", show_alert=True)

        if row["payment_status"] == "paid":
            return await call.answer("Order sudah diverifikasi.", show_alert=True)

        ok = await mark_order_paid(
            entity_id,
            bot,
            int(row["payment_total"] or row["total"]),
            verified_by=call.from_user.id
        )
        if not ok:
            return await call.answer("Verifikasi order gagal.", show_alert=True)

        await call.answer("Pembayaran dikonfirmasi.", show_alert=True)
        try:
            await call.message.edit_caption(
                caption=payment_proof_caption("order", row) + "\n\n✅ <b>DIKONFIRMASI OWNER</b>",
                parse_mode="HTML"
            )
        except Exception:
            pass
        return

    if entity == "topup":
        result, status = verify_topup_atomic(entity_id, call.from_user.id)
        if status == "already_completed":
            return await call.answer("Top up sudah diverifikasi.", show_alert=True)
        if status != "completed":
            return await call.answer("Top up gagal diverifikasi.", show_alert=True)

        row, balance = result
        try:
            await bot.send_message(
                row["user_id"],
                "✅ <b>TOP UP DIKONFIRMASI</b>\n\n"
                f"🧾 {topup_invoice(entity_id)}\n"
                f"💰 Saldo masuk: <b>{rupiah(row['amount'])}</b>\n"
                f"💵 Saldo sekarang: <b>{rupiah(balance)}</b>",
                parse_mode="HTML"
            )
        except Exception:
            pass

        await call.answer("Top up dikonfirmasi.", show_alert=True)
        try:
            await call.message.edit_caption(
                caption=payment_proof_caption("topup", row) + "\n\n✅ <b>DIKONFIRMASI OWNER</b>",
                parse_mode="HTML"
            )
        except Exception:
            pass


@router.callback_query(F.data.startswith("proofreject:"))
async def owner_proof_reject(call: CallbackQuery):
    if not is_owner(call.from_user.id):
        return await call.answer("Akses ditolak.", show_alert=True)

    _, entity, raw_id = call.data.split(":")
    entity_id = int(raw_id)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Bukti Tidak Valid", callback_data=f"proofrejectreason:{entity}:{entity_id}:invalid")],
        [InlineKeyboardButton(text="💰 Nominal Tidak Sesuai", callback_data=f"proofrejectreason:{entity}:{entity_id}:amount")],
        [InlineKeyboardButton(text="🔎 Pembayaran Tidak Ditemukan", callback_data=f"proofrejectreason:{entity}:{entity_id}:notfound")],
        [InlineKeyboardButton(text="↩️ Kembali", callback_data=f"proofpending:{entity}:{entity_id}")]
    ])

    await safe_edit_or_answer(
        call,
        "❌ <b>TOLAK BUKTI PEMBAYARAN</b>\n\nPilih alasan:",
        reply_markup=kb,
        parse_mode="HTML"
    )
    await call.answer()


@router.callback_query(F.data.startswith("proofrejectreason:"))
async def owner_proof_reject_reason(call: CallbackQuery, bot: Bot):
    if not is_owner(call.from_user.id):
        return await call.answer("Akses ditolak.", show_alert=True)

    _, entity, raw_id, reason_code = call.data.split(":")
    entity_id = int(raw_id)

    reasons = {
        "invalid": "Bukti pembayaran tidak valid.",
        "amount": "Nominal pembayaran tidak sesuai invoice.",
        "notfound": "Pembayaran belum ditemukan oleh owner.",
    }
    reason = reasons.get(reason_code, "Bukti pembayaran ditolak.")

    conn = db()
    if entity == "order":
        row = conn.execute("SELECT * FROM orders WHERE id=?", (entity_id,)).fetchone()
        if row:
            conn.execute(
                "UPDATE orders SET payment_reject_reason=? WHERE id=?",
                (reason, entity_id)
            )
    else:
        row = conn.execute("SELECT * FROM topups WHERE id=?", (entity_id,)).fetchone()
        if row:
            conn.execute(
                "UPDATE topups SET payment_reject_reason=? WHERE id=?",
                (reason, entity_id)
            )
    conn.commit()
    conn.close()

    if not row:
        return await call.answer("Transaksi tidak ditemukan.", show_alert=True)

    try:
        inv = invoice(entity_id) if entity == "order" else topup_invoice(entity_id)
        await bot.send_message(
            row["user_id"],
            "❌ <b>BUKTI PEMBAYARAN DITOLAK</b>\n\n"
            f"🧾 {inv}\n"
            f"Alasan: <b>{html.escape(reason)}</b>\n\n"
            "Silakan kirim ulang bukti yang benar selama invoice masih berlaku.",
            reply_markup=payment_proof_keyboard(entity, entity_id),
            parse_mode="HTML"
        )
    except Exception:
        pass

    await call.answer("Bukti ditolak.", show_alert=True)
    try:
        await call.message.edit_caption(
            caption=payment_proof_caption(entity, row) + f"\n\n❌ <b>DITOLAK</b>\n{html.escape(reason)}",
            parse_mode="HTML"
        )
    except Exception:
        pass


@router.callback_query(F.data.startswith("proofpending:"))
async def owner_proof_pending(call: CallbackQuery):
    if not is_owner(call.from_user.id):
        return await call.answer("Akses ditolak.", show_alert=True)

    _, entity, raw_id = call.data.split(":")
    entity_id = int(raw_id)

    conn = db()
    row = conn.execute(
        "SELECT * FROM orders WHERE id=?" if entity == "order" else "SELECT * FROM topups WHERE id=?",
        (entity_id,)
    ).fetchone()
    conn.close()

    if not row:
        return await call.answer("Transaksi tidak ditemukan.", show_alert=True)

    try:
        await call.message.edit_caption(
            caption=payment_proof_caption(entity, row) + "\n\n⏳ <b>MENUNGGU PEMERIKSAAN</b>",
            reply_markup=owner_payment_proof_keyboard(entity, entity_id),
            parse_mode="HTML"
        )
    except Exception:
        pass

    await call.answer("Ditandai pending.", show_alert=True)



async def render_owner_diagnostics(call: CallbackQuery, bot: Bot):
    snap = system_health_snapshot()
    score, notes = system_health_score()
    payment = await payment_health_report()
    selftests = await run_system_self_test(bot)
    txchecks = await transaction_self_test()

    icon = "🟢" if score >= 90 else "🟡" if score >= 70 else "🔴"
    lines = [
        f"{icon} <b>DIAGNOSTIK SISTEM • {score}%</b>",
        "",
        "📊 <b>Ringkasan</b>",
        f"• Produk aktif: <b>{snap['active_products']}</b>",
        f"• Variasi aktif: <b>{snap['active_variants']}</b>",
        f"• Pending order: <b>{snap['pending_orders']}</b>",
        f"• Paid belum terkirim: <b>{snap['paid_pending']}</b>",
        f"• Send failed: <b>{snap['send_failed']}</b>",
        f"• Stock mismatch: <b>{snap['stock_mismatch']}</b>",
        "",
        "💳 <b>Pembayaran</b>",
        f"• Manual pending: <b>{payment['pending_manual']}</b>",
        f"• Top up pending: <b>{payment['topup_pending']}</b>",
        f"• Top up processing: <b>{payment['topup_processing']}</b>",
        f"• Top up expired: <b>{payment['topup_expired']}</b>",
        f"• Wallet negatif: <b>{payment['wallet_negative']}</b>",
        f"• Duplicate paid event: <b>{payment['duplicate_paid_events']}</b>",
        "",
        f"• Auto Recovery: <b>{'ON' if get_setting('auto_recovery_enabled','1') == '1' else 'OFF'}</b>",
        "• FSM Storage: <b>SQLite Persistent</b>",
        "• Drop Pending Updates: <b>OFF</b>",
        "• Event Isolation: <b>ON</b>",
        "• Polling Concurrency Limit: <b>32</b>",
        "• SQLite WAL: <b>ON</b>",
        "• SQLite Busy Timeout: <b>10s</b>",
        "• Allowed Updates: <b>message + callback_query</b>",
        f"• Callback Terakhir: <code>{html.escape(LAST_CALLBACK_TRACE['data'] or '-')}</code>",
        f"• Callback Status: <b>{html.escape(LAST_CALLBACK_TRACE['status'])}</b> • {int(LAST_CALLBACK_TRACE['elapsed_ms'])}ms",
        f"• Auto Repair Inventory: <b>{'ON' if get_setting('auto_repair_inventory','1') == '1' else 'OFF'}</b>",
        "",
        "🧪 <b>Self-Test</b>",
    ]

    # Merge duplicate test outputs by display name.
    merged = {}
    for name, ok, detail in list(selftests) + list(txchecks):
        old = merged.get(name)
        if old is None or (not old[0] and ok):
            merged[name] = (ok, detail)

    for name, (ok, detail) in merged.items():
        lines.append(
            f"{'✅' if ok else '❌'} {html.escape(str(name))}: "
            f"{html.escape(str(detail))}"
        )

    if notes:
        lines += ["", "⚠️ <b>Catatan</b>"]
        lines += [f"• {html.escape(str(note))}" for note in notes]

    recent_errors=latest_error_diagnostics(5)
    lines += ["", "🧾 <b>ERROR TERAKHIR</b>"]

    if not recent_errors:
        lines.append("✅ Belum ada error tercatat.")
    else:
        for row in recent_errors:
            stamp=str(row["created_at"] or "-").replace("T"," ")[:19]
            lines.append(
                f"• <b>#{row['id']} {html.escape(row['exception_type'] or 'Exception')}</b> • "
                f"{html.escape(stamp)}\n"
                f"  Event: <code>{html.escape(row['event_type'] or '-')}</code>\n"
                f"  Callback: <code>{html.escape((row['callback_data'] or '-')[:120])}</code>\n"
                f"  State: <code>{html.escape((row['state_name'] or '-')[:120])}</code>\n"
                f"  User: <code>{int(row['user_id'] or 0)}</code> • "
                f"Update: <code>{int(row['update_id'] or 0)}</code>"
            )

    await safe_edit_or_answer(
        call,
        "\n".join(lines),
        reply_markup=owner_system_menu(),
        parse_mode="HTML"
    )


@router.callback_query(F.data == "owner:diagnostics")
async def owner_diagnostics(call: CallbackQuery, bot: Bot):
    if not is_owner(call.from_user.id):
        return await deny_owner_callback(call)

    await safe_callback_notice(call, "Menjalankan diagnostik...")
    try:
        await render_owner_diagnostics(call, bot)
    except Exception as exc:
        await owner_system_error_view(call, "Diagnostik Sistem", exc)



@router.callback_query(F.data == "owner:proof_info")
async def owner_proof_info(call: CallbackQuery):
    if not is_owner(call.from_user.id):
        return await call.answer("Akses ditolak.", show_alert=True)

    await safe_edit_or_answer(
        call,
        "📥 <b>VERIFIKASI PEMBAYARAN</b>\n\n"
        "Pembayaran manual sekarang diverifikasi langsung dari "
        "<b>PM bukti pembayaran</b> yang dikirim bot ke owner.\n\n"
        "Di PM bukti tersedia:\n"
        "✅ Konfirmasi\n"
        "❌ Tolak\n"
        "⏳ Tandai Pending\n\n"
        "Menu verifikasi manual lama disembunyikan agar tidak ada dua jalur yang sama.",
        reply_markup=owner_orders_menu(),
        parse_mode="HTML"
    )
    await call.answer()

@router.callback_query(F.data == "owner:test_pm")
async def owner_test_pm(call: CallbackQuery, bot: Bot):
    if not is_owner(call.from_user.id):
        return await deny_owner_callback(call)

    try:
        if not ADMIN_ID:
            raise RuntimeError("ADMIN_ID belum dikonfigurasi.")

        await bot.send_message(
            ADMIN_ID,
            "✅ <b>TEST PM OWNER BERHASIL</b>\n\n"
            "Bot dapat mengirim pesan langsung ke PM owner.",
            parse_mode="HTML"
        )
        await safe_edit_or_answer(
            call,
            "✅ <b>TEST PM OWNER BERHASIL</b>\n\n"
            "Pesan test sudah dikirim ke PM owner.",
            reply_markup=owner_system_menu(),
            parse_mode="HTML"
        )
        await safe_callback_notice(call)
    except Exception as exc:
        await owner_system_error_view(call, "Test PM Owner", exc)



@router.callback_query(F.data == "owner:test_channel")
async def owner_test_channel(call: CallbackQuery, bot: Bot):
    if not is_owner(call.from_user.id):
        return await deny_owner_callback(call)

    try:
        if not REQUIRED_CHANNEL_ID:
            raise RuntimeError("REQUIRED_CHANNEL_ID belum diisi.")

        raw_target = str(REQUIRED_CHANNEL_ID).strip()
        target = int(raw_target) if raw_target.lstrip("-").isdigit() else raw_target

        chat = await bot.get_chat(target)
        me = await bot.get_me()
        bot_member = await bot.get_chat_member(target, me.id)
        bot_status_obj = getattr(bot_member, "status", "")
        bot_status = str(getattr(bot_status_obj, "value", bot_status_obj)).lower()

        owner_member = await bot.get_chat_member(target, call.from_user.id)
        owner_status_obj = getattr(owner_member, "status", "")
        owner_status = str(getattr(owner_status_obj, "value", owner_status_obj)).lower()

        bot_admin = bot_status in {"administrator", "creator", "owner"}

        await safe_edit_or_answer(
            call,
            "📢 <b>TEST REQUIRED CHANNEL</b>\n\n"
            f"Channel: <b>{html.escape(getattr(chat, 'title', '') or str(target))}</b>\n"
            f"Status bot: <b>{html.escape(bot_status)}</b>\n"
            f"Status owner: <b>{html.escape(owner_status)}</b>\n\n"
            + (
                "✅ Bot sudah admin dan dapat memeriksa membership."
                if bot_admin
                else "❌ Bot belum admin channel."
            ),
            reply_markup=owner_system_menu(),
            parse_mode="HTML"
        )
        await safe_callback_notice(call)
    except Exception as exc:
        await owner_system_error_view(call, "Test Channel", exc)



@router.callback_query(F.data == "owner:launch_readiness")
async def owner_launch_readiness(call: CallbackQuery):
    if not is_owner(call.from_user.id):
        return await deny_owner_callback(call)

    await call.answer(
        "Pengecekan kesiapan sekarang dipindah ke /ping.",
        show_alert=True
    )



@router.callback_query(F.data == "owner:cleanup_data")
async def owner_cleanup_data(call: CallbackQuery):
    if not is_owner(call.from_user.id):
        return await deny_owner_callback(call)

    try:
        await safe_edit_or_answer(
            call,
            "🗑️ <b>HAPUS DATA</b>\n\n"
            "Pilih data yang ingin dibersihkan.\n\n"
            "🔒 Pending hanya bisa dihapus jika belum dibayar. Paid/completed, saldo user, dan akun terjual tidak ikut dihapus.",
            reply_markup=cleanup_data_keyboard(),
            parse_mode="HTML"
        )
        await safe_callback_notice(call)
    except Exception as exc:
        await owner_system_error_view(call, "Hapus Data", exc)


@router.callback_query(F.data.startswith("cleanup:preview:"))
async def owner_cleanup_preview(call: CallbackQuery):
    if not is_owner(call.from_user.id):
        return await deny_owner_callback(call)

    try:
        kind=call.data.split(":")[-1]
        data=cleanup_preview_text(kind)
        if not data:
            return await call.answer("Jenis data tidak valid.", show_alert=True)

        title,count,description=data
        await safe_edit_or_answer(
            call,
            f"🗑️ <b>{html.escape(title)}</b>\n\n"
            f"Data ditemukan: <b>{count}</b>\n\n"
            f"{html.escape(description)}\n\n"
            "⚠️ Data yang dihapus tidak bisa dikembalikan dari bot.",
            reply_markup=cleanup_confirm_keyboard(kind),
            parse_mode="HTML"
        )
        await safe_callback_notice(call)
    except Exception as exc:
        await owner_system_error_view(call, "Preview Hapus Data", exc)



@router.callback_query(F.data.startswith("cleanup:confirm:"))
async def owner_cleanup_confirm(call: CallbackQuery):
    if not is_owner(call.from_user.id):
        return await deny_owner_callback(call)

    kind=call.data.split(":")[-1]
    if kind not in {"orders","pending","topups","proofs","errors","safe"}:
        return await call.answer("Jenis data tidak valid.", show_alert=True)

    try:
        result=cleanup_execute(kind)
        await safe_edit_or_answer(
            call,
            "✅ <b>PEMBERSIHAN SELESAI</b>\n\n"
            f"🧾 Order expired: <b>{result['orders']}</b>\n"
            f"💰 Top up expired: <b>{result['topups']}</b>\n"
            f"📎 Session bukti: <b>{result['proofs']}</b>\n"
            f"🧯 Log error: <b>{result['errors']}</b>\n\n"
            "Data paid/completed dan akun terjual tetap aman.",
            reply_markup=cleanup_data_keyboard(),
            parse_mode="HTML"
        )
        await safe_callback_notice(call)
    except Exception as exc:
        await owner_system_error_view(call, "Hapus Data", exc)


@router.message(F.text == "🔄 Perbarui Keyboard")
async def refresh_user_keyboard(message: Message, state: FSMContext, bot: Bot):
    await state.clear()

    if not await is_channel_member(bot, message.from_user.id):
        return await send_join_required(message)

    mark_user_verified(
        message.from_user.id,
        message.from_user.username or ""
    )

    await force_refresh_user_keyboard(message)


@router.callback_query(F.data == "refresh_keyboard")
async def refresh_keyboard_callback(call: CallbackQuery, state: FSMContext, bot: Bot):
    await state.clear()

    if not await is_channel_member(bot, call.from_user.id):
        await safe_edit_or_answer(
            call,
            "🔐 <b>VERIFIKASI CHANNEL</b>\n\n"
            f"Silakan join <b>{REQUIRED_CHANNEL_NAME}</b> terlebih dahulu.",
            reply_markup=join_required_keyboard(),
            parse_mode="HTML"
        )
        return await safe_callback_notice(call)

    await safe_callback_notice(call, "Keyboard diperbarui.")
    await force_refresh_user_keyboard(call.message)


@router.callback_query(F.data.startswith("popular:toggle:"))
async def owner_popular_toggle(call: CallbackQuery):
    if not is_owner(call.from_user.id):
        return await deny_owner_callback(call)

    try:
        product_id=int(call.data.split(":")[-1])
        conn=db()
        row=conn.execute(
            "SELECT id,is_popular FROM products WHERE id=? AND active=1",
            (product_id,)
        ).fetchone()
        if not row:
            conn.close()
            return await call.answer("Produk tidak ditemukan.", show_alert=True)

        new_value=0 if int(row["is_popular"] or 0) else 1
        conn.execute(
            "UPDATE products SET is_popular=? WHERE id=?",
            (new_value,product_id)
        )
        conn.commit()
        conn.close()

        await call.answer(
            "Produk populer diperbarui.",
            show_alert=False
        )
        # reopen selector
        fake_state=None
        conn=db()
        rows=conn.execute(
            "SELECT id,name,is_popular FROM products WHERE active=1 ORDER BY id"
        ).fetchall()
        conn.close()
        kb=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text=f"{'✅' if int(r['is_popular'] or 0) else '▫️'} {r['name']}",
                callback_data=f"popular:toggle:{r['id']}"
            )] for r in rows
        ] + [[InlineKeyboardButton(text="⬅️ Kembali",callback_data="owner:back_products")]])
        await safe_edit_or_answer(
            call,
            "🔥 <b>PRODUK POPULER</b>\n\nTekan produk untuk mengaktifkan / menonaktifkan status populer.",
            reply_markup=kb,
            parse_mode="HTML"
        )
    except Exception as exc:
        await owner_product_error_view(call, "Produk Populer", exc)


@router.callback_query(F.data.startswith("flash:toggle:"))
async def owner_flash_toggle(call: CallbackQuery):
    if not is_owner(call.from_user.id):
        return await deny_owner_callback(call)

    try:
        product_id=int(call.data.split(":")[-1])
        conn=db()
        row=conn.execute(
            "SELECT id,is_flash_sale FROM products WHERE id=? AND active=1",
            (product_id,)
        ).fetchone()
        if not row:
            conn.close()
            return await call.answer("Produk tidak ditemukan.", show_alert=True)

        new_value=0 if int(row["is_flash_sale"] or 0) else 1
        conn.execute(
            "UPDATE products SET is_flash_sale=? WHERE id=?",
            (new_value,product_id)
        )
        conn.commit()
        conn.close()

        await call.answer("Flash Sale diperbarui.")
        conn=db()
        rows=conn.execute(
            "SELECT id,name,is_flash_sale FROM products WHERE active=1 ORDER BY id"
        ).fetchall()
        conn.close()
        kb=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text=f"{'✅' if int(r['is_flash_sale'] or 0) else '▫️'} {r['name']}",
                callback_data=f"flash:toggle:{r['id']}"
            )] for r in rows
        ] + [[InlineKeyboardButton(text="⬅️ Kembali",callback_data="owner:back_products")]])
        await safe_edit_or_answer(
            call,
            "⚡ <b>FLASH SALE</b>\n\nTekan produk untuk mengaktifkan / menonaktifkan Flash Sale.",
            reply_markup=kb,
            parse_mode="HTML"
        )
    except Exception as exc:
        await owner_product_error_view(call, "Flash Sale", exc)


@router.callback_query(F.data == "owner:auto_recovery_now")
async def owner_auto_recovery_now(call: CallbackQuery, bot: Bot):
    if not is_owner(call.from_user.id):
        return await deny_owner_callback(call)

    await safe_callback_notice(call, "Menjalankan auto recovery...")

    try:
        report=await auto_recovery_cycle(bot, source="manual_owner")

        lines=[
            "♻️ <b>AUTO RECOVERY SELESAI</b>",
            "",
            f"✅ Order recovered: <b>{report['recovered_orders']}</b>",
            f"📦 Paid belum terkirim: <b>{report['pending_paid']}</b>",
            f"🧹 Inventory repaired: <b>{report['inventory_repaired']}</b>",
            f"💰 Topup reset: <b>{report['topups_reset']}</b>",
            f"📎 Proof session cleaned: <b>{report['proof_sessions_cleaned']}</b>",
            f"🛟 Safe Mode triggered: <b>{'YA' if report['safe_mode_triggered'] else 'TIDAK'}</b>",
        ]

        if report["errors"]:
            lines += [
                "",
                "⚠️ <b>Error:</b>",
                *[f"• {html.escape(x)}" for x in report["errors"]]
            ]

        await safe_edit_or_answer(
            call,
            "\n".join(lines),
            reply_markup=owner_system_menu(),
            parse_mode="HTML"
        )
    except Exception as exc:
        await owner_system_error_view(call, "Auto Recovery", exc)


@router.callback_query(F.data.startswith("ownerstock:"))
async def owner_stock_product_pick(call: CallbackQuery):
    if not is_owner(call.from_user.id):
        return await deny_owner_callback(call)

    try:
        product_id=int(call.data.split(":")[-1])
    except Exception:
        return await call.answer("Produk tidak valid.", show_alert=True)

    conn=db()
    product=conn.execute(
        "SELECT id,name FROM products WHERE id=? AND active=1",
        (product_id,)
    ).fetchone()
    conn.close()

    if not product:
        return await call.answer("Produk tidak ditemukan.", show_alert=True)

    await safe_edit_or_answer(
        call,
        "📦 <b>ATUR STOK</b>\n\n"
        f"Produk: <b>{html.escape(product['name'])}</b>\n\n"
        "Pilih varian:",
        reply_markup=owner_stock_variants_keyboard(product_id),
        parse_mode="HTML"
    )
    await safe_callback_notice(call)


@router.callback_query(F.data.startswith("ownerstockvar:"))
async def owner_stock_variant_pick(call: CallbackQuery, state: FSMContext):
    if not is_owner(call.from_user.id):
        return await deny_owner_callback(call)

    try:
        variant_id=int(call.data.split(":")[-1])
    except Exception:
        return await call.answer("Varian tidak valid.", show_alert=True)

    conn=db()
    row=conn.execute(
        """SELECT v.id,v.name,v.stock,v.reserved_stock,p.name AS product_name
           FROM product_variants v
           JOIN products p ON p.id=v.product_id
           WHERE v.id=? AND v.active=1 AND p.active=1""",
        (variant_id,)
    ).fetchone()
    conn.close()

    if not row:
        return await call.answer("Varian tidak ditemukan.", show_alert=True)

    available=max(0,int(row["stock"] or 0)-int(row["reserved_stock"] or 0))

    await state.update_data(stock_variant_id=variant_id)

    await safe_edit_or_answer(
        call,
        "📦 <b>ATUR STOK</b>\n\n"
        f"Produk: <b>{html.escape(row['product_name'])}</b>\n"
        f"Varian: <b>{html.escape(row['name'])}</b>\n"
        f"Stok tersedia: <b>{available}</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="➕ Tambah Akun",
                callback_data=f"ownerstockadd:{variant_id}"
            )],
            [InlineKeyboardButton(
                text="⬅️ Kembali",
                callback_data="owner:set_stock"
            )]
        ]),
        parse_mode="HTML"
    )
    await safe_callback_notice(call)


@router.callback_query(F.data.startswith("ownerstockadd:"))
async def owner_stock_add_begin(call: CallbackQuery, state: FSMContext):
    if not is_owner(call.from_user.id):
        return await deny_owner_callback(call)

    try:
        variant_id=int(call.data.split(":")[-1])
    except Exception:
        return await call.answer("Varian tidak valid.", show_alert=True)

    await state.update_data(stock_variant_id=variant_id)
    await state.set_state(OwnerState.stock_add_items)

    await safe_edit_or_answer(
        call,
        "➕ <b>TAMBAH AKUN</b>\n\n"
        "Kirim isi akun bebas format.\n"
        "Satu pesan = satu akun = satu stok.\n\n"
        "Boleh multi-baris dan tidak perlu tanda <code>|</code>.",
        reply_markup=back_owner("owner:back_products"),
        parse_mode="HTML"
    )
    await safe_callback_notice(call)


@router.callback_query(F.data.startswith("ownerdelete:"))
async def owner_delete_product_pick(call: CallbackQuery):
    if not is_owner(call.from_user.id):
        return await deny_owner_callback(call)

    try:
        product_id=int(call.data.split(":")[-1])
    except Exception:
        return await call.answer("Produk tidak valid.", show_alert=True)

    conn=db()
    product=conn.execute(
        "SELECT id,name FROM products WHERE id=? AND active=1",
        (product_id,)
    ).fetchone()
    conn.close()

    if not product:
        return await call.answer("Produk tidak ditemukan.", show_alert=True)

    await safe_edit_or_answer(
        call,
        "🗑️ <b>KONFIRMASI HAPUS PRODUK</b>\n\n"
        f"Produk: <b>{html.escape(product['name'])}</b>\n\n"
        "Produk akan disembunyikan dari toko. Riwayat transaksi lama tetap aman.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="✅ Ya, Hapus",
                callback_data=f"ownerdeleteconfirm:{product_id}"
            )],
            [InlineKeyboardButton(
                text="❌ Batal",
                callback_data="owner:delete_product"
            )]
        ]),
        parse_mode="HTML"
    )
    await safe_callback_notice(call)


@router.callback_query(F.data.startswith("ownerdeleteconfirm:"))
async def owner_delete_product_confirm(call: CallbackQuery):
    if not is_owner(call.from_user.id):
        return await deny_owner_callback(call)

    try:
        product_id=int(call.data.split(":")[-1])
    except Exception:
        return await call.answer("Produk tidak valid.", show_alert=True)

    try:
        conn=db()
        conn.execute("BEGIN IMMEDIATE")

        product=conn.execute(
            "SELECT id,name FROM products WHERE id=? AND active=1",
            (product_id,)
        ).fetchone()

        if not product:
            conn.rollback()
            conn.close()
            return await call.answer("Produk sudah tidak aktif.", show_alert=True)

        active_paid=conn.execute(
            """SELECT COUNT(*) AS n FROM orders
               WHERE product_id=?
                 AND payment_status='paid'
                 AND status NOT IN ('completed','cancelled')""",
            (product_id,)
        ).fetchone()["n"]

        if int(active_paid or 0)>0:
            conn.rollback()
            conn.close()
            return await call.answer(
                "Masih ada order paid yang belum selesai.",
                show_alert=True
            )

        conn.execute("UPDATE products SET active=0 WHERE id=?",(product_id,))
        conn.execute("UPDATE product_variants SET active=0 WHERE product_id=?",(product_id,))
        conn.commit()
        conn.close()

        await safe_edit_or_answer(
            call,
            "✅ <b>PRODUK DIHAPUS</b>\n\n"
            f"<b>{html.escape(product['name'])}</b> sudah disembunyikan dari toko.",
            reply_markup=owner_products_menu(),
            parse_mode="HTML"
        )
        await safe_callback_notice(call)
    except Exception as exc:
        await owner_product_error_view(call, "Hapus Produk", exc)


@router.callback_query()
async def stale_callback_recovery(call: CallbackQuery, state: FSMContext):
    """
    FINAL fallback for callbacks that truly have no current handler.

    IMPORTANT:
    This handler MUST stay after all specific callback handlers.
    Otherwise it will swallow valid owner/system callbacks.
    """
    data = call.data or ""

    admin_prefixes = (
        "owner:",
        "ownerstock:",
        "ownerresend:",
        "ownercancel:",
        "ownerdelete:",
        "ownerbtnname:",
        "proofapprove:",
        "proofreject:",
        "proofrejectreason:",
        "proofpending:",
        "topupverify:",
        "topuprejectreason:",
        "cleanup:",
        "dailyreport:",
    )

    if data.startswith(admin_prefixes):
        if not is_owner(call.from_user.id):
            return await deny_owner_callback(call)

        await state.clear()
        await safe_edit_or_answer(
            call,
            "⚠️ <b>TOMBOL SUDAH KEDALUWARSA</b>\n\n"
            "Tombol dari pesan lama sudah tidak digunakan.\n"
            "Buka kembali panel owner untuk mendapatkan tombol terbaru.",
            reply_markup=owner_menu(),
            parse_mode="HTML"
        )
        return await safe_callback_notice(call, "Buka panel terbaru.")

    if data in {"back", "menu", "main_menu", "start"}:
        await state.clear()
        await safe_edit_or_answer(
            call,
            f"🛍️ <b>{STORE_NAME}</b>\n\nSilakan pilih menu:",
            reply_markup=main_menu(),
            parse_mode="HTML"
        )
        return await safe_callback_notice(call)

    await call.answer(
        "Tombol ini sudah kedaluwarsa. Buka menu terbaru.",
        show_alert=True
    )


@router.message(F.text)
async def persistent_owner_price_recovery(message: Message, state: FSMContext):
    if not is_owner(message.from_user.id):
        return

    session=get_owner_input_session(message.from_user.id)
    if not session:
        return

    flow=session["flow"]
    payload=session["payload"]

    if flow not in {"product_custom_price","variant_custom_price"}:
        return

    price=parse_rupiah_input(message.text or "")
    if not price:
        return await message.answer(
            "❌ <b>HARGA TIDAK VALID</b>\n\n"
            "Kirim nominal seperti <code>2500</code>, <code>2.500</code>, "
            "<code>12.750</code>, atau <code>Rp18.750</code>.",
            parse_mode="HTML"
        )

    if price > 1_000_000_000:
        return await message.answer(
            "❌ Harga terlalu besar. Maksimal Rp1.000.000.000."
        )

    try:
        if flow=="product_custom_price":
            # Rebuild FSM data from persistent session, then use the normal creator.
            await state.update_data(
                product_name=payload.get("product_name",""),
                product_description=payload.get("product_description",""),
                product_variant_name=payload.get("product_variant_name",""),
            )
            result=await create_product_from_wizard(
                state,
                message.from_user.id,
                price
            )

            if not result:
                clear_owner_input_session(message.from_user.id)
                await state.clear()
                return await message.answer(
                    "❌ Data produk tidak lengkap. Silakan ulangi Tambah Produk.",
                    reply_markup=owner_products_menu()
                )

            product_id,_,name,variant_name,price=result
            clear_owner_input_session(message.from_user.id)

            return await message.answer(
                "✅ <b>PRODUK BERHASIL DIBUAT</b>\n\n"
                f"📦 {html.escape(name)}\n"
                f"🧩 {html.escape(variant_name)}\n"
                f"💰 {rupiah(price)}\n"
                "📊 Stok awal: <b>0</b>",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(
                        text="➕ Tambah Variasi Lagi",
                        callback_data=f"addvariantprod:{product_id}"
                    )],
                    [InlineKeyboardButton(
                        text="📦 Atur Stok",
                        callback_data="owner:set_stock"
                    )],
                    [InlineKeyboardButton(
                        text="⬅️ Produk & Stok",
                        callback_data="owner:back_products"
                    )]
                ]),
                parse_mode="HTML"
            )

        if flow=="variant_custom_price":
            await state.update_data(
                add_variant_product_id=int(payload.get("add_variant_product_id") or 0),
                add_variant_name=payload.get("add_variant_name",""),
            )
            result=await create_variant_from_wizard(state,price)

            if result=="duplicate":
                clear_owner_input_session(message.from_user.id)
                await state.clear()
                return await message.answer(
                    "❌ Variasi dengan nama yang sama sudah ada.",
                    reply_markup=owner_products_menu()
                )

            if not result:
                clear_owner_input_session(message.from_user.id)
                await state.clear()
                return await message.answer(
                    "❌ Data variasi tidak lengkap.",
                    reply_markup=owner_products_menu()
                )

            clear_owner_input_session(message.from_user.id)

            return await message.answer(
                "✅ <b>VARIASI BERHASIL DITAMBAHKAN</b>\n\n"
                f"📦 Produk: <b>{html.escape(result['product_name'])}</b>\n"
                f"🧩 Variasi: <b>{html.escape(result['variant_name'])}</b>\n"
                f"💰 Harga: <b>{rupiah(result['price'])}</b>\n"
                "📊 Stok awal: <b>0</b>",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(
                        text="➕ Tambah Variasi Lagi",
                        callback_data=f"addvariantprod:{result['product_id']}"
                    )],
                    [InlineKeyboardButton(
                        text="📦 Atur Stok",
                        callback_data="owner:set_stock"
                    )],
                    [InlineKeyboardButton(
                        text="⬅️ Produk & Stok",
                        callback_data="owner:back_products"
                    )]
                ]),
                parse_mode="HTML"
            )

    except Exception as exc:
        logging.exception("Persistent owner price recovery failed: %s", exc)
        clear_owner_input_session(message.from_user.id)
        await state.clear()
        return await message.answer(
            "❌ <b>GAGAL MEMPROSES HARGA</b>\n\n"
            f"<code>{html.escape(str(exc)[:400])}</code>",
            reply_markup=owner_products_menu(),
            parse_mode="HTML"
        )


@router.message(F.text)
async def owner_price_recovery(message: Message, state: FSMContext):
    if not is_owner(message.from_user.id):
        return

    if get_owner_input_session(message.from_user.id):
        return

    current_state=await state.get_state()
    if current_state:
        return

    text=(message.text or "").strip()
    if not text:
        return

    # If an owner sends a bare nominal after the price screen but the FSM was
    # unexpectedly lost, never leave the message unanswered.
    if parse_rupiah_input(text):
        return await message.answer(
            "⚠️ <b>SESI HARGA SUDAH TERPUTUS</b>\n\n"
            "Bot menerima nominal Anda, tetapi sesi Tambah Produk sudah tidak aktif.\n"
            "Silakan buka <b>➕ Tambah Produk</b> lagi agar data tidak tersimpan setengah.",
            reply_markup=owner_products_menu(),
            parse_mode="HTML"
        )


@router.message()
async def fallback(message: Message):
    text = (message.text or "").strip()

    if text.startswith("/"):
        command = text.split()[0].split("@")[0].lower()

        if command in {"/owner", "/ping"} and not is_owner(message.from_user.id):
            return await message.answer(
                "⛔ <b>AKSES DITOLAK</b>\n\n"
                "Command ini khusus owner.\n"
                "Gunakan /start untuk membuka menu toko.",
                parse_mode="HTML"
            )

        if is_owner(message.from_user.id):
            return await message.answer(
                "ℹ️ Command owner:\n"
                "/start — Menu utama\n"
                "/owner — Panel owner\n"
                "/ping — Status bot"
            )

        return await message.answer(
            "ℹ️ Command user:\n"
            "/start — Menu utama"
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
    await asyncio.sleep(20)
    try:
        results = await startup_recovery_audit(bot)

        if ADMIN_ID:
            try:
                await bot.send_message(
                    ADMIN_ID,
                    "♻️ <b>STARTUP RECOVERY</b>\n\n"
                    f"✅ Order recovered: <b>{results['recovered_orders']}</b>\n"
                    f"📦 Paid belum terkirim: <b>{results['pending_orders']}</b>\n"
                    f"📦 Inventory mismatch: <b>{results['inventory_mismatch']}</b>\n"
                    f"🧹 Inventory repaired: <b>{results['inventory_repaired']}</b>\n"
                    f"💰 Topup processing reset: <b>{results['processing_topups_reset']}</b>\n"
            f"📎 Proof session cleaned: <b>{results.get('proof_sessions_cleaned',0)}</b>\n"
            f"🛟 Safe Mode triggered: <b>{'YA' if results.get('safe_mode_triggered') else 'TIDAK'}</b>"
            "\n\n<i>Paid belum terkirim = pembayaran sudah diterima tetapi akun belum berhasil dikirim. Order ini tidak dihapus otomatis.</i>",
                    parse_mode="HTML"
                )
            except Exception:
                pass
    except Exception as exc:
        logging.exception("Startup recovery failed: %s", exc)
        set_safe_mode(True)
        await notify_owner_system_error(
            bot,
            "STARTUP_RECOVERY",
            str(exc),
            recovered=False
        )


async def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN belum diisi.")

    init_db()
    bot = Bot(BOT_TOKEN)
    dp = Dispatcher(
        storage=SQLiteFSMStorage(DB_PATH),
        events_isolation=SimpleEventIsolation(),
    )
    dp.callback_query.outer_middleware(CallbackTraceMiddleware())
    dp.include_router(router)

    # Railway web endpoint for health check + payment callback.
    runner = await start_web_server(bot)

    backup_task = asyncio.create_task(backup_loop(bot))
    cleanup_task = asyncio.create_task(cleanup_expired_orders(bot))
    asyncio.create_task(periodic_auto_recovery(bot))
    recovery_task = asyncio.create_task(silent_recovery_loop(bot))
    operations_task = asyncio.create_task(periodic_operations_loop(bot))

    try:
        await bot.delete_webhook(drop_pending_updates=False)
        await dp.start_polling(
            bot,
            allowed_updates=["message","callback_query"],
            polling_timeout=30,
            handle_as_tasks=True,
            tasks_concurrency_limit=32,
            backoff_config=BackoffConfig(
                min_delay=1.0,
                max_delay=8.0,
                factor=1.5,
                jitter=0.2
            ),
        )
    finally:
        backup_task.cancel()
        cleanup_task.cancel()
        recovery_task.cancel()
        operations_task.cancel()
        await runner.cleanup()
        try:
            await dp.storage.close()
        except Exception:
            pass


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
