import os
import sqlite3
import logging
from datetime import datetime

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin").replace("@", "")
DB_PATH = "shop.db"

STORE_NAME = "Maboyy Digital"
STORE_SINCE = "Since 2020"
STORE_FOOTER = "Since 2020"

logging.basicConfig(level=logging.INFO)

router = Router()


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

    # Sample legal digital products. Edit/delete from admin commands as needed.
    count = cur.execute("SELECT COUNT(*) AS n FROM products").fetchone()["n"]
    if count == 0:
        samples = [
            ("Canva Pro - Legal Invite", 25000, 10, "Akses melalui undangan/team resmi."),
            ("CapCut Pro - Voucher", 30000, 8, "Voucher/aktivasi legal sesuai kebijakan layanan."),
            ("Music Premium Voucher", 20000, 15, "Voucher digital resmi."),
            ("AI Subscription Voucher", 50000, 5, "Voucher/akses resmi. Tidak menjual akun hasil pembajakan."),
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


# =========================
# KEYBOARDS
# =========================
def main_menu():
    kb = InlineKeyboardBuilder()
    kb.button(text="🏷️ List Produk", callback_data="products")
    kb.button(text="🎁 Voucher", callback_data="voucher")
    kb.button(text="📁 Laporan Stok", callback_data="stock_report")
    kb.adjust(2, 1)
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


# =========================
# USER COMMANDS
# =========================
@router.message(Command("start"))
async def start(message: Message):
    text = (
        "🛍️ <b>Maboyy Digital</b>\n<i>Premium Digital Shop • Since 2020</i>\n\n"
        "Selamat datang. Pilih menu di bawah untuk melihat produk, voucher, "
        "dan stok yang tersedia.\n\n"
        "✅ Tampilan simpel\n"
        "✅ Produk bernomor\n"
        "✅ Checkout mudah\n"
        "✅ Hubungi admin bila butuh bantuan\n\n"
        f"<i>{STORE_FOOTER}</i>"
    )
    await message.answer(text, reply_markup=main_menu(), parse_mode="HTML")


@router.message(Command("pm"))
async def pm_admin(message: Message):
    await message.answer(
        f"💬 Hubungi admin: https://t.me/{ADMIN_USERNAME}",
        disable_web_page_preview=True
    )


@router.message(Command("admin"))
async def admin_panel(message: Message):
    if message.from_user.id != ADMIN_ID:
        return await message.answer("⛔ Menu ini khusus owner/admin.")

    conn = db()
    product_count = conn.execute("SELECT COUNT(*) AS n FROM products").fetchone()["n"]
    stock = conn.execute("SELECT COALESCE(SUM(stock),0) AS n FROM products").fetchone()["n"]
    orders = conn.execute("SELECT COUNT(*) AS n FROM orders").fetchone()["n"]
    conn.close()

    await message.answer(
        f"🛠️ <b>PANEL ADMIN • {STORE_NAME}</b>\n<i>{STORE_SINCE}</i>\n\n"
        f"📦 Produk: {product_count}\n"
        f"🧾 Total stok: {stock}\n"
        f"🛒 Total order: {orders}\n\n"
        "<b>Perintah:</b>\n"
        "/addproduk Nama | Harga | Stok | Deskripsi\n"
        "/setstok ID JUMLAH\n"
        "/setharga ID HARGA\n"
        "/hapusproduk ID\n"
        "/orders\n"
        "/addvoucher KODE DISKON\n",
        parse_mode="HTML"
    )


# =========================
# CALLBACKS
# =========================
@router.callback_query(F.data == "home")
async def cb_home(call: CallbackQuery):
    await call.message.edit_text(
        "🛍️ <b>Maboyy Digital</b>\n<i>Premium Digital Shop • Since 2020</i>\n\nPilih menu:",
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
        text = "📦 Belum ada produk aktif."
    else:
        lines = ["🏷️ <b>LIST PRODUK</b>\n"]
        for i, row in enumerate(rows, 1):
            status = f"{row['stock']} stok" if row["stock"] > 0 else "HABIS"
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
        await call.answer("Produk tidak ditemukan.", show_alert=True)
        return

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
        await call.answer("Stok habis.", show_alert=True)
        return

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

    username = f"@{call.from_user.username}" if call.from_user.username else str(call.from_user.id)

    user_text = (
        f"✅ <b>ORDER DIBUAT</b>\n\n"
        f"🧾 Invoice: <b>#{order_id}</b>\n"
        f"📦 Produk: {product['name']}\n"
        f"💰 Total: <b>{rupiah(product['price'])}</b>\n"
        f"⏳ Status: Menunggu admin\n\n"
        f"Silakan hubungi @{ADMIN_USERNAME} untuk instruksi pembayaran.\n\n"
        f"<i>{STORE_FOOTER}</i>"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💬 Hubungi Admin", url=f"https://t.me/{ADMIN_USERNAME}")],
        [InlineKeyboardButton(text="⬅️ Menu Utama", callback_data="home")]
    ])

    await call.message.edit_text(user_text, reply_markup=kb, parse_mode="HTML")

    if ADMIN_ID:
        try:
            await bot.send_message(
                ADMIN_ID,
                "🔔 <b>ORDER BARU</b>\n\n"
                f"Invoice: #{order_id}\n"
                f"User: {username}\n"
                f"Produk: {product['name']}\n"
                f"Total: {rupiah(product['price'])}\n\n"
                f"Setelah pembayaran valid:\n"
                f"/selesai {order_id}",
                parse_mode="HTML"
            )
        except Exception:
            pass

    await call.answer("Order berhasil dibuat.")


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

    await call.message.edit_text(
        "\n".join(lines),
        reply_markup=back_home(),
        parse_mode="HTML"
    )
    await call.answer()


@router.callback_query(F.data == "voucher")
async def cb_voucher(call: CallbackQuery):
    await call.message.edit_text(
        "🎁 <b>VOUCHER</b>\n\n"
        "Masukkan voucher dengan format:\n"
        "<code>/voucher KODE</code>\n\n"
        f"Voucher yang valid akan menampilkan nilai diskonnya.\n\n<i>{STORE_FOOTER}</i>",
        reply_markup=back_home(),
        parse_mode="HTML"
    )
    await call.answer()


@router.message(Command("voucher"))
async def use_voucher(message: Message):
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        return await message.answer("Format: /voucher KODE")

    code = parts[1].strip().upper()
    conn = db()
    row = conn.execute(
        "SELECT * FROM vouchers WHERE code=? AND used=0", (code,)
    ).fetchone()
    conn.close()

    if not row:
        return await message.answer("❌ Voucher tidak ditemukan / sudah digunakan.")

    await message.answer(
        f"✅ Voucher <b>{code}</b> valid.\n"
        f"Diskon: <b>{rupiah(row['discount'])}</b>",
        parse_mode="HTML"
    )


# =========================
# ADMIN COMMANDS
# =========================
def is_admin(message: Message):
    return message.from_user.id == ADMIN_ID


@router.message(Command("addproduk"))
async def add_product(message: Message):
    if not is_admin(message):
        return

    raw = message.text.replace("/addproduk", "", 1).strip()
    parts = [p.strip() for p in raw.split("|")]

    if len(parts) < 4:
        return await message.answer(
            "Format:\n/addproduk Nama | Harga | Stok | Deskripsi"
        )

    name, price, stock, description = parts[0], int(parts[1]), int(parts[2]), parts[3]
    conn = db()
    conn.execute(
        "INSERT INTO products(name, price, stock, description) VALUES(?,?,?,?)",
        (name, price, stock, description)
    )
    conn.commit()
    conn.close()
    await message.answer("✅ Produk berhasil ditambahkan.")


@router.message(Command("setstok"))
async def set_stock(message: Message):
    if not is_admin(message):
        return

    try:
        _, product_id, stock = message.text.split()
        conn = db()
        conn.execute("UPDATE products SET stock=? WHERE id=?", (int(stock), int(product_id)))
        conn.commit()
        conn.close()
        await message.answer("✅ Stok diperbarui.")
    except Exception:
        await message.answer("Format: /setstok ID JUMLAH")


@router.message(Command("setharga"))
async def set_price(message: Message):
    if not is_admin(message):
        return

    try:
        _, product_id, price = message.text.split()
        conn = db()
        conn.execute("UPDATE products SET price=? WHERE id=?", (int(price), int(product_id)))
        conn.commit()
        conn.close()
        await message.answer("✅ Harga diperbarui.")
    except Exception:
        await message.answer("Format: /setharga ID HARGA")


@router.message(Command("hapusproduk"))
async def delete_product(message: Message):
    if not is_admin(message):
        return

    try:
        _, product_id = message.text.split()
        conn = db()
        conn.execute("UPDATE products SET active=0 WHERE id=?", (int(product_id),))
        conn.commit()
        conn.close()
        await message.answer("✅ Produk dinonaktifkan.")
    except Exception:
        await message.answer("Format: /hapusproduk ID")


@router.message(Command("addvoucher"))
async def add_voucher(message: Message):
    if not is_admin(message):
        return

    try:
        _, code, discount = message.text.split()
        conn = db()
        conn.execute(
            "INSERT INTO vouchers(code, discount) VALUES(?,?)",
            (code.upper(), int(discount))
        )
        conn.commit()
        conn.close()
        await message.answer("✅ Voucher berhasil dibuat.")
    except Exception:
        await message.answer("Format: /addvoucher KODE DISKON")


@router.message(Command("orders"))
async def orders(message: Message):
    if not is_admin(message):
        return

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
        return await message.answer("Belum ada order.")

    lines = ["🧾 <b>ORDER TERBARU</b>\n"]
    for row in rows:
        lines.append(
            f"#{row['id']} • {row['product_name']} • "
            f"{rupiah(row['total'])} • {row['status']}"
        )
    await message.answer("\n".join(lines), parse_mode="HTML")


@router.message(Command("selesai"))
async def complete_order(message: Message):
    if not is_admin(message):
        return

    try:
        _, order_id = message.text.split()
        conn = db()
        order = conn.execute("SELECT * FROM orders WHERE id=?", (int(order_id),)).fetchone()

        if not order:
            conn.close()
            return await message.answer("Order tidak ditemukan.")

        if order["status"] == "completed":
            conn.close()
            return await message.answer("Order sudah selesai.")

        product = conn.execute(
            "SELECT * FROM products WHERE id=?", (order["product_id"],)
        ).fetchone()

        if not product or product["stock"] < order["qty"]:
            conn.close()
            return await message.answer("Stok tidak cukup.")

        conn.execute(
            "UPDATE products SET stock=stock-? WHERE id=?",
            (order["qty"], order["product_id"])
        )
        conn.execute(
            "UPDATE orders SET status='completed' WHERE id=?",
            (int(order_id),)
        )
        conn.commit()
        conn.close()

        await message.answer(f"✅ Order #{order_id} selesai. Stok otomatis berkurang.")
    except Exception:
        await message.answer("Format: /selesai ID_ORDER")


async def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN belum diisi di file .env")

    init_db()
    bot = Bot(BOT_TOKEN)
    dp = Dispatcher()
    dp.include_router(router)

    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
