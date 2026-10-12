"""BuzzerPanel store core: additive SQLite tables and the existing wallet.

Request fields follow the owner's PHP/Node documentation for /api/json.php.
Response layouts follow the supplied official examples. Account currency and
pricing units must be read from the API or explicitly confirmed by the owner.
No non-idempotent order request is replayed. Ambiguous results retain the hold
for audited reconciliation. No undocumented cancellation action is sent.
"""
import asyncio
import hashlib
import html
import ipaddress
import json
import os
import re
import secrets
import sqlite3
import tempfile
import time
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_FLOOR
from urllib.parse import urlparse

import aiohttp

PREFIX = "sosmed:"
USER_BRAND = "MABOYY SOSMED STORE"
ADMIN_BRAND = "MABOYY SOSMED ADMIN"
TERMINAL = {"COMPLETED", "PARTIAL", "CANCELED", "FAILED"}
ACTIVE = {"PENDING", "PROCESSING", "IN_PROGRESS", "UNKNOWN"}
PAGE_SIZE = 8
CATALOG_PAGE_SIZE = 6
API_RESPONSE_BYTES = 8*1024*1024
CATALOG_RESPONSE_BYTES = 64*1024*1024
JSON_SPOOL_BYTES = 1024*1024
MAX_MONEY = 10**12


def encoded(value):
    def exact_decimal(item):
        if isinstance(item, Decimal):
            return str(item)
        raise TypeError("Unsupported JSON value")
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=exact_decimal)


def money(value):
    return "Rp" + f"{int(value):,}".replace(",", ".")


def escape(value):
    return html.escape(str(value or ""))


def number(value, low=0, high=MAX_MONEY, code="INPUT"):
    if isinstance(value, bool):
        raise StoreError(code)
    if isinstance(value, int):
        result = value
    elif isinstance(value, str) and re.fullmatch(r"[0-9]{1,16}", value.strip()):
        result = int(value.strip())
    else:
        raise StoreError(code)
    if not low <= result <= high:
        raise StoreError(code)
    return result


def decimal(value, low=0, high=MAX_MONEY):
    try:
        result = Decimal(str(value))
        if not result.is_finite() or not Decimal(low) <= result <= Decimal(high):
            raise ValueError
        if result.as_tuple().exponent < -6:
            raise ValueError
        return result
    except (InvalidOperation, ValueError, TypeError):
        raise StoreError("INPUT") from None


def catalog_integer(value, low=0, high=MAX_MONEY):
    """Catalogue-only integral numbers; wallet/checkout number() stays strict.

    JSON 100.0 and '100.00' are exact integral quantities. Localized grouping,
    fractional quantities and bools are not guessed into an order quantity.
    """
    if isinstance(value, bool) or value is None:
        raise StoreError('PROVIDER', detail='Nilai kosong/boolean tidak dapat menjadi bilangan bulat.')
    if isinstance(value, str):
        value = value.strip()
        # Repeated grouping separators/spaces are unambiguous counts; a single
        # dotted group remains ambiguous and must not change a charge by 1000x.
        if (re.fullmatch(r'[0-9]{1,3}(?:\.[0-9]{3}){2,}',value)
                or re.fullmatch(r'[0-9]{1,3}(?:,[0-9]{3}){2,}',value)):
            value = value.replace('.','').replace(',','')
        elif re.fullmatch(r'[0-9]{1,3}(?:[ \u00a0\u202f][0-9]{3})+',value):
            value = re.sub(r'[ \u00a0\u202f]','',value)
        if len(value)>64 or not re.fullmatch(r'[+-]?[0-9]+(?:\.[0-9]+)?(?:[eE][+-]?[0-9]{1,3})?', value):
            raise StoreError('PROVIDER', detail='Format angka tidak didukung; pemisah lokal atau teks tidak diasumsikan.')
        if re.fullmatch(r'[+-]?[0-9]{1,3}\.000', value):
            raise StoreError('PROVIDER', detail='Format bertitik ambigu: angka desimal atau pemisah ribuan belum diketahui.')
    elif not isinstance(value, (int, float, Decimal)):
        raise StoreError('PROVIDER', detail='Tipe nilai bukan angka.')
    try:
        result = Decimal(str(value))
        if not result.is_finite() or result != result.to_integral_value():
            raise StoreError('PROVIDER', detail='Nilai pecahan/nonfinite tidak dapat menjadi jumlah bulat.')
        if result<low or result>high:
            raise StoreError('PROVIDER', detail='Nilai negatif/nol atau melebihi batas jumlah yang didukung.')
        return int(result)
    except (InvalidOperation, ValueError, TypeError):
        raise StoreError('PROVIDER', detail='Nilai tidak dapat dibaca sebagai bilangan bulat.') from None


def catalog_value_label(value):
    # Owner diagnostics contain numeric evidence, never arbitrary API text.
    if value is None:
        return 'kosong'
    if isinstance(value, bool):
        return 'boolean'
    if isinstance(value, (int, float, Decimal)):
        return str(value)[:64]
    if isinstance(value, str) and len(value)<=64 and re.fullmatch(r'[0-9eE+., \t\r\n-]+', value):
        return value.strip()
    return 'format/tipe tidak didukung'


def flag(value):
    return value is True or value == 1 or (isinstance(value, str) and value.lower() in {"true", "yes", "1"})


def service_available(raw):
    # Missing status keeps the catalogue's existing availability contract.
    # An explicit inactive/unknown status must never be sold as active.
    values = [raw[key] for key in ('active', 'status') if key in raw]
    return all(flag(value) or (isinstance(value, str) and value.strip().casefold() in
               {'active', 'available', 'aktif', 'enabled'}) for value in values)


class StoreError(Exception):
    def __init__(self, code, message=None, *, uncertain=False, retry_after=0, detail="", stage=""):
        super().__init__(code)
        self.code, self.uncertain, self.retry_after = code, uncertain, retry_after
        # These are local, curated descriptions, never upstream response text.
        self.detail, self.stage = detail, stage
        messages = {
            "INPUT": "Input belum sesuai. Periksa kembali data pesanan.",
            "NOT_FOUND": "Layanan atau pesanan tidak ditemukan.",
            "FORBIDDEN": "Menu ini hanya untuk owner.",
            "TOKEN": "Tombol sudah kedaluwarsa. Buka /sosmed lagi.",
            "CONFIG": "Pengaturan pembelian belum lengkap. Hubungi owner.",
            "AUTH": "Koneksi toko belum dapat diautentikasi. Hubungi owner.",
            "IP_RESTRICTED": "Koneksi toko belum tersedia. Hubungi owner.",
            "API_DISABLED": "Koneksi toko belum tersedia. Hubungi owner.",
            "PROVIDER_BALANCE": "Layanan belum tersedia. Hubungi owner.",
            "REQUEST_SCHEMA": "Layanan belum tersedia. Hubungi owner.",
            "CLOSED": "Pembelian baru sedang ditutup oleh owner.",
            "USER_BALANCE": "Saldo kamu tidak cukup. Isi saldo melalui /start → Isi Saldo.",
            "CURRENCY": "Mata uang layanan belum didukung. Pembelian dihentikan sementara.",
            "NETWORK": "Layanan sedang mengalami gangguan koneksi. Coba kembali nanti.",
            "PROVIDER": "Layanan belum dapat memproses permintaan ini.",
            "RATE_LIMIT": "Permintaan terlalu cepat. Tunggu sebentar.",
            "UNKNOWN": "Hasil transaksi sedang diperiksa owner. Saldo ditahan; jangan membeli ulang.",
            "TYPE": "Tipe layanan ini belum tersedia untuk pembelian melalui bot.",
            "PRICE_CHANGED": "Harga atau ketentuan layanan berubah. Buat konfirmasi baru.",
            "QUOTE_EXPIRED": "Konfirmasi pembelian kedaluwarsa. Pilih layanan kembali.",
            "ACTIVE_LIMIT": "Batas pesanan aktif tercapai. Tunggu pesanan sebelumnya selesai.",
            "REFILL": "Refill belum tersedia untuk pesanan ini.",
            "CANCEL": "Pembatalan belum tersedia untuk pesanan ini.",
            "PROOF": "Bukti rekonsiliasi belum valid atau sudah digunakan.",
            "BELOW_COST": "Harga layanan perlu diperbarui owner.",
        }
        self.public = message or messages.get(code, "Layanan belum tersedia. Coba kembali nanti.")


@dataclass
class Config:
    token: str = ""
    secret: str = ""
    currency: str = ""
    rate_unit: str = ""
    url: str = "https://buzzerpanel.id/api/json.php"
    enabled: bool = False
    contract_verified: bool = False
    refill_verified: bool = False
    cancel_verified: bool = False
    mode: str = "percent"
    percent: str = "25"
    fixed: int = 0
    rounding: int = 100
    min_sale: int = 1000
    catalog_seconds: int = 600
    quote_ttl: int = 120
    poll_seconds: int = 120
    timeout: int = 30
    max_active: int = 5
    max_quantity: int = 10000000
    error: str = ""

    @classmethod
    def environment(cls):
        c = cls()
        variable = "BUZZERPANEL_CURRENCY"
        try:
            c.token = os.getenv("BUZZERPANEL_API_KEY", "").strip()
            c.secret = os.getenv("BUZZERPANEL_SECRET_KEY", "").strip()
            c.currency = os.getenv("BUZZERPANEL_CURRENCY", "").strip().upper()
            if c.currency not in {"", "IDR"}:
                raise ValueError
            variable = "SOSMED_RATE_UNIT"
            c.rate_unit = os.getenv("SOSMED_RATE_UNIT", "").strip()
            if c.rate_unit not in {"", "1000"}:
                raise ValueError
            variable = "BUZZERPANEL_API_URL"
            c.url = os.getenv("BUZZERPANEL_API_URL", c.url).strip().rstrip("/")
            if c.url != "https://buzzerpanel.id/api/json.php":
                raise ValueError("BUZZERPANEL_API_URL harus endpoint HTTPS resmi /api/json.php")
            for field, env in (("enabled", "SOSMED_ENABLED"),
                               ("contract_verified", "SOSMED_API_CONTRACT_VERIFIED"),
                               ("refill_verified", "SOSMED_REFILL_API_VERIFIED"),
                               ("cancel_verified", "SOSMED_CANCEL_API_VERIFIED")):
                variable = env
                value = os.getenv(env, "false").strip().lower()
                if value not in {"0", "1", "false", "true", "no", "yes"}:
                    raise ValueError
                setattr(c, field, value in {"1", "true", "yes"})
            variable = "SOSMED_MARKUP_MODE"
            c.mode = os.getenv(variable, "percent").strip().lower()
            c.mode = {"persen": "percent", "nominal": "fixed", "kombinasi": "combined"}.get(c.mode, c.mode)
            if c.mode not in {"percent", "fixed", "combined"}:
                raise ValueError
            variable = "SOSMED_MARKUP_PERCENT"
            c.percent = str(decimal(os.getenv("SOSMED_MARKUP_PERCENT", "25"), 0, 10000))
            for field, env, low, high in (
                ("fixed", "SOSMED_MARKUP_NOMINAL_IDR", 0, MAX_MONEY),
                ("rounding", "SOSMED_PRICE_ROUNDING_IDR", 0, 1000),
                ("min_sale", "SOSMED_MIN_SELLING_PRICE_IDR", 0, MAX_MONEY),
                ("catalog_seconds", "SOSMED_CATALOG_CACHE_SECONDS", 30, 86400),
                ("quote_ttl", "SOSMED_QUOTE_TTL_SECONDS", 15, 600),
                ("poll_seconds", "SOSMED_STATUS_POLL_SECONDS", 30, 3600),
                ("timeout", "SOSMED_HTTP_TIMEOUT_SECONDS", 3, 120),
                ("max_active", "SOSMED_MAX_ACTIVE_ORDERS_PER_USER", 1, 50),
                ("max_quantity", "SOSMED_MAX_QUANTITY", 1, 1000000000),
            ):
                variable = env
                setattr(c, field, number(os.getenv(env, str(getattr(c, field))), low, high))
            variable = "SOSMED_PRICE_ROUNDING_IDR"
            if c.rounding not in {0, 100, 500, 1000}:
                raise ValueError("Pembulatan harus 0, 100, 500 atau 1000")
        except (ValueError, StoreError):
            c.error, c.enabled = f"{variable} tidak valid", False
        return c


