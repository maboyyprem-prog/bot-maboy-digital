"""SMSCode.gg v1 store. Uses the host's SQLite wallet, router and HTTP server.

Money POSTs are only replayed by the persistent reconciler with the original
body and idempotency key. No provider credentials or SMS are logged.
"""
import asyncio
import base64
import hashlib
import hmac
import html
import json
import logging
import os
import re
import secrets
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_CEILING
from urllib.parse import urlparse

import aiohttp
from aiohttp import web
from Crypto.Cipher import AES
from aiogram import F
from aiogram.filters import Command
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, LinkPreviewOptions

PREFIX = "smscode_otp:"
USER_BRAND = "MABOYY OTP STORE"
ADMIN_BRAND = "MABOYY OTP ADMIN"
TERMINAL = {"COMPLETED", "CANCELED", "EXPIRED", "FAILED"}
ACTIVE = {"ACTIVE", "OTP_RECEIVED"}
DEFINITIVE = {"UNAUTHORIZED", "FORBIDDEN", "VALIDATION_ERROR", "NO_OFFER_AVAILABLE",
              "INSUFFICIENT_BALANCE", "PROVIDER_ERROR", "NOT_FOUND"}


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def integer(value, minimum=0, maximum=10**12):
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise StoreError("INVALID_RESPONSE", "Nilai rupiah/ID dari provider tidak valid.")
    return value


def money(value):
    return "Rp" + f"{int(value):,}".replace(",", ".")


def escape(value):
    return html.escape(str(value or ""))


def timestamp(value):
    if not value:
        return 0


async def bounded_body(stream, limit):
    parts, size = [], 0
    async for part in stream.iter_chunked(16384):
        size += len(part)
        if size > limit:
            raise StoreError("BODY_TOO_LARGE")
        parts.append(part)
    return b"".join(parts)
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError):
        return 0


class StoreError(Exception):
    def __init__(self, code, message=None, *, uncertain=False, retry_after=0, request_id=""):
        super().__init__(code)
        self.code, self.uncertain = code, uncertain
        self.retry_after, self.request_id = retry_after, str(request_id)[:100]
        messages = {
            "UNAUTHORIZED": "Token SMSCode belum valid. Hubungi owner.",
            "FORBIDDEN": "Akses SMSCode ditolak.", "NOT_FOUND": "Pesanan/produk tidak ditemukan.",
            "INSUFFICIENT_BALANCE": "Saldo provider belum cukup. Hubungi owner.",
            "CANCEL_TOO_EARLY": "Nomor belum boleh dibatalkan. Tunggu batas waktu provider.",
            "NO_OFFER_AVAILABLE": "Stok nomor habis atau harga provider berubah.",
            "REQUEST_IN_PROGRESS": "Transaksi sedang diproses; jangan membeli ulang.",
            "IDEMPOTENCY_KEY_REUSED": "Transaksi perlu diperiksa owner; saldo tetap ditahan.",
            "RATE_LIMIT_EXCEEDED": "Provider membatasi permintaan. Coba kembali setelah jeda.",
            "TEMP_BANNED_ABUSE_GUARD": "Provider meminta jeda penggunaan.",
            "SERVICE_UNAVAILABLE": "Provider sementara tidak tersedia.",
            "NETWORK": "Koneksi provider belum memberikan hasil pasti.",
            "CONFLICT": "Status nomor belum mengizinkan tindakan ini.",
            "PROVIDER_ERROR": "Provider tidak dapat memproses permintaan.",
            "VALIDATION_ERROR": "Provider menolak parameter permintaan.",
        }
        self.public = message or messages.get(code, "Layanan OTP perlu diperiksa. Coba kembali nanti.")


@dataclass
class Config:
    token: str = ""
    base_url: str = "https://api.smscode.gg/v1"
    webhook_secret: str = ""
    webhook_url: str = ""
    enabled: bool = True
    mode: str = "percent"
    percent: str = "25"
    fixed: int = 0
    rounding: int = 100
    max_active: int = 2
    max_cost: int = 20000
    poll_seconds: int = 10
    quote_ttl: int = 60
    timeout: int = 15
    retries: int = 8
    retention_hours: int = 24
    hourly_limit: int = 60
    purchase_cooldown: int = 5
    error: str = ""

    @classmethod
    def environment(cls):
        c = cls()
        try:
            c.token = os.getenv("SMSCODE_API_TOKEN", "").strip()
            c.base_url = os.getenv("SMSCODE_API_BASE_URL", c.base_url).strip().rstrip("/")
            if c.base_url != "https://api.smscode.gg/v1":
                raise ValueError("SMSCODE_API_BASE_URL wajib https://api.smscode.gg/v1")
            c.webhook_secret = os.getenv("SMSCODE_WEBHOOK_SECRET", "").strip()
            c.webhook_url = os.getenv("SMSCODE_WEBHOOK_PUBLIC_URL", "").strip()
            if c.webhook_url and (urlparse(c.webhook_url).scheme != "https" or
                                  urlparse(c.webhook_url).path != "/webhooks/smscode/otp"):
                raise ValueError("URL webhook harus HTTPS dengan path /webhooks/smscode/otp")
            c.enabled = os.getenv("SMSCODE_OTP_ENABLED", "true").lower() in ("true", "1", "yes")
            c.mode = os.getenv("OTP_MARKUP_MODE", "percent").lower()
            c.percent = str(Decimal(os.getenv("OTP_MARKUP_PERCENT", "25")))
            if c.mode not in {"percent", "fixed", "combined"} or not Decimal(c.percent).is_finite() or not 0 <= Decimal(c.percent) <= 10000:
                raise ValueError("Mode/markup OTP tidak valid")
            for name, env, low, high in [
                ("fixed", "OTP_MARKUP_FIXED_IDR", 0, 10**9),
                ("rounding", "OTP_PRICE_ROUNDING_IDR", 0, 1000),
                ("max_active", "OTP_MAX_ACTIVE_ORDERS_PER_USER", 1, 20),
                ("max_cost", "OTP_MAX_PROVIDER_PRICE_IDR", 1, 10**9),
                ("poll_seconds", "OTP_POLL_INTERVAL_SECONDS", 10, 300),
                ("quote_ttl", "OTP_QUOTE_TTL_SECONDS", 15, 300),
                ("timeout", "OTP_HTTP_TIMEOUT_SECONDS", 3, 60),
                ("retries", "OTP_DELIVERY_MAX_RETRIES", 1, 30),
                ("retention_hours", "OTP_SMS_RETENTION_HOURS", 1, 720),
                ("hourly_limit", "OTP_MAX_PURCHASES_PER_HOUR", 1, 1000),
                ("purchase_cooldown", "OTP_PURCHASE_COOLDOWN_SECONDS", 1, 300),
            ]:
                value = int(os.getenv(env, str(getattr(c, name))))
                if not low <= value <= high:
                    raise ValueError(env + " di luar batas")
                setattr(c, name, value)
            if c.rounding not in {0, 100, 500, 1000}:
                raise ValueError("Pembulatan OTP: 0, 100, 500 atau 1000")
        except (ValueError, InvalidOperation) as exc:
            c.error, c.enabled = str(exc), False
        return c


def init_schema(conn):
    # Additive only; never replaces the existing wallet, orders or deposit tables.
    statements = [
        """CREATE TABLE IF NOT EXISTS otp_settings(key TEXT PRIMARY KEY,value TEXT NOT NULL,updated_at REAL NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS otp_pricing_rules(scope TEXT NOT NULL,scope_key TEXT NOT NULL,rule TEXT NOT NULL,
           updated_at REAL NOT NULL,PRIMARY KEY(scope,scope_key))""",
        """CREATE TABLE IF NOT EXISTS otp_quotes(quote_id TEXT PRIMARY KEY,buyer_user_id INTEGER NOT NULL,
           product TEXT NOT NULL,provider_price_idr INTEGER NOT NULL CHECK(provider_price_idr>=0),
           selling_price_idr INTEGER NOT NULL CHECK(selling_price_idr>=0),pricing_rule_snapshot TEXT NOT NULL,
           parent_order_id INTEGER,expires_at REAL NOT NULL,status TEXT NOT NULL DEFAULT 'OPEN')""",
        """CREATE TABLE IF NOT EXISTS otp_purchase_attempts(attempt_id TEXT PRIMARY KEY,quote_id TEXT NOT NULL UNIQUE,
           user_id INTEGER NOT NULL,idempotency_key TEXT NOT NULL UNIQUE,request_body TEXT NOT NULL,request_hash TEXT NOT NULL,
           state TEXT NOT NULL,provider_order_id INTEGER UNIQUE,hold_idr INTEGER NOT NULL CHECK(hold_idr>=0),
           created_at REAL NOT NULL,updated_at REAL NOT NULL,next_retry_at REAL NOT NULL DEFAULT 0,
           retries INTEGER NOT NULL DEFAULT 0,lease_owner TEXT,lease_until REAL NOT NULL DEFAULT 0,error_code TEXT)""",
        """CREATE TABLE IF NOT EXISTS otp_orders(id INTEGER PRIMARY KEY AUTOINCREMENT,buyer_user_id INTEGER NOT NULL,
           provider_order_id INTEGER NOT NULL UNIQUE,parent_order_id INTEGER,attempt_id TEXT NOT NULL UNIQUE,
           country_id INTEGER,platform_id INTEGER,operator_id INTEGER,product_id INTEGER,catalog_product_id INTEGER,
           country_name TEXT NOT NULL,platform_name TEXT NOT NULL,operator_name TEXT NOT NULL,phone_number TEXT NOT NULL,
           provider_cost_idr INTEGER NOT NULL CHECK(provider_cost_idr>=0),selling_price_idr INTEGER NOT NULL CHECK(selling_price_idr>=0),
           gross_profit_idr INTEGER NOT NULL,status TEXT NOT NULL,created_at REAL NOT NULL,expires_at TEXT,
           updated_at REAL NOT NULL,completed_at REAL,last_sms_revision INTEGER NOT NULL DEFAULT 0,
           idempotency_key TEXT NOT NULL UNIQUE,capabilities TEXT NOT NULL DEFAULT '{}',refund_idr INTEGER NOT NULL DEFAULT 0,
           refund_state TEXT NOT NULL DEFAULT 'NONE',provider_refund_idr INTEGER NOT NULL DEFAULT 0,
           next_poll_at REAL NOT NULL DEFAULT 0)""",
        """CREATE TABLE IF NOT EXISTS otp_sms_events(provider_order_id INTEGER NOT NULL,sms_revision INTEGER NOT NULL,
           encrypted_payload TEXT NOT NULL,received_at REAL NOT NULL,source TEXT NOT NULL,
           PRIMARY KEY(provider_order_id,sms_revision))""",
        """CREATE TABLE IF NOT EXISTS otp_notifications(notification_id INTEGER PRIMARY KEY AUTOINCREMENT,
           dedup_key TEXT NOT NULL UNIQUE,order_id INTEGER NOT NULL,provider_order_id INTEGER NOT NULL,
           sms_revision INTEGER NOT NULL,user_id INTEGER NOT NULL,kind TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'PENDING',
           attempts INTEGER NOT NULL DEFAULT 0,next_retry_at REAL NOT NULL DEFAULT 0,sent_at REAL,
           lease_owner TEXT,lease_until REAL NOT NULL DEFAULT 0,error_code TEXT,telegram_message_id INTEGER,
           part_index INTEGER NOT NULL DEFAULT 0)""",
        """CREATE TABLE IF NOT EXISTS otp_webhook_inbox(digest TEXT PRIMARY KEY,provider_order_id INTEGER NOT NULL,
           encrypted_payload TEXT NOT NULL,created_at REAL NOT NULL,status TEXT NOT NULL DEFAULT 'PENDING')""",
        """CREATE TABLE IF NOT EXISTS otp_actions(id INTEGER PRIMARY KEY AUTOINCREMENT,order_id INTEGER NOT NULL,
           action TEXT NOT NULL,state TEXT NOT NULL,created_at REAL NOT NULL,updated_at REAL NOT NULL,
           response TEXT,error_code TEXT,lease_owner TEXT,lease_until REAL NOT NULL DEFAULT 0,next_retry_at REAL NOT NULL DEFAULT 0)""",
        """CREATE TABLE IF NOT EXISTS otp_callback_tokens(token TEXT PRIMARY KEY,user_id INTEGER NOT NULL,
           action TEXT NOT NULL,payload TEXT NOT NULL,expires_at REAL NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS otp_rate_limits(user_id INTEGER NOT NULL,action TEXT NOT NULL,
           window REAL NOT NULL,count INTEGER NOT NULL,PRIMARY KEY(user_id,action))""",
        """CREATE TABLE IF NOT EXISTS otp_worker_leases(name TEXT PRIMARY KEY,owner TEXT NOT NULL,until_ts REAL NOT NULL)""",
        "CREATE INDEX IF NOT EXISTS idx_otp_user_orders ON otp_orders(buyer_user_id,status,created_at)",
        "CREATE INDEX IF NOT EXISTS idx_otp_attempt_due ON otp_purchase_attempts(state,next_retry_at,lease_until)",
        "CREATE INDEX IF NOT EXISTS idx_otp_notification_due ON otp_notifications(status,next_retry_at,lease_until)",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_otp_action_pending ON otp_actions(order_id) WHERE state IN ('REQUESTING','PENDING_RECONCILIATION')",
    ]
    for statement in statements:
        conn.execute(statement)
    # A restart after a partially deployed 16.78 remains additive/idempotent.
    if "provider_refund_idr" not in {row[1] for row in conn.execute("PRAGMA table_info(otp_orders)")}:
        conn.execute("ALTER TABLE otp_orders ADD COLUMN provider_refund_idr INTEGER NOT NULL DEFAULT 0")


