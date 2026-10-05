import os
import sqlite3
import logging
import time
import random
import json
import hashlib
import hmac
import base64
from datetime import datetime, timezone, timedelta

from aiohttp import web, ClientSession
from Crypto.PublicKey import RSA
from Crypto.Signature import pkcs1_15
from Crypto.Hash import SHA256

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
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

DB_PATH = "shop.db"
STORE_NAME = "Maboyy Produk Digital"
STORE_FOOTER = "Aplikasi Premium • Since 2020"

logging.basicConfig(level=logging.INFO)
router = Router()
START_TIME = time.time()


# =========================
# DATABASE
# =========================
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
        CREATE TABLE IF NOT EXISTS restock_subscriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            variant_id INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            UNIQUE(user_id, product_id, variant_id)
        )
    """)

    # migrations from previous versions
    add_column_if_missing(conn, "products", "sold", "INTEGER NOT NULL DEFAULT 0")
    add_column_if_missing(conn, "products", "rating", "REAL NOT NULL DEFAULT 0")
    add_column_if_missing(conn, "products", "rating_count", "INTEGER NOT NULL DEFAULT 0")
    add_column_if_missing(conn, "products", "is_popular", "INTEGER NOT NULL DEFAULT 0")
    add_column_if_missing(conn, "products", "is_flash_sale", "INTEGER NOT NULL DEFAULT 0")
    add_column_if_missing(conn, "orders", "variant_id", "INTEGER DEFAULT 0")
    add_column_if_missing(conn, "orders", "unit_price", "INTEGER NOT NULL DEFAULT 0")
    add_column_if_missing(conn, "orders", "payment_method", "TEXT DEFAULT 'QRIS'")
    add_column_if_missing(conn, "orders", "payment_status", "TEXT DEFAULT 'unpaid'")
    add_column_if_missing(conn, "orders", "note", "TEXT DEFAULT ''")
    add_column_if_missing(conn, "orders", "unique_code", "INTEGER NOT NULL DEFAULT 0")
    add_column_if_missing(conn, "orders", "payment_total", "INTEGER NOT NULL DEFAULT 0")
    add_column_if_missing(conn, "orders", "provider_reference", "TEXT DEFAULT ''")
    add_column_if_missing(conn, "orders", "provider_qr_url", "TEXT DEFAULT ''")

    # Default store settings (editable from /owner)
    defaults = {
        "qris_file_id": "",
        "payment_note": DEFAULT_PAYMENT_NOTE,
        "unique_code_enabled": "1",
        "unique_code_min": "1",
        "unique_code_max": "999",
        "payment_mode": "manual",
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
        "Silakan pilih menu:\n\n"
        f"<i>{STORE_FOOTER}</i>",
        reply_markup=main_menu(),
        parse_mode="HTML"
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
    order = conn.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
    if not order:
        conn.close()
        return False

    if order["status"] == "completed":
        conn.close()
        return True

    variant = conn.execute(
        "SELECT * FROM product_variants WHERE id=?",
        (order["variant_id"],)
    ).fetchone()

    if not variant or variant["stock"] < order["qty"]:
        conn.close()
        return False

    conn.execute(
        "UPDATE product_variants SET stock=stock-? WHERE id=?",
        (order["qty"], order["variant_id"])
    )
    conn.execute(
        "UPDATE products SET sold=sold+? WHERE id=?",
        (order["qty"], order["product_id"])
    )
    conn.execute(
        """UPDATE orders
           SET status='completed', payment_status='paid'
           WHERE id=?""",
        (order_id,)
    )
    conn.commit()
    conn.close()

    try:
        await bot.send_message(
            order["user_id"],
            "✅ <b>PEMBAYARAN OTOMATIS BERHASIL</b>\n\n"
            f"🧾 Invoice: <b>{invoice(order_id)}</b>\n"
            f"💵 Dibayar: <b>{rupiah(paid_amount or order['payment_total'] or order['total'])}</b>\n"
            "🟢 Status: <b>Selesai</b>\n\n"
            "Pembayaran telah dikonfirmasi otomatis.\n\n"
            f"<i>{STORE_FOOTER}</i>",
            parse_mode="HTML"
        )
    except Exception:
        pass
    return True


# =========================
# FSM
# =========================
class OwnerState(StatesGroup):
    add_product = State()
    add_variant = State()
    set_stock = State()
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


def owner_menu():
    kb = InlineKeyboardBuilder()
    kb.button(text="➕ Tambah Produk", callback_data="owner:add_product")
    kb.button(text="🧩 Tambah Variasi", callback_data="owner:add_variant")
    kb.button(text="📦 Atur Stok", callback_data="owner:set_stock")
    kb.button(text="💰 Atur Harga", callback_data="owner:set_price")
    kb.button(text="🗑️ Hapus Produk", callback_data="owner:delete_product")
    kb.button(text="🧾 Pesanan", callback_data="owner:orders")
    kb.button(text="✅ Verifikasi Bayar", callback_data="owner:complete_order")
    kb.button(text="🔥 Produk Populer", callback_data="owner:mark_popular")
    kb.button(text="⚡ Flash Sale", callback_data="owner:mark_flash")
    kb.button(text="🎁 Tambah Voucher", callback_data="owner:add_voucher")
    kb.button(text="💳 Pengaturan Pembayaran", callback_data="owner:qris_settings")
    kb.button(text="💰 Manajemen Saldo", callback_data="owner:wallet")
    kb.button(text="📊 Statistik", callback_data="owner:stats")
    kb.button(text="🏠 Menu User", callback_data="home")
    kb.adjust(2, 2, 2, 2, 2, 2, 2)
    return kb.as_markup()


def back_home():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Menu Utama", callback_data="home")]
    ])


def back_owner():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Panel Owner", callback_data="owner:panel")]
    ])



def wallet_menu():
    kb = InlineKeyboardBuilder()
    kb.button(text="➕ Top Up Saldo", callback_data="wallet:topup")
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
    kb.button(text="📑 Riwayat Saldo", callback_data="owner:wallet_history")
    kb.button(text="⬅️ Panel Owner", callback_data="owner:panel")
    kb.adjust(2, 2, 1)
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
    kb.button(text="⬅️ Panel Owner", callback_data="owner:panel")
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
        label = f"{row['name']} ({row['stock']})"
        kb.button(text=label, callback_data=f"variant:{row['id']}")
    kb.adjust(1)
    kb.row(InlineKeyboardButton(text="⬅️ Kembali", callback_data="products"))
    return kb.as_markup()


def qty_keyboard(variant_id, qty):
    kb = InlineKeyboardBuilder()
    kb.button(text="➖", callback_data=f"qty:{variant_id}:{max(1, qty-1)}")
    kb.button(text=f"{qty}", callback_data="noop")
    kb.button(text="➕", callback_data=f"qty:{variant_id}:{qty+1}")
    kb.button(text="🛒 Beli Sekarang", callback_data=f"confirm:{variant_id}:{qty}")
    kb.button(text="🔔 Notif Restock", callback_data=f"restock:{variant_id}")
    kb.button(text="⬅️ Kembali", callback_data=f"back_product:{variant_id}")
    kb.adjust(3, 1, 1, 1)
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
        f"• Sisa Produk : <b>{variant['stock']}</b>\n"
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

    await show_main_menu_message(message)


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
        await call.message.edit_text(
            "🔐 <b>VERIFIKASI CHANNEL</b>\n\n"
            f"Silakan join <b>{REQUIRED_CHANNEL_NAME}</b> terlebih dahulu.",
            reply_markup=join_required_keyboard(),
            parse_mode="HTML"
        )
        return await call.answer()

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

    await call.message.edit_text(
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
    product_id = int(call.data.split(":")[1])
    conn = db()
    product = conn.execute("SELECT * FROM products WHERE id=?", (product_id,)).fetchone()
    conn.close()

    if not product:
        return await call.answer("Produk tidak ditemukan.", show_alert=True)

    await call.message.edit_text(
        product_card(product) + "\n\nPilih variasi:",
        reply_markup=variants_keyboard(product_id),
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

    await call.message.edit_text(
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

    await call.message.edit_text(
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

    if variant["stock"] > 0 and qty > variant["stock"]:
        qty = variant["stock"]
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
async def confirm_order(call: CallbackQuery):
    _, variant_id, qty = call.data.split(":")
    variant_id, qty = int(variant_id), max(1, int(qty))

    conn = db()
    variant = conn.execute("SELECT * FROM product_variants WHERE id=?", (variant_id,)).fetchone()
    product = conn.execute("SELECT * FROM products WHERE id=?", (variant["product_id"],)).fetchone() if variant else None
    conn.close()

    if not variant or not product:
        return await call.answer("Produk tidak ditemukan.", show_alert=True)

    if variant["stock"] < qty:
        return await call.answer("Stok tidak mencukupi.", show_alert=True)

    unit = effective_unit_price(variant, qty)
    total = unit * qty

    kb = InlineKeyboardBuilder()
    kb.button(text="💳 Pilih Pembayaran", callback_data=f"payselect:{variant_id}:{qty}")
    kb.button(text="❌ Batal", callback_data=f"variant:{variant_id}")
    kb.adjust(1)

    await call.message.edit_text(
        "🧾 <b>Konfirmasi Pesanan</b>\n\n"
        f"Produk: <b>{product['name']}</b>\n"
        f"Variasi: <b>{variant['name']}</b>\n"
        f"Qty: <b>{qty}</b>\n"
        f"Harga/unit: <b>{rupiah(unit)}</b>\n"
        f"Total: <b>{rupiah(total)}</b>\n\n"
        "Catatan untuk penjual:\n"
        "(tidak ada)\n\n"
        f"<i>{STORE_FOOTER}</i>",
        reply_markup=kb.as_markup(),
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
async def process_wallet_order(call: CallbackQuery, bot: Bot):
    _, variant_id, qty = call.data.split(":")
    variant_id, qty = int(variant_id), max(1, int(qty))

    conn = db()
    variant = conn.execute(
        "SELECT * FROM product_variants WHERE id=?",
        (variant_id,)
    ).fetchone()
    product = conn.execute(
        "SELECT * FROM products WHERE id=?",
        (variant["product_id"],)
    ).fetchone() if variant else None

    if not variant or not product or variant["stock"] < qty:
        conn.close()
        return await call.answer("Stok tidak mencukupi.", show_alert=True)

    unit = effective_unit_price(variant, qty)
    total = unit * qty
    balance = get_balance(call.from_user.id)

    if balance < total:
        conn.close()
        return await call.answer(
            f"Saldo tidak cukup. Saldo Anda {rupiah(balance)}.",
            show_alert=True
        )

    cur = conn.execute(
        """INSERT INTO orders
           (user_id, username, product_id, variant_id, qty, unit_price, total,
            status, payment_method, payment_status, note, unique_code,
            payment_total, provider_reference, provider_qr_url, created_at)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            call.from_user.id,
            call.from_user.username or "",
            product["id"],
            variant_id,
            qty,
            unit,
            total,
            "pending",
            "WALLET",
            "unpaid",
            "",
            0,
            total,
            "",
            "",
            datetime.now().isoformat(timespec="seconds")
        )
    )
    order_id = cur.lastrowid
    conn.commit()
    conn.close()

    try:
        new_balance = wallet_change(
            call.from_user.id,
            -total,
            "PURCHASE",
            invoice(order_id),
            f"Pembelian {product['name']} - {variant['name']}"
        )
    except ValueError:
        return await call.answer("Saldo tidak mencukupi.", show_alert=True)

    # finalize order immediately
    ok = await mark_order_paid(order_id, bot, total)
    if not ok:
        # refund automatically if fulfillment failed
        wallet_change(
            call.from_user.id,
            total,
            "REFUND",
            f"REFUND-{invoice(order_id)}",
            "Refund otomatis karena order gagal diproses."
        )
        return await call.message.edit_text(
            "❌ Order gagal diproses. Saldo sudah dikembalikan otomatis.",
            reply_markup=back_home()
        )

    await call.message.edit_text(
        "✅ <b>PEMBAYARAN SALDO BERHASIL</b>\n\n"
        f"🧾 Invoice: <b>{invoice(order_id)}</b>\n"
        f"📦 Produk: {product['name']} — {variant['name']}\n"
        f"💰 Total: <b>{rupiah(total)}</b>\n"
        f"💳 Metode: <b>Saldo</b>\n"
        f"💵 Sisa saldo: <b>{rupiah(new_balance)}</b>\n\n"
        f"<i>{STORE_FOOTER}</i>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🧾 Pesanan Saya", callback_data="my_orders")],
            [InlineKeyboardButton(text="🏠 Menu Utama", callback_data="home")]
        ]),
        parse_mode="HTML"
    )
    await call.answer("Pembayaran berhasil.")