def init_schema(conn):
    statements = [
        """CREATE TABLE IF NOT EXISTS sosmed_settings(key TEXT PRIMARY KEY,value TEXT NOT NULL,updated_at REAL NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS sosmed_services(provider_service_id INTEGER PRIMARY KEY,name TEXT NOT NULL,
          category TEXT NOT NULL,type TEXT NOT NULL,provider_rate TEXT NOT NULL,currency TEXT NOT NULL,
          rate_unit TEXT NOT NULL,min_quantity INTEGER NOT NULL,max_quantity INTEGER NOT NULL,
          refill_supported INTEGER NOT NULL DEFAULT 0,cancel_supported INTEGER NOT NULL DEFAULT 0,
          dripfeed_supported INTEGER NOT NULL DEFAULT 0,description TEXT NOT NULL DEFAULT '',
          metadata_source TEXT NOT NULL DEFAULT '',last_synced_at REAL NOT NULL,enabled INTEGER NOT NULL DEFAULT 1,
          order_supported INTEGER NOT NULL DEFAULT 0,raw_catalog TEXT NOT NULL DEFAULT '{}')""",
        """CREATE TABLE IF NOT EXISTS sosmed_service_settings(scope TEXT NOT NULL,scope_key TEXT NOT NULL,
          enabled INTEGER NOT NULL CHECK(enabled IN(0,1)),PRIMARY KEY(scope,scope_key))""",
        """CREATE TABLE IF NOT EXISTS sosmed_metadata(service_id INTEGER PRIMARY KEY,description TEXT NOT NULL,
          source TEXT NOT NULL,updated_at REAL NOT NULL,actor INTEGER NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS sosmed_pricing_rules(scope TEXT NOT NULL,scope_key TEXT NOT NULL,
          rule TEXT NOT NULL,updated_at REAL NOT NULL,PRIMARY KEY(scope,scope_key))""",
        """CREATE TABLE IF NOT EXISTS sosmed_quotes(quote_id TEXT PRIMARY KEY,user_id INTEGER NOT NULL,
          service_id INTEGER NOT NULL,service_snapshot TEXT NOT NULL,target TEXT NOT NULL,quantity INTEGER NOT NULL,
          parameters TEXT NOT NULL,cost INTEGER NOT NULL CHECK(cost>=0),sale INTEGER NOT NULL CHECK(sale>0),
          price_snapshot TEXT NOT NULL,expires_at REAL NOT NULL,state TEXT NOT NULL DEFAULT 'OPEN',created_at REAL NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS sosmed_purchase_attempts(attempt_id TEXT PRIMARY KEY,quote_id TEXT NOT NULL UNIQUE,
          user_id INTEGER NOT NULL,state TEXT NOT NULL,request_body TEXT NOT NULL,request_hash TEXT NOT NULL,
          hold_amount INTEGER NOT NULL CHECK(hold_amount>0),provider_order_id INTEGER UNIQUE,
          reconciliation_status TEXT NOT NULL DEFAULT 'NONE',error_code TEXT NOT NULL DEFAULT '',
          created_at REAL NOT NULL,updated_at REAL NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS sosmed_orders(id INTEGER PRIMARY KEY AUTOINCREMENT,
          provider_order_id INTEGER NOT NULL UNIQUE,attempt_id TEXT NOT NULL UNIQUE,
          user_id INTEGER NOT NULL,service_id INTEGER NOT NULL,service_name_snapshot TEXT NOT NULL,
          category_snapshot TEXT NOT NULL,target TEXT NOT NULL,quantity INTEGER NOT NULL,
          form_parameters TEXT NOT NULL,provider_cost INTEGER NOT NULL CHECK(provider_cost>=0),
          selling_price INTEGER NOT NULL CHECK(selling_price>0),gross_profit INTEGER NOT NULL,currency TEXT NOT NULL,
          status TEXT NOT NULL,raw_provider_status TEXT NOT NULL,start_count INTEGER,remains INTEGER,
          provider_charge TEXT,refill_supported INTEGER NOT NULL,cancel_supported INTEGER NOT NULL,
          cancel_state TEXT NOT NULL DEFAULT 'NONE',refund_amount INTEGER NOT NULL DEFAULT 0,
          refund_state TEXT NOT NULL DEFAULT 'NONE',created_at REAL NOT NULL,updated_at REAL NOT NULL,
          next_poll_at REAL NOT NULL DEFAULT 0,terminal_at REAL)""",
        """CREATE TABLE IF NOT EXISTS sosmed_refills(id INTEGER PRIMARY KEY AUTOINCREMENT,order_id INTEGER NOT NULL,
          provider_refill_id INTEGER UNIQUE,status TEXT NOT NULL,created_at REAL NOT NULL,updated_at REAL NOT NULL,
          FOREIGN KEY(order_id) REFERENCES sosmed_orders(id))""",
        """CREATE TABLE IF NOT EXISTS sosmed_refunds(refund_id TEXT PRIMARY KEY,order_id INTEGER NOT NULL,
          wallet_transaction_id INTEGER,amount INTEGER NOT NULL,provider_amount INTEGER NOT NULL,
          proof_reference TEXT NOT NULL UNIQUE,status TEXT NOT NULL,created_at REAL NOT NULL,
          FOREIGN KEY(order_id) REFERENCES sosmed_orders(id))""",
        """CREATE TABLE IF NOT EXISTS sosmed_favorites(user_id INTEGER NOT NULL,service_id INTEGER NOT NULL,
          created_at REAL NOT NULL,PRIMARY KEY(user_id,service_id))""",
        """CREATE TABLE IF NOT EXISTS sosmed_callback_tokens(token TEXT PRIMARY KEY,user_id INTEGER NOT NULL,
          action TEXT NOT NULL,payload TEXT NOT NULL,expires_at REAL NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS sosmed_ui_sessions(user_id INTEGER PRIMARY KEY,message_id INTEGER NOT NULL DEFAULT 0,
          payload TEXT NOT NULL DEFAULT '{}',updated_at REAL NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS sosmed_rate_limits(user_id INTEGER NOT NULL,action TEXT NOT NULL,
          window REAL NOT NULL,count INTEGER NOT NULL,PRIMARY KEY(user_id,action))""",
        """CREATE TABLE IF NOT EXISTS sosmed_leases(name TEXT PRIMARY KEY,owner TEXT NOT NULL,until_at REAL NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS sosmed_reconciliation_proofs(proof_reference TEXT PRIMARY KEY,
          attempt_id TEXT NOT NULL UNIQUE,action TEXT NOT NULL,actor INTEGER NOT NULL,created_at REAL NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS sosmed_audit(id INTEGER PRIMARY KEY AUTOINCREMENT,actor INTEGER NOT NULL,
          action TEXT NOT NULL,payload TEXT NOT NULL,created_at REAL NOT NULL)""",
        "CREATE INDEX IF NOT EXISTS idx_sosmed_order_user ON sosmed_orders(user_id,created_at)",
        "CREATE INDEX IF NOT EXISTS idx_sosmed_order_poll ON sosmed_orders(status,next_poll_at)",
        "CREATE INDEX IF NOT EXISTS idx_sosmed_attempt_state ON sosmed_purchase_attempts(state)",
        "CREATE INDEX IF NOT EXISTS idx_sosmed_services_category ON sosmed_services(category,enabled)",
        "CREATE INDEX IF NOT EXISTS idx_sosmed_callback_expiry ON sosmed_callback_tokens(expires_at)",
    ]
    for statement in statements:
        conn.execute(statement)


class Repository:
    def __init__(self, host):
        self.host = host

    @contextmanager
    def connection(self, write=False):
        conn = self.host.db()
        conn.row_factory = sqlite3.Row
        try:
            if write:
                conn.execute("PRAGMA synchronous=FULL")
                conn.execute("BEGIN IMMEDIATE")
            yield conn
            if write:
                conn.commit()
        except BaseException:
            if write:
                conn.rollback()
            raise
        finally:
            conn.close()

    def one(self, sql, args=()):
        with self.connection() as conn:
            row = conn.execute(sql, args).fetchone()
            return dict(row) if row is not None else None

    def all(self, sql, args=()):
        with self.connection() as conn:
            return [dict(row) for row in conn.execute(sql, args).fetchall()]

    def order(self, user, order_id):
        row = self.one("SELECT * FROM sosmed_orders WHERE id=? AND user_id=?", (number(order_id, 1), user))
        if not row:
            raise StoreError("NOT_FOUND")
        row["internal_order_id"] = row["id"]
        return row

    def orders(self, user, page=0, history=False, admin=False):
        if admin and not self.host.is_owner(user):
            raise StoreError("FORBIDDEN")
        page = number(page, 0, 100000)
        terms, args = [], []
        if not admin:
            terms.append("user_id=?")
            args.append(user)
        if not history:
            terms.append("status NOT IN ('COMPLETED','PARTIAL','CANCELED','FAILED')")
        where = " WHERE " + " AND ".join(terms) if terms else ""
        total = self.one("SELECT COUNT(*) AS count FROM sosmed_orders" + where, args)["count"]
        return self.all("SELECT * FROM sosmed_orders" + where + " ORDER BY id DESC LIMIT ? OFFSET ?", (*args, PAGE_SIZE, page*PAGE_SIZE)), total

    def rate(self, user, action, count=10, seconds=60):
        now = time.time()
        with self.connection(True) as conn:
            row = conn.execute("SELECT * FROM sosmed_rate_limits WHERE user_id=? AND action=?", (user, action)).fetchone()
            fresh = not row or now-row["window"] >= seconds
            hits = 1 if fresh else row["count"]+1
            if hits > count:
                raise StoreError("RATE_LIMIT")
            conn.execute("INSERT OR REPLACE INTO sosmed_rate_limits VALUES(?,?,?,?)", (user, action, now if fresh else row["window"], hits))

    def audit(self, actor, action, payload):
        with self.connection(True) as conn:
            conn.execute("INSERT INTO sosmed_audit(actor,action,payload,created_at) VALUES(?,?,?,?)", (actor, action, encoded(payload), time.time()))

    def favorites(self, user):
        return self.all("SELECT s.* FROM sosmed_services s JOIN sosmed_favorites f ON f.service_id=s.provider_service_id WHERE f.user_id=? AND s.enabled=1 ORDER BY f.created_at DESC", (user,))

    def favorite(self, user, service_id):
        service_id = number(service_id, 1)
        with self.connection(True) as conn:
            if not conn.execute("SELECT 1 FROM sosmed_services WHERE provider_service_id=?", (service_id,)).fetchone():
                raise StoreError("NOT_FOUND")
            old = conn.execute("SELECT 1 FROM sosmed_favorites WHERE user_id=? AND service_id=?", (user, service_id)).fetchone()
            if old:
                conn.execute("DELETE FROM sosmed_favorites WHERE user_id=? AND service_id=?", (user, service_id))
            else:
                conn.execute("INSERT INTO sosmed_favorites VALUES(?,?,?)", (user, service_id, time.time()))
            return not bool(old)


class WalletAdapter:
    @staticmethod
    def change(conn, user, kind, amount, reference, note="Maboyy SOSMED"):
        if isinstance(amount, bool) or not isinstance(amount, int) or abs(amount)>MAX_MONEY:
            raise StoreError("INPUT")
        existing = conn.execute("SELECT id FROM wallet_ledger WHERE user_id=? AND type=? AND reference=?", (user, kind, reference)).fetchone()
        if existing:
            return False
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        conn.execute("INSERT OR IGNORE INTO wallets(user_id,balance,updated_at) VALUES(?,0,?)", (user, now))
        balance = conn.execute("SELECT balance FROM wallets WHERE user_id=?", (user,)).fetchone()[0] + amount
        if balance < 0:
            raise StoreError("USER_BALANCE")
        number(balance)
        conn.execute("UPDATE wallets SET balance=?,updated_at=? WHERE user_id=?", (balance, now, user))
        conn.execute("INSERT INTO wallet_ledger(user_id,type,amount,balance_after,reference,note,created_at) VALUES(?,?,?,?,?,?,?)", (user, kind, amount, balance, reference, note, now))
        return True