class APIClient:
    def __init__(self, config):
        self.config, self.session = config, None
        self.last_ok, self.last_error, self.blocked_until, self.last_request_id = 0, "", 0, ""

    async def request(self, method, path, *, params=None, body=None, key=None):
        if not self.config.token or self.config.error:
            raise StoreError("NOT_CONFIGURED", "Toko OTP belum dikonfigurasi owner.")
        if time.time() < self.blocked_until:
            raise StoreError("RATE_LIMIT_EXCEEDED", retry_after=self.blocked_until-time.time(), uncertain=method != "GET")
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self.config.timeout), trust_env=True)
        headers = {"Authorization": "Bearer " + self.config.token, "Accept": "application/json"}
        if key:
            headers["Idempotency-Key"] = key
        try:
            async with self.session.request(method, self.config.base_url + path, params=params, json=body,
                                            headers=headers, allow_redirects=False) as response:
                request_id = response.headers.get("X-Request-Id", "")
                self.last_request_id = request_id[:100]
                try:
                    retry = min(86400, max(0, float(response.headers.get("Retry-After", "0"))))
                except ValueError:
                    retry = 0
                if response.status in (429, 503):
                    self.blocked_until = time.time() + max(retry, 10)
                try:
                    raw = await bounded_body(response.content, 1024*1024)
                except StoreError:
                    raise StoreError("INVALID_RESPONSE", uncertain=method != "GET") from None
                try:
                    result = json.loads(raw)
                except (ValueError, UnicodeDecodeError):
                    raise StoreError("INVALID_RESPONSE", uncertain=method != "GET")
                if not isinstance(result, dict):
                    raise StoreError("INVALID_RESPONSE", uncertain=method != "GET")
                if response.status < 200 or response.status >= 300 or result.get("success") is not True:
                    error = result.get("error") or {}
                    code = str(error.get("code") or "INVALID_RESPONSE") if isinstance(error, dict) else "INVALID_RESPONSE"
                    raise StoreError(code, uncertain=method != "GET" and code not in DEFINITIVE,
                                     retry_after=retry, request_id=request_id)
                if "data" not in result:
                    raise StoreError("INVALID_RESPONSE", uncertain=method != "GET")
                self.last_ok, self.last_error = time.time(), ""
                return result["data"]
        except StoreError as exc:
            self.last_error = exc.code
            request_id = re.sub(r"[^A-Za-z0-9_.:-]", "", exc.request_id)[:80]
            logging.warning("SMSCode API error code=%s request_id=%s", exc.code, request_id or "-")
            raise
        except (asyncio.TimeoutError, aiohttp.ClientError, OSError):
            self.last_error = "NETWORK"
            raise StoreError("NETWORK", uncertain=method != "GET") from None

    async def close(self):
        if self.session is not None:
            await self.session.close()


class Repository:
    def __init__(self, host):
        self.host = host

    @contextmanager
    def connection(self, write=False):
        conn = self.host.db()
        try:
            if write:
                # Stronger durability only for OTP writes; host transaction logic
                # and database engine remain unchanged.
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

    def one(self, sql, params=()):
        with self.connection() as conn:
            row = conn.execute(sql, params).fetchone()
            return dict(row) if row else None

    def rows(self, sql, params=()):
        with self.connection() as conn:
            return [dict(row) for row in conn.execute(sql, params).fetchall()]

    def execute(self, sql, params=()):
        with self.connection(True) as conn:
            return conn.execute(sql, params).rowcount

    def owned(self, user, order_id):
        try:
            order_id = int(order_id)
        except (ValueError, TypeError):
            raise StoreError("NOT_FOUND") from None
        row = self.one("SELECT * FROM otp_orders WHERE id=? AND buyer_user_id=?", (order_id, user))
        if not row:
            raise StoreError("NOT_FOUND")
        return row

    def rate(self, user, action, count=10, seconds=60):
        now = time.time()
        with self.connection(True) as conn:
            row = conn.execute("SELECT * FROM otp_rate_limits WHERE user_id=? AND action=?", (user, action)).fetchone()
            new_window = not row or now-row["window"] >= seconds
            hits = 1 if new_window else row["count"]+1
            if hits > count:
                raise StoreError("COOLDOWN", "Terlalu banyak permintaan. Tunggu sebentar.")
            conn.execute("INSERT OR REPLACE INTO otp_rate_limits VALUES(?,?,?,?)",
                         (user, action, now if new_window else row["window"], hits))


class WalletAdapter:
    @staticmethod
    def change(conn, user, kind, amount, reference):
        previous = conn.execute("SELECT id FROM wallet_ledger WHERE user_id=? AND type=? AND reference=?",
                                (user, kind, reference)).fetchone()
        if previous:
            return False
        now = datetime.now().isoformat(timespec="seconds")
        conn.execute("INSERT OR IGNORE INTO wallets(user_id,balance,updated_at) VALUES(?,0,?)", (user, now))
        old = conn.execute("SELECT balance FROM wallets WHERE user_id=?", (user,)).fetchone()[0]
        new = old + amount
        if new < 0:
            raise StoreError("USER_BALANCE", "Saldo kamu tidak cukup. Isi saldo melalui menu deposit yang tersedia.")
        integer(new)
        conn.execute("UPDATE wallets SET balance=?,updated_at=? WHERE user_id=?", (new, now, user))
        conn.execute("""INSERT INTO wallet_ledger(user_id,type,amount,balance_after,reference,note,created_at)
                     VALUES(?,?,?,?,?,'SMSCode OTP',?)""", (user, kind, amount, new, reference, now))
        return True