@router.callback_query(F.data.startswith("process:"))
async def process_order(call: CallbackQuery, bot: Bot):
    _, variant_id, qty = call.data.split(":")
    variant_id, qty = int(variant_id), max(1, int(qty))

    conn = db()
    variant = conn.execute("SELECT * FROM product_variants WHERE id=?", (variant_id,)).fetchone()
    product = conn.execute("SELECT * FROM products WHERE id=?", (variant["product_id"],)).fetchone() if variant else None

    if not variant or not product or variant["stock"] < qty:
        conn.close()
        return await call.answer("Stok tidak mencukupi.", show_alert=True)

    unit = effective_unit_price(variant, qty)
    total = unit * qty
    unique_code = unique_code_for_order()
    payment_total = total + unique_code

    cur = conn.execute(
        """INSERT INTO orders
           (user_id, username, product_id, variant_id, qty, unit_price, total,
            status, payment_method, payment_status, note, unique_code,
            payment_total, created_at)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
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
            "",
            unique_code,
            payment_total,
            datetime.now().isoformat(timespec="seconds")
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

    unique_text = (
        f"🔢 Kode unik: <b>+{unique_code}</b>\n"
        if unique_code > 0 else ""
    )

    payment_text = (
        "💳 <b>TRANSAKSI PENDING</b>\n\n"
        f"🧾 Invoice: <b>{inv}</b>\n"
        "💠 Pembayaran: <b>QRIS Pribadi</b>\n"
        f"📦 Produk: {product['name']} — {variant['name']}\n"
        f"🔢 Jumlah: <b>{qty}</b>\n"
        f"💰 Subtotal: <b>{rupiah(total)}</b>\n"
        f"{unique_text}"
        f"💵 <b>TOTAL TRANSFER: {rupiah(payment_total)}</b>\n\n"
        "⚠️ Transfer harus <b>sesuai total hingga kode unik</b> agar mudah dicocokkan.\n"
        f"📝 {payment_note}\n\n"
        "Setelah pembayaran, owner akan memverifikasi transaksi secara manual.\n\n"
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
            await bot.send_message(
                ADMIN_ID,
                "🔔 <b>ORDER BARU / MENUNGGU BAYAR</b>\n\n"
                f"🧾 {inv}\n"
                f"👤 {user}\n"
                f"📦 {product['name']} — {variant['name']}\n"
                f"🔢 Qty: {qty}\n"
                f"💰 Subtotal: {rupiah(total)}\n"
                f"🔢 Kode unik: +{unique_code}\n"
                f"💵 Transfer: {rupiah(payment_total)}\n\n"
                "Buka /owner → ✅ Verifikasi Bayar setelah pembayaran valid.",
                parse_mode="HTML"
            )
        except Exception:
            pass

    await call.answer("Pesanan dibuat.")



@router.callback_query(F.data.startswith("processauto:"))
async def process_auto_order(call: CallbackQuery, bot: Bot):
    if not shopeepay_ready():
        return await call.answer(
            "QRIS otomatis belum dikonfigurasi lengkap.",
            show_alert=True
        )

    _, variant_id, qty = call.data.split(":")
    variant_id, qty = int(variant_id), max(1, int(qty))

    conn = db()
    variant = conn.execute(
        "SELECT * FROM product_variants WHERE id=?",
        (variant_id,)
    ).fetchone()
    product = conn.execute(
        "SELECT * FROM products WHERE id=?",
        (variant["product_id"],)
    ).fetchone() if variant else None

    if not variant or not product or variant["stock"] < qty:
        conn.close()
        return await call.answer("Stok tidak mencukupi.", show_alert=True)

    unit = effective_unit_price(variant, qty)
    total = unit * qty

    cur = conn.execute(
        """INSERT INTO orders
           (user_id, username, product_id, variant_id, qty, unit_price, total,
            status, payment_method, payment_status, note, unique_code,
            payment_total, provider_reference, provider_qr_url, created_at)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            call.from_user.id,
            call.from_user.username or "",
            product["id"],
            variant_id,
            qty,
            unit,
            total,
            "pending",
            "SHOPEEPAY_MPM",
            "unpaid",
            "",
            0,
            total,
            "",
            "",
            datetime.now().isoformat(timespec="seconds")
        )
    )
    order_id = cur.lastrowid
    conn.commit()
    conn.close()

    try:
        qr = await shopeepay_generate_qr(order_id, total)
    except Exception as e:
        # Do not delete order; keep it for audit but mark failed.
        conn = db()
        conn.execute(
            "UPDATE orders SET status='payment_error', note=? WHERE id=?",
            (str(e)[:250], order_id)
        )
        conn.commit()
        conn.close()

        return await call.message.edit_text(
            "❌ <b>QRIS SHOPEEPAY BELUM BERHASIL DIBUAT</b>\n\n"
            "Pembayaran otomatis belum siap atau credential/API belum valid.\n"
            "Silakan kembali dan gunakan QRIS pribadi sementara.\n\n"
            f"<code>{str(e)[:180]}</code>",
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

    caption = (
        "⚡ <b>QRIS OTOMATIS</b>\n\n"
        f"🧾 Invoice: <b>{invoice(order_id)}</b>\n"
        f"📦 {product['name']} — {variant['name']}\n"
        f"🔢 Qty: <b>{qty}</b>\n"
        f"💵 Total: <b>{rupiah(total)}</b>\n\n"
        "QR ini dibuat khusus untuk transaksi ini.\n"
        "Setelah pembayaran sukses dan callback tervalidasi, status order akan berubah otomatis.\n\n"
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
            caption + "\n\nQR image URL tidak tersedia dari API.",
            reply_markup=kb,
            parse_mode="HTML"
        )

    if ADMIN_ID:
        try:
            await bot.send_message(
                ADMIN_ID,
                "⚡ <b>ORDER QRIS OTOMATIS</b>\n\n"
                f"🧾 {invoice(order_id)}\n"
                f"💰 {rupiah(total)}\n"
                f"🔗 Reference: <code>{qr['partner_reference']}</code>\n"
                "⏳ Menunggu callback pembayaran.",
                parse_mode="HTML"
            )
        except Exception:
            pass

    await call.answer("QR Payment Gateway berhasil dibuat.")


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
            icon = "✅" if row["status"] == "completed" else "🟡"
            lines.append(
                f"{icon} <b>{invoice(row['id'])}</b>\n"
                f"   {row['product_name']} — {row['variant_name'] or 'Standard'}\n"
                f"   Qty {row['qty']} • {rupiah(row['total'])}\n"
                f"   Status: {row['status'].title()}\n"
            )
        lines.append(f"<i>{STORE_FOOTER}</i>")
        text = "\n".join(lines)

    await call.message.edit_text(text, reply_markup=back_home(), parse_mode="HTML")
    await call.answer()


@router.callback_query(F.data == "stock_report")
async def stock_report(call: CallbackQuery):
    conn = db()
    rows = conn.execute("""
        SELECT p.name AS product_name, v.name AS variant_name, v.stock
        FROM product_variants v
        JOIN products p ON p.id=v.product_id
        WHERE p.active=1 AND v.active=1
        ORDER BY p.id, v.id
    """).fetchall()
    conn.close()

    lines = ["📁 <b>LAPORAN STOK</b>\n"]
    for row in rows:
        icon = "✅" if row["stock"] > 0 else "❌"
        lines.append(f"{icon} {row['product_name']} — {row['variant_name']}: <b>{row['stock']}</b>")
    lines.append(f"\n<i>{STORE_FOOTER}</i>")

    await call.message.edit_text("\n".join(lines), reply_markup=back_home(), parse_mode="HTML")
    await call.answer()


@router.callback_query(F.data == "voucher_info")
async def voucher_info(call: CallbackQuery):
    await call.message.edit_text(
        "🎁 <b>VOUCHER</b>\n\n"
        "Voucher promo dikelola owner dan dapat diterapkan sesuai program promo toko.\n\n"
        f"<i>{STORE_FOOTER}</i>",
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

    await call.message.edit_text(
        "💰 <b>SALDO KAMU</b>\n\n"
        f"Saldo tersedia: <b>{rupiah(balance)}</b>\n"
        f"Total top up: <b>{rupiah(topup_total)}</b>\n"
        f"Total digunakan: <b>{rupiah(spend_total)}</b>\n\n"
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
    await state.set_state(OwnerState.topup_amount)
    await call.message.edit_text(
        "➕ <b>TOP UP SALDO</b>\n\n"
        "Kirim nominal top up dalam angka.\n"
        "Contoh: <code>50000</code>\n\n"
        "Top up sementara menggunakan QRIS manual + kode unik.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Saldo Kamu", callback_data="wallet")]
        ]),
        parse_mode="HTML"
    )
    await call.answer()