class APIClient:
    def __init__(self, config):
        self.config = config
        self.session = None
        self.contract_validator = None
        self.checked_at, self.last_ok, self.error, self.cooldown_until = 0, False, "", 0
        self.last_action, self.http_status, self.detail = "", None, ""

    @staticmethod
    def read_rejection(envelope):
        """Classify a failed read without reflecting account details or secrets."""
        containers = [envelope]
        if isinstance(envelope.get('data'), dict):
            containers.append(envelope['data'])
        hints = [str(item.get(key, '')).casefold() for item in containers
                 for key in ('code', 'error', 'message', 'msg') if isinstance(item.get(key), (str, int))]
        hint = ' '.join(hints)
        if (re.search(r'\bip\b|ip_address|ip_whitelist', hint)
                and any(word in hint for word in ('whitelist', 'allowlist', 'not allowed', 'tidak diizinkan', 'blocked', 'ditolak'))):
            return 'IP_RESTRICTED', 'Izin IP API ditolak. Cocokkan whitelist provider dengan IP keluar server Railway.'
        if (any(word in hint for word in ('api key', 'secret key', 'api_key', 'secret_key', 'authentication', 'unauthorized'))
                and any(word in hint for word in ('salah', 'invalid', 'wrong', 'tidak valid', 'not found', 'missing', 'kosong', 'unauthorized', 'failed'))):
            return 'AUTH', 'Autentikasi ditolak. Periksa API Key dan Secret Key dari akun yang sama.'
        if (any(word in hint for word in ('api', 'account', 'akun'))
                and any(word in hint for word in ('disabled', 'nonaktif', 'dinonaktifkan', 'suspended'))):
            return 'API_DISABLED', 'API atau akun dinonaktifkan oleh provider. Periksa pengaturan akun provider.'
        if any(word in hint for word in ('rate limit', 'too many requests', 'terlalu banyak permintaan')):
            return 'RATE_LIMIT', 'Batas request provider tercapai. Tunggu sebelum memeriksa kembali.'
        if any(word in hint for word in ('saldo tidak cukup', 'insufficient balance', 'not enough funds')):
            return 'PROVIDER_BALANCE', 'Saldo akun provider tidak cukup menurut API. Periksa/isi saldo akun BuzzerPanel, bukan wallet user bot.'
        if 'permintaan tidak sesuai' in hint or 'jumlah pesan tidak sesuai' in hint:
            return 'REQUEST_SCHEMA', 'API menolak format/parameter request. Cocokkan action profile/services dengan dokumentasi akun dan endpoint /api/json.php.'
        if 'layanan tidak ditemukan' in hint or 'layanan tidak tersedia' in hint:
            return 'PROVIDER', 'API menyatakan layanan tidak ditemukan/tersedia. Periksa katalog dan status layanan provider.'
        if 'pesanan tidak ditemukan' in hint:
            return 'NOT_FOUND', 'API belum menemukan ID pesanan/refill tersebut. Periksa ID provider; transaksi lokal tidak dihapus atau direfund otomatis.'
        return 'PROVIDER', 'API mengembalikan status gagal. Periksa izin akun dan respons profile/services pada panel provider.'

    @staticmethod
    def read_success(value):
        if type(value) is bool:
            return value
        if type(value) is int and value in (0, 1):
            return bool(value)
        if isinstance(value, str) and value.strip().casefold() in {'true', 'false', '1', '0'}:
            return value.strip().casefold() in {'true', '1'}
        return None

    @staticmethod
    async def response_json(response, wire_action, write, problem):
        limit = CATALOG_RESPONSE_BYTES if wire_action in {'services', 'services_1', 'services2', 'services3'} else API_RESPONSE_BYTES
        # Do not retain a list of chunks and another joined copy of a large
        # catalogue. The temporary file rolls onto disk and is always closed.
        try:
            with tempfile.SpooledTemporaryFile(max_size=JSON_SPOOL_BYTES, mode='w+b') as body:
                size = 0
                async for part in response.content.iter_chunked(65536):
                    size += len(part)
                    if size > limit:
                        raise problem(f'Respons melebihi batas {limit//(1024*1024)} MiB untuk {wire_action}.')
                    body.write(part)
                body.seek(0)
                if size <= JSON_SPOOL_BYTES:
                    return json.load(body, parse_float=Decimal)
                # Large JSON decoding is CPU work; it must not block incoming
                # Telegram updates. Cancellation waits for the decoder before
                # its file is closed, and never repeats an HTTP request.
                with ThreadPoolExecutor(max_workers=1, thread_name_prefix='sosmed-json') as executor:
                    job = executor.submit(json.load, body, parse_float=Decimal)
                    try:
                        while not job.done():
                            await asyncio.sleep(.01)
                    except asyncio.CancelledError:
                        # Keep the file alive until its reader exits, including
                        # shutdown; this executor belongs only to this decode.
                        while not job.done():
                            await asyncio.sleep(.01)
                        raise
                    return job.result()
        except (ValueError, UnicodeError):
            code = 'AUTH' if not write and response.status in {401, 403} else 'PROVIDER'
            raise problem('Respons bukan JSON. Periksa endpoint, izin API/IP, dan filter akses provider.', code) from None
        except OSError:
            raise problem('Penyimpanan sementara respons API tidak dapat dibaca. Periksa ruang penyimpanan server.') from None

    async def request(self, action, **parameters):
        if (not self.config.token or not self.config.secret or self.config.error
                or self.config.url != "https://buzzerpanel.id/api/json.php"):
            raise StoreError("CONFIG")
        if time.time() < self.cooldown_until:
            raise StoreError("RATE_LIMIT", retry_after=int(self.cooldown_until-time.time()))
        if action not in {"services", "services_1", "services2", "services3", "balance", "profile", "add", "order", "status", "refill", "refill_status", "status_refill"}:
            # There is no documented cancel endpoint. Never send one.
            raise StoreError("INPUT")
        if set(parameters) & {"key", "api_key", "secret_key", "action"}:
            raise StoreError("INPUT")
        wire_action = {"balance": "profile", "add": "order", "refill_status": "status_refill"}.get(action, action)
        self.last_action, self.http_status, self.detail = wire_action, None, ""
        write = wire_action in {"order", "refill"}
        catalog_read = wire_action in {'profile', 'services', 'services_1', 'services2', 'services3'}
        verified = (self.contract_validator() if self.contract_validator is not None
                    else self.config.contract_verified)
        if write and not verified:
            raise StoreError("CONFIG")
        if wire_action=="refill" and not self.config.refill_verified:
            raise StoreError("REFILL")
        wire_parameters = dict(parameters)
        if wire_action in {"status", "refill", "status_refill"}:
            source = "refill" if action=="refill_status" else "order"
            if source in wire_parameters:
                if "id" in wire_parameters:
                    raise StoreError("INPUT")
                wire_parameters["id"] = wire_parameters.pop(source)
            wire_parameters["id"] = number(wire_parameters.get("id"), 1)
            if set(wire_parameters)!={"id"}:
                raise StoreError("INPUT")
        if wire_action=="order":
            if "link" in wire_parameters:
                raise StoreError("INPUT")
            if not {"service", "data"}.issubset(wire_parameters):
                raise StoreError("INPUT")
            multiline = {"komen", "comments", "usernames"} & set(wire_parameters)
            if len(multiline)>1 or (not multiline and "quantity" not in wire_parameters):
                raise StoreError("INPUT")
            wire_parameters["service"] = number(wire_parameters["service"], 1)
            if not isinstance(wire_parameters["data"], str) or not wire_parameters["data"].strip():
                raise StoreError("INPUT")
            if not multiline:
                wire_parameters["quantity"] = number(wire_parameters["quantity"], 1, 1000000000)
            else:
                text = wire_parameters[next(iter(multiline))]
                if not isinstance(text, str) or not text.strip() or len(text)>20000 or "\x00" in text:
                    raise StoreError("INPUT")
            if set(wire_parameters)-{"service", "data", "quantity", "komen", "comments", "usernames", "username", "hashtags", "keywords"}:
                raise StoreError("INPUT")
        try:
            if self.session is None or self.session.closed:
                self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self.config.timeout), trust_env=True)
            form = {"api_key": self.config.token, "secret_key": self.config.secret, "action": wire_action, **wire_parameters}
            async with self.session.post(self.config.url, data=form, allow_redirects=False,
                                         headers={'Accept': 'application/json'}) as response:
                self.http_status = response.status
                def problem(detail, code='PROVIDER', *, retry_after=0):
                    return StoreError(code, uncertain=write, retry_after=retry_after,
                                      detail=f'{wire_action} • HTTP {response.status}: {detail}', stage=wire_action)
                if response.status == 429:
                    try:
                        delay = min(86400, max(1, int(response.headers.get("Retry-After", "60"))))
                    except (TypeError, ValueError):
                        delay = 60
                    self.cooldown_until = time.time()+delay
                    raise problem('Batas request tercapai. Tunggu sesuai Retry-After.', 'RATE_LIMIT', retry_after=delay)
                if response.status >= 500:
                    raise problem('Server provider mengalami gangguan. Coba kembali nanti.', 'NETWORK')
                if 300 <= response.status < 400:
                    raise problem('Endpoint mengalihkan request. Gunakan URL resmi /api/json.php; redirect API tidak diikuti.')
                envelope = await self.response_json(response, wire_action, write, problem)
                if not isinstance(envelope, dict):
                    raise problem('Respons harus berupa objek JSON dengan field status dan data.')
                if not write and response.status in {401, 403}:
                    code, detail = self.read_rejection(envelope)
                    raise problem(detail, code if code in {'IP_RESTRICTED', 'API_DISABLED'} else 'AUTH')
                if response.status!=200:
                    raise problem('Request HTTP ditolak; periksa endpoint dan konfigurasi API.')
                success = self.read_success(envelope.get('status')) if catalog_read else envelope.get('status')
                if type(success) is not bool:
                    raise problem('Field status tidak dikenali; diperlukan status true/false dan data.')
                if success is not True:
                    # The observed auth rejection belongs to a READ services
                    # request. No paid-order rejection semantics were supplied;
                    # never infer that an unsuccessful order envelope proves
                    # that the provider did not create/charge the order.
                    if not write:
                        code, detail = self.read_rejection(envelope)
                        if code=='RATE_LIMIT':
                            self.cooldown_until=time.time()+60
                        raise problem(detail, code, retry_after=60 if code=='RATE_LIMIT' else 0)
                    raise problem('Hasil order/refill belum pasti; perlu rekonsiliasi dan tidak dikirim ulang.')
                data = envelope.get("data")
                if wire_action in {"order", "refill"}:
                    if not isinstance(data, dict):
                        raise StoreError("PROVIDER", uncertain=True)
                    try:
                        ident = number(data.get("id"), 1, 10**12)
                    except StoreError:
                        raise StoreError("PROVIDER", uncertain=True) from None
                    data = {"order" if wire_action=="order" else "refill": ident}
                elif wire_action in {"services", "services_1", "services2", "services3"}:
                    if isinstance(data, dict) and 'services' in data:
                        data = data["services"]
                    if (isinstance(data, dict) and data and all(re.fullmatch(r'[0-9]+', key) for key in data)
                            and all(isinstance(row, dict) and ('service' in row or 'id' in row) for row in data.values())):
                        data = list(data.values())
                    if not isinstance(data, list):
                        raise problem('Data services bukan daftar layanan. Cocokkan bentuk respons services pada akun provider.')
                elif wire_action=='profile' and isinstance(data, list) and len(data)==1 and isinstance(data[0], dict):
                    data = data[0]
                elif not isinstance(data, dict):
                    raise problem('Data respons bukan objek yang dapat dibaca.')
                self.last_ok, self.error, self.checked_at = True, "", time.time()
                return data
        except (aiohttp.ClientError, asyncio.TimeoutError):
            self.last_ok, self.error, self.checked_at = False, "NETWORK", time.time()
            self.detail = wire_action+': koneksi/timeout gagal. Periksa akses keluar server ke API provider.'
            raise StoreError("NETWORK", uncertain=write, detail=self.detail, stage=wire_action) from None
        except StoreError as exc:
            self.last_ok, self.error, self.checked_at = False, exc.code, time.time()
            self.detail = exc.detail
            raise

    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()