class PricingService:
    def __init__(self, store):
        self.store = store

    def calculate(self, product, cost=None):
        cost = integer(product.get("price") if cost is None else cost)
        settings = self.store.settings()
        rule = {"mode": settings["mode"], "percent": settings["percent"], "fixed": settings["fixed"]}
        scopes = [("product", str(product["id"])),
                  ("country_service", f"{product.get('country_id')}:{product.get('platform_id')}"),
                  ("service", str(product.get("platform_id"))), ("country", str(product.get("country_id")))]
        scope = "global"
        for kind, key in scopes:
            found = self.store.repo.one("SELECT rule FROM otp_pricing_rules WHERE scope=? AND scope_key=?", (kind, key))
            if found:
                rule, scope = json.loads(found["rule"]), kind + ":" + key
                break
        if "sale" in rule:
            sale = integer(rule["sale"])
        else:
            base = Decimal(cost)
            if rule["mode"] in {"percent", "combined"}:
                base *= 1 + Decimal(str(rule.get("percent", "0")))/100
            if rule["mode"] in {"fixed", "combined"}:
                base += integer(rule.get("fixed", 0))
            sale = int(base.to_integral_value(rounding=ROUND_CEILING))
        rounding = settings["rounding"]
        if rounding:
            sale = ((sale + rounding - 1)//rounding)*rounding
        integer(sale)
        if sale < cost and not settings["allow_loss"]:
            raise StoreError("BELOW_COST", "Harga jual berada di bawah modal; owner perlu memperbarui harga.")
        snapshot = {"scope": scope, "rule": rule, "rounding": rounding, "allow_loss": settings["allow_loss"]}
        return sale, encoded(snapshot)


class CatalogService:
    def __init__(self, store):
        self.store = store

    async def listing(self, path, params=None):
        rows = await self.store.api.request("GET", path, params=params)
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise StoreError("INVALID_RESPONSE")
        return rows

    async def products(self, country, platform, operator=None, page=1):
        params = {"country_id": country, "platform_id": platform, "page": page, "limit": 50, "sort": "price_asc"}
        if operator is not None:
            params["operator_id"] = operator
        raw = await self.listing("/catalog/products", params)
        rows = [row for row in raw if row.get("active") is True and isinstance(row.get("available"), int)
                and row["available"] > 0 and row.get("country_id") == country
                and row.get("platform_id") == platform and row.get("operator_id") == operator
                and isinstance(row.get("catalog_product_id"), int)]
        return rows, len(raw) == 50

    async def live_product(self, product):
        for page in range(1, 201):
            rows, more = await self.products(product["country_id"], product["platform_id"], product.get("operator_id"), page)
            for row in rows:
                if row["id"] == product["id"] and row["catalog_product_id"] == product["catalog_product_id"]:
                    return {**product, **row}
            if not more:
                break
        raise StoreError("NO_OFFER_AVAILABLE")


class PurchaseService:
    def __init__(self, store):
        self.store = store

    async def quote(self, user, product, parent=None):
        self.store.require_ready()
        if parent:
            current = await self.store.api.request("GET", f"/orders/{parent['provider_order_id']}")
            if current.get("can_reactivate") is not True:
                raise StoreError("CONFLICT", "Nomor ini belum mendukung reaktivasi.")
            options = await self.store.api.request("GET", f"/orders/{parent['provider_order_id']}/reactivate-options")
            cost = integer(options.get("cost"))
        else:
            product = await self.store.catalog.live_product(product)
            cost = integer(product["price"])
        if cost > self.store.config.max_cost:
            raise StoreError("PRICE_LIMIT", "Modal nomor melebihi batas toko.")
        sale, rule = self.store.pricing.calculate(product, cost)
        quote_id = secrets.token_urlsafe(12)
        self.store.repo.execute("""INSERT INTO otp_quotes(quote_id,buyer_user_id,product,provider_price_idr,
               selling_price_idr,pricing_rule_snapshot,parent_order_id,expires_at) VALUES(?,?,?,?,?,?,?,?)""",
               (quote_id, user, encoded(product), cost, sale, rule, parent["id"] if parent else None,
                time.time()+self.store.config.quote_ttl))
        return self.store.repo.one("SELECT * FROM otp_quotes WHERE quote_id=?", (quote_id,))

    async def buy(self, user, quote_id):
        self.store.require_ready()
        quote = self.store.repo.one("SELECT * FROM otp_quotes WHERE quote_id=? AND buyer_user_id=?", (quote_id, user))
        if not quote:
            raise StoreError("NOT_FOUND")
        existing = self.store.repo.one("SELECT * FROM otp_purchase_attempts WHERE quote_id=?", (quote_id,))
        if existing:
            return existing
        if quote["status"] != "OPEN" or quote["expires_at"] <= time.time():
            raise StoreError("QUOTE_EXPIRED", "Konfirmasi harga kedaluwarsa. Pilih produk lagi.")
        product = json.loads(quote["product"])
        parent = self.store.repo.owned(user, quote["parent_order_id"]) if quote["parent_order_id"] else None
        if parent:
            current = await self.store.api.request("GET", f"/orders/{parent['provider_order_id']}")
            if current.get("can_reactivate") is not True:
                raise StoreError("CONFLICT")
            fresh = await self.store.api.request("GET", f"/orders/{parent['provider_order_id']}/reactivate-options")
            cost = integer(fresh.get("cost"))
        else:
            fresh = await self.store.catalog.live_product(product)
            cost = integer(fresh["price"])
        sale, rule = self.store.pricing.calculate(product, cost)
        if cost != quote["provider_price_idr"] or sale != quote["selling_price_idr"] or rule != quote["pricing_rule_snapshot"]:
            self.store.repo.execute("UPDATE otp_quotes SET status='PRICE_CHANGED' WHERE quote_id=?", (quote_id,))
            raise StoreError("PRICE_CHANGED", "Harga berubah. Pilih kembali produk untuk menyetujui harga terbaru.")
        body = {"id": parent["provider_order_id"], "max_price": cost} if parent else {
            "catalog_product_id": product["catalog_product_id"], "quantity": 1, "max_price": cost}
        if not parent and product.get("operator_id") is not None:
            body["operator_id"] = product["operator_id"]
        attempt_id, key, now = secrets.token_urlsafe(18), secrets.token_hex(24), time.time()
        with self.store.repo.connection(True) as conn:
            duplicate = conn.execute("SELECT * FROM otp_purchase_attempts WHERE quote_id=?", (quote_id,)).fetchone()
            if duplicate:
                return dict(duplicate)
            settings = self.store.settings(conn)
            if not settings["enabled"]:
                raise StoreError("DISABLED", "Pembelian baru sedang ditutup owner.")
            live_quote = conn.execute("SELECT * FROM otp_quotes WHERE quote_id=?", (quote_id,)).fetchone()
            if live_quote["status"] != "OPEN" or live_quote["expires_at"] <= now:
                raise StoreError("QUOTE_EXPIRED", "Konfirmasi kedaluwarsa. Pilih produk lagi.")
            active = conn.execute("SELECT count(*) FROM otp_orders WHERE buyer_user_id=? AND status IN ('ACTIVE','OTP_RECEIVED')", (user,)).fetchone()[0]
            pending = conn.execute("SELECT count(*) FROM otp_purchase_attempts WHERE user_id=? AND state IN ('RESERVED','REQUESTING','PENDING_RECONCILIATION')", (user,)).fetchone()[0]
            if active + pending >= settings["max_active"]:
                raise StoreError("ORDER_LIMIT", "Batas pesanan aktif tercapai. Selesaikan pesanan sebelumnya.")
            recent = conn.execute("SELECT count(*) FROM otp_purchase_attempts WHERE user_id=? AND created_at>?", (user, now-3600)).fetchone()[0]
            latest = conn.execute("SELECT max(created_at) FROM otp_purchase_attempts WHERE user_id=?", (user,)).fetchone()[0]
            if recent >= settings["hourly_limit"] or latest and now-latest < settings["purchase_cooldown"]:
                raise StoreError("COOLDOWN", "Batas/jeda pembelian tercapai. Tunggu sebelum membeli lagi.")
            WalletAdapter.change(conn, user, "OTP_HOLD", -sale, "OTP:"+attempt_id)
            conn.execute("""INSERT INTO otp_purchase_attempts(attempt_id,quote_id,user_id,idempotency_key,request_body,
                 request_hash,state,hold_idr,created_at,updated_at) VALUES(?,?,?,?,?,?,'RESERVED',?,?,?)""",
                 (attempt_id, quote_id, user, key, encoded(body), hashlib.sha256(encoded(body).encode()).hexdigest(), sale, now, now))
            conn.execute("UPDATE otp_quotes SET status='RESERVED' WHERE quote_id=?", (quote_id,))
        await self.process(attempt_id)
        return self.store.repo.one("SELECT * FROM otp_purchase_attempts WHERE attempt_id=?", (attempt_id,))

    async def process(self, attempt_id):
        owner, now = secrets.token_hex(12), time.time()
        with self.store.repo.connection(True) as conn:
            row = conn.execute("SELECT * FROM otp_purchase_attempts WHERE attempt_id=?", (attempt_id,)).fetchone()
            if not row or row["state"] not in {"RESERVED", "REQUESTING", "PENDING_RECONCILIATION"} or row["lease_until"] > now or row["next_retry_at"] > now:
                return
            attempt = dict(row)
            quote = dict(conn.execute("SELECT * FROM otp_quotes WHERE quote_id=?", (row["quote_id"],)).fetchone())
            conn.execute("UPDATE otp_purchase_attempts SET state='REQUESTING',lease_owner=?,lease_until=?,updated_at=? WHERE attempt_id=?",
                         (owner, now+self.store.config.timeout+30, now, attempt_id))
        try:
            if hashlib.sha256(attempt["request_body"].encode()).hexdigest() != attempt["request_hash"]:
                raise StoreError("REQUEST_HASH", uncertain=True)
            data = await self.store.api.request("POST", "/orders/reactivate" if quote["parent_order_id"] else "/orders/create",
                       body=json.loads(attempt["request_body"]), key=attempt["idempotency_key"])
            self.capture(attempt, quote, data, owner)
        except StoreError as exc:
            if exc.code in DEFINITIVE and not exc.uncertain and attempt["state"] == "RESERVED":
                # A definitive first response confirms no order. An uncertain prior
                # attempt must never be released based on a later generic error.
                self.release(attempt, exc.code, owner)
            else:
                self.defer(attempt, owner, exc.code, exc.retry_after)
        except (sqlite3.Error, ValueError, TypeError, KeyError):
            self.defer(attempt, owner, "LOCAL_PERSISTENCE_OR_RESPONSE", 30)

    def capture(self, attempt, quote, data, owner):
        orders = data.get("orders") if isinstance(data, dict) else None
        if not isinstance(orders, list) or len(orders) != 1 or not isinstance(orders[0], dict):
            if orders == [] and data.get("failed_count") == 1:
                raise StoreError("PROVIDER_ERROR")
            raise StoreError("INVALID_RESPONSE", uncertain=True)
        order, product = orders[0], json.loads(quote["product"])
        provider_id, cost = integer(order.get("id"), 1), integer(order.get("amount"))
        number = order.get("phone_number")
        if cost > quote["provider_price_idr"] or not isinstance(number, str) or not re.fullmatch(r"\+?[0-9]{5,20}", number):
            raise StoreError("INVALID_RESPONSE", uncertain=True)
        if order.get("catalog_product_id") != product["catalog_product_id"] or order.get("operator_id") != product.get("operator_id") or order.get("status") not in ACTIVE:
            raise StoreError("INVALID_RESPONSE", uncertain=True)
        if quote["parent_order_id"]:
            parent = self.store.repo.owned(attempt["user_id"], quote["parent_order_id"])
            if number != parent["phone_number"] or provider_id == parent["provider_order_id"]:
                raise StoreError("INVALID_RESPONSE", uncertain=True)
        sale, now, reference = quote["selling_price_idr"], time.time(), "OTP:"+attempt["attempt_id"]
        with self.store.repo.connection(True) as conn:
            current = conn.execute("SELECT * FROM otp_purchase_attempts WHERE attempt_id=?", (attempt["attempt_id"],)).fetchone()
            if current["state"] == "CAPTURED":
                return
            if current["lease_owner"] != owner or current["state"] != "REQUESTING":
                raise StoreError("LEASE_LOST", uncertain=True)
            cursor = conn.execute("""INSERT INTO otp_orders(buyer_user_id,provider_order_id,parent_order_id,attempt_id,
                 country_id,platform_id,operator_id,product_id,catalog_product_id,country_name,platform_name,operator_name,
                 phone_number,provider_cost_idr,selling_price_idr,gross_profit_idr,status,created_at,expires_at,updated_at,
                 idempotency_key,capabilities) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                 (attempt["user_id"], provider_id, quote["parent_order_id"], attempt["attempt_id"], product.get("country_id"),
                  product.get("platform_id"), product.get("operator_id"), integer(order.get("product_id"), 1),
                  product["catalog_product_id"], product.get("country_name", ""), product.get("platform_name", ""),
                  product.get("operator_name") or "Any", number, cost, sale, sale-cost, order["status"], now,
                  order.get("expires_at"), now, attempt["idempotency_key"], self.store.capabilities(order)))
            WalletAdapter.change(conn, attempt["user_id"], "OTP_CAPTURE_RELEASE", sale, reference)
            WalletAdapter.change(conn, attempt["user_id"], "PURCHASE", -sale, reference)
            conn.execute("UPDATE otp_purchase_attempts SET state='CAPTURED',provider_order_id=?,updated_at=?,lease_until=0,lease_owner=NULL WHERE attempt_id=?",
                         (provider_id, now, attempt["attempt_id"]))
            conn.execute("UPDATE otp_quotes SET status='CAPTURED' WHERE quote_id=?", (quote["quote_id"],))
            self.store.queue(conn, cursor.lastrowid, provider_id, attempt["user_id"], "PURCHASE", 0)
        # Inbox deliveries that arrived before this mapping are processed by worker.

    def release(self, attempt, code, owner):
        with self.store.repo.connection(True) as conn:
            row = conn.execute("SELECT * FROM otp_purchase_attempts WHERE attempt_id=?", (attempt["attempt_id"],)).fetchone()
            if row["state"] == "CAPTURED" or row["lease_owner"] != owner:
                return
            WalletAdapter.change(conn, row["user_id"], "OTP_RELEASE", row["hold_idr"], "OTP:"+row["attempt_id"])
            conn.execute("UPDATE otp_purchase_attempts SET state='FAILED',error_code=?,lease_until=0,lease_owner=NULL,updated_at=? WHERE attempt_id=?",
                         (code, time.time(), row["attempt_id"]))
            conn.execute("UPDATE otp_quotes SET status='FAILED' WHERE quote_id=?", (row["quote_id"],))

    def defer(self, attempt, owner, code, retry):
        delay = max(retry, min(3600, 10*2**min(attempt["retries"], 8)))
        self.store.repo.execute("""UPDATE otp_purchase_attempts SET state='PENDING_RECONCILIATION',error_code=?,
            retries=retries+1,next_retry_at=?,lease_owner=NULL,lease_until=0,updated_at=? WHERE attempt_id=? AND lease_owner=?""",
            (code, time.time()+delay, time.time(), attempt["attempt_id"], owner))


class SMSEventProcessor:
    def __init__(self, store):
        self.store = store

    def process(self, data, source):
        provider_id = integer(data.get("order_id", data.get("id")), 1)
        revision = integer(data.get("sms_revision"), 1)
        code, message = data.get("otp_code"), data.get("otp_message")
        if code is not None and not isinstance(code, str) or message is not None and not isinstance(message, str):
            raise StoreError("INVALID_RESPONSE")
        if not code and not message:
            return False
        if len(code or "") > 2048 or len(message or "") > 100000:
            raise StoreError("INVALID_RESPONSE")
        payload = self.store.encrypt({"otp_code": code, "otp_message": message})
        with self.store.repo.connection(True) as conn:
            order = conn.execute("SELECT * FROM otp_orders WHERE provider_order_id=?", (provider_id,)).fetchone()
            if not order:
                return False
            for field in ("phone_number", "product_id", "catalog_product_id", "operator_id"):
                if field in data and data[field] != order[field]:
                    raise StoreError("ORDER_IDENTITY", "Snapshot SMS tidak cocok dengan pesanan lokal.")
            if revision <= order["last_sms_revision"]:
                return True
            # Both webhook and polling share this unique revision and queue.
            conn.execute("INSERT OR IGNORE INTO otp_sms_events VALUES(?,?,?,?,?)", (provider_id, revision, payload, time.time(), source))
            conn.execute("UPDATE otp_orders SET last_sms_revision=?,status=CASE WHEN status='ACTIVE' THEN 'OTP_RECEIVED' ELSE status END,updated_at=? WHERE id=?", (revision, time.time(), order["id"]))
            self.store.queue(conn, order["id"], provider_id, order["buyer_user_id"], "SMS", revision)
        return True


class RefundService:
    def __init__(self, store):
        self.store = store

    def confirm(self, order, response):
        if not isinstance(response, dict) or response.get("order_id") != order["provider_order_id"] or response.get("status") not in {"CANCELED", "EXPIRED"}:
            raise StoreError("INVALID_RESPONSE", uncertain=True)
        try:
            amount = integer(response.get("refund_amount"))
        except StoreError:
            raise StoreError("INVALID_RESPONSE", uncertain=True) from None
        with self.store.repo.connection(True) as conn:
            current = conn.execute("SELECT * FROM otp_orders WHERE id=?", (order["id"],)).fetchone()
            if current["refund_state"] == "REFUNDED":
                return
            if current["status"] == "COMPLETED" or current["last_sms_revision"] > 0:
                conn.execute("UPDATE otp_orders SET refund_state='REVIEW_REQUIRED' WHERE id=?", (order["id"],))
                return
            if amount < current["provider_cost_idr"]:
                conn.execute("UPDATE otp_orders SET status=?,refund_state='PARTIAL_RECONCILIATION',provider_refund_idr=?,updated_at=? WHERE id=?",
                             (response["status"], amount, time.time(), order["id"]))
                return
            WalletAdapter.change(conn, current["buyer_user_id"], "REFUND", current["selling_price_idr"], "OTP:ORDER:"+str(order["id"]))
            conn.execute("UPDATE otp_orders SET status=?,refund_idr=selling_price_idr,refund_state='REFUNDED',provider_refund_idr=?,updated_at=? WHERE id=?",
                         (response["status"], amount, time.time(), order["id"]))
            self.store.queue(conn, order["id"], order["provider_order_id"], order["buyer_user_id"], "REFUND", 0)


class OrderService:
    def __init__(self, store):
        self.store = store

    async def refresh(self, order):
        data = await self.store.api.request("GET", f"/orders/{order['provider_order_id']}")
        self.apply(order, data)
        return data

    def apply(self, order, data):
        if not isinstance(data, dict) or data.get("id") != order["provider_order_id"] or data.get("status") not in ACTIVE | TERMINAL:
            raise StoreError("INVALID_RESPONSE")
        if isinstance(data.get("sms_revision"), int) and data["sms_revision"] > 0 and (data.get("otp_message") or data.get("otp_code")):
            self.store.sms.process(data, "polling")
        now = time.time()
        self.store.repo.execute("""UPDATE otp_orders SET status=CASE WHEN status IN ('COMPLETED','CANCELED','EXPIRED','FAILED')
            THEN status WHEN last_sms_revision>0 AND ?='ACTIVE' THEN 'OTP_RECEIVED' ELSE ? END,capabilities=?,expires_at=COALESCE(?,expires_at),
            updated_at=?,completed_at=CASE WHEN ?='COMPLETED' THEN COALESCE(completed_at,?) ELSE completed_at END,
            next_poll_at=? WHERE id=?""", (data["status"], data["status"], self.store.capabilities(data), data.get("expires_at"),
            now, data["status"], now, now+self.store.config.poll_seconds, order["id"]))
        if data["status"] in {"CANCELED", "EXPIRED"}:
            if "refund_amount" in data:
                self.store.refund.confirm(order, {**data, "order_id": data["id"]})
            else:
                # The official GET schema has no refund_amount. A terminal status
                # alone is insufficient evidence of a credit to the provider wallet.
                self.store.repo.execute("UPDATE otp_orders SET refund_state='AWAITING_PROVIDER_PROOF' WHERE id=? AND refund_state='NONE'", (order["id"],))

    async def action(self, user, order_id, action):
        order = self.store.repo.owned(user, order_id)
        self.store.repo.rate(user, "action:"+action, 3 if action == "resend" else 6, 60)
        data = await self.refresh(order)
        if data.get("can_"+action) is not True:
            at = data.get({"cancel": "cancel_available_at", "resend": "resend_available_at"}.get(action, ""))
            raise StoreError("CONFLICT", "Tindakan belum diizinkan provider." + (" Tersedia: " + str(at) if at else ""))
        if action == "cancel" and (data.get("otp_message") or data.get("otp_code") or data.get("otp_received_at")):
            raise StoreError("CONFLICT", "SMS sudah diterima. Gunakan Selesai.")
        now, owner = time.time(), secrets.token_hex(12)
        with self.store.repo.connection(True) as conn:
            pending = conn.execute("SELECT id FROM otp_actions WHERE order_id=? AND state IN ('REQUESTING','PENDING_RECONCILIATION')", (order["id"],)).fetchone()
            if pending:
                raise StoreError("REQUEST_IN_PROGRESS")
            latest = conn.execute("SELECT max(created_at) FROM otp_actions WHERE order_id=? AND action='resend'", (order["id"],)).fetchone()[0]
            if action == "resend" and latest and now-latest < 30:
                raise StoreError("COOLDOWN", "Tunggu 30 detik sebelum resend berikutnya.")
            cursor = conn.execute("INSERT INTO otp_actions(order_id,action,state,created_at,updated_at,lease_owner,lease_until) VALUES(?,?,'REQUESTING',?,?,?,?)",
                                  (order["id"], action, now, now, owner, now+self.store.config.timeout+30))
            action_id = cursor.lastrowid
        try:
            response = await self.store.api.request("POST", "/orders/"+action, body={"id": order["provider_order_id"]})
            if not isinstance(response, dict) or response.get("order_id") != order["provider_order_id"]:
                raise StoreError("INVALID_RESPONSE", uncertain=True)
            # Persist provider refund proof before updating wallet; restart can replay locally.
            self.store.repo.execute("UPDATE otp_actions SET response=?,updated_at=? WHERE id=?", (encoded(response), time.time(), action_id))
            self.complete(action_id, order, action, response)
            return response
        except StoreError as exc:
            self.store.repo.execute("UPDATE otp_actions SET state=?,error_code=?,lease_owner=NULL,lease_until=0,next_retry_at=?,updated_at=? WHERE id=?",
               ("PENDING_RECONCILIATION" if exc.uncertain else "FAILED", exc.code, time.time()+max(30, exc.retry_after), time.time(), action_id))
            raise
        except sqlite3.Error:
            # REQUESTING remains durable and gets reconciled after the lease expires.
            raise StoreError("LOCAL_DATABASE", "Hasil tindakan akan direkonsiliasi; jangan mengulang.", uncertain=True) from None

    def complete(self, action_id, order, action, response):
        if action in {"cancel", "refund-proof"}:
            self.store.refund.confirm(order, response)
        elif action == "finish":
            if response.get("status") != "COMPLETED":
                raise StoreError("INVALID_RESPONSE", uncertain=True)
            self.store.repo.execute("UPDATE otp_orders SET status='COMPLETED',completed_at=?,updated_at=? WHERE id=?", (time.time(), time.time(), order["id"]))
        elif action == "resend" and response.get("resent") is not True:
            raise StoreError("CONFLICT")
        self.store.repo.execute("UPDATE otp_actions SET state='DONE',updated_at=?,lease_owner=NULL,lease_until=0 WHERE id=?", (time.time(), action_id))

    async def reconcile_actions(self):
        for row in self.store.repo.rows("SELECT * FROM otp_actions WHERE state IN ('REQUESTING','PENDING_RECONCILIATION','PROOF_RECORDED') AND lease_until<? AND next_retry_at<? LIMIT 10", (time.time(), time.time())):
            owner = secrets.token_hex(12)
            if not self.store.repo.execute("UPDATE otp_actions SET lease_owner=?,lease_until=? WHERE id=? AND lease_until<?", (owner, time.time()+self.store.config.timeout+30, row["id"], time.time())):
                continue
            order = self.store.repo.one("SELECT * FROM otp_orders WHERE id=?", (row["order_id"],))
            try:
                if row["response"]:
                    self.complete(row["id"], order, row["action"], json.loads(row["response"]))
                    continue
                data = await self.refresh(order)
                if row["action"] == "finish" and data["status"] == "COMPLETED":
                    self.complete(row["id"], order, "finish", {"order_id": order["provider_order_id"], "status": "COMPLETED"})
                elif row["action"] == "cancel":
                    # GET lacks money proof. Don't infer refund or repeat a money mutation.
                    self.store.repo.execute("UPDATE otp_orders SET refund_state='AWAITING_PROVIDER_PROOF' WHERE id=? AND refund_state!='REFUNDED'", (order["id"],))
                    self.store.repo.execute("UPDATE otp_actions SET next_retry_at=?,state='PENDING_RECONCILIATION',lease_until=0 WHERE id=?", (time.time()+300, row["id"]))
                else:
                    self.store.repo.execute("UPDATE otp_actions SET state='REVIEW_REQUIRED',lease_until=0 WHERE id=?", (row["id"],))
            except (StoreError, sqlite3.Error, ValueError):
                self.store.repo.execute("UPDATE otp_actions SET state='PENDING_RECONCILIATION',next_retry_at=?,lease_until=0 WHERE id=?", (time.time()+60, row["id"]))


class NotificationQueue:
    def __init__(self, store):
        self.store = store

    async def deliver(self, bot):
        now = time.time()
        jobs = self.store.repo.rows("SELECT * FROM otp_notifications WHERE status IN ('PENDING','SENDING') AND next_retry_at<=? AND lease_until<? ORDER BY notification_id LIMIT 20", (now, now))
        for job in jobs:
            owner = secrets.token_hex(12)
            if not self.store.repo.execute("UPDATE otp_notifications SET status='SENDING',lease_owner=?,lease_until=? WHERE notification_id=? AND status IN ('PENDING','SENDING') AND lease_until<?",
                     (owner, time.time()+120, job["notification_id"], time.time())):
                continue
            order = self.store.repo.one("SELECT * FROM otp_orders WHERE id=?", (job["order_id"],))
            try:
                if not order or order["buyer_user_id"] != job["user_id"]:
                    raise StoreError("NOT_FOUND")
                if job["kind"] == "SMS":
                    event = self.store.repo.one("SELECT * FROM otp_sms_events WHERE provider_order_id=? AND sms_revision=?", (job["provider_order_id"], job["sms_revision"]))
                    if not event or not event["encrypted_payload"]:
                        raise StoreError("RETENTION", "SMS melewati masa retensi.")
                    payload = self.store.decrypt(event["encrypted_payload"])
                    texts = self.store.ui.sms_texts(order, payload, job["sms_revision"])
                elif job["kind"] == "REFUND":
                    texts = [f"✅ Refund OTP #{order['id']} berhasil: <b>{money(order['refund_idr'])}</b> masuk ke saldo kamu."]
                else:
                    texts = ["✅ <b>PEMBELIAN BERHASIL</b>\n"+self.store.ui.order_text(order)+"\n📩 SMS akan dikirim otomatis saat masuk."]
                for index in range(job["part_index"], len(texts)):
                    if not self.store.repo.execute("UPDATE otp_notifications SET lease_until=? WHERE notification_id=? AND lease_owner=?",
                            (time.time()+120, job["notification_id"], owner)):
                        raise StoreError("LEASE_LOST")
                    sent = await bot.send_message(job["user_id"], texts[index], parse_mode="HTML",
                         reply_markup=self.store.ui.order_keyboard(order, job["user_id"]) if index == len(texts)-1 else None,
                         link_preview_options=LinkPreviewOptions(is_disabled=True))
                    self.store.repo.execute("UPDATE otp_notifications SET part_index=?,telegram_message_id=? WHERE notification_id=? AND lease_owner=?",
                           (index+1, getattr(sent, "message_id", None), job["notification_id"], owner))
                self.store.repo.execute("UPDATE otp_notifications SET status='SENT',sent_at=?,lease_until=0,lease_owner=NULL WHERE notification_id=? AND lease_owner=?", (time.time(), job["notification_id"], owner))
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                # Exception strings may include request payloads. Store class only.
                attempts = job["attempts"]+1
                delay = max(getattr(exc, "retry_after", 0) or 0, min(3600, 5*2**min(attempts, 10)))
                self.store.repo.execute("UPDATE otp_notifications SET status=?,attempts=?,next_retry_at=?,error_code=?,lease_until=0,lease_owner=NULL WHERE notification_id=? AND lease_owner=?",
                    ("FAILED" if attempts >= self.store.config.retries else "PENDING", attempts, time.time()+delay, type(exc).__name__, job["notification_id"], owner))


class WebhookController:
    def __init__(self, store):
        self.store = store

    async def handle(self, request):
        secret = self.store.config.webhook_secret
        if not secret or not self.store.has_encryption():
            return web.json_response({"ok": False}, status=503)
        try:
            if request.content_length and request.content_length > 262144:
                return web.json_response({"ok": False}, status=413)
            try:
                raw = await bounded_body(request.content, 262144)
            except StoreError:
                return web.json_response({"ok": False}, status=413)
            expected = "sha256="+hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
            signature = request.headers.get("X-Webhook-Signature", "")
            if not re.fullmatch(r"sha256=[0-9a-f]{64}", signature) or not hmac.compare_digest(signature, expected):
                return web.json_response({"ok": False}, status=401)
            event = json.loads(raw)
            if not isinstance(event, dict) or not isinstance(event.get("data"), dict):
                return web.json_response({"ok": False}, status=400)
            if event.get("event") == "webhook.test":
                self.store.set_setting("last_webhook_at", time.time())
                return web.json_response({"ok": True})
            if event.get("event") not in {"order.otp_received", "order.completed", "order.expired", "order.canceled"}:
                return web.json_response({"ok": True, "ignored": True})
            provider_id = integer(event["data"].get("order_id"), 1)
            if event["event"] == "order.otp_received":
                integer(event["data"].get("sms_revision"), 1)
                for key in ("otp_code", "otp_message"):
                    value = event["data"].get(key)
                    if value is not None and (not isinstance(value, str) or len(value) > 100000):
                        raise StoreError("INVALID_RESPONSE")
            digest = hashlib.sha256(raw).hexdigest()
            encrypted = self.store.encrypt(event)
            self.store.repo.execute("INSERT OR IGNORE INTO otp_webhook_inbox(digest,provider_order_id,encrypted_payload,created_at) VALUES(?,?,?,?)", (digest, provider_id, encrypted, time.time()))
            self.store.set_setting("last_webhook_at", time.time())
            # No provider request or Telegram send before this fast durable response.
            return web.json_response({"ok": True})
        except (ValueError, UnicodeDecodeError, StoreError):
            return web.json_response({"ok": False}, status=400)
        except sqlite3.Error:
            return web.json_response({"ok": False}, status=503)

    async def drain(self):
        rows = self.store.repo.rows("""SELECT i.* FROM otp_webhook_inbox i LEFT JOIN otp_orders o
            ON o.provider_order_id=i.provider_order_id WHERE i.status='PENDING'
            ORDER BY (o.id IS NOT NULL) DESC,i.created_at LIMIT 100""")
        for row in rows:
            order = self.store.repo.one("SELECT * FROM otp_orders WHERE provider_order_id=?", (row["provider_order_id"],))
            if not order:
                # A create may not yet be persisted. Keep encrypted orphan for 24h.
                if time.time()-row["created_at"] > 86400:
                    self.store.repo.execute("UPDATE otp_webhook_inbox SET status='UNMAPPED',encrypted_payload='' WHERE digest=?", (row["digest"],))
                continue
            try:
                event = self.store.decrypt(row["encrypted_payload"])
                if event["event"] == "order.otp_received":
                    self.store.sms.process(event["data"], "webhook")
                else:
                    # Terminal webhook lacks a refund amount; verify via official GET.
                    self.store.repo.execute("UPDATE otp_orders SET next_poll_at=0 WHERE id=?", (order["id"],))
                self.store.repo.execute("UPDATE otp_webhook_inbox SET status='DONE',encrypted_payload='' WHERE digest=?", (row["digest"],))
            except StoreError:
                self.store.repo.execute("UPDATE otp_webhook_inbox SET status='REVIEW_REQUIRED' WHERE digest=?", (row["digest"],))


class Store:
    def __init__(self, host, config=None):
        self.host, self.config = host, config or Config.environment()
        self.repo, self.api = Repository(host), APIClient(self.config)
        self.pricing, self.catalog, self.purchase = PricingService(self), CatalogService(self), PurchaseService(self)
        self.sms, self.refund, self.orders = SMSEventProcessor(self), RefundService(self), OrderService(self)
        self.notifications, self.webhook, self.ui = NotificationQueue(self), WebhookController(self), UIBuilder(self)
        self.worker_id = secrets.token_hex(16)
        self._tasks = []

    def encryption_key(self):
        seed = os.getenv("OTP_STORAGE_ENCRYPTION_KEY", "") or getattr(self.host, "TEMPMAIL_ENCRYPTION_KEY", "") or getattr(self.host, "BOT_TOKEN", "")
        if not seed:
            raise StoreError("ENCRYPTION", "Kunci penyimpanan OTP belum dikonfigurasi.")
        return hashlib.sha256(("maboyy:smscode:otp:v1:"+seed).encode()).digest()

    def has_encryption(self):
        try:
            self.encryption_key()
            return True
        except StoreError:
            return False

    def encrypt(self, payload):
        cipher = AES.new(self.encryption_key(), AES.MODE_GCM, nonce=secrets.token_bytes(12))
        cipher.update(b"smscode-otp-v1")
        encrypted, tag = cipher.encrypt_and_digest(encoded(payload).encode())
        return base64.b64encode(cipher.nonce+tag+encrypted).decode()

    def decrypt(self, payload):
        try:
            raw = base64.b64decode(payload, validate=True)
            cipher = AES.new(self.encryption_key(), AES.MODE_GCM, nonce=raw[:12])
            cipher.update(b"smscode-otp-v1")
            return json.loads(cipher.decrypt_and_verify(raw[28:], raw[12:28]))
        except (ValueError, KeyError):
            raise StoreError("ENCRYPTION", "Data SMS tidak dapat dibaca dengan kunci penyimpanan saat ini.") from None

    def settings(self, conn=None):
        c = self.config
        result = {"enabled": c.enabled, "mode": c.mode, "percent": c.percent, "fixed": c.fixed,
                  "rounding": c.rounding, "max_active": c.max_active, "allow_loss": False,
                  "hourly_limit": c.hourly_limit, "purchase_cooldown": c.purchase_cooldown, "last_webhook_at": 0,
                  "last_poll_at": 0, "last_delivery_at": 0, "last_worker_error": ""}
        rows = conn.execute("SELECT key,value FROM otp_settings").fetchall() if conn else self.repo.rows("SELECT key,value FROM otp_settings")
        for row in rows:
            result[row["key"]] = json.loads(row["value"])
        return result

    def set_setting(self, key, value, actor=None):
        if actor is not None and not self.host.is_owner(actor):
            raise StoreError("FORBIDDEN")
        self.repo.execute("INSERT INTO otp_settings VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at", (key, encoded(value), time.time()))

    def require_ready(self):
        if self.config.error:
            raise StoreError("CONFIG", "Konfigurasi toko OTP perlu diperbaiki owner.")
        if not self.config.token or not self.has_encryption():
            raise StoreError("NOT_CONFIGURED", "Toko OTP belum dikonfigurasi owner.")
        if not self.settings()["enabled"]:
            raise StoreError("DISABLED", "Pembelian baru sedang ditutup owner. Pesanan lama tetap dipantau.")

    @staticmethod
    def capabilities(data):
        return encoded({key: data.get(key) for key in ["can_cancel", "can_finish", "can_resend", "can_reactivate", "resend_available_at", "cancel_available_at"]})

    @staticmethod
    def queue(conn, order_id, provider_id, user, kind, revision):
        conn.execute("""INSERT OR IGNORE INTO otp_notifications(dedup_key,order_id,provider_order_id,sms_revision,user_id,kind)
                     VALUES(?,?,?,?,?,?)""", (f"{kind}:{provider_id}:{revision}", order_id, provider_id, revision, user, kind))

    def token(self, user, action, payload=None, ttl=300):
        token = secrets.token_urlsafe(12)
        self.repo.execute("INSERT INTO otp_callback_tokens VALUES(?,?,?,?,?)", (token, user, action, encoded(payload or {}), time.time()+ttl))
        return PREFIX+token

    def read_token(self, user, token):
        row = self.repo.one("SELECT * FROM otp_callback_tokens WHERE token=? AND user_id=? AND expires_at>?", (token, user, time.time()))
        if not row:
            raise StoreError("TOKEN", "Tombol kedaluwarsa atau bukan milik kamu. Buka /otp lagi.")
        return row["action"], json.loads(row["payload"])

    def lease(self, name, seconds=120):
        now = time.time()
        with self.repo.connection(True) as conn:
            row = conn.execute("SELECT * FROM otp_worker_leases WHERE name=?", (name,)).fetchone()
            if row and row["until_ts"] > now and row["owner"] != self.worker_id:
                return False
            conn.execute("INSERT OR REPLACE INTO otp_worker_leases VALUES(?,?,?)", (name, self.worker_id, now+seconds))
        return True

    async def polling_cycle(self):
        lease_seconds = max(60, self.config.timeout+30)
        if not self.lease("polling", lease_seconds):
            return
        orders = self.repo.rows("SELECT * FROM otp_orders WHERE status IN ('ACTIVE','OTP_RECEIVED') AND next_poll_at<=? ORDER BY next_poll_at LIMIT 100", (time.time(),))
        if not orders:
            self.set_setting("last_poll_at", time.time())
            return
        try:
            active = await self.catalog.listing("/orders/active")
        except StoreError as exc:
            if exc.retry_after or time.time() < getattr(self.api, "blocked_until", 0):
                raise
            # An oversized/malformed account-wide response must not prevent
            # checking relevant individual local orders through the official API.
            active = []
        by_id = {row.get("id"): row for row in active}
        for order in orders:
            if not self.lease("polling", lease_seconds):
                break
            try:
                data = by_id.get(order["provider_order_id"])
                if data is not None:
                    self.orders.apply(order, data)
                else:
                    await self.orders.refresh(order)
            except StoreError as exc:
                self.repo.execute("UPDATE otp_orders SET next_poll_at=? WHERE id=?", (time.time()+max(exc.retry_after, self.config.poll_seconds), order["id"]))
                if exc.retry_after:
                    break
        self.set_setting("last_poll_at", time.time())

    async def bootstrap_webhook(self):
        data = await self.api.request("GET", "/webhook")
        if not isinstance(data, dict):
            raise StoreError("INVALID_RESPONSE")
        official = data.get("webhook_secret")
        if self.config.webhook_url and data.get("webhook_url") == self.config.webhook_url and official:
            if self.config.webhook_secret and not hmac.compare_digest(self.config.webhook_secret, official):
                self.set_setting("webhook_config_error", "SECRET_MISMATCH")
                self.config.webhook_secret = ""
            else:
                self.config.webhook_secret = official
                self.set_setting("webhook_config_error", "")
        return data

    async def configure_webhook(self, actor):
        if not self.host.is_owner(actor):
            raise StoreError("FORBIDDEN")
        if not self.config.webhook_url:
            raise StoreError("CONFIG", "Isi SMSCODE_WEBHOOK_PUBLIC_URL dengan URL HTTPS endpoint bot.")
        data = await self.api.request("GET", "/webhook")
        if data.get("webhook_url") not in {None, "", self.config.webhook_url}:
            raise StoreError("WEBHOOK_CONFLICT", "Akun provider sudah memakai webhook sistem lain. Pengaturan tidak diubah.")
        # Keep the provider's existing signing secret. On first setup the provider
        # generates it officially; adopt the returned value, never invent a key.
        response = await self.api.request("PATCH", "/webhook", body={"webhook_url": self.config.webhook_url})
        if response.get("webhook_url") != self.config.webhook_url or not response.get("webhook_secret"):
            raise StoreError("INVALID_RESPONSE")
        self.config.webhook_secret = response["webhook_secret"]
        self.set_setting("webhook_config_error", "")
        return response

    def cleanup(self):
        now = time.time()
        self.repo.execute("DELETE FROM otp_callback_tokens WHERE expires_at<?", (now,))
        # Pending delivery is retained until successful/exhausted; live orders also
        # retain their SMS so resend and /otp cek remain usable during the rental.
        self.repo.execute("""UPDATE otp_sms_events SET encrypted_payload='' WHERE received_at<? AND encrypted_payload!=''
            AND NOT EXISTS(SELECT 1 FROM otp_orders o WHERE o.provider_order_id=otp_sms_events.provider_order_id AND o.status IN ('ACTIVE','OTP_RECEIVED'))
            AND NOT EXISTS(SELECT 1 FROM otp_notifications n WHERE n.provider_order_id=otp_sms_events.provider_order_id
            AND n.sms_revision=otp_sms_events.sms_revision AND n.status IN ('PENDING','SENDING'))""", (now-self.config.retention_hours*3600,))

    async def run_loop(self, kind, bot):
        last_cleanup = 0
        while True:
            try:
                if kind == "notifications":
                    if self.has_encryption():
                        await self.notifications.deliver(bot)
                        self.set_setting("last_delivery_at", time.time())
                elif kind == "polling":
                    if self.has_encryption():
                        await self.webhook.drain()
                    if self.config.token and not self.config.error:
                        await self.polling_cycle()
                elif self.config.token and not self.config.error:
                    for row in self.repo.rows("SELECT attempt_id FROM otp_purchase_attempts WHERE state IN ('RESERVED','REQUESTING','PENDING_RECONCILIATION') AND next_retry_at<=? AND lease_until<? LIMIT 10", (time.time(), time.time())):
                        await self.purchase.process(row["attempt_id"])
                    await self.orders.reconcile_actions()
                if kind == "reconciliation" and time.time()-last_cleanup > 300:
                    self.cleanup()
                    last_cleanup = time.time()
                self.set_setting("worker_error_"+kind, "")
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logging.warning("OTP worker %s: %s", kind, type(exc).__name__)
                try:
                    self.set_setting("worker_error_"+kind, type(exc).__name__)
                except sqlite3.Error:
                    pass
            await asyncio.sleep(self.config.poll_seconds if kind == "polling" else 2)

    async def start(self, bot):
        if any(not task.done() for task in self._tasks):
            return self._tasks
        if self.config.token and not self.config.error:
            try:
                await self.bootstrap_webhook()
            except StoreError:
                pass
        self._tasks = [asyncio.create_task(self.run_loop(kind, bot), name="smscode_otp_"+kind)
                       for kind in ("polling", "notifications", "reconciliation")]
        return self._tasks

    async def close(self):
        try:
            self.repo.execute("DELETE FROM otp_worker_leases WHERE owner=?", (self.worker_id,))
        finally:
            await self.api.close()


class OTPState(StatesGroup):
    search = State()
    admin_value = State()


class UserFormatter:
    """Public shop text; never format internal pricing, API or refund evidence."""

    @staticmethod
    def label(value):
        # Catalog labels can contain upstream branding/URLs. SMS bodies and OTP
        # codes never use this function: their original contents are preserved.
        text = re.sub(r"https?://[^\s<>]+", "", str(value or ""), flags=re.IGNORECASE)
        text = re.sub(r"\b(?:[a-z0-9_-]+\.)*smscode\.gg(?:/[^\s<>]*)?", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\bsmscode\b(?:\s*\.\s*gg\b)?", "", text, flags=re.IGNORECASE)
        return " ".join(text.split()).strip(" •|·-/") or "-"

    @staticmethod
    def status(value):
        return {"ACTIVE": "Menunggu SMS", "OTP_RECEIVED": "SMS diterima", "COMPLETED": "Selesai",
                "CANCELED": "Dibatalkan", "EXPIRED": "Kedaluwarsa", "FAILED": "Gagal",
                "RESERVED": "Sedang diproses", "REQUESTING": "Sedang diproses",
                "PENDING_RECONCILIATION": "Menunggu kepastian transaksi"}.get(value, "Sedang diperiksa")

    @staticmethod
    def refund_status(value):
        return {"NONE": "Belum ada refund", "REFUNDED": "Sudah masuk ke saldo",
                "AWAITING_PROVIDER_PROOF": "Menunggu konfirmasi pengembalian dana",
                "PARTIAL_RECONCILIATION": "Pengembalian dana sedang diperiksa",
                "REVIEW_REQUIRED": "Pengembalian dana sedang diperiksa"}.get(value, "Sedang diperiksa")

    @staticmethod
    def error(exc):
        # Select by code, rather than exposing API/config details or arbitrary
        # exception messages. Admin errors are handled in their own context.
        if getattr(exc, "code", "") == "FORBIDDEN" and getattr(exc, "public", "") in {
                "Menu ini hanya untuk owner.", "Akun kamu dibatasi owner."}:
            return exc.public
        return {
            "PRIVATE": "Gunakan /otp melalui chat privat bot.",
            "CHANNEL": "Akses mengikuti verifikasi channel bot. Buka /start dan ikuti petunjuk bergabung dahulu.",
            "FORBIDDEN": "Layanan OTP sementara belum tersedia. Hubungi owner.",
            "NOT_FOUND": "Pesanan atau produk tidak ditemukan.",
            "USER_BALANCE": "Saldo kamu tidak cukup. Isi saldo melalui menu deposit bot.",
            "UNAUTHORIZED": "Pembelian OTP sementara belum tersedia. Hubungi owner.",
            "NOT_CONFIGURED": "Pembelian OTP sementara belum tersedia. Hubungi owner.",
            "CONFIG": "Pembelian OTP sementara belum tersedia. Hubungi owner.",
            "ENCRYPTION": "Data SMS sementara tidak tersedia. Hubungi owner.",
            "INSUFFICIENT_BALANCE": "Nomor sementara tidak dapat dibeli. Saldo yang ditahan untuk pembelian gagal akan dilepas.",
            "CANCEL_TOO_EARLY": "Nomor belum boleh dibatalkan. Tunggu sampai pembatalan tersedia.",
            "NO_OFFER_AVAILABLE": "Stok nomor habis atau harga berubah. Pilih produk kembali.",
            "PRICE_CHANGED": "Harga berubah. Pilih kembali produk untuk menyetujui harga terbaru.",
            "PRICE_LIMIT": "Produk ini belum tersedia untuk dibeli di toko.",
            "BELOW_COST": "Harga produk perlu diperbarui. Pilih produk lain atau hubungi owner.",
            "QUOTE_EXPIRED": "Konfirmasi harga kedaluwarsa. Pilih produk lagi.",
            "DISABLED": "Pembelian baru sedang ditutup. Pesanan lama tetap dipantau.",
            "ORDER_LIMIT": "Batas pesanan aktif tercapai. Selesaikan pesanan sebelumnya.",
            "COOLDOWN": "Batas atau jeda permintaan tercapai. Tunggu sebelum mencoba kembali.",
            "RATE_LIMIT_EXCEEDED": "Terlalu banyak permintaan. Coba kembali setelah jeda.",
            "TEMP_BANNED_ABUSE_GUARD": "Layanan meminta jeda penggunaan. Coba kembali nanti.",
            "REQUEST_IN_PROGRESS": "Transaksi sedang diproses; jangan membeli ulang.",
            "IDEMPOTENCY_KEY_REUSED": "Transaksi sedang diperiksa; jangan membeli ulang.",
            "NETWORK": "Hasil permintaan belum pasti. Periksa pesanan dan jangan membeli ulang.",
            "LOCAL_DATABASE": "Hasil tindakan sedang diperiksa; jangan mengulang.",
            "CONFLICT": "Tindakan belum tersedia untuk pesanan ini. Cek status pesanan.",
            "TOKEN": "Tombol kedaluwarsa atau bukan milik kamu. Buka /otp lagi.",
            "INPUT": "Perintah tidak valid. Gunakan /otp bantuan untuk format yang benar.",
            "RETENTION": "SMS sudah melewati masa penyimpanan.",
        }.get(getattr(exc, "code", ""), "Layanan OTP mengalami gangguan sementara. Coba kembali nanti.")


class OwnerFormatter:
    """Private dashboard text; balance is supplied by GET /balance only."""

    @staticmethod
    def dashboard(*, stats, settings, balance, api_status, attempts, notifications, worker_errors, config_error):
        return (f"👑 <b>{ADMIN_BRAND}</b>\n📱 Provider: SMSCode.gg (v1 IDR)\n"
            f"🔌 Status API: {escape(api_status)}\n"
            f"💰 Saldo provider: {escape(balance)}\n🛒 Total penjualan: {stats['total']}\n"
            f"✅ Selesai: {stats['completed']} • ⏳ Aktif: {stats['pending']} • ❌ Terminal lain: {stats['canceled']}\n"
            f"💵 Omzet setelah refund: {money(stats['revenue'])}\n📈 Profit kotor sementara: {money(stats['profit'])}\n"
            f"📈 Markup: {escape(settings['percent'])}% • Tambahan: {money(settings['fixed'])}\n"
            f"⚙️ Mode harga: {escape(settings['mode'])}\n"
            f"⚠️ Refund perlu rekonsiliasi: {stats['refund_review']}\n⏳ Pembelian belum pasti: {attempts}\n"
            f"📩 Notifikasi pending/gagal: {notifications}\n🛍 Toko: {'ON' if settings['enabled'] else 'OFF'}\n"
            f"📦 Limit aktif: {settings['max_active']}/user\n🕒 Poll terakhir: {settings['last_poll_at'] or 'belum'}\n"
            f"Webhook terakhir: {settings['last_webhook_at'] or 'belum'}\n"
            f"Worker: {escape(worker_errors or settings['last_worker_error']) or 'Tidak ada error tercatat'}\n"
            f"Config: {escape(config_error) or 'valid'}\n"
            "OTP dan isi SMS user tidak ditampilkan di dashboard.")

    @staticmethod
    def dashboard_rows():
        return [
            [("💰 SALDO PROVIDER", "admin_balance", {}), ("📊 STATISTIK", "admin_stats", {})],
            [("💵 HARGA PROVIDER", "admin_prices", {"kind": "provider"}), ("🏷️ HARGA JUAL", "admin_prices", {"kind": "jual"})],
            [("📈 MARKUP & PROFIT", "admin_profit", {}), ("⚙️ PENGATURAN HARGA", "admin_prices_menu", {})],
            [("📦 SEMUA ORDER", "admin_orders", {}), ("⏳ PEMBELIAN PENDING", "admin_pending", {})],
            [("📩 STATUS AUTO SMS", "admin_status", {}), ("📩 WEBHOOK", "admin_webhook", {})],
            [("🟢 TOKO ON/OFF", "admin_toggle", {}), ("🔄 RETRY NOTIFIKASI GAGAL", "admin_retry", {})],
            [("🏠 MABOYY OTP", "home", {})]]


class UIBuilder:
    def __init__(self, store):
        self.store = store

    def keyboard(self, user, rows):
        if any(action.startswith("admin") for row in rows for _, action, _ in row) and not self.store.host.is_owner(user):
            raise StoreError("FORBIDDEN", "Menu ini hanya untuk owner.")
        return InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text=label[:64], callback_data=self.store.token(user, action, payload))
            for label, action, payload in row] for row in rows])

    def admin_keyboard(self, user, rows):
        if not self.store.host.is_owner(user):
            raise StoreError("FORBIDDEN", "Menu ini hanya untuk owner.")
        return self.keyboard(user, rows)

    def home_keyboard(self, user):
        rows = [[("📱 BELI NOMOR OTP", "countries", {})], [("🌍 PILIH NEGARA", "countries", {})],
                [("📦 PESANAN SAYA", "orders", {}), ("🔐 CEK KODE OTP", "orders", {})],
                [("💰 SALDO SAYA", "balance", {}), ("📜 RIWAYAT", "history", {})],
                [("❓ BANTUAN", "help", {})]]
        if self.store.host.is_owner(user):
            rows.append([("⚙️ OTP ADMIN", "admin", {})])
        return self.keyboard(user, rows)

    @staticmethod
    def order_text(order):
        return (f"🛍️ <b>{USER_BRAND}</b>\n🆔 Order: <b>#{order['id']}</b>\n"
                f"🌍 Negara: {escape(UserFormatter.label(order['country_name']))}\n📱 Layanan: {escape(UserFormatter.label(order['platform_name']))}\n"
                f"📶 Operator: {escape(UserFormatter.label(order['operator_name']))}\n📞 Nomor: <code>{escape(order['phone_number'])}</code>\n"
                f"💰 Harga: {money(order['selling_price_idr'])}\n⏳ Status: {UserFormatter.status(order['status'])}\n"
                f"🕒 Beli: {datetime.fromtimestamp(order['created_at'],timezone.utc).isoformat(timespec='seconds')}\n"
                f"⌛ Kedaluwarsa: {escape(UserFormatter.label(order['expires_at']))}\n"
                + (f"✅ Selesai: {datetime.fromtimestamp(order['completed_at'],timezone.utc).isoformat(timespec='seconds')}\n" if order.get('completed_at') else "")
                + f"↩️ Refund: {money(order['refund_idr'])} • {UserFormatter.refund_status(order['refund_state'])}")

    def order_keyboard(self, order, user):
        oid = {"id": order["id"]}
        caps = json.loads(order["capabilities"])
        rows = [[("🔄 CEK OTP", "check", oid)]]
        if order["status"] in ACTIVE:
            if caps.get("can_resend"):
                rows.append([("📨 RESEND", "resend", oid)])
            if caps.get("can_cancel"):
                rows.append([("❌ BATALKAN", "confirm_cancel", oid)])
            if caps.get("can_finish"):
                rows.append([("✅ SELESAI", "confirm_finish", oid)])
        elif caps.get("can_reactivate"):
            rows.append([("♻️ AKTIFKAN LAGI", "reactivate", oid)])
        rows.append([("📦 PESANAN", "orders", {}), ("🏠 MABOYY OTP", "home", {})])
        return self.keyboard(user, rows)

    @staticmethod
    def sms_texts(order, payload, revision):
        header = (f"🛍️ <b>{USER_BRAND}</b>\n📩 <b>SMS OTP MASUK!</b>\n"
                  f"📱 {escape(UserFormatter.label(order['platform_name']))} • 🌍 {escape(UserFormatter.label(order['country_name']))}\n"
                  f"📞 <code>{escape(order['phone_number'])}</code>\n🆔 #{order['id']} • SMS ke-{revision}\n")
        code_parts = []
        if payload.get("otp_code"):
            code = escape(payload["otp_code"])
            if len(code) <= 1000:
                header += "🔐 KODE VERIFIKASI: <code>"+code+"</code>\n"
            else:
                # Preserve a long classified token without exceeding message limits.
                part = ""
                for character in payload["otp_code"]:
                    encoded_char = escape(character)
                    if len(part)+len(encoded_char) > 2500:
                        code_parts.append("🔐 KODE VERIFIKASI • #"+str(order["id"])+"\n<pre>"+part+"</pre>")
                        part = ""
                    part += encoded_char
                code_parts.append("🔐 KODE VERIFIKASI • #"+str(order["id"])+"\n<pre>"+part+"</pre>")
                header += "🔐 Kode panjang dikirim lengkap pada pesan berikutnya.\n"
        else:
            header += "📩 SMS diterima tanpa kode verifikasi.\n"
        message = payload.get("otp_message") or "Isi SMS belum tersedia."
        # Small escaped chunks also handle non-numeric SMS and Telegram's limit.
        chunks, part = [], ""
        for character in message:
            encoded_char = escape(character)
            if len(part)+len(encoded_char) > 2500:
                chunks.append(part)
                part = ""
            part += encoded_char
        chunks.append(part)
        return [(header if index == 0 else f"📩 SMS #{order['id']} • lanjutan {index+1}\n")+
                "📨 ISI SMS:\n<pre>"+chunk+"</pre>\n✅ OTP DITERIMA" for index, chunk in enumerate(chunks)] + code_parts

    async def send(self, message, text, keyboard=None):
        return await message.answer(text, reply_markup=keyboard, parse_mode="HTML", link_preview_options=LinkPreviewOptions(is_disabled=True))

    async def home(self, message, user):
        settings, api = self.store.settings(), self.store.api
        if not self.store.config.token or self.store.config.error:
            status = "Pembelian belum tersedia"
        elif not settings["enabled"]:
            status = "Pembelian ditutup"
        elif api.last_error:
            status = "Gangguan sementara"
        elif time.time()-api.last_ok <= 120:
            status = "Siap menerima pesanan (pemeriksaan terakhir)"
        else:
            status = "Status belum tersedia"
        profile = self.store.repo.one("SELECT username FROM verified_users WHERE user_id=?", (user,))
        username = profile["username"] if profile else ""
        if message.from_user and message.from_user.id == user:
            username = getattr(message.from_user, "username", "") or username
        identity = "@"+username.lstrip("@") if username else f"User {user}"
        await self.send(message, f"🛍️ <b>{USER_BRAND}</b>\n👤 User: {escape(identity)}\n\n"
            f"💰 Saldo Kamu: <b>{money(self.store.host.get_balance(user))}</b>\n"
            f"🛍️ Status toko: {escape(status)}\n\nSilakan pilih menu:", self.home_keyboard(user))

    async def selection(self, message, user, kind, payload=None, query=""):
        self.store.require_ready()
        payload = payload or {}
        page = max(0, min(int(payload.get("page", 0)), 1000))
        if kind == "countries":
            rows = await self.store.catalog.listing("/catalog/countries")
            rows = [row for row in rows if row.get("active") is True]
            rows = [row for row in rows if query.casefold() in (str(row.get("name"))+str(row.get("code"))).casefold()]
            buttons = [(UserFormatter.label(row.get("emoji") or "🌍")+" "+UserFormatter.label(row["name"]), "services",
                        {"country": row["id"], "country_name": row["name"]}) for row in rows]
            title = "🌍 PILIH NEGARA"
        elif kind == "services":
            rows = await self.store.catalog.listing("/catalog/services", {"country_id": payload["country"]})
            rows = [row for row in rows if row.get("active") is True and query.casefold() in str(row.get("name", "")).casefold()]
            buttons = [(UserFormatter.label(row["name"]), "operators", {**payload, "platform": row["id"], "platform_name": row["name"], "page": 0}) for row in rows]
            title = "📱 PILIH LAYANAN • "+escape(UserFormatter.label(payload.get("country_name")))
        elif kind == "operators":
            rows = await self.store.catalog.listing("/catalog/operators", {"country_id": payload["country"], "platform_id": payload["platform"]})
            if not rows:
                rows = [{"operator_id": None, "name": "Any"}]
            buttons = [(UserFormatter.label(row.get("name") or "Any"), "products", {**payload, "operator": row["operator_id"], "operator_name": row.get("name") or "Any", "page": 0}) for row in rows]
            title = "📶 PILIH OPERATOR"
        else:
            rows, more = await self.store.catalog.products(payload["country"], payload["platform"], payload.get("operator"), page+1)
            buttons = []
            for row in rows[:50]:
                try:
                    sale, _ = self.store.pricing.calculate(row)
                    if integer(row["price"]) > self.store.config.max_cost:
                        continue
                    product = {**row, "country_name": payload["country_name"], "platform_name": payload["platform_name"]}
                    buttons.append((f"{money(sale)} • Stok {row['available']}", "quote", {"product": product}))
                except StoreError:
                    continue
            title = "🛒 PRODUK TERSEDIA • "+escape(UserFormatter.label(payload["platform_name"]))+" / "+escape(UserFormatter.label(payload["country_name"]))
            keyboard_rows = [[button] for button in buttons]
            nav = []
            if page:
                nav.append(("⬅️", kind, {**payload, "page": page-1}))
            if more:
                nav.append(("➡️", kind, {**payload, "page": page+1}))
            if nav:
                keyboard_rows.append(nav)
            keyboard_rows.append([("🏠 MABOYY OTP", "home", {})])
            return await self.send(message, title+"\n\n"+("Pilih harga nomor:" if buttons else "Belum ada stok pada halaman ini."), self.keyboard(user, keyboard_rows))
        subset = buttons[page*8:(page+1)*8]
        keyboard_rows = [[button] for button in subset]
        nav = []
        if page:
            nav.append(("⬅️", kind, {**payload, "page": page-1, "query": query}))
        if len(buttons) > (page+1)*8:
            nav.append(("➡️", kind, {**payload, "page": page+1, "query": query}))
        if nav:
            keyboard_rows.append(nav)
        if kind in {"countries", "services"}:
            keyboard_rows.append([("🔎 CARI", "search", {"kind": kind, "context": {**payload, "page": 0}})])
        keyboard_rows.append([("🏠 MABOYY OTP", "home", {})])
        await self.send(message, title+f"\nHalaman {page+1} • {len(buttons)} pilihan\n"+("Pilih menu:" if subset else "Tidak ada hasil."), self.keyboard(user, keyboard_rows))

    async def quote(self, message, user, quote):
        product = json.loads(quote["product"])
        balance = self.store.host.get_balance(user)
        await self.send(message, "🛒 <b>KONFIRMASI "+("REAKTIVASI" if quote["parent_order_id"] else "PEMBELIAN")+"</b>\n\n"
            f"🌍 Negara: {escape(UserFormatter.label(product['country_name']))}\n📱 Layanan: {escape(UserFormatter.label(product['platform_name']))}\n"
            f"📶 Operator: {escape(UserFormatter.label(product.get('operator_name') or 'Any'))}\n"
            f"💰 Harga: <b>{money(quote['selling_price_idr'])}</b>\n💳 Saldo: {money(balance)}\n"
            f"Saldo setelah beli: {money(balance-quote['selling_price_idr'])}\n"
            f"⏳ Berlaku {self.store.config.quote_ttl} detik. Pembelian memakai saldo kamu.",
            self.keyboard(user, [[("✅ BELI SEKARANG", "buy", {"quote": quote["quote_id"]})], [("❌ BATAL", "home", {})]]))

    async def history(self, message, user, history=False, page=0, admin=False):
        if admin and not self.store.host.is_owner(user):
            raise StoreError("FORBIDDEN")
        clause, args = ("1=1", []) if admin else ("buyer_user_id=?", [user])
        if not history and not admin:
            clause += " AND status IN ('ACTIVE','OTP_RECEIVED')"
        rows = self.store.repo.rows("SELECT * FROM otp_orders WHERE "+clause+" ORDER BY id DESC LIMIT 6 OFFSET ?", (*args, max(0, page)*5))
        text, buttons = [f"👑 <b>{ADMIN_BRAND}</b>\n📦 SEMUA ORDER" if admin else "📜 <b>RIWAYAT OTP</b>" if history else "📦 <b>PESANAN OTP</b>"], []
        for order in rows[:5]:
            if admin:
                text.append(f"#{order['id']} • Buyer {order['buyer_user_id']} • {escape(order['platform_name'])} • {escape(order['status'])} • {money(order['selling_price_idr'])} • Modal {money(order['provider_cost_idr'])} • Refund {money(order['refund_idr'])}")
            else:
                text.append(self.order_text(order))
                buttons.append([(f"🔎 #{order['id']}", "check", {"id": order["id"]})])
        if not rows:
            text.append("Belum ada pesanan.")
        pending = self.store.repo.rows("SELECT attempt_id,state,hold_idr FROM otp_purchase_attempts WHERE user_id=? AND state IN ('RESERVED','REQUESTING','PENDING_RECONCILIATION')", (user,))
        if not admin:
            for item in pending:
                text.append(f"⏳ {UserFormatter.status(item['state'])} • Saldo ditahan {money(item['hold_idr'])}; jangan membeli ulang.")
        nav, action = [], "admin_orders" if admin else "history" if history else "orders"
        if page:
            nav.append(("⬅️", action, {"page": page-1}))
        if len(rows) > 5:
            nav.append(("➡️", action, {"page": page+1}))
        if nav:
            buttons.append(nav)
        buttons.append([("⬅️ ADMIN", "admin", {})] if admin else [("🏠 MABOYY OTP", "home", {})])
        await self.send(message, "\n\n".join(text), self.admin_keyboard(user, buttons) if admin else self.keyboard(user, buttons))

    async def check(self, message, user, order_id):
        order = self.store.repo.owned(user, order_id)
        self.store.repo.rate(user, "status", 10, 60)
        try:
            await self.store.orders.refresh(order)
        except StoreError:
            pass
        order = self.store.repo.owned(user, order_id)
        await self.send(message, self.order_text(order), self.order_keyboard(order, user))
        event = self.store.repo.one("SELECT * FROM otp_sms_events WHERE provider_order_id=? ORDER BY sms_revision DESC LIMIT 1", (order["provider_order_id"],))
        if event and event["encrypted_payload"]:
            for text in self.sms_texts(order, self.store.decrypt(event["encrypted_payload"]), event["sms_revision"]):
                await self.send(message, text)
        else:
            await self.send(message, "📩 SMS belum diterima atau sudah melewati masa retensi.")


HELP = (f"🛍️ <b>{USER_BRAND}</b>\n❓ PANDUAN TOKO OTP\n\n"
    "/otp — menu toko\n/otp beli • /otp negara — pilih negara\n/otp layanan — pilih layanan\n"
    "/otp saldo — saldo bot kamu\n/otp pesanan — pesanan aktif\n/otp cek &lt;id&gt; — nomor dan SMS\n"
    "/otp ulang &lt;id&gt; — minta SMS baru jika tersedia\n/otp batal &lt;id&gt; — konfirmasi pembatalan\n"
    "/otp selesai &lt;id&gt; — konfirmasi selesai\n/otp riwayat — riwayat pribadi\n"
    "/otp aktifkan &lt;id&gt; — reaktivasi berbayar jika didukung\n/otp bantuan — panduan\n\n"
    "Gunakan ID order bot (#), bukan ID order orang lain. SMS dikirim otomatis ke chat privat ini. "
    "Saldo ditahan saat pemesanan dan ditagihkan setelah nomor terkonfirmasi. "
    "Refund masuk ke saldo setelah pembatalan dan pengembalian dana terkonfirmasi. "
    "Pengembalian dana yang belum pasti ditinjau owner.")


class AdminHandler:
    def __init__(self, store):
        self.store = store

    def authorize(self, user):
        if not self.store.host.is_owner(user):
            raise StoreError("FORBIDDEN", "Menu ini hanya untuk owner.")

    async def handle(self, message, user, args):
        self.authorize(user)
        settings = self.store.settings()
        worker_errors = ", ".join(kind+":"+str(settings.get("worker_error_"+kind)) for kind in ("polling","notifications","reconciliation") if settings.get("worker_error_"+kind))
        args = list(args)
        section = args[0].lower() if args else "dashboard"
        if section not in {"dashboard", "saldo", "statistik", "profit", "orders", "pending", "harga", "status", "webhook", "on", "off", "limit", "markup", "retry", "refund-proof"}:
            raise StoreError("INPUT", "Command admin belum dikenal. Gunakan /otp admin.")
        if section == "retry":
            self.store.repo.execute("UPDATE otp_notifications SET status='PENDING',attempts=0,next_retry_at=0 WHERE status='FAILED'")
            return await self.store.ui.send(message, "✅ Notifikasi gagal dijadwalkan ulang.")
        if section == "pending":
            page = self.number(args[1], 1, 10000)-1 if len(args)>1 else 0
            rows = self.store.repo.rows("""SELECT attempt_id,user_id,state,hold_idr,retries,error_code,created_at FROM otp_purchase_attempts
                WHERE state IN ('RESERVED','REQUESTING','PENDING_RECONCILIATION') ORDER BY created_at LIMIT 10 OFFSET ?""", (page*10,))
            text = [f"⏳ REKONSILIASI PEMBELIAN • halaman {page+1}"]
            for row in rows:
                text.append(f"Ref {escape(row['attempt_id'])}\nBuyer {row['user_id']} • {escape(row['state'])}\nHold {money(row['hold_idr'])} • Retry {row['retries']} • Error {escape(row['error_code']) or '-'}")
            if not rows:
                text.append("Tidak ada attempt pending pada halaman ini.")
            text.append("Worker memakai key/request asli. Jangan membuat order pengganti atau melepas hold tanpa bukti hasil provider.")
            return await self.store.ui.send(message,"\n\n".join(text))
        if section == "refund-proof":
            # Official GET endpoints expose no refund amount. A provider-account
            # operator must reconcile a documented receipt for uncertain refunds.
            if len(args) != 4 or not re.fullmatch(r"[A-Za-z0-9_.:-]{4,100}", args[3]):
                raise StoreError("INPUT", "Gunakan refund-proof <id bot> <refund modal IDR> <referensi bukti provider>. Hanya setelah memeriksa bukti kredit provider.")
            oid, amount = self.number(args[1], 1, 2**31-1), self.number(args[2], 0, 10**9)
            order = self.store.repo.one("SELECT * FROM otp_orders WHERE id=?", (oid,))
            if not order:
                raise StoreError("NOT_FOUND")
            data = await self.store.orders.refresh(order)
            if data["status"] not in {"CANCELED", "EXPIRED"} or data.get("otp_message") or data.get("otp_code") or data.get("otp_received_at"):
                raise StoreError("CONFLICT", "Status provider belum memenuhi syarat refund tanpa SMS.")
            response = {"order_id": order["provider_order_id"], "status": data["status"], "refund_amount": amount,
                        "proof_reference": args[3], "proof_actor": user, "proof_source": "OWNER_VERIFIED_PROVIDER_RECEIPT"}
            now = time.time()
            with self.store.repo.connection(True) as conn:
                cursor = conn.execute("INSERT INTO otp_actions(order_id,action,state,created_at,updated_at,response) VALUES(?,'refund-proof','PROOF_RECORDED',?,?,?)", (oid, now, now, encoded(response)))
                proof_id = cursor.lastrowid
            self.store.refund.confirm(order, response)
            self.store.repo.execute("UPDATE otp_actions SET state='DONE',updated_at=? WHERE id=?", (time.time(), proof_id))
            self.store.repo.execute("UPDATE otp_actions SET state='DONE',lease_until=0 WHERE order_id=? AND action='cancel' AND state='PENDING_RECONCILIATION'", (oid,))
            return await self.store.ui.send(message, "✅ Bukti refund provider dicatat dengan identitas owner. Kredit user mengikuti jumlah modal yang terbukti; refund parsial tetap direkonsiliasi.")
        if section in {"on", "off"}:
            self.store.set_setting("enabled", section == "on", user)
            return await self.store.ui.send(message, "✅ Pembelian OTP "+("diaktifkan." if section == "on" else "ditutup. Pesanan lama tetap dipantau."))
        if section == "limit" and len(args) == 2:
            value = self.number(args[1], 1, 20)
            self.store.set_setting("max_active", value, user)
            return await self.store.ui.send(message, f"✅ Batas order aktif: {value}/user.")
        if section == "markup" and len(args) == 3:
            key, value = args[1].lower(), args[2].lower()
            if key == "persen":
                try:
                    decimal = Decimal(value)
                except InvalidOperation:
                    raise StoreError("INPUT", "Persentase tidak valid.") from None
                if not decimal.is_finite() or not 0 <= decimal <= 10000 or decimal.as_tuple().exponent < -4:
                    raise StoreError("INPUT", "Persentase 0–10000, maksimal 4 angka desimal.")
                self.store.set_setting("percent", str(decimal), user)
            elif key == "nominal":
                self.store.set_setting("fixed", self.number(value, 0, 10**9), user)
            elif key == "mode" and value in {"persen", "nominal", "kombinasi", "percent", "fixed", "combined"}:
                self.store.set_setting("mode", {"persen": "percent", "nominal": "fixed", "kombinasi": "combined"}.get(value, value), user)
            else:
                raise StoreError("INPUT", "Gunakan markup persen, nominal atau mode.")
            return await self.store.ui.send(message, "✅ Pengaturan markup tersimpan. Quote lama akan divalidasi ulang.")
        if section == "harga" and len(args) >= 2:
            sub = args[1].lower()
            if sub == "round" and len(args) == 3:
                value = self.number(args[2], 0, 1000)
                if value not in {0, 100, 500, 1000}:
                    raise StoreError("INPUT", "Pembulatan: 0, 100, 500 atau 1000.")
                self.store.set_setting("rounding", value, user)
                return await self.store.ui.send(message, "✅ Pembulatan disimpan.")
            if sub == "allow-loss" and len(args) == 3 and args[2] in {"on", "off"}:
                self.store.set_setting("allow_loss", args[2] == "on", user)
                return await self.store.ui.send(message, "✅ Izin jual di bawah modal: "+args[2])
            if sub in {"set", "reset"} and len(args) == (4 if sub == "set" else 3):
                product_id = self.number(args[2], 1, 2**31-1)
                if sub == "reset":
                    self.store.repo.execute("DELETE FROM otp_pricing_rules WHERE scope='product' AND scope_key=?", (str(product_id),))
                else:
                    self.rule(user, "product", str(product_id), {"sale": self.number(args[3], 0, 10**9)})
                return await self.store.ui.send(message, "✅ Harga khusus produk disimpan/dihapus.")
            if sub == "rule":
                # /otp admin harga rule country 7 persen 25
                # /otp admin harga rule country_service 7:3 kombinasi 25 2000
                if len(args) < 5 or args[2] not in {"country", "service", "country_service", "product"}:
                    raise StoreError("INPUT", "harga rule <country|service|country_service|product> <id atau negara:layanan> <persen|nominal|kombinasi|jual|reset> <nilai> [nominal]")
                scope, key, mode = args[2:5]
                if not re.fullmatch(r"[1-9][0-9]{0,9}(?::[1-9][0-9]{0,9})?", key) or (":" in key) != (scope == "country_service"):
                    raise StoreError("INPUT", "ID scope tidak valid.")
                if mode == "reset":
                    self.store.repo.execute("DELETE FROM otp_pricing_rules WHERE scope=? AND scope_key=?", (scope, key))
                elif mode == "jual":
                    if len(args) != 6:
                        raise StoreError("INPUT", "Cantumkan harga jual.")
                    self.rule(user, scope, key, {"sale": self.number(args[5], 0, 10**9)})
                else:
                    if mode not in {"persen", "nominal", "kombinasi"}:
                        raise StoreError("INPUT", "Mode rule tidak valid.")
                    if len(args) != (7 if mode == "kombinasi" else 6):
                        raise StoreError("INPUT", "Cantumkan nilai markup sesuai mode.")
                    percent = Decimal(args[5]) if mode in {"persen", "kombinasi"} else Decimal(0)
                    if not percent.is_finite() or not 0 <= percent <= 10000:
                        raise StoreError("INPUT", "Persentase tidak valid.")
                    fixed = self.number(args[6], 0, 10**9) if mode == "kombinasi" and len(args) == 7 else self.number(args[5], 0, 10**9) if mode == "nominal" else 0
                    self.rule(user, scope, key, {"mode": {"persen": "percent", "nominal": "fixed", "kombinasi": "combined"}[mode], "percent": str(percent), "fixed": fixed})
                return await self.store.ui.send(message, "✅ Aturan harga scope disimpan.")
            if sub in {"provider", "jual"}:
                country = self.number(args[2], 1, 2**31-1) if len(args) >= 4 else None
                platform = self.number(args[3], 1, 2**31-1) if len(args) >= 4 else None
                page = self.number(args[4], 1, 10000) if len(args) >= 5 else 1
                params = {"limit": 10, "page": page, "sort": "price_asc"}
                if country and platform:
                    params.update(country_id=country, platform_id=platform)
                rows = await self.store.catalog.listing("/catalog/products", params)
                text = [f"📋 HARGA {sub.upper()} • halaman {page}"]
                for row in rows:
                    if row.get("active") is not True or row.get("available", 0) <= 0:
                        continue
                    sale, _ = self.store.pricing.calculate(row)
                    text.append(f"Produk {row['id']} • {escape(row.get('name'))}\nModal {money(row['price'])} • Jual {money(sale)} • Stok {row['available']}")
                text.append("Halaman berikut: /otp admin harga "+sub+" <negara_id> <layanan_id> <halaman>")
                return await self.store.ui.send(message, "\n\n".join(text))
        if section == "orders":
            return await self.store.ui.history(message, user, page=int(args[1]) if len(args) > 1 else 0, admin=True)
        if section in {"limit", "markup"}:
            raise StoreError("INPUT", "Parameter admin belum lengkap. Gunakan /otp admin harga untuk panduan.")
        if section == "webhook":
            data = await self.store.bootstrap_webhook()
            text = ("📩 <b>STATUS WEBHOOK</b>\n"+f"URL: {escape(data.get('webhook_url')) or 'Belum diatur'}\n"
                    f"Secret resmi: {'tersedia' if data.get('webhook_secret') else 'belum tersedia'}\n"
                    f"Nonaktif otomatis: {'ya' if data.get('webhook_disabled_at') else 'tidak'}\n"
                    f"Gagal beruntun: {data.get('webhook_consecutive_failures',0)}\n"
                    "Tombol Hubungkan hanya mengatur URL ini jika webhook kosong atau sudah memakai URL bot. Secret tidak ditampilkan.")
            return await self.store.ui.send(message, text, self.store.ui.admin_keyboard(user, [[("🔗 HUBUNGKAN WEBHOOK", "admin_webhook_connect", {})], [("🧪 TEST WEBHOOK", "admin_webhook_test", {})], [("⬅️ ADMIN", "admin", {})]]))
        if section == "harga":
            example = {"id": -1, "price": 8000}
            sale, _ = self.store.pricing.calculate(example)
            text = ("⚙️ <b>PENGATURAN HARGA OTP</b>\n"
                f"Mode: {escape(settings['mode'])}\nMarkup: {escape(settings['percent'])}%\nTambahan: {money(settings['fixed'])}\n"
                f"Pembulatan: {settings['rounding']}\nContoh modal {money(8000)} → jual {money(sale)}\n"
                "Prioritas: produk → negara+layanan → layanan → negara → global.\n\n"
                "/otp admin markup persen 25\n/otp admin markup nominal 2000\n/otp admin markup mode kombinasi\n"
                "/otp admin harga set &lt;product_id&gt; &lt;harga&gt;\n/otp admin harga reset &lt;product_id&gt;\n"
                "/otp admin harga round 100\n/otp admin harga allow-loss on|off\n"
                "/otp admin harga rule country_service 7:3 kombinasi 25 2000")
            return await self.store.ui.send(message, text, self.store.ui.admin_keyboard(user, [
                [("📈 ATUR PERSENTASE", "admin_input", {"setting": "percent"}), ("💵 ATUR NOMINAL", "admin_input", {"setting": "fixed"})],
                [("⚙️ PILIH MODE", "admin_modes", {})], [("📋 HARGA PROVIDER", "admin_prices", {"kind": "provider"}), ("🛒 HARGA JUAL", "admin_prices", {"kind": "jual"})], [("⬅️ ADMIN", "admin", {})]]))
        stats = self.store.repo.one("""SELECT count(*) total,COALESCE(sum(selling_price_idr-refund_idr),0) revenue,
            COALESCE(sum(selling_price_idr-refund_idr-provider_cost_idr+provider_refund_idr),0) profit,
            COALESCE(sum(status='COMPLETED'),0) completed,COALESCE(sum(status IN ('ACTIVE','OTP_RECEIVED')),0) pending,
            COALESCE(sum(status IN ('CANCELED','EXPIRED','FAILED')),0) canceled,
            COALESCE(sum(refund_state IN ('AWAITING_PROVIDER_PROOF','PARTIAL_RECONCILIATION','REVIEW_REQUIRED')),0) refund_review FROM otp_orders""")
        balance, api_status = "Belum diperiksa", "Belum diperiksa"
        if section in {"dashboard", "saldo", "status"}:
            try:
                response = await self.store.api.request("GET", "/balance")
                if not isinstance(response, dict) or response.get("currency") != "IDR":
                    raise StoreError("INVALID_RESPONSE")
                balance, api_status = money(integer(response.get("balance"))), "Terhubung"
            except StoreError as exc:
                balance, api_status = "Tidak tersedia", "Tidak terhubung • "+exc.public
            except Exception as exc:
                logging.warning("OTP provider balance: %s", type(exc).__name__)
                balance, api_status = "Tidak tersedia", "Tidak terhubung"
        attempts = self.store.repo.one("SELECT count(*) n FROM otp_purchase_attempts WHERE state IN ('RESERVED','REQUESTING','PENDING_RECONCILIATION')")["n"]
        notifications = self.store.repo.one("SELECT count(*) n FROM otp_notifications WHERE status IN ('PENDING','SENDING','FAILED')")["n"]
        settings = self.store.settings()
        text = OwnerFormatter.dashboard(stats=stats, settings=settings, balance=balance, api_status=api_status,
            attempts=attempts, notifications=notifications, worker_errors=worker_errors, config_error=self.store.config.error)
        await self.store.ui.send(message, text, self.store.ui.admin_keyboard(user, OwnerFormatter.dashboard_rows()))

    @staticmethod
    def number(value, low, high):
        if not re.fullmatch(r"[0-9]{1,12}", str(value)):
            raise StoreError("INPUT", "Gunakan angka bulat tanpa pemisah.")
        return integer(int(value), low, high)

    def rule(self, user, scope, key, rule):
        self.authorize(user)
        self.store.repo.execute("INSERT INTO otp_pricing_rules VALUES(?,?,?,?) ON CONFLICT(scope,scope_key) DO UPDATE SET rule=excluded.rule,updated_at=excluded.updated_at", (scope, key, encoded(rule), time.time()))


def register(router, store):
    admin = AdminHandler(store)

    async def guard(message, user):
        if not message or str(message.chat.type) != "private" or message.chat.id != user:
            raise StoreError("PRIVATE", "Gunakan /otp melalui chat privat bot.")
        if store.host.security_blocked(user):
            raise StoreError("FORBIDDEN", "Akun kamu dibatasi owner.")
        if not await store.host.is_channel_member(message.bot, user):
            raise StoreError("CHANNEL", "Akses mengikuti verifikasi channel bot. Buka /start dan ikuti petunjuk bergabung dahulu.")
        profile = store.repo.one("SELECT username FROM verified_users WHERE user_id=?", (user,))
        username = profile["username"] if profile else ""
        if message.from_user and message.from_user.id == user:
            username = getattr(message.from_user, "username", "") or username
        store.host.mark_user_verified(user, username)

    async def failure(message, exc, *, user=None, admin_context=False):
        text = (exc.public if admin_context and store.host.is_owner(user) and isinstance(exc, StoreError)
                else UserFormatter.error(exc))
        if not isinstance(exc, StoreError):
            logging.warning("OTP handler: %s", type(exc).__name__)
        await store.ui.send(message, "⚠️ "+escape(text))

    async def dispatch(message, user, action, payload, state):
        # Apply this before every admin action, including history pagination and
        # previously issued callbacks whose owner's role may have been revoked.
        if action.startswith("admin"):
            admin.authorize(user)
        if action in {"home", "help", "balance", "countries", "orders", "history"}:
            await state.clear()
        if action == "home":
            await store.ui.home(message, user)
        elif action == "help":
            await store.ui.send(message, HELP, store.ui.home_keyboard(user))
        elif action == "balance":
            await store.ui.send(message, "💰 Saldo kamu: <b>"+money(store.host.get_balance(user))+"</b>\nGunakan menu deposit bot untuk mengisi saldo.", store.ui.home_keyboard(user))
        elif action in {"countries", "services", "operators", "products"}:
            if action == "services" and "country" not in payload:
                await store.ui.selection(message, user, "countries")
            else:
                await store.ui.selection(message, user, action, payload, payload.get("query", ""))
        elif action in {"orders", "history", "admin_orders"}:
            await store.ui.history(message, user, action == "history", int(payload.get("page", 0)), action == "admin_orders")
        elif action == "search":
            await state.set_state(OTPState.search)
            await state.update_data(otp_search=payload)
            await store.ui.send(message, "🔎 Kirim nama negara/layanan untuk dicari. /otp untuk kembali.")
        elif action == "quote":
            quote = await store.purchase.quote(user, payload["product"])
            await store.ui.quote(message, user, quote)
        elif action == "buy":
            attempt = await store.purchase.buy(user, payload["quote"])
            if attempt["state"] == "CAPTURED":
                order = store.repo.one("SELECT * FROM otp_orders WHERE attempt_id=?", (attempt["attempt_id"],))
                await store.ui.send(message, "✅ Nomor berhasil dibeli. Detail akan dikirim otomatis. Order #"+str(order["id"])+".", store.ui.order_keyboard(order, user))
            elif attempt["state"] == "FAILED":
                await store.ui.send(message, "❌ Pembelian gagal. Saldo yang ditahan telah dilepas. "+escape(UserFormatter.error(StoreError(attempt["error_code"]))))
            else:
                await store.ui.send(message, "⏳ Pembelian sedang direkonsiliasi. Saldo ditahan untuk transaksi ini. Jangan membeli ulang; hasil akan dikirim otomatis.")
        elif action == "check":
            await store.ui.check(message, user, payload["id"])
        elif action in {"confirm_cancel", "confirm_finish"}:
            order = store.repo.owned(user, payload["id"])
            kind = action.removeprefix("confirm_")
            await store.ui.send(message, "Konfirmasi "+("pembatalan" if kind == "cancel" else "penyelesaian")+f" order #{order['id']}?\n"
                + ("Refund diproses setelah pembatalan dan pengembalian dana terkonfirmasi." if kind == "cancel" else "Order selesai tidak mendapat refund."),
                store.ui.keyboard(user, [[("✅ KONFIRMASI", kind, {"id": order["id"]})], [("⬅️ KEMBALI", "check", {"id": order["id"]})]]))
        elif action in {"cancel", "finish", "resend"}:
            await store.orders.action(user, payload["id"], action)
            await store.ui.send(message, "✅ "+{"cancel": "Pembatalan diterima. Status refund tersedia di pesanan.", "finish": "Order selesai.", "resend": "Permintaan SMS baru diterima. Tunggu SMS berikutnya; SMS lama tidak dikirim ulang."}[action])
        elif action == "reactivate":
            parent = store.repo.owned(user, payload["id"])
            product = {"id": parent["product_id"], "catalog_product_id": parent["catalog_product_id"], "country_id": parent["country_id"], "platform_id": parent["platform_id"],
                       "operator_id": parent["operator_id"], "operator_name": parent["operator_name"], "country_name": parent["country_name"], "platform_name": parent["platform_name"]}
            await store.ui.quote(message, user, await store.purchase.quote(user, product, parent))
        elif action.startswith("admin"):
            admin.authorize(user)
            sections = {"admin": [], "admin_prices_menu": ["harga"], "admin_balance": ["saldo"], "admin_stats": ["statistik"], "admin_profit": ["profit"], "admin_status": ["status"], "admin_webhook": ["webhook"], "admin_pending": ["pending"]}
            if action in sections:
                await admin.handle(message, user, sections[action])
            elif action == "admin_prices":
                await admin.handle(message, user, ["harga", payload["kind"]])
            elif action == "admin_toggle":
                await admin.handle(message, user, ["off" if store.settings()["enabled"] else "on"])
            elif action == "admin_modes":
                await store.ui.send(message, "Pilih mode harga:", store.ui.admin_keyboard(user, [[(name, "admin_set_mode", {"mode": mode})] for name, mode in [("Persentase", "persen"), ("Nominal", "nominal"), ("Kombinasi", "kombinasi")]]))
            elif action == "admin_set_mode":
                await admin.handle(message, user, ["markup", "mode", payload["mode"]])
            elif action == "admin_input":
                await state.set_state(OTPState.admin_value)
                await state.update_data(otp_admin_setting=payload["setting"])
                await store.ui.send(message, "Kirim nilai "+("persentase" if payload["setting"] == "percent" else "tambahan nominal rupiah (angka bulat)")+". /otp untuk kembali.")
            elif action == "admin_webhook_connect":
                await store.configure_webhook(user)
                await store.ui.send(message, "✅ Webhook resmi terhubung. Secret diselaraskan dalam memori; polling tetap aktif.")
            elif action == "admin_webhook_test":
                result = await store.api.request("POST", "/webhook/test")
                await store.ui.send(message, "🧪 Provider menerima permintaan test webhook. Periksa /otp admin webhook dan log HTTP untuk hasil pengiriman.")
            elif action == "admin_retry":
                store.repo.execute("UPDATE otp_notifications SET status='PENDING',attempts=0,next_retry_at=0 WHERE status='FAILED'")
                await store.ui.send(message, "✅ Notifikasi gagal dijadwalkan ulang; notifikasi yang sudah terkirim tetap tersimpan.")

    @router.message(Command("otp"))
    async def otp_command(message, state):
        user, admin_context = None, False
        try:
            user = message.from_user.id
            await guard(message, user)
            store.repo.rate(user, "command", 30, 60)
            text = message.text or ""
            args = text.split()[1:]
            if len(text) > 1024 or len(args) > 10:
                raise StoreError("INPUT", "Command terlalu panjang.")
            admin_context = bool(args and args[0].lower() == "admin")
            if admin_context:
                await admin.handle(message, user, args[1:])
                return
            name = args[0].lower() if args else ""
            mapping = {"": "home", "beli": "countries", "negara": "countries", "layanan": "services", "saldo": "balance", "pesanan": "orders", "cek": "check", "ulang": "resend", "batal": "confirm_cancel", "selesai": "confirm_finish", "riwayat": "history", "aktifkan": "reactivate", "bantuan": "help"}
            if name not in mapping:
                raise StoreError("INPUT", "Command belum dikenal. Gunakan /otp bantuan.")
            action, payload = mapping[name], {}
            if action in {"check", "resend", "confirm_cancel", "confirm_finish", "reactivate"}:
                if len(args) != 2:
                    raise StoreError("INPUT", "Gunakan /otp "+name+" <id order bot>.")
                payload["id"] = admin.number(args[1], 1, 2**31-1)
            await dispatch(message, user, action, payload, state)
        except Exception as exc:
            await failure(message, exc, user=user, admin_context=admin_context)

    @router.callback_query(F.data.startswith(PREFIX))
    async def otp_callback(call, state):
        action = ""
        try:
            user = call.from_user.id
            await guard(call.message, user)
            store.repo.rate(user, "callback", 40, 60)
            action, payload = store.read_token(user, (call.data or "")[len(PREFIX):])
            await call.answer()
            await dispatch(call.message, user, action, payload, state)
        except Exception as exc:
            await call.answer("Permintaan OTP belum berhasil.", show_alert=True)
            if call.message and str(call.message.chat.type) == "private" and call.message.chat.id == call.from_user.id:
                await failure(call.message, exc, user=call.from_user.id, admin_context=action.startswith("admin"))

    @router.message(OTPState.search, F.text & ~F.text.startswith("/"))
    async def otp_search(message, state):
        try:
            await guard(message, message.from_user.id)
            store.repo.rate(message.from_user.id, "search", 10, 60)
            data = (await state.get_data()).get("otp_search", {})
            await state.clear()
            await store.ui.selection(message, message.from_user.id, data["kind"], data["context"], (message.text or "")[:80])
        except Exception as exc:
            await failure(message, exc, user=message.from_user.id)

    @router.message(OTPState.admin_value, F.text & ~F.text.startswith("/"))
    async def otp_admin_input(message, state):
        try:
            await guard(message, message.from_user.id)
            admin.authorize(message.from_user.id)
            key = (await state.get_data()).get("otp_admin_setting")
            await admin.handle(message, message.from_user.id, ["markup", "persen" if key == "percent" else "nominal", (message.text or "").strip()])
            await state.clear()
        except Exception as exc:
            await failure(message, exc, user=message.from_user.id, admin_context=True)

    return store
