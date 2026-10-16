"""Private payment-photo outbox; reads confirmed host payments, never moves money."""
import asyncio
import html
import io
import json
import logging
import math
import re
import secrets
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from aiogram.types import BufferedInputFile
from PIL import Image, ImageDraw, ImageFont

WIB = ZoneInfo("Asia/Jakarta")
SOURCES = ("order", "topup", "otp_payment", "otp_order", "sosmed", "qris_review")


def display_datetime(value):
    """Interpret historical naive Railway dates as UTC, only for display."""
    if value is None or isinstance(value, bool):
        return None
    try:
        if isinstance(value, datetime):
            result = value
        elif isinstance(value, (int, float)) or re.fullmatch(r"\d{10,13}(?:\.\d+)?", str(value).strip()):
            stamp = float(value)
            if not math.isfinite(stamp):
                return None
            if abs(stamp) >= 100_000_000_000:
                stamp /= 1000  # Provider timestamps can be milliseconds.
            result = datetime.fromtimestamp(stamp, timezone.utc)
        else:
            raw = str(value).strip()
            result = datetime.fromisoformat(raw[:-1]+"+00:00" if raw.endswith("Z") else raw)
        return result.replace(tzinfo=timezone.utc) if result.tzinfo is None else result
    except (ValueError, TypeError, OverflowError, OSError):
        return None


def format_wib(value, *, seconds=False, compact=False, missing="-"):
    result = display_datetime(value)
    if result is None:
        return missing
    pattern = "%d/%m/%Y • %H:%M" if compact else "%d-%m-%Y %H:%M"
    if seconds:
        pattern += ":%S"
    return result.astimezone(WIB).strftime(pattern+" WIB")


def public_text(value, limit=380):
    """Invoice labels contain no provider links, markup, OTP or login data."""
    value = re.sub(r"https?://\S+", "", str(value or ""), flags=re.I)
    value = re.sub(r"\b(?:smscode\s*\.\s*gg|buzzer\s*panel(?:\s*\.\s*id)?)\b", "", value, flags=re.I)
    return " ".join(value.split()).strip(" •|-/")[:limit] or "-"


def rupiah(value):
    return "Rp"+f"{int(value):,}".replace(",", ".")


def method_label(value):
    return {"QRIS_MANUAL": "QRIS", "AUTO_QRIS": "QRIS Otomatis",
            "KLIKQRIS_AUTO": "⚡ QRIS Otomatis",
            "QRIS": "QRIS", "BALANCE": "Saldo Bot", "SALDO": "Saldo Bot",
            "WALLET": "Saldo Bot", "BANK": "Transfer Bank", "TRANSFER": "Transfer Bank",
            "BANK_TRANSFER": "Transfer Bank",
            "SHOPEEPAY": "QRIS Otomatis"}.get(str(value or "").upper(), public_text(value, 80))


def font(size, bold=False):
    filename = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    for path in ("/usr/share/fonts/truetype/dejavu/"+filename, filename):
        try:
            return ImageFont.truetype(path, size=size)
        except OSError:
            pass
    return ImageFont.load_default(size=size)


def wrapped(draw, value, face, width):
    lines, current = [], ""
    for word in str(value).split():
        probe = (current+" "+word).strip()
        if draw.textlength(probe, font=face) <= width:
            current = probe
            continue
        if current:
            lines.append(current)
        current = ""
        for char in word:
            if current and draw.textlength(current+char, font=face) > width:
                lines.append(current)
                current = ""
            current += char
    if current:
        lines.append(current)
    return lines or ["-"]


