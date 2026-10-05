import os
import sqlite3
import logging
import time
from datetime import datetime

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

    count = cur.execute("SELECT COUNT(*) AS n FROM products").fetchone()["n"]
    if count == 0:
        samples = [
            ("Canva Pro - Legal Invite", 25000, 10, "Akses melalui undangan/team resmi."),
            ("CapCut Pro - Voucher", 30000, 8, "Voucher/aktivasi legal sesuai kebijakan layanan."),
            ("Music Premium Voucher", 20000, 15, "Voucher digital resmi."),
            ("AI Subscription Voucher", 50000, 5, "Voucher/akses resmi."),
            ("Email Fresh", 5000, 20, "Produk digital sesuai kebutuhan toko."),
        ]
        cur.executemany(
            "INSERT INTO products(name, price, stock, description) VALUES(?,?,?,?)",
            samples
        )

    conn.commit()
    conn.close()


def rupiah(value: int) -> str:
    return f"Rp{value:,.0f}".replace(",", ".")


def is_owner(user_id: int) -> bool:
    return user_id == ADMIN_ID


# =========================
# FSM OWNER PANEL
# =========================
class OwnerState(StatesGroup):
    add_product = State()
    set_stock = State()
    set_price = State()
    delete_product = State()
    add_voucher = State()
    complete_order = State()


# =========================
# KEYBOARDS
# =========================
def main_menu():
    kb = InlineKeyboardBuilder()
    kb.button(text="🏷️ List Produk", callback_data="products")
    kb.button(text="🎁 Voucher", callback_data="voucher_info")
    kb.button(text="📁 Laporan Stok", callback_data="stock_report")
    kb.button(text="🧾 Pesanan Saya", callback_data="my_orders")
    kb.adjust(2, 2)
    return kb.as_markup()


def owner_menu():
    kb = InlineKeyboardBuilder()
    kb.button(text="➕ Tambah Produk", callback_data="owner:add_product")
    kb.button(text="📦 Atur Stok", callback_data="owner:set_stock")
    kb.button(text="💰 Atur Harga", callback_data="owner:set_price")
    kb.button(text="🗑️ Hapus Produk", callback_data="owner:delete_product")
    kb.button(text="🧾 Pesanan", callback_data="owner:orders")
    kb.button(text="✅ Selesaikan Order", callback_data="owner:complete_order")
    kb.button(text="🎁 Tambah Voucher", callback_data="owner:add_voucher")
    kb.button(text="📊 Statistik", callback_data="owner:stats")
    kb.button(text="🏠 Menu User", callback_data="home")
    kb.adjust(2, 2, 2, 2, 1)
    return kb.as_markup()


def product_keyboard():
    conn = db()
    rows = conn.execute(
        "SELECT id, name, stock FROM products WHERE active=1 ORDER BY id"
    ).fetchall()
    conn.close()

    kb = InlineKeyboardBuilder()
    for i, row in enumerate(rows, 1):
        kb.button(text=str(i), callback_data=f"product:{row['id']}")
    kb.adjust(5)
    kb.row(InlineKeyboardButton(text="⬅️ Menu Utama", callback_data="home"))
    return kb.as_markup()


def back_home():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Menu Utama", callback_data="home")]
    ])


def back_owner():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Panel Owner", callback_data="owner:panel")]
    ])


# =========================
# PUBLIC COMMANDS ONLY
# =========================
@router.message(Command("start"))
async def start(message: Message):
    text = (
        f"🛍️ <b>{STORE_NAME}</b>\n\n"
        "Selamat datang.\n"
        "Silakan pilih menu:\n\n"
        f"<i>{STORE_FOOTER}</i>"
    )
    await message.answer(text, reply_markup=main_menu(), parse_mode="HTML")