class FormAdapter:
    """Input fields documented in the owner's PHP/Node examples.

    Response fields, account currency and pricing units still require runtime
    validation. No package, drip-feed, subscription or cancellation is inferred.
    """
    TYPES = {"default", "comment", "mentions custom list", "comment replies"}
    MULTILINE = {"comment", "mentions custom list", "comment replies"}

    @staticmethod
    def catalogue_type(raw, override=None):
        supplied = raw.get('type')
        if supplied is not None and not isinstance(supplied, str):
            raise StoreError('PROVIDER')
        supplied = (supplied or '').strip()
        aliases = {'default': 'Default', 'comment': 'Comment',
                   'mentions custom list': 'Mentions Custom List', 'mentionscustomlist': 'Mentions Custom List',
                   'comment replies': 'Comment Replies', 'commentreplies': 'Comment Replies'}
        if supplied and supplied.casefold() not in aliases:
            # A package/subscription/unknown explicit type cannot be forced
            # into a per-1,000 quantity form by an owner override.
            return supplied, 'API'
        if override in aliases.values():
            return override, 'OWNER'
        if supplied:
            return aliases[supplied.casefold()], 'API'
        native = {'id', 'name', 'price', 'min', 'max', 'category'}.issubset(raw) and 'service' not in raw and 'rate' not in raw
        text = ' '.join(str(raw.get(key, '')) for key in ('name','category','note','description')).casefold()
        special = re.search(r'comment|komentar|mention|repl(?:y|ies)|balasan|package|paket|subscription|poll|drip|hashtag|keyword|commentlike',text)
        if native and not special:
            # The supplied native documentation defines the standard request
            # as service + data + quantity even though services omits type.
            return 'Default', 'DOCUMENTED_STANDARD'
        return 'Unknown', 'UNVERIFIED'

    @staticmethod
    def target_kind(service):
        raw = service.get('raw_catalog', {})
        if isinstance(raw, str):
            try:raw=json.loads(raw)
            except ValueError:return 'any'
        note = str(raw.get('note','')) if isinstance(raw,dict) else ''
        username=bool(re.search(r'\b(?:input|masukkan)\s+username\b',note,re.I))
        url=bool(re.search(r'\b(?:input|masukkan)\s+(?:post\s+)?(?:url|link)\b',note,re.I))
        return 'username' if username and not url else 'url' if url and not username else 'any'

    @classmethod
    def target_for(cls, service, value):
        value=cls.target(value)
        kind=cls.target_kind(service)
        if kind=='username' and not re.fullmatch(r'@?[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}',value):
            raise StoreError('INPUT','Catatan layanan meminta username. Kirim username, bukan URL.')
        if kind=='url' and urlparse(value).scheme.lower() not in {'https','http'}:
            raise StoreError('INPUT','Catatan layanan meminta URL. Kirim link HTTP/HTTPS target.')
        return value

    @classmethod
    def target_prompt(cls, service):
        kind=cls.target_kind(service)
        return ('👤 Kirim username target sesuai catatan layanan.' if kind=='username' else
                '🔗 Kirim URL HTTP/HTTPS target sesuai catatan layanan.' if kind=='url' else
                '🔗 Kirim link atau username target sesuai layanan. Bot tidak membuka link ini.')

    @classmethod
    def supported(cls, service):
        kind = str(service.get("type", "")).strip().lower()
        if kind not in cls.TYPES:
            return False
        raw = service.get("raw_catalog", {})
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except ValueError:
                return False
        if not isinstance(raw, dict):
            return False
        required = raw.get("required_fields", raw.get("required_parameters", []))
        allowed = {"service", "data", "quantity", "api_key", "secret_key", "action"}
        allowed.update({"komen", "comments"} if kind in {"comment", "comment replies"} else {"usernames"} if kind=="mentions custom list" else set())
        if isinstance(required, str):
            required = [part.strip() for part in required.split(",") if part.strip()]
        if not isinstance(required, list) or any(not isinstance(field, str) or field not in allowed for field in required):
            return False
        for field in ("username", "hashtags", "keywords"):
            if flag(raw.get(field+"_required")):
                return False
        return True

    @classmethod
    def fields(cls, service, drip=False):
        if not cls.supported(service) or drip:
            raise StoreError("TYPE")
        kind = service["type"].strip().lower()
        return ["link", "quantity"] if kind=="default" else ["link", "usernames" if kind=="mentions custom list" else "comments"]

    @staticmethod
    def target(value):
        if not isinstance(value, str) or not 1 <= len(value) <= 2000:
            raise StoreError("INPUT")
        value = value.strip()
        # The supplied order documentation explicitly accepts URL OR username.
        if re.fullmatch(r"@?[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}", value):
            return value
        try:
            parsed = urlparse(value)
            host = parsed.hostname or ""
            if parsed.scheme not in {"https", "http"} or not host or parsed.username or parsed.password or any(c.isspace() for c in value):
                raise ValueError
            if host.lower() == "localhost" or host.lower().endswith((".localhost", ".local", ".internal")):
                raise ValueError
            try:
                address = ipaddress.ip_address(host)
            except ValueError:
                if "." not in host or not re.fullmatch(r"[A-Za-z0-9.-]+", host):
                    raise ValueError
            else:
                if not address.is_global:
                    raise ValueError
            if parsed.port and not 1 <= parsed.port <= 65535:
                raise ValueError
        except ValueError:
            raise StoreError("INPUT", "Masukkan link HTTP/HTTPS atau username sesuai layanan.") from None
        # No request is ever made to the user's target.
        return value

    @classmethod
    def validate(cls, service, parameters):
        if not cls.supported(service) or not isinstance(parameters, dict):
            raise StoreError("TYPE")
        kind = service["type"].strip().lower()
        target = cls.target_for(service, parameters.get("link"))
        body = {"service": number(service["provider_service_id"], 1), "data": target}
        if kind=="default":
            quantity = number(parameters.get("quantity"), 1, 1000000000)
            allowed = {"link", "quantity"}
        else:
            field = "usernames" if kind=="mentions custom list" else "comments"
            text = parameters.get(field)
            if not isinstance(text, str) or len(text)>20000 or "\x00" in text:
                raise StoreError("INPUT")
            # PHP normalizes CRLF and derives quantity from valid nonblank
            # lines for ALL three documented multiline types.
            lines = [line for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n") if line.strip()]
            if not lines or any(len(line)>2000 for line in lines):
                raise StoreError("INPUT", "Masukkan minimal satu baris valid.")
            if field=="usernames" and any(not re.fullmatch(r"@?[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}", line.strip()) for line in lines):
                raise StoreError("INPUT", "Masukkan satu username valid per baris.")
            quantity = len(lines)
            outgoing = "komen" if kind=="comment" else field
            body[outgoing] = "\n".join(lines)
            allowed = {"link", field}
        if kind=="default":
            body["quantity"] = quantity
        if not service["min_quantity"] <= quantity <= service["max_quantity"]:
            raise StoreError("INPUT", f"Jumlah harus antara {service['min_quantity']} dan {service['max_quantity']}.")
        if set(parameters)-allowed:
            raise StoreError("INPUT")
        return {"body": body, "quantity": quantity, "target": target, "parameters": dict(parameters)}

    @classmethod
    def instructions(cls, service):
        kind = str(service.get("type", "")).strip().lower()
        if kind=="mentions custom list":
            return "Kirim target layanan, lalu satu username per baris. Jumlah dihitung dari baris valid."
        if kind in {"comment", "comment replies"}:
            return "Kirim target layanan, lalu komentar asli: satu komentar per baris. Jumlah dihitung dari baris valid."
        if kind=="default":
            return cls.target_prompt(service)+" Lalu kirim jumlah sesuai min/max."
        return "Tipe ini belum tersedia untuk pemesanan melalui bot."


class CatalogService:
    def __init__(self, store):
        self.store = store
        self.lock = asyncio.Lock()
        self.last_profile = None
        self.last_profile_fingerprint = ''
        self.profile_checked_at = 0
        self.failure_stage = 'profile'

    def diagnostics(self):
        row = self.store.repo.one("SELECT value FROM sosmed_settings WHERE key='catalog_diagnostics'")
        try:
            report = json.loads(row['value']) if row else {}
            return report if isinstance(report,dict) and report.get('fingerprint') == self.store.contract_fingerprint() else {}
        except (ValueError,TypeError):
            return {}

    @staticmethod
    def duplicate_signature(service):
        fields = ('name','category','type','currency','rate_unit','min_quantity','max_quantity',
                  'refill_supported','dripfeed_supported','description','enabled','order_supported')
        return (tuple(service[field] for field in fields),Decimal(service['provider_rate']),FormAdapter.target_kind(service))

    async def sync(self, force=False, return_rows=True):
        async with self.lock:
            synced = self.store.repo.one("SELECT MAX(last_synced_at) AS stamp FROM sosmed_services")
            if not force and synced and synced["stamp"] and time.time()-synced["stamp"]<self.store.settings()["catalog_seconds"]:
                return self.store.repo.all("SELECT * FROM sosmed_services ORDER BY category,provider_service_id") if return_rows else None
            self.failure_stage = 'profile'
            self.last_profile = None
            self.last_profile_fingerprint = ''
            self.profile_checked_at = 0
            profile_fingerprint = self.store.contract_fingerprint()
            balance = await self.store.provider_balance()
            if profile_fingerprint != self.store.contract_fingerprint():
                raise StoreError('CONFIG', 'Konfigurasi berubah selama pemeriksaan profil. Periksa kembali.', stage='profile')
            self.last_profile = balance
            self.last_profile_fingerprint = profile_fingerprint
            self.profile_checked_at = time.time()
            currency = balance["currency"]
            self.failure_stage = 'services'
            rows = await self.store.api.request("services")
            if not isinstance(rows, list) or len(rows)>100000:
                raise StoreError("PROVIDER", detail='services: data bukan daftar layanan atau terlalu besar.', stage='services')
            prepared, blocked = {}, set()
            report = {'fingerprint':profile_fingerprint,'checked_at':time.time(),'received':len(rows),
                      'valid_unique':0,'rejected_rows':0,'identical_duplicates':0,'conflicting_ids':0,
                      'purchasable':0,'reasons':{},'examples':[],'state':'PROCESSING'}
            def reject(index, raw, sid, field, reason):
                report['rejected_rows'] += 1
                report['reasons'][field] = report['reasons'].get(field,0)+1
                if sid is not None:
                    blocked.add(sid)
                    prepared.pop(sid,None)
                if len(report['examples'])<1000:
                    report['examples'].append({'row':index,'id':sid,'field':field,'reason':reason,
                        'min':catalog_value_label(raw.get('min')) if isinstance(raw,dict) else 'kosong',
                        'max':catalog_value_label(raw.get('max')) if isinstance(raw,dict) else 'kosong'})
            fallback_unit = self.store.provider_units()["rate_unit"]
            form_rules={}
            for row in self.store.repo.all("SELECT key,value FROM sosmed_settings WHERE key LIKE 'service_form:%'"):
                try:form_rules[row['key'].split(':',1)[1]]=json.loads(row['value'])['type']
                except (ValueError,KeyError,TypeError):continue
            now = time.time()
            for index, raw in enumerate(rows,1):
                if not isinstance(raw, dict):
                    reject(index,raw,None,'objek','Entri layanan bukan objek JSON.')
                    continue
                field = 'service/id'
                sid = None
                try:
                    # Native id is authoritative; legacy service IDs still work.
                    sid = catalog_integer(raw.get('id',raw.get('service')),1,10**12)
                    if 'id' in raw and 'service' in raw:
                        try: legacy = catalog_integer(raw['service'],1,10**12)
                        except StoreError: legacy = None  # Some feeds use service as a display name.
                        if legacy is not None and legacy!=sid:
                            raise StoreError('PROVIDER',detail='Kolom id dan service menunjuk ID yang berbeda.')
                    if sid in blocked:
                        reject(index,raw,sid,'ID','ID ini memiliki entri lain yang invalid/bertentangan; seluruh ID dinonaktifkan.')
                        continue
                    field = 'name/category'
                    name, category = (raw.get(key) for key in ('name', 'category'))
                    if any(not isinstance(x, str) or not x.strip() for x in (name, category)):
                        raise StoreError("PROVIDER")
                    field = 'type'
                    kind,form_source=FormAdapter.catalogue_type(raw,form_rules.get(str(sid)))
                    raw={**raw,'_form_source':form_source}
                    field = 'rate/price'
                    rate = str(decimal(raw.get("rate", raw.get("price"))))
                    field = 'min'
                    low = catalog_integer(raw.get('min'))
                    field = 'max'
                    high = catalog_integer(raw.get('max'))
                    field = 'min/max'
                    if high<low:
                        raise StoreError('PROVIDER',detail='Max lebih kecil daripada min; batas tidak ditukar atau diasumsikan.')
                    available = service_available(raw) and low >= 1 and high >= low
                    field = 'currency'
                    service_currency = raw.get("currency", currency)
                    if not isinstance(service_currency, str) or (service_currency and not re.fullmatch(r"[A-Za-z]{3}", service_currency.strip())):
                        raise StoreError("PROVIDER")
                    service_currency = service_currency.strip().upper()
                    raw_unit = raw.get("rate_unit", raw.get("pricing_unit", fallback_unit))
                    unit = str(raw_unit).strip() if raw_unit is not None else ""
                    unit = {"per_1000":"1000", "per1000":"1000", "per 1000":"1000"}.get(unit.lower(), unit)
                    service = {"provider_service_id": sid, "name": name.strip()[:1000], "category": category.strip()[:500],
                               "type": kind.strip()[:100], "provider_rate": rate, "currency": service_currency,
                               "rate_unit": unit,
                               "min_quantity": low, "max_quantity": high,
                               "refill_supported": int(flag(raw.get("refill"))), "cancel_supported": 0,
                               "dripfeed_supported": 0,
                               "description": raw.get('description') if isinstance(raw.get('description'),str) and raw.get('description') else raw.get('note','') if isinstance(raw.get('note',''),str) else '',
                               "metadata_source": "API" if raw.get("description") or raw.get('note') else "", "last_synced_at": now,
                               "enabled": int(available), "order_supported": int(available and FormAdapter.supported({"type":kind,"raw_catalog":raw}) and service_currency=="IDR" and currency=="IDR" and unit=="1000"),
                               "raw_catalog": encoded(raw)}
                except StoreError as exc:
                    reject(index,raw,sid,field,exc.detail or 'Kolom '+field+' tidak valid.')
                    continue
                if sid in prepared:
                    if self.duplicate_signature(prepared[sid]) == self.duplicate_signature(service):
                        report['identical_duplicates'] += 1
                    else:
                        report['conflicting_ids'] += 1
                        reject(index,raw,sid,'ID duplikat','ID duplikat memiliki harga, batas, status atau input berbeda; seluruh ID dinonaktifkan.')
                    continue
                prepared[sid] = service
            report['valid_unique'] = len(prepared)
            report['blocked_ids'] = len(blocked)
            report['state'] = 'PARTIAL' if report['rejected_rows'] else 'COMPLETE'
            if profile_fingerprint != self.store.contract_fingerprint():
                raise StoreError('CONFIG','Konfigurasi berubah selama pemeriksaan katalog. Periksa kembali.',stage='services')
            if rows and not prepared:
                report['state'] = 'REJECTED'
                with self.store.repo.connection(True) as conn:
                    conn.execute('INSERT OR REPLACE INTO sosmed_settings VALUES(?,?,?)',('catalog_diagnostics',encoded(report),now))
                first = report['examples'][0]
                ident = 'ID #'+str(first['id']) if first['id'] is not None else 'ID tidak valid'
                detail = (f"services: {report['rejected_rows']} entri ditolak; belum ada layanan valid. "
                          f"Entri {first['row']}, {ident}, kolom {first['field']}: {first['reason']} "
                          'Katalog terakhir dipertahankan. Lihat tombol Rincian Katalog.')
                raise StoreError('PROVIDER',detail,detail=detail,stage='services')
            with self.store.repo.connection(True) as conn:
                conn.execute("UPDATE sosmed_services SET enabled=0,order_supported=0")
                for service in prepared.values():
                    fields = list(service)
                    conn.execute("INSERT INTO sosmed_services("+",".join(fields)+") VALUES("+",".join("?" for _ in fields)+") ON CONFLICT(provider_service_id) DO UPDATE SET "+",".join(f"{field}=excluded.{field}" for field in fields if field!="provider_service_id"), tuple(service.values()))
                for setting in conn.execute("SELECT * FROM sosmed_service_settings").fetchall():
                    field = "provider_service_id" if setting["scope"]=="service" else "category"
                    if not setting["enabled"]:
                        conn.execute(f"UPDATE sosmed_services SET enabled=0 WHERE {field}=?", (setting["scope_key"],))
                for meta in conn.execute("SELECT * FROM sosmed_metadata").fetchall():
                    conn.execute("UPDATE sosmed_services SET description=?,metadata_source=? WHERE provider_service_id=?", (meta["description"], meta["source"], meta["service_id"]))
                report['purchasable'] = conn.execute('SELECT COUNT(*) FROM sosmed_services WHERE enabled=1 AND order_supported=1').fetchone()[0]
                conn.execute('INSERT OR REPLACE INTO sosmed_settings VALUES(?,?,?)',('catalog_diagnostics',encoded(report),now))
            self.last_profile = balance
            return self.store.repo.all("SELECT * FROM sosmed_services ORDER BY category,provider_service_id") if return_rows else None

    def categories(self):
        return [r["category"] for r in self.store.repo.all("SELECT DISTINCT category FROM sosmed_services WHERE enabled=1 ORDER BY category")]

    def listing(self, category=None, query="", page=0, filters=None, page_size=PAGE_SIZE):
        page = number(page, 0, 100000)
        page_size = number(page_size, 1, 50)
        filters = dict(filters or {})
        aliases = {"min_quantity": "min", "max_quantity": "max", "max_price_idr": "price"}
        for original, alias in aliases.items():
            if original in filters:
                filters[alias] = filters.pop(original)
        category = category or filters.pop("category", None)
        terms, args = ["enabled=1"], []
        if category:
            terms.append("category=?")
            args.append(str(category))
        if query:
            if not isinstance(query, str) or len(query)>200:
                raise StoreError("INPUT")
            terms.append("(name LIKE ? ESCAPE '\\' OR category LIKE ? ESCAPE '\\')")
            escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            args.extend(["%"+escaped+"%"]*2)
        for key, field in (("refill", "refill_supported"), ("available", "order_supported")):
            if key in filters:
                if type(filters[key]) is not bool:
                    raise StoreError("INPUT")
                terms.append(field+"=?")
                args.append(int(filters[key]))
        if "min" in filters:
            terms.append("min_quantity<=?")
            args.append(number(filters["min"], 1))
        if "max" in filters:
            terms.append("max_quantity>=?")
            args.append(number(filters["max"], 1))
        where = " WHERE "+" AND ".join(terms)
        if "price" not in filters:
            total = self.store.repo.one("SELECT COUNT(*) n FROM sosmed_services"+where, args)["n"]
            rows = self.store.repo.all("SELECT * FROM sosmed_services"+where+" ORDER BY category,provider_service_id LIMIT ? OFFSET ?",
                                       (*args, page_size, page*page_size))
            return rows, total
        rows = self.store.repo.all("SELECT * FROM sosmed_services"+where+" ORDER BY category,provider_service_id", args)
        if "price" in filters:
            cap = number(filters["price"], 1)
            priced = []
            for row in rows:
                try:
                    sale = self.store.pricing.rate(row)[1]
                except StoreError as exc:
                    if exc.code in {"CURRENCY", "TYPE", "BELOW_COST"}:
                        continue  # Unknown prices cannot satisfy a price filter.
                    raise
                if sale<=cap:
                    priced.append(row)
            rows = priced
        return rows[page*page_size:(page+1)*page_size], len(rows)

    def service(self, ident, active=True):
        row = self.store.repo.one("SELECT * FROM sosmed_services WHERE provider_service_id=?"+(" AND enabled=1" if active else ""), (number(ident, 1),))
        if not row:
            raise StoreError("NOT_FOUND")
        return row

    async def live(self, ident):
        await self.sync(force=True, return_rows=False)
        return self.service(ident)

    def metadata(self, actor, ident, text, source):
        self.store.require_owner(actor)
        self.service(ident, False)
        if not isinstance(text, str) or len(text)>6000 or not isinstance(source, str) or not 1<=len(source)<=300:
            raise StoreError("INPUT")
        with self.store.repo.connection(True) as conn:
            conn.execute("INSERT OR REPLACE INTO sosmed_metadata VALUES(?,?,?,?,?)", (number(ident, 1), text, source, time.time(), actor))
            conn.execute("UPDATE sosmed_services SET description=?,metadata_source=? WHERE provider_service_id=?", (text, source, ident))
        self.store.repo.audit(actor, "metadata", {"service": ident, "source": source})

    def set_form(self, actor, ident, kind):
        self.store.require_owner(actor)
        ident=number(ident,1)
        row=self.service(ident,active=False)
        if kind is not None and kind not in {'Default','Comment','Mentions Custom List','Comment Replies'}:
            raise StoreError('TYPE')
        raw=json.loads(row['raw_catalog'])
        supplied=(raw.get('type') or '').strip().casefold()
        if supplied and supplied not in {'default','comment','mentions custom list','mentionscustomlist','comment replies','commentreplies'}:
            raise StoreError('TYPE','Tipe khusus API ini belum didukung; jenis dan satuan harganya tidak dapat diganti secara paksa.')
        with self.store.repo.connection(True) as conn:
            self.store.require_owner(actor)
            if kind is None:
                conn.execute('DELETE FROM sosmed_settings WHERE key=?',('service_form:'+str(ident),))
            else:
                conn.execute('INSERT OR REPLACE INTO sosmed_settings VALUES(?,?,?)',
                             ('service_form:'+str(ident),encoded({'type':kind,'source':'OWNER','actor':actor}),time.time()))
            conn.execute('UPDATE sosmed_services SET last_synced_at=0')
            # Old quotes must be reconfirmed after an input contract changes.
            conn.execute("UPDATE sosmed_quotes SET state='EXPIRED' WHERE service_id=? AND state='OPEN'",(ident,))
            conn.execute('INSERT INTO sosmed_audit(actor,action,payload,created_at) VALUES(?,?,?,?)',
                         (actor,'service_form',encoded({'service':ident,'type':kind}),time.time()))

    def toggle(self, actor, scope, key, enabled):
        self.store.require_owner(actor)
        if scope not in {"category", "service"} or type(enabled) is not bool:
            raise StoreError("INPUT")
        key = str(number(key, 1)) if scope=="service" else str(key)
        with self.store.repo.connection(True) as conn:
            conn.execute("INSERT OR REPLACE INTO sosmed_service_settings VALUES(?,?,?)", (scope, key, int(enabled)))
            # Enable only services present in the last official catalogue. A
            # disappeared service is never resurrected by an owner toggle.
            field = "provider_service_id" if scope=="service" else "category"
            if not enabled:
                conn.execute(f"UPDATE sosmed_services SET enabled=0 WHERE {field}=?", (key,))
            else:
                conn.execute("DELETE FROM sosmed_service_settings WHERE scope=? AND scope_key=?", (scope, key))
                conn.execute("UPDATE sosmed_services SET last_synced_at=0")
        self.store.repo.audit(actor, "availability", {"scope": scope, "key": key, "enabled": enabled})


class PricingService:
    def __init__(self, store):
        self.store = store

    def calculate(self, service, quantity, parameters=None):
        if service.get("currency") != "IDR":
            raise StoreError("CURRENCY")
        if service.get("rate_unit")!="1000":
            raise StoreError("TYPE", "Satuan harga layanan belum terverifikasi.")
        quantity = number(quantity, 1, 1000000000)
        provider_rate = decimal(service["provider_rate"])
        divisor = Decimal(1000)
        raw_cost = provider_rate*Decimal(quantity)/divisor
        cost = int(raw_cost.to_integral_value(rounding=ROUND_CEILING))
        settings = self.store.settings()
        rule, scope = {"mode": settings["mode"], "percent": settings["percent"], "fixed": settings["fixed"]}, "global"
        for kind, key in (("service", str(service["provider_service_id"])), ("category", service["category"])):
            row = self.store.repo.one("SELECT rule FROM sosmed_pricing_rules WHERE scope=? AND scope_key=?", (kind, key))
            if row:
                rule, scope = json.loads(row["rule"]), kind+":"+key
                break
        if "sale_rate" in rule:
            sale = decimal(rule["sale_rate"])*Decimal(quantity)/divisor
        else:
            sale = raw_cost
            if rule["mode"] in {"percent", "combined"}:
                sale *= 1+decimal(rule.get("percent", "0"), 0, 10000)/100
            if rule["mode"] in {"fixed", "combined"}:
                sale += number(rule.get("fixed", 0))
        sale = max(settings["min_sale"], int(sale.to_integral_value(rounding=ROUND_CEILING)))
        step = settings["rounding"]
        if step:
            sale = ((sale+step-1)//step)*step
        number(cost)
        number(sale, 1)
        if sale<cost and not settings["allow_loss"]:
            raise StoreError("BELOW_COST")
        return cost, sale, {"scope": scope, "rule": rule, "rate": str(provider_rate), "unit": service["rate_unit"], "quantity": quantity, "rounding": step, "min_sale": settings["min_sale"]}

    def rate(self, service):
        return self.calculate(service, 1000)[:2]

    def set_rule(self, actor, scope, key, rule):
        self.store.require_owner(actor)
        if scope not in {"service", "category"} or not isinstance(rule, dict):
            raise StoreError("INPUT")
        key = str(number(key, 1)) if scope=="service" else str(key)
        if scope=="service":
            self.store.catalog.service(key, False)
        if set(rule)-{"mode", "percent", "fixed", "sale_rate"}:
            raise StoreError("INPUT")
        old = self.store.repo.one("SELECT rule FROM sosmed_pricing_rules WHERE scope=? AND scope_key=?", (scope, key))
        global_settings = self.store.settings()
        previous = json.loads(old["rule"]) if old else {"mode":global_settings["mode"],"percent":global_settings["percent"],"fixed":global_settings["fixed"]}
        if any(field in rule for field in ("mode", "percent", "fixed")):
            previous.pop("sale_rate", None)
        rule = {**previous, **rule}
        if "sale_rate" in rule:
            checked = {"sale_rate": str(decimal(rule["sale_rate"], 1))}
        else:
            mode = rule.get("mode", "percent")
            if mode not in {"percent", "fixed", "combined"}:
                raise StoreError("INPUT")
            checked = {"mode": mode, "percent": str(decimal(rule.get("percent", "0"), 0, 10000)), "fixed": number(rule.get("fixed", 0))}
        with self.store.repo.connection(True) as conn:
            conn.execute("INSERT OR REPLACE INTO sosmed_pricing_rules VALUES(?,?,?,?)", (scope, key, encoded(checked), time.time()))
        self.store.repo.audit(actor, "pricing", {"scope": scope, "key": key, "rule": checked})

    def reset_rule(self, actor, scope, key):
        self.store.require_owner(actor)
        if scope not in {"service", "category"}:
            raise StoreError("INPUT")
        with self.store.repo.connection(True) as conn:
            conn.execute("DELETE FROM sosmed_pricing_rules WHERE scope=? AND scope_key=?", (scope, str(key)))
        self.store.repo.audit(actor, "pricing_reset", {"scope": scope, "key": str(key)})


class PurchaseService:
    def __init__(self, store):
        self.store = store

    async def quote(self, user, service_id, parameters):
        self.store.purchase_guard(user)
        self.store.repo.rate(user, "quote", 20, 60)
        service = await self.store.catalog.live(service_id)
        self.store.purchase_guard(user)
        if not service.get("order_supported"):
            raise StoreError("CURRENCY" if service.get("currency")!="IDR" else "TYPE")
        validated = FormAdapter.validate(service, parameters)
        if validated["quantity"]>self.store.settings()["max_quantity"]:
            raise StoreError("INPUT", "Jumlah melebihi batas transaksi toko.")
        cost, sale, snapshot = self.store.pricing.calculate(service, validated["quantity"], parameters)
        ident, now = secrets.token_hex(12), time.time()
        with self.store.repo.connection(True) as conn:
            self.store.purchase_guard(user)
            latest = conn.execute("SELECT * FROM sosmed_services WHERE provider_service_id=? AND enabled=1", (service["provider_service_id"],)).fetchone()
            if not latest:
                raise StoreError("NOT_FOUND")
            service = dict(latest)
            if not service.get("order_supported"):
                raise StoreError("CURRENCY" if service.get("currency")!="IDR" else "TYPE")
            validated = FormAdapter.validate(service, parameters)
            if validated["quantity"]>self.store.settings()["max_quantity"]:
                raise StoreError("INPUT", "Jumlah melebihi batas transaksi toko.")
            cost, sale, snapshot = self.store.pricing.calculate(service, validated["quantity"], parameters)
            conn.execute("INSERT INTO sosmed_quotes(quote_id,user_id,service_id,service_snapshot,target,quantity,parameters,cost,sale,price_snapshot,expires_at,state,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,'OPEN',?)",
                         (ident, user, service["provider_service_id"], encoded(service), validated["target"], validated["quantity"], encoded(parameters), cost, sale, encoded(snapshot), now+self.store.config.quote_ttl, now))
        return self.get_quote(user, ident)

    def get_quote(self, user, ident):
        row = self.store.repo.one("SELECT * FROM sosmed_quotes WHERE quote_id=? AND user_id=?", (str(ident), user))
        if not row:
            raise StoreError("NOT_FOUND")
        row["service"] = json.loads(row.pop("service_snapshot"))
        row["parameters"] = json.loads(row["parameters"])
        row["price_snapshot"] = json.loads(row["price_snapshot"])
        return row

    def result(self, attempt):
        row = self.store.repo.one("SELECT * FROM sosmed_orders WHERE attempt_id=?", (attempt["attempt_id"],))
        if row:
            row["internal_order_id"] = row["id"]
        return {"state": attempt["state"], "attempt_id": attempt["attempt_id"], "order": row}

    async def buy(self, user, quote_id):
        # Existing attempt lookup precedes guard/TTL: a stale double click may
        # show its settled order even if the owner closed new purchases.
        existing = self.store.repo.one("SELECT * FROM sosmed_purchase_attempts WHERE quote_id=? AND user_id=?", (str(quote_id), user))
        if existing:
            return self.result(existing)
        self.store.purchase_guard(user)
        quote = self.get_quote(user, quote_id)
        if quote["expires_at"]<time.time() or quote["state"]!="OPEN":
            raise StoreError("QUOTE_EXPIRED")
        service = await self.store.catalog.live(quote["service_id"])
        self.store.purchase_guard(user)
        if not service.get("order_supported"):
            raise StoreError("CURRENCY" if service.get("currency")!="IDR" else "TYPE")
        checked = FormAdapter.validate(service, quote["parameters"])
        cost, sale, snapshot = self.store.pricing.calculate(service, checked["quantity"])
        # Provider cost, form type and sale changes require a new confirmation.
        if (cost!=quote["cost"] or sale!=quote["sale"] or service["provider_rate"]!=quote["service"]["provider_rate"]
                or service["type"]!=quote["service"]["type"] or checked["quantity"]!=quote["quantity"]):
            raise StoreError("PRICE_CHANGED")
        if checked["quantity"]>self.store.settings()["max_quantity"]:
            raise StoreError("INPUT")
        body, now = checked["body"], time.time()
        with self.store.repo.connection(True) as conn:
            attempt = conn.execute("SELECT * FROM sosmed_purchase_attempts WHERE quote_id=?", (quote_id,)).fetchone()
            if attempt:
                if attempt["user_id"]!=user:
                    raise StoreError("NOT_FOUND")
                return self.result(dict(attempt))
            current = conn.execute("SELECT * FROM sosmed_quotes WHERE quote_id=? AND user_id=?", (quote_id, user)).fetchone()
            if not current or current["state"]!="OPEN" or current["expires_at"]<now:
                raise StoreError("QUOTE_EXPIRED")
            # Owner/user guards and catalogue availability must be checked
            # AFTER all asynchronous work, under the same wallet write lock.
            self.store.purchase_guard(user)
            settings = self.store.settings()
            latest = conn.execute("SELECT * FROM sosmed_services WHERE provider_service_id=? AND enabled=1", (service["provider_service_id"],)).fetchone()
            if not latest:
                raise StoreError("NOT_FOUND")
            if not latest["order_supported"]:
                raise StoreError("CURRENCY" if latest["currency"]!="IDR" else "TYPE")
            latest_checked = FormAdapter.validate(dict(latest), quote["parameters"])
            latest_cost, latest_sale, _ = self.store.pricing.calculate(dict(latest), latest_checked["quantity"])
            if (latest_cost!=cost or latest_sale!=sale or latest["provider_rate"]!=service["provider_rate"]
                    or latest["type"]!=service["type"] or latest_checked["quantity"]!=checked["quantity"]):
                raise StoreError("PRICE_CHANGED")
            if latest_checked["quantity"]>settings["max_quantity"]:
                raise StoreError("INPUT")
            active_orders = conn.execute("SELECT COUNT(*) FROM sosmed_orders WHERE user_id=? AND status NOT IN ('COMPLETED','PARTIAL','CANCELED','FAILED')", (user,)).fetchone()[0]
            pending = conn.execute("SELECT COUNT(*) FROM sosmed_purchase_attempts WHERE user_id=? AND state IN ('REQUESTING','RECONCILIATION_REQUIRED')", (user,)).fetchone()[0]
            if active_orders+pending>=settings["max_active"]:
                raise StoreError("ACTIVE_LIMIT")
            recent = conn.execute("SELECT created_at FROM sosmed_purchase_attempts WHERE user_id=? ORDER BY created_at DESC LIMIT 1", (user,)).fetchone()
            if recent and now-recent[0]<3:
                raise StoreError("RATE_LIMIT")
            ident = secrets.token_hex(12)
            WalletAdapter.change(conn, user, "SOSMED_HOLD", -sale, ident)
            conn.execute("INSERT INTO sosmed_purchase_attempts(attempt_id,quote_id,user_id,state,request_body,request_hash,hold_amount,created_at,updated_at) VALUES(?,?,?,'REQUESTING',?,?,?,?,?)",
                         (ident, quote_id, user, encoded(body), hashlib.sha256(encoded(body).encode()).hexdigest(), sale, now, now))
            conn.execute("UPDATE sosmed_quotes SET state='PROCESSING' WHERE quote_id=?", (quote_id,))
        try:
            response = await self.store.api.request("add", **body)
            if not isinstance(response, dict) or "order" not in response:
                raise StoreError("UNKNOWN", uncertain=True)
            try:
                provider_id = number(response["order"], 1, 10**12)
            except StoreError:
                raise StoreError("UNKNOWN", uncertain=True) from None
        except StoreError as exc:
            if exc.uncertain:
                self.unknown(ident, exc.code)
            else:
                self.release(ident, exc.code)
        except asyncio.CancelledError:
            self.unknown(ident, "INTERRUPTED")
            raise
        except Exception:
            # Includes a database error AFTER successful provider creation.
            # Never release a hold or automatically repeat add here.
            try:
                self.unknown(ident, "LOCAL_COMMIT")
            except Exception:
                pass  # Durable REQUESTING record is recovered on restart.
        else:
            try:
                self.capture(ident, provider_id)
            except Exception:
                # The provider has created the order. No local error may
                # release money or permit another add attempt.
                try:
                    self.unknown(ident, "LOCAL_COMMIT")
                except Exception:
                    pass
        attempt = self.store.repo.one("SELECT * FROM sosmed_purchase_attempts WHERE attempt_id=?", (ident,))
        return self.result(attempt)

    def capture(self, attempt_id, provider_id, proof=None, actor=None):
        now = time.time()
        with self.store.repo.connection(True) as conn:
            attempt = conn.execute("SELECT * FROM sosmed_purchase_attempts WHERE attempt_id=?", (attempt_id,)).fetchone()
            if not attempt or attempt["state"] not in {"REQUESTING", "RECONCILIATION_REQUIRED", "SUCCESS"}:
                raise StoreError("PROOF")
            if attempt["state"]=="SUCCESS":
                if attempt["provider_order_id"]!=provider_id:
                    raise StoreError("PROOF")
                return
            if proof:
                self.store.require_owner(actor)
                try:
                    conn.execute("INSERT INTO sosmed_reconciliation_proofs VALUES(?,?,?,?,?)", (proof, attempt_id, "ATTACH", actor, now))
                except sqlite3.IntegrityError:
                    raise StoreError("PROOF") from None
                conn.execute("INSERT INTO sosmed_audit(actor,action,payload,created_at) VALUES(?,?,?,?)", (actor,"reconcile_attach",encoded({"attempt":attempt_id,"provider_order":provider_id,"proof":proof}),now))
            quote = conn.execute("SELECT * FROM sosmed_quotes WHERE quote_id=?", (attempt["quote_id"],)).fetchone()
            service = json.loads(quote["service_snapshot"])
            conn.execute("INSERT INTO sosmed_orders(provider_order_id,attempt_id,user_id,service_id,service_name_snapshot,category_snapshot,target,quantity,form_parameters,provider_cost,selling_price,gross_profit,currency,status,raw_provider_status,refill_supported,cancel_supported,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,'PENDING','Pending',?,?,?,?)",
                         (provider_id, attempt_id, quote["user_id"], quote["service_id"], service["name"], service["category"], quote["target"], quote["quantity"], quote["parameters"], quote["cost"], quote["sale"], quote["sale"]-quote["cost"], "IDR", service["refill_supported"], service["cancel_supported"], now, now))
            WalletAdapter.change(conn, quote["user_id"], "SOSMED_CAPTURE", 0, attempt_id)
            conn.execute("UPDATE sosmed_purchase_attempts SET state='SUCCESS',provider_order_id=?,reconciliation_status='RESOLVED',updated_at=? WHERE attempt_id=?", (provider_id, now, attempt_id))
            conn.execute("UPDATE sosmed_quotes SET state='PURCHASED' WHERE quote_id=?", (attempt["quote_id"],))

    def unknown(self, attempt_id, code):
        with self.store.repo.connection(True) as conn:
            conn.execute("UPDATE sosmed_purchase_attempts SET state='RECONCILIATION_REQUIRED',reconciliation_status='OWNER_REVIEW',error_code=?,updated_at=? WHERE attempt_id=? AND state='REQUESTING'", (code, time.time(), attempt_id))

    def release(self, attempt_id, code, proof=None, actor=None):
        with self.store.repo.connection(True) as conn:
            row = conn.execute("SELECT * FROM sosmed_purchase_attempts WHERE attempt_id=?", (attempt_id,)).fetchone()
            if not row:
                raise StoreError("NOT_FOUND")
            if row["state"]=="FAILED":
                return
            if row["state"] not in {"REQUESTING", "RECONCILIATION_REQUIRED"} or (row["state"]=="RECONCILIATION_REQUIRED" and not proof):
                raise StoreError("PROOF")
            if proof and row["state"]!="RECONCILIATION_REQUIRED":
                # Owner cannot release a live, in-flight add request. Only the
                # internal definitive-rejection path may release REQUESTING.
                raise StoreError("PROOF")
            if proof:
                self.store.require_owner(actor)
                try:
                    conn.execute("INSERT INTO sosmed_reconciliation_proofs VALUES(?,?,?,?,?)", (proof, attempt_id, "RELEASE", actor, time.time()))
                except sqlite3.IntegrityError:
                    raise StoreError("PROOF") from None
                conn.execute("INSERT INTO sosmed_audit(actor,action,payload,created_at) VALUES(?,?,?,?)", (actor,"reconcile_release",encoded({"attempt":attempt_id,"proof":proof}),time.time()))
            WalletAdapter.change(conn, row["user_id"], "SOSMED_RELEASE", row["hold_amount"], attempt_id)
            conn.execute("UPDATE sosmed_purchase_attempts SET state='FAILED',reconciliation_status='RESOLVED',error_code=?,updated_at=? WHERE attempt_id=?", (code, time.time(), attempt_id))
            conn.execute("UPDATE sosmed_quotes SET state='FAILED' WHERE quote_id=?", (row["quote_id"],))

    def recover(self):
        # Multiple instances can start while a request is actively in flight.
        # Wait beyond HTTP timeout before labeling an interrupted request; no
        # state in this method ever triggers another POST add.
        with self.store.repo.connection(True) as conn:
            conn.execute("UPDATE sosmed_purchase_attempts SET state='RECONCILIATION_REQUIRED',reconciliation_status='OWNER_REVIEW',error_code='INTERRUPTED',updated_at=? WHERE state='REQUESTING' AND updated_at<?", (time.time(), time.time()-self.store.config.timeout-10))


class OrderService:
    def __init__(self, store):
        self.store = store

    @staticmethod
    def mapped(status):
        key = str(status or "").strip().lower().replace("_", " ")
        return {"pending": "PENDING", "processing": "PROCESSING", "in progress": "IN_PROGRESS", "completed": "COMPLETED", "success": "COMPLETED", "error": "FAILED", "failed": "FAILED", "partial": "PARTIAL", "canceled": "CANCELED", "cancelled": "CANCELED"}.get(key, "UNKNOWN")

    async def refresh(self, user, order_id, admin=False):
        if admin:
            self.store.require_owner(user)
            row = self.store.repo.one("SELECT * FROM sosmed_orders WHERE id=?", (number(order_id, 1),))
            if not row:
                raise StoreError("NOT_FOUND")
        else:
            row = self.store.repo.order(user, order_id)
        self.store.repo.rate(user, "status", 30, 60)
        return await self._refresh(row)

    async def _refresh(self, row):
        response = await self.store.api.request("status", order=row["provider_order_id"])
        if not isinstance(response, dict) or not isinstance(response.get("status"), str):
            raise StoreError("PROVIDER")
        currency = response.get("currency")
        if currency is not None and currency != "IDR":
            raise StoreError("CURRENCY")
        status = self.mapped(response["status"])
        start, remains, charge = None, None, None
        if response.get("start_count") not in (None, ""):
            start = number(response["start_count"])
        if response.get("remains") not in (None, ""):
            remains = number(response["remains"])
        if response.get("charge") not in (None, ""):
            charge = str(decimal(response["charge"]))
        now = time.time()
        with self.store.repo.connection(True) as conn:
            current = conn.execute("SELECT status FROM sosmed_orders WHERE id=?", (row["id"],)).fetchone()
            # Provider can revise terminal states. Persist the real latest
            # response, and keep UNKNOWN visible instead of guessing success.
            conn.execute("UPDATE sosmed_orders SET status=?,raw_provider_status=?,start_count=?,remains=?,provider_charge=?,updated_at=?,next_poll_at=?,terminal_at=?,refund_state=CASE WHEN ? IN ('PARTIAL','CANCELED','FAILED') AND refund_amount=0 THEN 'AWAITING_PROVIDER_PROOF' ELSE refund_state END WHERE id=?",
                         (status, response["status"][:100], start, remains, charge, now, now+self.store.settings()["poll_seconds"], now if status in TERMINAL else None, status, row["id"]))
        result = self.store.repo.one("SELECT * FROM sosmed_orders WHERE id=?", (row["id"],))
        result["internal_order_id"] = result["id"]
        return result

    async def refill(self, user, order_id):
        row = await self.refresh(user, order_id)
        if not self.store.purchase_contract_verified() or not self.store.config.refill_verified or not row["refill_supported"] or row["status"]!="COMPLETED":
            raise StoreError("REFILL")
        self.store.repo.rate(user, "refill", 3, 3600)
        now = time.time()
        with self.store.repo.connection(True) as conn:
            pending = conn.execute("SELECT * FROM sosmed_refills WHERE order_id=? AND status IN ('REQUESTING','PENDING','UNKNOWN','In progress') ORDER BY id DESC LIMIT 1", (row["id"],)).fetchone()
            if pending:
                return dict(pending)
            cur = conn.execute("INSERT INTO sosmed_refills(order_id,status,created_at,updated_at) VALUES(?,'REQUESTING',?,?)", (row["id"], now, now))
            ident = cur.lastrowid
        try:
            response = await self.store.api.request("refill", order=row["provider_order_id"])
            if not isinstance(response, dict) or "refill" not in response:
                raise StoreError("UNKNOWN", uncertain=True)
            try:
                provider_id = number(response["refill"], 1)
            except StoreError:
                raise StoreError("UNKNOWN", uncertain=True) from None
            state = "PENDING"
        except StoreError as exc:
            provider_id, state = None, "UNKNOWN" if exc.uncertain else "REJECTED"
        except asyncio.CancelledError:
            with self.store.repo.connection(True) as conn:
                conn.execute("UPDATE sosmed_refills SET status='UNKNOWN',updated_at=? WHERE id=?", (time.time(), ident))
            raise
        except Exception:
            provider_id, state = None, "UNKNOWN"
        with self.store.repo.connection(True) as conn:
            conn.execute("UPDATE sosmed_refills SET provider_refill_id=?,status=?,updated_at=? WHERE id=?", (provider_id, state, time.time(), ident))
        return self.store.repo.one("SELECT * FROM sosmed_refills WHERE id=?", (ident,))

    async def refill_status(self, user, order_id):
        self.store.repo.order(user, order_id)
        if not self.store.config.refill_verified:
            raise StoreError("REFILL")
        row = self.store.repo.one("SELECT * FROM sosmed_refills WHERE order_id=? ORDER BY id DESC LIMIT 1", (order_id,))
        if not row:
            raise StoreError("REFILL")
        if not row["provider_refill_id"] or row["status"] in {"COMPLETED", "REJECTED", "FAILED"}:
            return row
        return await self._refill_status(row)

    async def _refill_status(self, row):
        response = await self.store.api.request("refill_status", refill=row["provider_refill_id"])
        if not isinstance(response, dict) or not isinstance(response.get("status"), str):
            raise StoreError("PROVIDER")
        raw = response["status"].strip().lower()
        state = {"completed": "COMPLETED", "success": "COMPLETED", "rejected": "REJECTED", "failed": "FAILED", "error": "FAILED", "pending": "PENDING", "processing": "PENDING", "in progress": "PENDING"}.get(raw, "UNKNOWN")
        with self.store.repo.connection(True) as conn:
            conn.execute("UPDATE sosmed_refills SET status=?,updated_at=? WHERE id=?", (state, time.time(), row["id"]))
        return self.store.repo.one("SELECT * FROM sosmed_refills WHERE id=?", (row["id"],))

    async def cancel(self, user, order_id, confirmed=False):
        self.store.repo.order(user, order_id)
        raise StoreError("CANCEL", "Pembatalan belum didukung oleh kontrak layanan yang tersedia.")

    async def poll_once(self):
        now = time.time()
        self.store.purchase.recover()
        rows = self.store.repo.all("SELECT * FROM sosmed_orders WHERE status NOT IN ('COMPLETED','PARTIAL','CANCELED','FAILED') AND next_poll_at<=? ORDER BY next_poll_at LIMIT 20", (now,))
        for row in rows:
            try:
                await self._refresh(row)
            except StoreError as exc:
                with self.store.repo.connection(True) as conn:
                    conn.execute("UPDATE sosmed_orders SET next_poll_at=? WHERE id=?", (now+max(self.store.settings()["poll_seconds"], exc.retry_after), row["id"]))
                if exc.code=="RATE_LIMIT":
                    break
            except Exception:
                # Isolate one bad row/API/DB failure from other orders; no
                # provider errors or user target data are written to logs.
                continue
        for row in self.store.repo.all("SELECT * FROM sosmed_refills WHERE status IN('PENDING','UNKNOWN') AND provider_refill_id IS NOT NULL AND updated_at<? ORDER BY updated_at LIMIT 10", (now-self.store.settings()["poll_seconds"],)):
            try:
                await self._refill_status(row)
            except Exception:
                continue
        # A crash during non-idempotent actions does not justify a replay.
        with self.store.repo.connection(True) as conn:
            conn.execute("UPDATE sosmed_refills SET status='UNKNOWN',updated_at=? WHERE status='REQUESTING' AND updated_at<?", (now, now-self.store.config.timeout-10))
            conn.execute("UPDATE sosmed_orders SET cancel_state='UNKNOWN' WHERE cancel_state='REQUESTING' AND updated_at<?", (now-self.store.config.timeout-10,))


class Store:
    def __init__(self, host, config=None):
        self.host, self.config = host, config or Config.environment()
        self.repo = Repository(host)
        self.api = APIClient(self.config)
        self.api.contract_validator = self.purchase_contract_verified
        self.catalog, self.pricing = CatalogService(self), PricingService(self)
        self.purchase, self.orders = PurchaseService(self), OrderService(self)
        self._tasks, self._bot, self._owner_token = [], None, secrets.token_hex(12)
        self._started = False
        self._last_check = None

    def owner(self, user):
        return bool(self.host.is_owner(user))

    def require_owner(self, user):
        if not self.owner(user):
            raise StoreError("FORBIDDEN")

    def configuration_issues(self):
        issues = [self.config.error] if self.config.error else []
        if self.config.url != "https://buzzerpanel.id/api/json.php":
            issues.append("BUZZERPANEL_API_URL harus https://buzzerpanel.id/api/json.php")
        for key, value in (("BUZZERPANEL_API_KEY", self.config.token),
                           ("BUZZERPANEL_SECRET_KEY", self.config.secret)):
            if not value:
                issues.append(f"{key} belum diisi")
        return issues

    def contract_fingerprint(self):
        # Store only a digest, never credentials. A different account, endpoint,
        # currency or unit must be checked again before accepting purchases.
        units = self.provider_units()
        return hashlib.sha256(encoded({"url": self.config.url, "key": self.config.token,
            "secret": self.config.secret, "currency": units["currency"],
            "unit": units["rate_unit"], "contract": "json.php-order-v1"}).encode()).hexdigest()

    def account_fingerprint(self):
        # A saved unit confirmation belongs to this account, not every future
        # account that happens to use the same bot/database.
        return hashlib.sha256(encoded({"url": self.config.url, "key": self.config.token,
                                      "secret": self.config.secret}).encode()).hexdigest()

    def confirmed_provider_units(self, conn=None):
        try:
            row = (conn.execute("SELECT value FROM sosmed_settings WHERE key='provider_units'").fetchone()
                   if conn is not None else self.repo.one("SELECT value FROM sosmed_settings WHERE key='provider_units'"))
            proof = json.loads(row["value"]) if row else {}
            if (isinstance(proof, dict) and proof.get("account") == self.account_fingerprint()
                    and proof.get("currency", "") in {"", "IDR"}
                    and proof.get("rate_unit", "") in {"", "1000"}):
                return proof
        except (sqlite3.OperationalError, ValueError, TypeError):
            pass
        return {}

    def provider_units(self):
        proof = self.confirmed_provider_units()
        return {"currency": self.config.currency or proof.get("currency", ""),
                "rate_unit": self.config.rate_unit or proof.get("rate_unit", ""),
                "currency_source": "VARIABLE" if self.config.currency else "OWNER" if proof.get("currency") else "UNAVAILABLE",
                "unit_source": "VARIABLE" if self.config.rate_unit else "OWNER" if proof.get("rate_unit") else "UNAVAILABLE"}

    def set_provider_unit(self, actor, field, value, account):
        self.require_owner(actor)
        if field not in {"currency", "rate_unit", "reset"} or value != {"currency": "IDR", "rate_unit": "1000", "reset": None}[field]:
            raise StoreError("INPUT")
        if self.configuration_issues() or account != self.account_fingerprint():
            raise StoreError("CONFIG", "Konfigurasi akun berubah atau belum lengkap. Buka pengaturan mata uang/satuan lagi.")
        with self.repo.connection(True) as conn:
            self.require_owner(actor)
            if account != self.account_fingerprint():
                raise StoreError("CONFIG")
            before = self.confirmed_provider_units(conn)
            after = {} if field == "reset" else {**before, field: value}
            if field != "reset" and getattr(self.config, field) and getattr(self.config, field) != value:
                raise StoreError("CURRENCY")
            if before == after:
                return
            now = time.time()
            after.update(account=account, actor=actor, checked_at=now)
            if field == "reset":
                conn.execute("DELETE FROM sosmed_settings WHERE key='provider_units'")
            else:
                conn.execute("INSERT OR REPLACE INTO sosmed_settings VALUES(?,?,?)", ("provider_units", encoded(after), now))
            # Only new, unpaid purchases need a new quote/check. Existing
            # orders, holds, wallet entries and background tracking are intact.
            conn.execute("DELETE FROM sosmed_settings WHERE key='verified_purchase_contract'")
            conn.execute("INSERT OR REPLACE INTO sosmed_settings VALUES(?,?,?)", ("enabled", "false", now))
            conn.execute("UPDATE sosmed_services SET last_synced_at=0,order_supported=0")
            conn.execute("UPDATE sosmed_quotes SET state='EXPIRED' WHERE state='OPEN'")
            conn.execute("INSERT INTO sosmed_audit(actor,action,payload,created_at) VALUES(?,?,?,?)",
                         (actor, "provider_unit", encoded({"field": field, "value": value,
                          "before": {key: before.get(key, "") for key in ("currency", "rate_unit")}}), now))
        self._last_check = None

    def purchase_contract_verified(self):
        if self.configuration_issues():
            return False
        if self.config.contract_verified:
            return True
        try:
            row = self.repo.one("SELECT value FROM sosmed_settings WHERE key='verified_purchase_contract'")
            proof = json.loads(row["value"]) if row else {}
            return (isinstance(proof, dict) and proof.get("verified") is True
                    and proof.get("fingerprint") == self.contract_fingerprint())
        except (sqlite3.OperationalError, ValueError, TypeError):
            return False

    async def check_provider(self, actor):
        self.require_owner(actor)
        issues = self.configuration_issues()
        if issues:
            raise StoreError("CONFIG", "Lengkapi Railway Variables: "+"; ".join(issues)+". Redeploy setelah memperbaiki variabel.")
        fingerprint = self.contract_fingerprint()
        check = {'fingerprint': fingerprint, 'connected': False, 'checked_at': time.time(),
                 'stage': 'profile', 'error': '', 'detail': '', 'http_status': None}
        self._last_check = check
        try:
            rows = await self.catalog.sync(force=True)
        except StoreError as exc:
            stage = exc.stage or self.catalog.failure_stage
            detail = exc.detail or {
                'AUTH': 'Autentikasi ditolak. Periksa BUZZERPANEL_API_KEY dan BUZZERPANEL_SECRET_KEY dari akun yang sama.',
                'IP_RESTRICTED': 'Izin IP API ditolak. Periksa whitelist pada akun provider.',
                'API_DISABLED': 'API atau akun provider dinonaktifkan.',
                'NETWORK': 'Koneksi/timeout gagal. Periksa akses server ke API provider.',
                'RATE_LIMIT': 'Batas request tercapai. Tunggu sebelum memeriksa kembali.',
            }.get(exc.code, 'Respons '+stage+' belum dapat dibaca. Cocokkan respons profile/services pada panel provider.')
            check.update(stage=stage, error=exc.code, detail=detail, checked_at=time.time(),
                         http_status=getattr(self.api, 'http_status', None))
            raise StoreError(exc.code if exc.code!='INPUT' else 'PROVIDER', detail,
                             detail=detail, stage=stage, retry_after=exc.retry_after) from None
        self.require_owner(actor)
        if fingerprint != self.contract_fingerprint():
            raise StoreError("CONFIG", "Konfigurasi berubah selama pemeriksaan. Periksa koneksi kembali.")
        check.update(connected=True, checked_at=time.time(), stage='complete',
                     http_status=getattr(self.api, 'http_status', None))
        return {"profile": self.catalog.last_profile, "services": rows, "fingerprint": fingerprint}

    def catalogue_issues(self, rows=None, profile=None):
        rows = rows if rows is not None else self.repo.all("SELECT * FROM sosmed_services")
        profile = profile if profile is not None else self.catalog.last_profile
        issues = []
        if profile is not None and profile.get("currency") != "IDR":
            if profile.get("currency"):
                issues.append("Mata uang profil bukan IDR; konversi belum didukung")
            else:
                issues.append("API profile tidak menyebut mata uang. Konfirmasi IDR pada tombol Mata Uang & Satuan setelah memeriksa akun; alternatif BUZZERPANEL_CURRENCY=IDR")
        if not rows:
            issues.append("Katalog belum berisi layanan; periksa Status API / Sync Katalog")
        elif not any(row["enabled"] and row["order_supported"] for row in rows):
            if not any(row["enabled"] for row in rows):
                issues.append("Semua layanan/kategori ditutup atau tidak aktif")
            if any(row["enabled"] and not row["rate_unit"] for row in rows):
                issues.append("API tidak menyebut satuan rate. Konfirmasi per 1.000 pada tombol Mata Uang & Satuan setelah memeriksa tarif; alternatif SOSMED_RATE_UNIT=1000")
            if not any(row["currency"] == "IDR" for row in rows):
                issues.append("Mata uang layanan IDR belum dikonfirmasi")
            if not any(FormAdapter.supported(row) for row in rows):
                issues.append("Form layanan khusus belum didukung/dipastikan. Owner dapat memilih Tipe/Input pada detail layanan berdasarkan dokumentasi resmi")
            if not issues:
                issues.append("Belum ada layanan dengan mata uang, satuan harga, dan form yang didukung")
        return issues

    async def enable_from_provider(self, actor):
        """Owner's ON action checks only profile/catalog; it never buys an order."""
        result = await self.check_provider(actor)
        issues = self.catalogue_issues(result["services"], result["profile"])
        if issues:
            raise StoreError("CONFIG", "Toko belum dibuka: "+"; ".join(issues)+".")
        eligible = [row for row in result["services"] if row["enabled"] and row["order_supported"]]
        usable = False
        for row in eligible:
            try:
                if row["min_quantity"] <= self.settings()["max_quantity"]:
                    self.pricing.calculate(row, row["min_quantity"])
                    usable = True
                    break
            except StoreError:
                continue
        if not usable:
            raise StoreError("CONFIG", "Toko belum dibuka: periksa harga jual, markup, dan batas jumlah; belum ada layanan yang dapat dijual.")
        self.require_owner(actor)
        now = time.time()
        proof = {"verified": True, "fingerprint": result["fingerprint"], "actor": actor,
                 "checked_at": now, "currency": "IDR", "contract": "json.php-order-v1"}
        with self.repo.connection(True) as conn:
            self.require_owner(actor)
            if self.configuration_issues() or result["fingerprint"] != self.contract_fingerprint():
                raise StoreError("CONFIG", "Konfigurasi berubah. Periksa koneksi kembali.")
            # Verification and ON survive restart together, without wallet writes.
            conn.execute("INSERT OR REPLACE INTO sosmed_settings VALUES(?,?,?)", ("verified_purchase_contract", encoded(proof), now))
            conn.execute("INSERT OR REPLACE INTO sosmed_settings VALUES(?,?,?)", ("enabled", "true", now))
            conn.execute("INSERT INTO sosmed_audit(actor,action,payload,created_at) VALUES(?,?,?,?)",
                         (actor, "verified_enable", encoded({"services": len(eligible), "currency": "IDR"}), now))
        return result

    def settings(self):
        c = self.config
        values = {"enabled": c.enabled, "mode": c.mode, "percent": c.percent, "fixed": c.fixed,
                  "rounding": c.rounding, "min_sale": c.min_sale, "max_active": c.max_active,
                  "max_quantity": c.max_quantity, "poll_seconds": c.poll_seconds,
                  "catalog_seconds": c.catalog_seconds, "allow_loss": False}
        try:
            for row in self.repo.all("SELECT key,value FROM sosmed_settings"):
                if row["key"] in values:
                    values[row["key"]] = json.loads(row["value"])
        except sqlite3.OperationalError:
            # During import schema is initialized by the existing launcher.
            pass
        return values

    def set_setting(self, key, value, actor):
        self.require_owner(actor)
        bounds = {"fixed": (0, MAX_MONEY), "rounding": (0, 1000), "min_sale": (0, MAX_MONEY),
                  "max_active": (1, 50), "max_quantity": (1, 1000000000), "poll_seconds": (30, 3600), "catalog_seconds": (30, 86400)}
        if key in {"enabled", "allow_loss"}:
            if type(value) is not bool:
                raise StoreError("INPUT")
            if key=="enabled" and value and not self.purchase_contract_verified():
                raise StoreError("CONFIG")
        elif key=="mode":
            value = {"persen": "percent", "nominal": "fixed", "kombinasi": "combined"}.get(value, value)
            if value not in {"percent", "fixed", "combined"}:
                raise StoreError("INPUT")
        elif key=="percent":
            value = str(decimal(value, 0, 10000))
        elif key in bounds:
            value = number(value, *bounds[key])
            if key=="rounding" and value not in {0, 100, 500, 1000}:
                raise StoreError("INPUT")
        else:
            raise StoreError("INPUT")
        with self.repo.connection(True) as conn:
            conn.execute("INSERT OR REPLACE INTO sosmed_settings VALUES(?,?,?)", (key, encoded(value), time.time()))
        self.repo.audit(actor, "setting", {"key": key, "value": value})

    def balance(self, user):
        row = self.repo.one("SELECT balance FROM wallets WHERE user_id=?", (number(user, 1),))
        return row["balance"] if row else 0

    async def provider_balance(self):
        response = await self.api.request("balance")
        problem = lambda detail: StoreError('PROVIDER', detail='profile: '+detail, stage='profile')
        if not isinstance(response, dict):
            raise problem('data profil harus berupa objek JSON.')
        containers = [response]+[response[key] for key in ('profile', 'account', 'user') if isinstance(response.get(key), dict)]
        values, currencies = [], []
        try:
            for item in containers:
                values.extend(decimal(item[key]) for key in ('balance', 'saldo') if key in item)
                for key in ('currency', 'mata_uang'):
                    if key in item and item[key] is not None:
                        raw = item[key]
                        if not isinstance(raw, str) or not re.fullmatch(r'[A-Za-z]{3}', raw.strip()):
                            raise problem('currency/mata_uang harus kode tiga huruf seperti IDR.')
                        currencies.append(raw.strip().upper())
        except StoreError as exc:
            if exc.stage == 'profile':
                raise
            raise problem('balance/saldo harus angka nonnegatif, tanpa pemisah ribuan atau simbol Rp.') from None
        if not values:
            raise problem('field balance/saldo tidak ditemukan, termasuk di profile/account/user. Cocokkan nama field saldo pada respons profile.')
        if len(set(values)) != 1 or len(set(currencies)) > 1:
            raise problem('field saldo atau mata uang saling bertentangan; respons perlu diperiksa, saldo tidak dipilih secara acak.')
        value = str(values[0])
        if currencies:
            currency, source = currencies[0], "API"
        elif self.provider_units()["currency"]:
            units = self.provider_units()
            currency = units["currency"]
            source = "OWNER_ATTESTATION" if units["currency_source"] == "VARIABLE" else "OWNER_CONFIRMATION"
        else:
            currency, source = "", "UNAVAILABLE"
        return {"balance": value, "currency": currency, "currency_source": source}

    def purchase_guard(self, user):
        number(user, 1)
        if not self.purchase_contract_verified():
            raise StoreError("CONFIG")
        if not self.settings()["enabled"]:
            raise StoreError("CLOSED")
        if getattr(self.host, "security_blocked", lambda value: False)(user):
            raise StoreError("FORBIDDEN", "Akun kamu dibatasi owner.")
        if not self.owner(user):
            if getattr(self.host, "maintenance_enabled", lambda: False)() or getattr(self.host, "safe_mode_enabled", lambda: False)():
                raise StoreError("CLOSED")

    def health(self):
        row = self.repo.one("SELECT MAX(last_synced_at) AS stamp FROM sosmed_services")
        check = self._last_check or {}
        if check.get('fingerprint') != self.contract_fingerprint():
            check = {}
        return {"connected": check.get('connected', bool(getattr(self.api, "last_ok", False))),
                "checked_at": check.get('checked_at', getattr(self.api, "checked_at", 0)),
                "error": check.get('error', getattr(self.api, "error", "")),
                "stage": check.get('stage', ''), "detail": check.get('detail', ''),
                "http_status": check.get('http_status'),
                "configured": not bool(self.configuration_issues()),
                "configuration_issues": self.configuration_issues(),
                "contract_verified": self.purchase_contract_verified(),
                "refill_verified": bool(self.config.refill_verified),
                "cancel_verified": False,
                "cancel_supported": False,
                "catalog_synced_at": row["stamp"] if row else 0}

    def token(self, user, action, payload=None, ttl=86400):
        if action.startswith("admin"):
            self.require_owner(user)
        ident = secrets.token_urlsafe(9)
        ttl = number(ttl, 1, 86400)
        with self.repo.connection(True) as conn:
            conn.execute("INSERT INTO sosmed_callback_tokens VALUES(?,?,?,?,?)", (ident, user, action, encoded(payload or {}), time.time()+ttl))
            conn.execute("DELETE FROM sosmed_callback_tokens WHERE expires_at<?", (time.time(),))
        return PREFIX+ident

    def resolve(self, user, callback):
        if not isinstance(callback, str) or not callback.startswith(PREFIX):
            raise StoreError("TOKEN")
        row = self.repo.one("SELECT * FROM sosmed_callback_tokens WHERE token=? AND user_id=? AND expires_at>=?", (callback[len(PREFIX):], user, time.time()))
        if not row:
            raise StoreError("TOKEN")
        if row["action"].startswith("admin"):
            self.require_owner(user)
        return row["action"], json.loads(row["payload"])

    def stats(self, actor):
        self.require_owner(actor)
        rows = self.repo.all("SELECT status,COUNT(*) AS count FROM sosmed_orders GROUP BY status")
        states = {row["status"]: row["count"] for row in rows}
        totals = self.repo.one("SELECT COUNT(*) AS total,COALESCE(SUM(selling_price-refund_amount),0) AS revenue,COALESCE(SUM(gross_profit-refund_amount),0) AS gross_profit FROM sosmed_orders")
        totals.update({"states": states, "active": sum(value for key,value in states.items() if key not in TERMINAL),
                       "pending": states.get("PENDING",0), "processing": states.get("PROCESSING",0)+states.get("IN_PROGRESS",0),
                       "failed": states.get('FAILED',0),
                       "completed": states.get("COMPLETED",0), "partial": states.get("PARTIAL",0), "canceled": states.get("CANCELED",0),
                       "reconciliation": self.repo.one("SELECT COUNT(*) AS count FROM sosmed_purchase_attempts WHERE state='RECONCILIATION_REQUIRED'")["count"],
                       "refund_pending": self.repo.one("SELECT COUNT(*) AS count FROM sosmed_orders WHERE refund_state='AWAITING_PROVIDER_PROOF'")["count"],
                       "refill_pending": self.repo.one("SELECT COUNT(*) AS count FROM sosmed_refills WHERE status IN('PENDING','REQUESTING','UNKNOWN')")["count"]})
        # Refunds reduce both user revenue and confirmed provider cost.
        confirmed = self.repo.one("SELECT COALESCE(SUM(provider_amount),0) AS amount FROM sosmed_refunds WHERE status='CREDITED'")["amount"]
        totals["gross_profit"] += confirmed
        return totals

    @staticmethod
    def proof(reference):
        if not isinstance(reference, str) or not 6<=len(reference.strip())<=200 or "\x00" in reference:
            raise StoreError("PROOF")
        return reference.strip()

    async def admin_reconcile(self, user, attempt_id, provider_order_id, proof_ref):
        self.require_owner(user)
        proof = self.proof(proof_ref)
        attempt = self.repo.one("SELECT * FROM sosmed_purchase_attempts WHERE attempt_id=?", (str(attempt_id),))
        if not attempt or attempt["state"]!="RECONCILIATION_REQUIRED":
            raise StoreError("PROOF")
        provider_id = number(provider_order_id, 1)
        response = await self.api.request("status", order=provider_id)
        if not isinstance(response, dict) or not isinstance(response.get("status"), str) or response.get("currency", "IDR")!="IDR":
            raise StoreError("PROOF")
        # The status endpoint cannot prove target/service/buyer association.
        # Owner must verify that association separately on their provider account.
        self.purchase.capture(str(attempt_id), provider_id, proof=proof, actor=user)
        order = self.repo.one("SELECT * FROM sosmed_orders WHERE attempt_id=?", (str(attempt_id),))
        return await self.orders._refresh(order)

    def admin_release(self, user, attempt_id, proof_ref):
        self.require_owner(user)
        proof = self.proof(proof_ref)
        self.purchase.release(str(attempt_id), "OWNER_PROOF_NO_ORDER", proof=proof, actor=user)

    async def admin_refund(self, user, order_id, provider_refund_idr, proof_ref):
        self.require_owner(user)
        proof = self.proof(proof_ref)
        row = await self.orders.refresh(user, order_id, admin=True)
        if row["status"] not in {"PARTIAL", "CANCELED", "FAILED"}:
            raise StoreError("PROOF")
        provider_amount = number(provider_refund_idr, 1, row["provider_cost"])
        # The documented API has no refund receipt endpoint. This operation is
        # deliberately owner-authorized and records their independently checked
        # account credit receipt. A status charge alone does not prove a refund.
        with self.repo.connection(True) as conn:
            existing = conn.execute("SELECT * FROM sosmed_refunds WHERE proof_reference=?", (proof,)).fetchone()
            if existing:
                if existing["order_id"]!=row["id"] or existing["provider_amount"]!=provider_amount:
                    raise StoreError("PROOF")
                return dict(existing)
            current = conn.execute("SELECT * FROM sosmed_orders WHERE id=?", (row["id"],)).fetchone()
            already_provider = conn.execute("SELECT COALESCE(SUM(provider_amount),0) FROM sosmed_refunds WHERE order_id=? AND status='CREDITED'", (row["id"],)).fetchone()[0]
            if already_provider+provider_amount>current["provider_cost"]:
                raise StoreError("PROOF")
            cumulative = current["selling_price"] if already_provider+provider_amount==current["provider_cost"] else int((Decimal(current["selling_price"])*Decimal(already_provider+provider_amount)/Decimal(current["provider_cost"])).to_integral_value(rounding=ROUND_FLOOR))
            amount = cumulative-current["refund_amount"]
            if amount<0:
                raise StoreError("PROOF")
            ident = secrets.token_hex(12)
            WalletAdapter.change(conn, current["user_id"], "SOSMED_REFUND", amount, ident, "Refund SOSMED terverifikasi owner")
            ledger = conn.execute("SELECT id FROM wallet_ledger WHERE user_id=? AND type='SOSMED_REFUND' AND reference=?", (current["user_id"],ident)).fetchone()[0]
            conn.execute("INSERT INTO sosmed_refunds VALUES(?,?,?,?,?,?,?,?)", (ident,current["id"],ledger,amount,provider_amount,proof,"CREDITED",time.time()))
            conn.execute("UPDATE sosmed_orders SET refund_amount=?,refund_state=?,updated_at=? WHERE id=?", (cumulative, "FULL" if cumulative==current["selling_price"] else "PARTIAL", time.time(), current["id"]))
            conn.execute("INSERT INTO sosmed_audit(actor,action,payload,created_at) VALUES(?,?,?,?)", (user,"refund_proof",encoded({"order":current["id"],"proof":proof,"provider_amount":provider_amount,"wallet_amount":amount}),time.time()))
        return self.repo.one("SELECT * FROM sosmed_refunds WHERE refund_id=?", (ident,))

    def lease(self, name, seconds):
        now = time.time()
        with self.repo.connection(True) as conn:
            row = conn.execute("SELECT * FROM sosmed_leases WHERE name=?", (name,)).fetchone()
            if row and row["owner"]!=self._owner_token and row["until_at"]>now:
                return False
            conn.execute("INSERT OR REPLACE INTO sosmed_leases VALUES(?,?,?)", (name,self._owner_token,now+seconds))
            return True

    async def _batch(self):
        await self.orders.poll_once()
        if self.settings()["enabled"] and self.config.token:
            try:
                await self.catalog.sync(return_rows=False)
            except StoreError:
                pass

    async def _heartbeat(self, batch):
        while not batch.done():
            await asyncio.sleep(15)
            try:
                retained = self.lease("status", 90)
            except Exception:
                batch.cancel()
                raise
            if not retained:
                batch.cancel()
                return

    async def worker(self):
        while True:
            batch = heartbeat = None
            try:
                if self.lease("status", 90):
                    batch = asyncio.create_task(self._batch(), name="sosmed-poll-batch")
                    heartbeat = asyncio.create_task(self._heartbeat(batch), name="sosmed-lease-heartbeat")
                    await batch
            except asyncio.CancelledError:
                raise
            except Exception:
                # A provider failure must never take down the host bot.
                pass
            finally:
                for task in (batch, heartbeat):
                    if task and not task.done():
                        task.cancel()
                await asyncio.gather(*(task for task in (batch, heartbeat) if task), return_exceptions=True)
                try:
                    with self.repo.connection(True) as conn:
                        conn.execute("DELETE FROM sosmed_leases WHERE name='status' AND owner=?", (self._owner_token,))
                except sqlite3.Error:
                    pass
            await asyncio.sleep(min(30,self.settings()["poll_seconds"]))

    async def start(self, bot):
        if self._started:
            return []
        self._bot = bot
        try:
            self.purchase.recover()
            self._tasks = [asyncio.create_task(self.worker(), name="sosmed-status-worker")]
        except Exception:
            self._tasks, self._started = [], False
            raise
        self._started = True
        return list(self._tasks)

    async def close(self):
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        self._started = False
        try:
            with self.repo.connection(True) as conn:
                conn.execute("DELETE FROM sosmed_leases WHERE owner=?", (self._owner_token,))
        except sqlite3.Error:
            pass
        await self.api.close()