@router.message(OwnerState.topup_amount)
async def wallet_topup_amount(message: Message, state: FSMContext, bot: Bot):
    try:
        amount = int((message.text or "").strip())
        if amount < 1000:
            raise ValueError
    except Exception:
        return await message.answer("❌ Minimal top up Rp1.000 dan harus berupa angka.")

    code = unique_code_for_order()
    payment_total = amount + code

    conn = db()
    cur = conn.execute(
        """INSERT INTO topups
           (user_id, username, amount, unique_code, payment_total, payment_method, status, created_at)
           VALUES(?,?,?,?,?,?,?,?)""",
        (
            message.from_user.id,
            message.from_user.username or "",
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

    await state.clear()

    qris_file_id = get_setting("qris_file_id", "")
    payment_note = get_setting("payment_note", DEFAULT_PAYMENT_NOTE)
    caption = (
        "➕ <b>TOP UP SALDO</b>\n\n"
        f"🧾 Invoice: <b>{topup_invoice(topup_id)}</b>\n"
        f"💰 Nominal saldo: <b>{rupiah(amount)}</b>\n"
        f"🔢 Kode unik: <b>+{code}</b>\n"
        f"💵 TOTAL TRANSFER: <b>{rupiah(payment_total)}</b>\n\n"
        "Transfer harus sesuai nominal sampai kode unik.\n"
        f"📝 {payment_note}\n\n"
        "Setelah pembayaran masuk, owner akan memverifikasi top up."
    )

    if qris_file_id:
        await bot.send_photo(
            message.from_user.id,
            qris_file_id,
            caption=caption,
            reply_markup=wallet_menu(),
            parse_mode="HTML"
        )
    else:
        await message.answer(
            caption + "\n\n⚠️ QRIS belum dipasang owner.",
            reply_markup=wallet_menu(),
            parse_mode="HTML"
        )

    if ADMIN_ID:
        try:
            user = f"@{message.from_user.username}" if message.from_user.username else str(message.from_user.id)
            await bot.send_message(
                ADMIN_ID,
                "💰 <b>TOP UP BARU</b>\n\n"
                f"🧾 {topup_invoice(topup_id)}\n"
                f"👤 {user}\n"
                f"💰 Saldo: {rupiah(amount)}\n"
                f"💵 Transfer: {rupiah(payment_total)}\n\n"
                "Buka /owner → 💰 Manajemen Saldo → ✅ Verifikasi Top Up.",
                parse_mode="HTML"
            )
        except Exception:
            pass



# =========================
# OWNER PANEL
# =========================
@router.callback_query(F.data == "owner:panel")
async def owner_panel(call: CallbackQuery, state: FSMContext):
    if not is_owner(call.from_user.id):
        return await call.answer("Akses ditolak.", show_alert=True)
    await state.clear()
    await call.message.edit_text(
        f"🛠️ <b>PANEL OWNER • {STORE_NAME}</b>\n\n"
        "Pilih pengaturan toko:\n\n"
        f"<i>{STORE_FOOTER}</i>",
        reply_markup=owner_menu(),
        parse_mode="HTML"
    )
    await call.answer()




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
    await state.set_state(OwnerState.owner_topup_verify)

    conn = db()
    rows = conn.execute(
        "SELECT * FROM topups WHERE status='pending' ORDER BY id DESC LIMIT 10"
    ).fetchall()
    conn.close()

    lines = ["✅ <b>VERIFIKASI TOP UP</b>\n"]
    if rows:
        for row in rows:
            user = f"@{row['username']}" if row["username"] else str(row["user_id"])
            lines.append(
                f"{topup_invoice(row['id'])} • {user}\n"
                f"Saldo {rupiah(row['amount'])} • Transfer {rupiah(row['payment_total'])}"
            )
        lines.append("\nKirim ID top up, contoh: <code>1</code>")
    else:
        lines.append("Tidak ada top up pending.")

    await call.message.edit_text(
        "\n\n".join(lines),
        reply_markup=back_owner(),
        parse_mode="HTML"
    )
    await call.answer()


@router.message(OwnerState.owner_topup_verify)
async def owner_wallet_verify_input(message: Message, state: FSMContext, bot: Bot):
    if not is_owner(message.from_user.id):
        return
    try:
        topup_id = int(message.text.strip().upper().replace("TOP-", ""))
    except Exception:
        return await message.answer("❌ ID top up tidak valid.")

    conn = db()
    row = conn.execute("SELECT * FROM topups WHERE id=?", (topup_id,)).fetchone()
    if not row:
        conn.close()
        return await message.answer("❌ Top up tidak ditemukan.")
    if row["status"] == "completed":
        conn.close()
        await state.clear()
        return await message.answer("ℹ️ Top up sudah pernah diverifikasi.", reply_markup=owner_wallet_menu())
    conn.close()

    balance = wallet_change(
        row["user_id"],
        row["amount"],
        "TOPUP",
        topup_invoice(topup_id),
        "Top up saldo terverifikasi."
    )

    conn = db()
    conn.execute("UPDATE topups SET status='completed' WHERE id=?", (topup_id,))
    conn.commit()
    conn.close()

    await state.clear()
    await message.answer(
        f"✅ {topup_invoice(topup_id)} selesai.\nSaldo user: {rupiah(balance)}",
        reply_markup=owner_wallet_menu()
    )

    try:
        await bot.send_message(
            row["user_id"],
            "✅ <b>TOP UP BERHASIL</b>\n\n"
            f"🧾 {topup_invoice(topup_id)}\n"
            f"💰 Saldo masuk: <b>{rupiah(row['amount'])}</b>\n"
            f"💵 Saldo sekarang: <b>{rupiah(balance)}</b>\n\n"
            f"<i>{STORE_FOOTER}</i>",
            parse_mode="HTML"
        )
    except Exception:
        pass


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


@router.callback_query(F.data == "owner:stats")
async def owner_stats(call: CallbackQuery):
    if not is_owner(call.from_user.id):
        return await call.answer("Akses ditolak.", show_alert=True)

    conn = db()
    products = conn.execute("SELECT COUNT(*) AS n FROM products WHERE active=1").fetchone()["n"]
    variants = conn.execute("SELECT COUNT(*) AS n FROM product_variants WHERE active=1").fetchone()["n"]
    stock = conn.execute("SELECT COALESCE(SUM(stock),0) AS n FROM product_variants WHERE active=1").fetchone()["n"]
    orders = conn.execute("SELECT COUNT(*) AS n FROM orders").fetchone()["n"]
    completed = conn.execute("SELECT COUNT(*) AS n FROM orders WHERE status='completed'").fetchone()["n"]
    revenue = conn.execute("SELECT COALESCE(SUM(total),0) AS n FROM orders WHERE status='completed'").fetchone()["n"]
    conn.close()

    await call.message.edit_text(
        "📊 <b>STATISTIK TOKO</b>\n\n"
        f"📦 Produk aktif: <b>{products}</b>\n"
        f"🧩 Variasi aktif: <b>{variants}</b>\n"
        f"🧮 Total stok: <b>{stock}</b>\n"
        f"🧾 Total order: <b>{orders}</b>\n"
        f"✅ Order selesai: <b>{completed}</b>\n"
        f"💰 Omzet: <b>{rupiah(revenue)}</b>\n\n"
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


@router.callback_query(F.data == "owner:set_stock")
async def owner_set_stock(call: CallbackQuery, state: FSMContext):
    await prompt_state(
        call, state, OwnerState.set_stock,
        "📦 <b>ATUR STOK VARIASI</b>\n\n"
        "Kirim:\n<code>ID VARIASI | STOK BARU</code>\n\nContoh: <code>1 | 100</code>"
    )


@router.message(OwnerState.set_stock)
async def owner_set_stock_input(message: Message, state: FSMContext, bot: Bot):
    if not is_owner(message.from_user.id):
        return
    try:
        vid, stock = [x.strip() for x in message.text.split("|", 1)]
        vid, stock = int(vid), int(stock)
        conn = db()
        variant = conn.execute("SELECT * FROM product_variants WHERE id=?", (vid,)).fetchone()
        old_stock = variant["stock"] if variant else 0
        conn.execute("UPDATE product_variants SET stock=? WHERE id=?", (stock, vid))
        conn.commit()

        subscribers = []
        if old_stock <= 0 and stock > 0 and variant:
            subscribers = conn.execute(
                "SELECT * FROM restock_subscriptions WHERE variant_id=?",
                (vid,)
            ).fetchall()
            conn.execute("DELETE FROM restock_subscriptions WHERE variant_id=?", (vid,))
            conn.commit()

        conn.close()
        await state.clear()
        await message.answer("✅ Stok berhasil diperbarui.", reply_markup=owner_menu())

        if subscribers:
            for sub in subscribers:
                try:
                    await bot.send_message(
                        sub["user_id"],
                        "🔔 <b>RESTOCK!</b>\n\n"
                        f"Variasi yang Anda tunggu sudah tersedia kembali.\n"
                        f"Stok sekarang: <b>{stock}</b>\n\n"
                        "Buka /start untuk membeli.",
                        parse_mode="HTML"
                    )
                except Exception:
                    pass
    except Exception:
        await message.answer("❌ Format salah. Contoh: 1 | 100")


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


@router.callback_query(F.data == "owner:delete_product")
async def owner_delete_product(call: CallbackQuery, state: FSMContext):
    await prompt_state(
        call, state, OwnerState.delete_product,
        "🗑️ <b>NONAKTIFKAN PRODUK</b>\n\nKirim ID produk.\nContoh: <code>3</code>"
    )


@router.message(OwnerState.delete_product)
async def owner_delete_product_input(message: Message, state: FSMContext):
    if not is_owner(message.from_user.id):
        return
    try:
        pid = int(message.text.strip())
        conn = db()
        conn.execute("UPDATE products SET active=0 WHERE id=?", (pid,))
        conn.execute("UPDATE product_variants SET active=0 WHERE product_id=?", (pid,))
        conn.commit()
        conn.close()
        await state.clear()
        await message.answer("✅ Produk dinonaktifkan.", reply_markup=owner_menu())
    except Exception:
        await message.answer("❌ ID produk tidak valid.")


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
    await prompt_state(
        call, state, OwnerState.add_voucher,
        "🎁 <b>TAMBAH VOUCHER</b>\n\nKirim:\n<code>KODE | DISKON</code>"
    )


@router.message(OwnerState.add_voucher)
async def owner_add_voucher_input(message: Message, state: FSMContext):
    if not is_owner(message.from_user.id):
        return
    try:
        code, discount = [x.strip() for x in message.text.split("|", 1)]
        conn = db()
        conn.execute("INSERT INTO vouchers(code, discount) VALUES(?,?)", (code.upper(), int(discount)))
        conn.commit()
        conn.close()
        await state.clear()
        await message.answer("✅ Voucher berhasil dibuat.", reply_markup=owner_menu())
    except sqlite3.IntegrityError:
        await message.answer("❌ Kode voucher sudah ada.")
    except Exception:
        await message.answer("❌ Format salah.")


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
        conn = db()
        order = conn.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()

        if not order:
            conn.close()
            return await message.answer("❌ Order tidak ditemukan.")

        if order["status"] == "completed":
            conn.close()
            await state.clear()
            return await message.answer("ℹ️ Order sudah selesai.", reply_markup=owner_menu())

        variant = conn.execute("SELECT * FROM product_variants WHERE id=?", (order["variant_id"],)).fetchone()
        if not variant or variant["stock"] < order["qty"]:
            conn.close()
            return await message.answer("❌ Stok variasi tidak cukup.")

        conn.execute(
            "UPDATE product_variants SET stock=stock-? WHERE id=?",
            (order["qty"], order["variant_id"])
        )
        conn.execute(
            "UPDATE products SET sold=sold+? WHERE id=?",
            (order["qty"], order["product_id"])
        )
        conn.execute(
            """UPDATE orders
               SET status='completed', payment_status='paid'
               WHERE id=?""",
            (order_id,)
        )
        conn.commit()
        conn.close()

        await state.clear()
        await message.answer(
            f"✅ {invoice(order_id)} berhasil diverifikasi.\n"
            "Stok otomatis berkurang dan angka terjual bertambah.",
            reply_markup=owner_menu()
        )

        try:
            await bot.send_message(
                order["user_id"],
                "✅ <b>PEMBAYARAN BERHASIL</b>\n\n"
                f"🧾 Invoice: <b>{invoice(order_id)}</b>\n"
                f"💵 Dibayar: <b>{rupiah(order['payment_total'] or order['total'])}</b>\n"
                "🟢 Status: <b>Selesai</b>\n\n"
                "Terima kasih telah berbelanja di Maboyy Produk Digital.\n\n"
                f"<i>{STORE_FOOTER}</i>",
                parse_mode="HTML"
            )
        except Exception:
            pass
    except Exception:
        await message.answer("❌ ID order tidak valid.")


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
        paid_amount = int(float(amount_value))
    except Exception:
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
        await mark_order_paid(order_id, bot, paid_amount)

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


async def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN belum diisi.")

    init_db()
    bot = Bot(BOT_TOKEN)
    dp = Dispatcher()
    dp.include_router(router)

    # Railway web endpoint for health check + Payment Gateway callback.
    runner = await start_web_server(bot)

    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    finally:
        await runner.cleanup()


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