@router.message(Command("owner"))
async def owner(message: Message, state: FSMContext):
    await state.clear()

    if not is_owner(message.from_user.id):
        return await message.answer("⛔ Panel owner hanya dapat diakses pemilik bot.")

    await message.answer(
        f"🛠️ <b>PANEL OWNER • {STORE_NAME}</b>\n\n"
        "Kelola toko menggunakan tombol di bawah.\n"
        "Tidak perlu menghafal banyak command.\n\n"
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
        f"🟢 Status: <b>Online</b>\n"
        f"⏱️ Uptime: <b>{h}j {m}m {s}d</b>\n\n"
        f"<i>{STORE_FOOTER}</i>",
        parse_mode="HTML"
    )


# =========================
# USER CALLBACKS
# =========================
@router.callback_query(F.data == "home")
async def cb_home(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.edit_text(
        f"🛍️ <b>{STORE_NAME}</b>\n\n"
        "Selamat datang.\n"
        "Silakan pilih menu:\n\n"
        f"<i>{STORE_FOOTER}</i>",
        reply_markup=main_menu(),
        parse_mode="HTML"
    )
    await call.answer()


@router.callback_query(F.data == "products")
async def cb_products(call: CallbackQuery):
    conn = db()
    rows = conn.execute(
        "SELECT id, name, stock FROM products WHERE active=1 ORDER BY id"
    ).fetchall()
    conn.close()

    if not rows:
        text = f"📦 Belum ada produk aktif.\n\n<i>{STORE_FOOTER}</i>"
    else:
        lines = ["🏷️ <b>LIST PRODUK</b>\n"]
        for i, row in enumerate(rows, 1):
            status = f"{row['stock']}" if row["stock"] > 0 else "HABIS"
            lines.append(f"[{i}]. {row['name']} ({status})")
        lines.append(f"\nKlik nomor produk di bawah.\n\n<i>{STORE_FOOTER}</i>")
        text = "\n".join(lines)

    await call.message.edit_text(text, reply_markup=product_keyboard(), parse_mode="HTML")
    await call.answer()


@router.callback_query(F.data.startswith("product:"))
async def cb_product(call: CallbackQuery):
    product_id = int(call.data.split(":")[1])
    conn = db()
    row = conn.execute("SELECT * FROM products WHERE id=?", (product_id,)).fetchone()
    conn.close()

    if not row:
        return await call.answer("Produk tidak ditemukan.", show_alert=True)

    kb = InlineKeyboardBuilder()
    if row["stock"] > 0:
        kb.button(text="🛒 Pesan Sekarang", callback_data=f"buy:{row['id']}")
    kb.button(text="⬅️ Kembali", callback_data="products")
    kb.adjust(1)

    text = (
        f"📦 <b>{row['name']}</b>\n\n"
        f"💰 Harga: <b>{rupiah(row['price'])}</b>\n"
        f"📊 Stok: <b>{row['stock']}</b>\n\n"
        f"📝 {row['description'] or '-'}\n\n"
        f"<i>{STORE_FOOTER}</i>"
    )
    await call.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")
    await call.answer()


@router.callback_query(F.data.startswith("buy:"))
async def cb_buy(call: CallbackQuery, bot: Bot):
    product_id = int(call.data.split(":")[1])

    conn = db()
    product = conn.execute("SELECT * FROM products WHERE id=?", (product_id,)).fetchone()

    if not product or product["stock"] <= 0:
        conn.close()
        return await call.answer("Stok habis.", show_alert=True)

    cur = conn.execute(
        """
        INSERT INTO orders(user_id, username, product_id, qty, total, status, created_at)
        VALUES(?,?,?,?,?,?,?)
        """,
        (
            call.from_user.id,
            call.from_user.username or "",
            product_id,
            1,
            product["price"],
            "pending",
            datetime.now().isoformat(timespec="seconds")
        )
    )
    order_id = cur.lastrowid
    conn.commit()
    conn.close()

    invoice = f"MBY-{order_id:06d}"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💬 Hubungi Owner", url=f"https://t.me/{ADMIN_USERNAME}")],
        [InlineKeyboardButton(text="🧾 Pesanan Saya", callback_data="my_orders")],
        [InlineKeyboardButton(text="⬅️ Menu Utama", callback_data="home")]
    ])

    await call.message.edit_text(
        "✅ <b>ORDER BERHASIL DIBUAT</b>\n\n"
        f"🧾 Invoice: <b>{invoice}</b>\n"
        f"📦 Produk: {product['name']}\n"
        f"💰 Total: <b>{rupiah(product['price'])}</b>\n"
        "🟡 Status: <b>Menunggu Pembayaran</b>\n\n"
        f"Silakan hubungi @{ADMIN_USERNAME} untuk proses pembayaran.\n\n"
        f"<i>{STORE_FOOTER}</i>",
        reply_markup=kb,
        parse_mode="HTML"
    )

    if ADMIN_ID:
        try:
            username = f"@{call.from_user.username}" if call.from_user.username else str(call.from_user.id)
            await bot.send_message(
                ADMIN_ID,
                "🔔 <b>ORDER BARU</b>\n\n"
                f"🧾 Invoice: <b>{invoice}</b>\n"
                f"👤 User: {username}\n"
                f"📦 Produk: {product['name']}\n"
                f"💰 Total: {rupiah(product['price'])}\n\n"
                "Buka /owner → ✅ Selesaikan Order setelah pembayaran valid.",
                parse_mode="HTML"
            )
        except Exception:
            pass

    await call.answer("Order dibuat.")