def render_invoice(snapshot, *, simulation=False):
    """One layout for products, deposits, OTP and Sosmed; return a PNG in memory."""
    value = dict(snapshot)
    amount = int(value["amount"])
    if amount <= 0:
        raise ValueError("A successful payment must have a positive amount")
    title, label_face, face, small = font(42, True), font(24, True), font(25), font(21)
    probe = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    rows = [("Invoice", public_text(value["reference"], 90)),
            ("Pembayaran", public_text(value.get("category", "Pembelian"), 80)),
            ("Pelanggan", public_text(value.get("customer", "-"), 80)),
            ("Waktu", format_wib(value.get("paid_at"), seconds=True)),
            ("Layanan / Produk", public_text(value.get("item", "-"))),
            ("Jumlah", public_text(value.get("quantity", "1"), 60)),
            ("Metode", method_label(value.get("method")))]
    if value.get("variant"):
        rows.insert(5, ("Variasi", public_text(value["variant"], 180)))
    if value.get("subtotal"):
        rows.append(("Subtotal", rupiah(value["subtotal"])))
    if value.get("discount"):
        rows.append(("Diskon", "-"+rupiah(value["discount"])))
    if value.get("unique_code"):
        rows.append(("Kode unik", "+"+str(int(value["unique_code"]))))
    if value.get("qris_adjustment"):
        rows.append(("Biaya/penyesuaian QRIS", rupiah(value['qris_adjustment'])))
    if value.get("credit"):
        rows.append(("Saldo masuk", rupiah(value["credit"])))
    measured = [(label, wrapped(probe, data, face, 540)) for label, data in rows]
    detail_height = 88+sum(max(56, len(lines)*37+18) for _, lines in measured)
    total_y = 274+detail_height+24
    height = total_y+230
    img = Image.new("RGB", (1080, height), "#edf1f8")
    draw = ImageDraw.Draw(img)
    draw.rectangle((0, 0, 1080, 236), fill="#15223b")
    draw.rectangle((0, 236, 1080, 242), fill="#8158ef")
    draw.text((56, 38), "MABOYY DIGITAL", font=title, fill="white")
    draw.text((56, 103), "INVOICE PEMBAYARAN", font=font(29), fill="#c4cbda")
    draw.rounded_rectangle((56, 157, 390, 211), radius=16, fill="#16834c")
    draw.text((78, 167), "PEMBAYARAN BERHASIL", font=font(22, True), fill="white")
    if simulation:
        draw.rounded_rectangle((803, 49, 1022, 103), radius=14, fill="#fbbf24")
        draw.text((826, 61), "SIMULASI", font=font(25, True), fill="#15223b")
    draw.rounded_rectangle((48, 274, 1032, 274+detail_height), radius=23, fill="white")
    draw.text((76, 300), "RINGKASAN TRANSAKSI", font=font(26, True), fill="#15223b")
    y = 362
    for label, lines in measured:
        draw.text((76, y), label, font=label_face, fill="#64748b")
        for index, line in enumerate(lines):
            draw.text((438, y+index*37), line, font=face, fill="#15223b")
        y += max(56, len(lines)*37+18)
    draw.rounded_rectangle((48, total_y, 1032, total_y+108), radius=23, fill="#15223b")
    draw.text((76, total_y+37), "TOTAL DIBAYAR", font=font(26, True), fill="#c4cbda")
    total = rupiah(amount)
    total_face = font(40, True)
    draw.text((996-draw.textlength(total, font=total_face), total_y+28), total, font=total_face, fill="white")
    draw.text((56, total_y+135), "Terima kasih telah berbelanja di Maboyy Digital.", font=small, fill="#475569")
    footer = "CONTOH • DATA SIMULASI, BUKAN BUKTI PEMBAYARAN" if simulation else "Bukti pembayaran • Semua waktu dalam WIB"
    draw.text((56, total_y+173), footer, font=font(19, True), fill="#8158ef")
    output = io.BytesIO()
    img.save(output, "PNG", optimize=True)
    return output.getvalue()