@router.callback_query(F.data == "my_orders")
async def my_orders(call: CallbackQuery):
    conn = db()
    rows = conn.execute("""
        SELECT o.*, p.name AS product_name
        FROM orders o
        JOIN products p ON p.id=o.product_id
        WHERE o.user_id=?
        ORDER BY o.id DESC
        LIMIT 10
    """, (call.from_user.id,)).fetchall()
    conn.close()

    if not rows:
        text = f"🧾 <b>PESANAN SAYA</b>\n\nBelum ada pesanan.\n\n<i>{STORE_FOOTER}</i>"
    else:
        icons = {
            "pending": "🟡",
            "completed": "✅",
            "cancelled": "❌"
        }
        lines = ["🧾 <b>PESANAN SAYA</b>\n"]
        for row in rows:
            invoice = f"MBY-{row['id']:06d}"
            icon = icons.get(row["status"], "🔵")
            lines.append(
                f"{icon} <b>{invoice}</b>\n"
                f"   {row['product_name']} • {rupiah(row['total'])}\n"
                f"   Status: {row['status'].title()}\n"
            )
        lines.append(f"<i>{STORE_FOOTER}</i>")
        text = "\n".join(lines)

    await call.message.edit_text(text, reply_markup=back_home(), parse_mode="HTML")
    await call.answer()


@router.callback_query(F.data == "stock_report")
async def cb_stock(call: CallbackQuery):
    conn = db()
    rows = conn.execute(
        "SELECT name, stock FROM products WHERE active=1 ORDER BY id"
    ).fetchall()
    conn.close()

    lines = ["📁 <b>LAPORAN STOK</b>\n"]
    for row in rows:
        icon = "✅" if row["stock"] > 0 else "❌"
        lines.append(f"{icon} {row['name']}: <b>{row['stock']}</b>")
    lines.append(f"\n<i>{STORE_FOOTER}</i>")

    await call.message.edit_text("\n".join(lines), reply_markup=back_home(), parse_mode="HTML")
    await call.answer()


@router.callback_query(F.data == "voucher_info")
async def cb_voucher_info(call: CallbackQuery):
    await call.message.edit_text(
        "🎁 <b>VOUCHER</b>\n\n"
        "Voucher digunakan saat promo tertentu.\n"
        "Untuk penggunaan voucher, hubungi owner agar diskon dapat diverifikasi.\n\n"
        f"<i>{STORE_FOOTER}</i>",
        reply_markup=back_home(),
        parse_mode="HTML"
    )
    await call.answer()


# =========================
# OWNER CALLBACKS
# =========================
@router.callback_query(F.data == "owner:panel")
async def owner_panel_cb(call: CallbackQuery, state: FSMContext):
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


@router.callback_query(F.data == "owner:stats")
async def owner_stats(call: CallbackQuery):
    if not is_owner(call.from_user.id):
        return await call.answer("Akses ditolak.", show_alert=True)

    conn = db()
    products = conn.execute("SELECT COUNT(*) AS n FROM products WHERE active=1").fetchone()["n"]
    stock = conn.execute("SELECT COALESCE(SUM(stock),0) AS n FROM products WHERE active=1").fetchone()["n"]
    orders = conn.execute("SELECT COUNT(*) AS n FROM orders").fetchone()["n"]
    completed = conn.execute("SELECT COUNT(*) AS n FROM orders WHERE status='completed'").fetchone()["n"]
    revenue = conn.execute("SELECT COALESCE(SUM(total),0) AS n FROM orders WHERE status='completed'").fetchone()["n"]
    conn.close()

    await call.message.edit_text(
        "📊 <b>STATISTIK TOKO</b>\n\n"
        f"📦 Produk aktif: <b>{products}</b>\n"
        f"🧮 Total stok: <b>{stock}</b>\n"
        f"🧾 Total order: <b>{orders}</b>\n"
        f"✅ Order selesai: <b>{completed}</b>\n"
        f"💰 Omzet tercatat: <b>{rupiah(revenue)}</b>\n\n"
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
        SELECT o.*, p.name AS product_name
        FROM orders o
        JOIN products p ON p.id=o.product_id
        ORDER BY o.id DESC
        LIMIT 15
    """).fetchall()
    conn.close()

    if not rows:
        text = f"🧾 <b>PESANAN</b>\n\nBelum ada order.\n\n<i>{STORE_FOOTER}</i>"
    else:
        lines = ["🧾 <b>PESANAN TERBARU</b>\n"]
        for row in rows:
            invoice = f"MBY-{row['id']:06d}"
            user = f"@{row['username']}" if row["username"] else str(row["user_id"])
            lines.append(
                f"<b>{invoice}</b> • {row['status'].upper()}\n"
                f"👤 {user}\n"
                f"📦 {row['product_name']}\n"
                f"💰 {rupiah(row['total'])}\n"
            )
        lines.append(f"<i>{STORE_FOOTER}</i>")
        text = "\n".join(lines)

    await call.message.edit_text(text, reply_markup=back_owner(), parse_mode="HTML")
    await call.answer()


@router.callback_query(F.data == "owner:add_product")
async def owner_add_product(call: CallbackQuery, state: FSMContext):
    if not is_owner(call.from_user.id):
        return await call.answer("Akses ditolak.", show_alert=True)

    await state.set_state(OwnerState.add_product)
    await call.message.edit_text(
        "➕ <b>TAMBAH PRODUK</b>\n\n"
        "Kirim data dengan format:\n"
        "<code>Nama | Harga | Stok | Deskripsi</code>\n\n"
        "Contoh:\n"
        "<code>Canva Pro | 25000 | 10 | Invite legal</code>",
        reply_markup=back_owner(),
        parse_mode="HTML"
    )
    await call.answer()


@router.message(OwnerState.add_product)
async def owner_add_product_input(message: Message, state: FSMContext):
    if not is_owner(message.from_user.id):
        return

    parts = [p.strip() for p in message.text.split("|")]
    if len(parts) < 4:
        return await message.answer("❌ Format salah. Gunakan: Nama | Harga | Stok | Deskripsi")

    try:
        name, price, stock, desc = parts[0], int(parts[1]), int(parts[2]), parts[3]
        conn = db()
        conn.execute(
            "INSERT INTO products(name, price, stock, description) VALUES(?,?,?,?)",
            (name, price, stock, desc)
        )
        conn.commit()
        conn.close()
        await state.clear()
        await message.answer("✅ Produk berhasil ditambahkan.", reply_markup=owner_menu())
    except ValueError:
        await message.answer("❌ Harga dan stok harus berupa angka.")


@router.callback_query(F.data == "owner:set_stock")
async def owner_set_stock(call: CallbackQuery, state: FSMContext):
    if not is_owner(call.from_user.id):
        return await call.answer("Akses ditolak.", show_alert=True)

    await state.set_state(OwnerState.set_stock)
    await call.message.edit_text(
        "📦 <b>ATUR STOK</b>\n\nKirim:\n<code>ID PRODUK | STOK BARU</code>\n\nContoh:\n<code>1 | 25</code>",
        reply_markup=back_owner(),
        parse_mode="HTML"
    )
    await call.answer()


@router.message(OwnerState.set_stock)
async def owner_set_stock_input(message: Message, state: FSMContext):
    if not is_owner(message.from_user.id):
        return
    try:
        pid, stock = [x.strip() for x in message.text.split("|", 1)]
        conn = db()
        conn.execute("UPDATE products SET stock=? WHERE id=?", (int(stock), int(pid)))
        conn.commit()
        conn.close()
        await state.clear()
        await message.answer("✅ Stok berhasil diperbarui.", reply_markup=owner_menu())
    except Exception:
        await message.answer("❌ Format salah. Contoh: 1 | 25")


@router.callback_query(F.data == "owner:set_price")
async def owner_set_price(call: CallbackQuery, state: FSMContext):
    if not is_owner(call.from_user.id):
        return await call.answer("Akses ditolak.", show_alert=True)

    await state.set_state(OwnerState.set_price)
    await call.message.edit_text(
        "💰 <b>ATUR HARGA</b>\n\nKirim:\n<code>ID PRODUK | HARGA BARU</code>\n\nContoh:\n<code>1 | 30000</code>",
        reply_markup=back_owner(),
        parse_mode="HTML"
    )
    await call.answer()


@router.message(OwnerState.set_price)
async def owner_set_price_input(message: Message, state: FSMContext):
    if not is_owner(message.from_user.id):
        return
    try:
        pid, price = [x.strip() for x in message.text.split("|", 1)]
        conn = db()
        conn.execute("UPDATE products SET price=? WHERE id=?", (int(price), int(pid)))
        conn.commit()
        conn.close()
        await state.clear()
        await message.answer("✅ Harga berhasil diperbarui.", reply_markup=owner_menu())
    except Exception:
        await message.answer("❌ Format salah. Contoh: 1 | 30000")


@router.callback_query(F.data == "owner:delete_product")
async def owner_delete_product(call: CallbackQuery, state: FSMContext):
    if not is_owner(call.from_user.id):
        return await call.answer("Akses ditolak.", show_alert=True)

    await state.set_state(OwnerState.delete_product)
    await call.message.edit_text(
        "🗑️ <b>HAPUS PRODUK</b>\n\n"
        "Kirim ID produk yang ingin dinonaktifkan.\n"
        "Contoh: <code>3</code>",
        reply_markup=back_owner(),
        parse_mode="HTML"
    )
    await call.answer()


@router.message(OwnerState.delete_product)
async def owner_delete_product_input(message: Message, state: FSMContext):
    if not is_owner(message.from_user.id):
        return
    try:
        pid = int(message.text.strip())
        conn = db()
        conn.execute("UPDATE products SET active=0 WHERE id=?", (pid,))
        conn.commit()
        conn.close()
        await state.clear()
        await message.answer("✅ Produk berhasil dinonaktifkan.", reply_markup=owner_menu())
    except Exception:
        await message.answer("❌ ID produk tidak valid.")


@router.callback_query(F.data == "owner:add_voucher")
async def owner_add_voucher(call: CallbackQuery, state: FSMContext):
    if not is_owner(call.from_user.id):
        return await call.answer("Akses ditolak.", show_alert=True)

    await state.set_state(OwnerState.add_voucher)
    await call.message.edit_text(
        "🎁 <b>TAMBAH VOUCHER</b>\n\n"
        "Kirim:\n<code>KODE | DISKON</code>\n\n"
        "Contoh:\n<code>HEMAT10 | 10000</code>",
        reply_markup=back_owner(),
        parse_mode="HTML"
    )
    await call.answer()


@router.message(OwnerState.add_voucher)
async def owner_add_voucher_input(message: Message, state: FSMContext):
    if not is_owner(message.from_user.id):
        return
    try:
        code, discount = [x.strip() for x in message.text.split("|", 1)]
        conn = db()
        conn.execute(
            "INSERT INTO vouchers(code, discount) VALUES(?,?)",
            (code.upper(), int(discount))
        )
        conn.commit()
        conn.close()
        await state.clear()
        await message.answer("✅ Voucher berhasil dibuat.", reply_markup=owner_menu())
    except sqlite3.IntegrityError:
        await message.answer("❌ Kode voucher sudah ada.")
    except Exception:
        await message.answer("❌ Format salah. Contoh: HEMAT10 | 10000")


@router.callback_query(F.data == "owner:complete_order")
async def owner_complete_order(call: CallbackQuery, state: FSMContext):
    if not is_owner(call.from_user.id):
        return await call.answer("Akses ditolak.", show_alert=True)

    await state.set_state(OwnerState.complete_order)
    await call.message.edit_text(
        "✅ <b>SELESAIKAN ORDER</b>\n\n"
        "Kirim ID order atau nomor belakang invoice.\n"
        "Contoh untuk MBY-000001: <code>1</code>",
        reply_markup=back_owner(),
        parse_mode="HTML"
    )
    await call.answer()


@router.message(OwnerState.complete_order)
async def owner_complete_order_input(message: Message, state: FSMContext, bot: Bot):
    if not is_owner(message.from_user.id):
        return

    try:
        order_id = int(message.text.strip().replace("MBY-", ""))
        conn = db()
        order = conn.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()

        if not order:
            conn.close()
            return await message.answer("❌ Order tidak ditemukan.")

        if order["status"] == "completed":
            conn.close()
            await state.clear()
            return await message.answer("ℹ️ Order ini sudah selesai.", reply_markup=owner_menu())

        product = conn.execute("SELECT * FROM products WHERE id=?", (order["product_id"],)).fetchone()

        if not product or product["stock"] < order["qty"]:
            conn.close()
            return await message.answer("❌ Stok tidak cukup.")

        conn.execute(
            "UPDATE products SET stock=stock-? WHERE id=?",
            (order["qty"], order["product_id"])
        )
        conn.execute("UPDATE orders SET status='completed' WHERE id=?", (order_id,))
        conn.commit()
        conn.close()

        await state.clear()
        await message.answer(
            f"✅ Order MBY-{order_id:06d} selesai.\nStok otomatis berkurang.",
            reply_markup=owner_menu()
        )

        try:
            await bot.send_message(
                order["user_id"],
                "✅ <b>PEMBAYARAN BERHASIL</b>\n\n"
                f"🧾 Invoice: <b>MBY-{order_id:06d}</b>\n"
                "🟢 Status: <b>Selesai</b>\n\n"
                "Terima kasih telah berbelanja.\n\n"
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
            "ℹ️ Command yang tersedia:\n"
            "/start — Menu utama\n"
            "/owner — Panel pemilik\n"
            "/ping — Cek status bot"
        )


async def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN belum diisi di Railway Variables / .env")

    init_db()

    bot = Bot(BOT_TOKEN)
    dp = Dispatcher()
    dp.include_router(router)

    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