def init_schema(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS payment_receipts(
        source TEXT NOT NULL,entity_id TEXT NOT NULL,user_id INTEGER NOT NULL,
        snapshot_json TEXT NOT NULL DEFAULT '{}',status TEXT NOT NULL DEFAULT 'PENDING',
        attempts INTEGER NOT NULL DEFAULT 0,next_retry_at REAL NOT NULL DEFAULT 0,
        lease_token TEXT,lease_until REAL NOT NULL DEFAULT 0,message_id INTEGER,sent_at REAL,
        error_code TEXT,created_at REAL NOT NULL,PRIMARY KEY(source,entity_id))""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_payment_receipts_queue ON payment_receipts(status,next_retry_at,lease_until)")
    conn.execute("CREATE TABLE IF NOT EXISTS payment_receipt_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL)")
    first = conn.execute("INSERT OR IGNORE INTO payment_receipt_meta VALUES('initialized','16.99')").rowcount
    if first:
        # Past transactions already had text confirmations. Do not flood buyers
        # with their history after deployment; unfinished deposits remain eligible.
        old = {
            "order": "SELECT id,user_id FROM orders WHERE payment_status='paid' AND invoice_sent=1",
            "topup": "SELECT id,user_id FROM topups WHERE status='completed'",
            "otp_payment": "SELECT payment_id,user_id FROM otp_payments WHERE paid_at IS NOT NULL",
            "otp_order": "SELECT id,buyer_user_id FROM otp_orders",
            "sosmed": "SELECT id,user_id FROM sosmed_orders",
        }
        for source, sql in old.items():
            conn.execute("""INSERT OR IGNORE INTO payment_receipts(source,entity_id,user_id,status,created_at)
                SELECT ?,CAST(id AS TEXT),user_id,'LEGACY',? FROM ("""+
                sql.replace("payment_id,user_id", "payment_id AS id,user_id").replace("id,buyer_user_id", "id,buyer_user_id AS user_id")+
                ")", (source, time.time()))


class ReceiptService:
    def __init__(self, host):
        self.host = host
        self._worker = None

    @staticmethod
    def candidates(source):
        # All selectors require durable confirmed payment state. Pending holds,
        # canceled invoices, failed purchases and unknown outcomes are excluded.
        return {
            "order": "SELECT o.id AS entity_id FROM orders o WHERE o.payment_status='paid' AND o.payment_method!='OWNER_FREE' AND COALESCE(NULLIF(o.payment_total,0),o.total)>0",
            "topup": "SELECT t.id AS entity_id FROM topups t WHERE t.status='completed' AND NOT EXISTS(SELECT 1 FROM otp_payments p WHERE p.topup_id=t.id)",
            "otp_payment": "SELECT p.payment_id AS entity_id FROM otp_payments p WHERE p.paid_at IS NOT NULL",
            "otp_order": "SELECT o.id AS entity_id FROM otp_orders o JOIN otp_purchase_attempts a ON a.attempt_id=o.attempt_id WHERE a.state='CAPTURED' AND NOT EXISTS(SELECT 1 FROM otp_payments p WHERE p.attempt_id=o.attempt_id AND p.paid_at IS NOT NULL)",
            "sosmed": "SELECT o.id AS entity_id FROM sosmed_orders o JOIN sosmed_purchase_attempts a ON a.attempt_id=o.attempt_id WHERE a.state='SUCCESS'",
            "qris_review": "SELECT t.id AS entity_id FROM klikqris_transactions t JOIN wallet_ledger w ON w.id=t.review_ledger_id WHERE t.state='SETTLED_BALANCE' AND t.sandbox=0 AND w.user_id=t.user_id AND w.amount=t.amount AND w.type='TOPUP' AND w.reference='AQ-REVIEW-'||t.id",
        }[source]

    @staticmethod
    def customer(conn, user, username=""):
        if not username:
            found = conn.execute("SELECT username FROM verified_users WHERE user_id=?", (user,)).fetchone()
            username = found[0] if found else ""
        if re.fullmatch(r"@?[A-Za-z0-9_]{3,32}", str(username or "")):
            return "@"+str(username).lstrip("@")
        return "User #"+str(int(user))

    def snapshot(self, conn, source, entity_id):
        eligible = conn.execute("SELECT 1 FROM ("+self.candidates(source)+") WHERE CAST(entity_id AS TEXT)=?", (str(entity_id),)).fetchone()
        if not eligible:
            return None
        if source == "order":
            row = dict(conn.execute("SELECT o.*,p.name AS product_name,v.name AS variant_name FROM orders o LEFT JOIN products p ON p.id=o.product_id LEFT JOIN product_variants v ON v.id=o.variant_id WHERE o.id=?", (entity_id,)).fetchone())
            user = row["user_id"]
            result = dict(reference=self.host.invoice(row["id"]), category="Produk Digital", item=row["product_name"] or "Produk Digital",
                variant=row["variant_name"], quantity=row["qty"], amount=row["payment_total"] or row["total"], subtotal=row["total"],
                discount=row["discount_amount"], unique_code=row["unique_code"], method=row["payment_method"],
                paid_at=row["payment_verified_at"] or row["completed_at"] or row["created_at"])
            result["customer"] = self.customer(conn, user, row["username"])
            if row['payment_method']=='KLIKQRIS_AUTO':
                result['qris_adjustment']=max(0,int(result['amount'])-int(row['total'])+int(row['discount_amount'] or 0))
        elif source == "topup":
            row = dict(conn.execute("SELECT * FROM topups WHERE id=?", (entity_id,)).fetchone())
            user = row["user_id"]
            result = dict(reference=self.host.topup_invoice(row["id"]), category="Isi Saldo", item="Saldo Bot • seluruh fitur",
                quantity=1, amount=row["payment_total"] or row["amount"], credit=row["amount"],
                unique_code=row["unique_code"], method=row["payment_method"], paid_at=row["verified_at"] or row["updated_at"] or row["created_at"])
            result["customer"] = self.customer(conn, user, row["username"])
            if row['payment_method']=='KLIKQRIS_AUTO':
                result['qris_adjustment']=max(0,int(result['amount'])-int(row['amount']))
        elif source == 'qris_review':
            row=dict(conn.execute('SELECT * FROM klikqris_transactions WHERE id=?',(entity_id,)).fetchone())
            user=row['user_id']
            result=dict(reference=self.host.topup_invoice(row['entity_id']) if row['purpose']=='topup' else self.host.invoice(row['entity_id']),
                category='Isi Saldo',item='Pembayaran QRIS dipindahkan ke saldo',quantity=1,
                amount=row['total_amount'],credit=row['amount'],qris_adjustment=row['total_amount']-row['amount'],
                method='KLIKQRIS_AUTO',paid_at=row['api_verified_at'])
        elif source == "otp_payment":
            row = dict(conn.execute("SELECT p.*,q.product FROM otp_payments p JOIN otp_quotes q ON q.quote_id=p.quote_id WHERE p.payment_id=?", (entity_id,)).fetchone())
            product = json.loads(row["product"])
            user = row["user_id"]
            result = dict(reference=row["partner_reference"], category="Nomor OTP", item=public_text(product.get("service_name") or product.get("platform_name") or "Nomor OTP"),
                variant=public_text(product.get("country_name", "")), quantity=1, amount=row["payment_total_idr"],
                subtotal=row["amount_idr"], unique_code=row["payment_total_idr"]-row["amount_idr"], method=row["method"], paid_at=row["paid_at"])
        elif source == "otp_order":
            row = dict(conn.execute("SELECT * FROM otp_orders WHERE id=?", (entity_id,)).fetchone())
            user = row["buyer_user_id"]
            result = dict(reference="OTP-"+str(row["provider_order_id"]), category="Nomor OTP", item=public_text(row["platform_name"]),
                variant=public_text(row["country_name"]), quantity=1, amount=row["selling_price_idr"], method="WALLET", paid_at=row["created_at"])
        else:
            row = dict(conn.execute("SELECT * FROM sosmed_orders WHERE id=?", (entity_id,)).fetchone())
            user = row["user_id"]
            result = dict(reference="SMM-"+str(row["id"]).zfill(6), category="Layanan Sosmed", item=public_text(row["service_name_snapshot"]),
                quantity=row["quantity"], amount=row["selling_price"], method="WALLET", paid_at=row["created_at"])
        if source not in {"order", "topup"}:
            result["customer"] = self.customer(conn, user)
        if int(user) <= 0 or int(result["amount"]) <= 0:
            raise ValueError("Invalid receipt identity/amount")
        result["user_id"] = int(user)
        # Never put raw provider response, credentials, OTP or wallet owner
        # balance in a receipt. Only these selected buyer-facing fields persist.
        return result

    def discover(self, limit=50):
        conn = self.host.db()
        try:
            conn.execute("BEGIN IMMEDIATE")
            count = 0
            for source in SOURCES:
                pending = conn.execute("SELECT c.entity_id FROM ("+self.candidates(source)+") c LEFT JOIN payment_receipts r ON r.source=? AND r.entity_id=CAST(c.entity_id AS TEXT) WHERE r.entity_id IS NULL LIMIT ?", (source, limit)).fetchall()
                for item in pending:
                    entity = str(item[0])
                    data = self.snapshot(conn, source, entity)
                    if data:
                        count += conn.execute("INSERT OR IGNORE INTO payment_receipts(source,entity_id,user_id,snapshot_json,created_at) VALUES(?,?,?,?,?)", (source, entity, data["user_id"], json.dumps(data, ensure_ascii=False), time.time())).rowcount
            conn.commit()
            return count
        finally:
            if conn.in_transaction:
                conn.rollback()
            conn.close()

    def enqueue(self, source, entity):
        if source not in SOURCES:
            return False
        conn = self.host.db()
        try:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute("SELECT 1 FROM payment_receipts WHERE source=? AND entity_id=?", (source, str(entity))).fetchone()
            if not existing:
                data = self.snapshot(conn, source, entity)
                if data is None:
                    return False
                conn.execute("INSERT INTO payment_receipts(source,entity_id,user_id,snapshot_json,created_at) VALUES(?,?,?,?,?)", (source, str(entity), data["user_id"], json.dumps(data, ensure_ascii=False), time.time()))
            conn.commit()
            return True
        finally:
            if conn.in_transaction:
                conn.rollback()
            conn.close()

    def claim(self, source, entity):
        now, token = time.time(), secrets.token_hex(16)
        conn = self.host.db()
        try:
            conn.execute("BEGIN IMMEDIATE")
            changed = conn.execute("""UPDATE payment_receipts SET status='SENDING',lease_token=?,lease_until=?,attempts=attempts+1
                WHERE source=? AND entity_id=? AND status IN ('PENDING','SENDING') AND next_retry_at<=? AND lease_until<=?""", (token, now+120, source, str(entity), now, now)).rowcount
            row = conn.execute("SELECT * FROM payment_receipts WHERE source=? AND entity_id=? AND lease_token=?", (source, str(entity), token)).fetchone() if changed else None
            conn.commit()
            return dict(row) if row else None
        finally:
            if conn.in_transaction:
                conn.rollback()
            conn.close()

    def finish(self, row, *, message_id=None, error=None, retry_after=0):
        conn = self.host.db()
        try:
            if error is None:
                changed = conn.execute("""UPDATE payment_receipts SET status='SENT',sent_at=?,message_id=?,lease_token=NULL,lease_until=0,error_code=NULL
                    WHERE source=? AND entity_id=? AND lease_token=?""", (time.time(), message_id, row["source"], row["entity_id"], row["lease_token"])).rowcount
                if changed and row["source"] == "order":
                    conn.execute("UPDATE orders SET invoice_sent=1 WHERE id=?", (row["entity_id"],))
            else:
                delay = max(float(retry_after or 0), min(3600, 10*2**min(row["attempts"], 8)))
                conn.execute("""UPDATE payment_receipts SET status=CASE WHEN status='UNKNOWN' THEN 'UNKNOWN' ELSE 'PENDING' END,
                    next_retry_at=?,lease_token=NULL,lease_until=0,error_code=CASE WHEN error_code='QRIS_EDIT' THEN error_code ELSE ? END
                    WHERE source=? AND entity_id=? AND lease_token=?""", (time.time()+delay, str(error)[:80], row["source"], row["entity_id"], row["lease_token"]))
            conn.commit()
        finally:
            conn.close()

    async def send_for(self, bot, source, entity):
        if not self.enqueue(source, entity):
            return False
        row = self.claim(source, entity)
        if row is None:
            return False  # Already sent, backed off, or another instance owns it.
        pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="invoice-photo")
        future = None
        try:
            data = json.loads(row["snapshot_json"])
            future = pool.submit(render_invoice, data)
            while not future.done():
                await asyncio.sleep(.01)
            photo = BufferedInputFile(future.result(), filename="Invoice_"+re.sub(r"[^A-Za-z0-9_-]", "_", data["reference"])+".png")
            caption = ("✅ <b>PEMBAYARAN BERHASIL</b>\n"
                       f"🧾 {html.escape(data['reference'])}\n"
                       f"💰 Total: <b>{rupiah(data['amount'])}</b>\n"
                       f"🕒 {format_wib(data['paid_at'], seconds=True)}")
            gateway = getattr(self.host, "KLIKQRIS_GATEWAY", None)
            linked = gateway.receipt_transaction(source, entity) if gateway is not None else None
            if linked:
                message = await asyncio.wait_for(gateway.deliver_receipt_photo(bot, row, photo, caption), timeout=40)
            else:
                message = await asyncio.wait_for(bot.send_photo(row["user_id"], photo, caption=caption, parse_mode="HTML"), timeout=40)
            message_id = getattr(message, "message_id", None)
            if not isinstance(message_id, int) or isinstance(message_id, bool) or message_id <= 0:
                raise ValueError("Photo delivery not acknowledged")
            self.finish(row, message_id=message_id)
            if linked:
                try:
                    await gateway.retire_paid_messages(bot, linked['id'])
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logging.warning("QRIS cleanup deferred type=%s", type(exc).__name__)
            return True
        except asyncio.CancelledError:
            self.finish(row, error="CANCELLED")
            raise
        except Exception as exc:
            self.finish(row, error=type(exc).__name__, retry_after=getattr(exc, "retry_after", 0))
            logging.warning("Invoice photo deferred source=%s entity=%s type=%s", source, entity, type(exc).__name__)
            return False
        finally:
            # No default asyncio executor; cancellation waits for the small PNG
            # render to release its memory before shutting down the worker.
            if future is not None:
                while not future.done():
                    await asyncio.sleep(.01)
            pool.shutdown(wait=False)

    async def run_once(self, bot):
        self.discover()
        conn = self.host.db()
        try:
            rows = conn.execute("""SELECT source,entity_id FROM payment_receipts
                WHERE status IN ('PENDING','SENDING') AND next_retry_at<=? AND lease_until<=?
                ORDER BY created_at LIMIT 20""", (time.time(), time.time())).fetchall()
        finally:
            conn.close()
        for row in rows:
            await self.send_for(bot, row["source"], row["entity_id"])

    async def worker(self, bot):
        while True:
            try:
                await self.run_once(bot)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logging.warning("Invoice worker deferred type=%s", type(exc).__name__)
            await asyncio.sleep(5)

    def start(self, bot):
        if self._worker is not None and not self._worker.done():
            return []
        self._worker = asyncio.create_task(self.worker(bot), name="payment-invoice-worker")
        return [self._worker]


async def notify(host, bot, source, entity):
    """A delivery failure never interrupts payment, fulfillment or other menus."""
    service = getattr(host, "PAYMENT_RECEIPTS", None)
    if service is None:
        return False
    try:
        return await service.send_for(bot, source, entity)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logging.warning("Invoice enqueue deferred source=%s type=%s", source, type(exc).__name__)
        return False


def queue(host, source, entity):
    """Commit an image job quickly; account delivery never waits for the photo."""
    service = getattr(host, "PAYMENT_RECEIPTS", None)
    if service is None:
        return False
    try:
        return service.enqueue(source, entity)
    except Exception as exc:
        logging.warning("Invoice enqueue deferred source=%s type=%s", source, type(exc).__name__)
        return False
