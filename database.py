"""
database.py - Manajemen database SQLite

Tabel:
- users   : data pengguna Telegram
- products: katalog produk
- orders  : rekap order dan status pembayaran
"""

import sqlite3
import os
import json
import logging
from datetime import datetime, timezone
from contextlib import contextmanager
from typing import Generator

import config

logger = logging.getLogger(__name__)


# ── Koneksi ───────────────────────────────────────────────────────────────────

def _get_connection() -> sqlite3.Connection:
    """Buat koneksi SQLite dengan row_factory."""
    os.makedirs(os.path.dirname(config.DB_PATH), exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")   # performa & konkurensi
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def get_db() -> Generator[sqlite3.Connection, None, None]:
    """Context manager untuk koneksi database (auto-commit / rollback)."""
    conn = _get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ── Inisialisasi Tabel ────────────────────────────────────────────────────────

def init_db() -> None:
    """Buat semua tabel jika belum ada dan isi produk contoh."""
    with get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id              INTEGER PRIMARY KEY,
                telegram_id     INTEGER UNIQUE NOT NULL,
                username        TEXT,
                full_name       TEXT,
                created_at      TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS products (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                name             TEXT NOT NULL,
                description      TEXT,
                price            INTEGER NOT NULL,   -- harga dalam rupiah (integer)
                stock            INTEGER DEFAULT -1, -- -1 = unlimited
                delivery_content TEXT DEFAULT '',    -- pesan / info akun yang otomatis dikirim setelah bayar
                is_active        INTEGER DEFAULT 1,
                created_at       TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS orders (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                order_ref       TEXT UNIQUE NOT NULL,   -- referensi unik (misal: ORD-20260825-XXXX)
                paykita_id      TEXT,                   -- ID order dari PayKita
                user_id         INTEGER NOT NULL,
                product_id      INTEGER NOT NULL,
                qty             INTEGER NOT NULL DEFAULT 1,
                base_amount     INTEGER NOT NULL,       -- harga sebelum fee unik
                final_amount    INTEGER,                -- nominal akhir dari PayKita
                status          TEXT NOT NULL DEFAULT 'PENDING',
                -- PENDING | PAID | PROCESSING | COMPLETED | FAILED | EXPIRED
                qris_data       TEXT,   -- konten QRIS string
                checkout_url    TEXT,   -- URL halaman pembayaran PayKita
                payment_info    TEXT,   -- JSON respons PayKita (disimpan sebagai teks)
                fulfillment     TEXT,   -- hasil fulfillment (lisensi, akun, dsb.)
                chat_id         INTEGER, -- Telegram chat_id
                message_id      INTEGER, -- Telegram message_id untuk pin & auto update
                created_at      TEXT NOT NULL DEFAULT (datetime('now')),
                paid_at         TEXT,
                completed_at    TEXT,
                FOREIGN KEY (user_id)    REFERENCES users(id),
                FOREIGN KEY (product_id) REFERENCES products(id)
            );

            CREATE TABLE IF NOT EXISTS product_stocks (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id  INTEGER NOT NULL,
                content     TEXT NOT NULL,        -- info akun/lisensi per unit stok
                is_used     INTEGER DEFAULT 0,    -- 0 = ready, 1 = sold
                order_id    INTEGER,              -- ID order pembeli
                created_at  TEXT NOT NULL DEFAULT (datetime('now')),
                used_at     TEXT,
                FOREIGN KEY (product_id) REFERENCES products(id),
                FOREIGN KEY (order_id)   REFERENCES orders(id)
            );

            CREATE TABLE IF NOT EXISTS admin_states (
                telegram_id INTEGER PRIMARY KEY,
                state       TEXT NOT NULL,
                data        TEXT,
                updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE INDEX IF NOT EXISTS idx_orders_user   ON orders(user_id);
            CREATE INDEX IF NOT EXISTS idx_orders_ref    ON orders(order_ref);
            CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);
            CREATE INDEX IF NOT EXISTS idx_stocks_prod   ON product_stocks(product_id, is_used);
        """)

        # Migrasi: pastikan kolom delivery_content ada jika tabel sudah pernah dibuat sebelumnya
        cols = [r["name"] for r in conn.execute("PRAGMA table_info(products)").fetchall()]
        if "delivery_content" not in cols:
            conn.execute("ALTER TABLE products ADD COLUMN delivery_content TEXT DEFAULT ''")

        # Migrasi: pastikan kolom chat_id dan message_id ada di orders
        cols_orders = [r["name"] for r in conn.execute("PRAGMA table_info(orders)").fetchall()]
        if "chat_id" not in cols_orders:
            conn.execute("ALTER TABLE orders ADD COLUMN chat_id INTEGER")
        if "message_id" not in cols_orders:
            conn.execute("ALTER TABLE orders ADD COLUMN message_id INTEGER")

        # Bersihkan item stok yang sudah pernah terjual dari pool
        conn.execute("DELETE FROM product_stocks WHERE is_used = 1")

        # Isi produk contoh jika tabel masih kosong
        row = conn.execute("SELECT COUNT(*) AS cnt FROM products").fetchone()
        if row["cnt"] == 0:
            _seed_products(conn)

    sync_all_products_stock()
    logger.info("Database diinisialisasi: %s", config.DB_PATH)


def _seed_products(conn: sqlite3.Connection) -> None:
    """Isi produk demo."""
    products = [
        (
            "Akun Netflix Premium 1 Bulan",
            "Akun Netflix Premium, 4 layar UHD, garansi 30 hari.",
            45_000,
            -1,
            "📧 Email: netflix.user@mail.com\n🔑 Password: NetFlixPass2026\n📌 Profile: No. 1 (PIN: 1234)\n⚠️ Dilarang ubah password/email.",
        ),
        (
            "Akun Spotify Premium 1 Bulan",
            "Akun Spotify Premium individual, streaming tanpa iklan.",
            25_000,
            -1,
            "📧 Email: spotify.premium@mail.com\n🔑 Password: SpotifyPass2026\n🎵 Selamat mendengarkan musik tanpa jeda!",
        ),
        (
            "VPN Premium 30 Hari",
            "Akses VPN cepat, server 50+ negara, bandwidth unlimited.",
            35_000,
            50,
            "🔑 License Key: VPN-PREM-9948-2847-XF88\n🌐 Download app: https://example.com/vpn\n📋 Paste license key di aplikasi.",
        ),
        (
            "Domain .com 1 Tahun",
            "Registrasi domain .com baru untuk 1 tahun.",
            150_000,
            -1,
            "🌐 Kode Kupon Registrasi: DOMAIN-COM-2026-X88\n🔗 Link redeem: https://example.com/domain/redeem",
        ),
    ]
    conn.executemany(
        """
        INSERT INTO products (name, description, price, stock, delivery_content)
        VALUES (?, ?, ?, ?, ?)
        """,
        products,
    )
    logger.info("Produk demo berhasil ditambahkan.")


# ── Helper: Users ─────────────────────────────────────────────────────────────

def upsert_user(telegram_id: int, username: str | None, full_name: str) -> None:
    """Simpan atau perbarui data pengguna."""
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO users (telegram_id, username, full_name)
            VALUES (?, ?, ?)
            ON CONFLICT(telegram_id) DO UPDATE SET
                username  = excluded.username,
                full_name = excluded.full_name
            """,
            (telegram_id, username, full_name),
        )


def get_user_db_id(telegram_id: int) -> int | None:
    """Ambil primary key (id) pengguna berdasarkan telegram_id."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT id FROM users WHERE telegram_id = ?", (telegram_id,)
        ).fetchone()
    return row["id"] if row else None


def get_all_users() -> list[sqlite3.Row]:
    """Ambil semua pengguna yang terdaftar di database untuk keperluan broadcast."""
    with get_db() as conn:
        return conn.execute(
            "SELECT telegram_id, username, full_name, created_at FROM users ORDER BY id ASC"
        ).fetchall()


def get_user_count() -> int:
    """Hitung total pengguna yang terdaftar."""
    with get_db() as conn:
        row = conn.execute("SELECT COUNT(*) AS cnt FROM users").fetchone()
        return row["cnt"] if row else 0


# ── Helper: Products ──────────────────────────────────────────────────────────

def get_all_products(only_in_stock: bool = False) -> list[sqlite3.Row]:
    with get_db() as conn:
        if only_in_stock:
            return conn.execute(
                "SELECT * FROM products WHERE is_active = 1 AND (stock > 0 OR stock = -1) ORDER BY id"
            ).fetchall()
        return conn.execute(
            "SELECT * FROM products WHERE is_active = 1 ORDER BY id"
        ).fetchall()


def get_product(product_id: int) -> sqlite3.Row | None:
    with get_db() as conn:
        return conn.execute(
            "SELECT * FROM products WHERE id = ? AND is_active = 1", (product_id,)
        ).fetchone()


def add_product(
    name: str,
    description: str,
    price: int,
    stock: int = -1,
    delivery_content: str = "",
) -> int:
    """Tambah produk baru ke katalog."""
    with get_db() as conn:
        cursor = conn.execute(
            """
            INSERT INTO products (name, description, price, stock, delivery_content, is_active)
            VALUES (?, ?, ?, ?, ?, 1)
            """,
            (name, description, price, stock, delivery_content),
        )
        return cursor.lastrowid  # type: ignore[return-value]


def update_product_delivery_content(product_id: int, delivery_content: str) -> None:
    """Ubah pesan pengiriman / info akun yang dikirim setelah bayar."""
    with get_db() as conn:
        conn.execute(
            "UPDATE products SET delivery_content = ? WHERE id = ?",
            (delivery_content, product_id),
        )


def update_product_name(product_id: int, name: str) -> None:
    """Ubah nama produk."""
    with get_db() as conn:
        conn.execute("UPDATE products SET name = ? WHERE id = ?", (name, product_id))


def update_product_description(product_id: int, description: str) -> None:
    """Ubah deskripsi produk."""
    with get_db() as conn:
        conn.execute("UPDATE products SET description = ? WHERE id = ?", (description, product_id))


def update_product_price(product_id: int, price: int) -> None:
    """Ubah harga produk."""
    with get_db() as conn:
        conn.execute("UPDATE products SET price = ? WHERE id = ?", (price, product_id))


def update_product_stock(product_id: int, new_stock: int) -> None:
    """Ubah jumlah stok produk (misal: 0, 50, atau -1 untuk unlimited)."""
    with get_db() as conn:
        conn.execute(
            "UPDATE products SET stock = ? WHERE id = ?",
            (new_stock, product_id),
        )


def adjust_product_stock(product_id: int, delta: int) -> int | None:
    """
    Tambah atau kurangi stok produk.
    Mengembalikan nilai stok yang baru.
    """
    with get_db() as conn:
        prod = conn.execute("SELECT stock FROM products WHERE id = ?", (product_id,)).fetchone()
        if not prod:
            return None
        current = prod["stock"]
        if current == -1:
            # Jika sebelumnya unlimited dan ditambah, set ke delta atau tetap
            new_stock = max(0, delta) if delta > 0 else 0
        else:
            new_stock = max(0, current + delta)

        conn.execute("UPDATE products SET stock = ? WHERE id = ?", (new_stock, product_id))
        return new_stock


def delete_product(product_id: int) -> None:
    """Nonaktifkan / hapus produk dari katalog."""
    with get_db() as conn:
        # Cek apakah sudah pernah dipesan
        orders_cnt = conn.execute(
            "SELECT COUNT(*) AS cnt FROM orders WHERE product_id = ?", (product_id,)
        ).fetchone()["cnt"]

        if orders_cnt > 0:
            # Soft delete agar riwayat order masa lalu tetap terjaga
            conn.execute("UPDATE products SET is_active = 0 WHERE id = ?", (product_id,))
        else:
            # Hard delete jika belum pernah ada transaksi
            conn.execute("DELETE FROM product_stocks WHERE product_id = ?", (product_id,))
            conn.execute("DELETE FROM products WHERE id = ?", (product_id,))


# ── Helper: Stock Items (Info Akun Per Unit Stok) ────────────────────────────

def add_stock_items(product_id: int, items: list[str]) -> int:
    """Tambah satu atau beberapa item stok akun ke pool produk."""
    clean_items = [it.strip() for it in items if it.strip()]
    if not clean_items:
        return 0
    with get_db() as conn:
        conn.executemany(
            "INSERT INTO product_stocks (product_id, content, is_used) VALUES (?, ?, 0)",
            [(product_id, it) for it in clean_items],
        )
    sync_product_stock_count(product_id)
    return len(clean_items)


def get_available_stock_items(product_id: int) -> list[sqlite3.Row]:
    """Ambil semua stok yang masih tersedia (ready / belum terjual)."""
    with get_db() as conn:
        return conn.execute(
            "SELECT * FROM product_stocks WHERE product_id = ? AND is_used = 0 ORDER BY id ASC",
            (product_id,),
        ).fetchall()


def get_all_stock_items(product_id: int) -> list[sqlite3.Row]:
    """Ambil semua stok (tersedia & terjual)."""
    with get_db() as conn:
        return conn.execute(
            "SELECT * FROM product_stocks WHERE product_id = ? ORDER BY is_used ASC, id ASC",
            (product_id,),
        ).fetchall()


def get_stock_item(stock_id: int) -> sqlite3.Row | None:
    """Ambil data satu item stok berdasarkan ID."""
    with get_db() as conn:
        return conn.execute(
            "SELECT * FROM product_stocks WHERE id = ?", (stock_id,)
        ).fetchone()


def update_stock_item_content(stock_id: int, content: str) -> None:
    """Edit isi pesan info akun pada stok tertentu."""
    with get_db() as conn:
        conn.execute("UPDATE product_stocks SET content = ? WHERE id = ?", (content, stock_id))


def delete_stock_item(stock_id: int) -> None:
    """Hapus satu item stok."""
    # BUG-07: Pastikan product_id di-init sebelum with-block agar tidak UnboundLocalError
    product_id: int | None = None
    with get_db() as conn:
        row = conn.execute("SELECT product_id FROM product_stocks WHERE id = ?", (stock_id,)).fetchone()
        if row:
            product_id = row["product_id"]
            conn.execute("DELETE FROM product_stocks WHERE id = ?", (stock_id,))
    if product_id is not None:
        sync_product_stock_count(product_id)


def claim_stock_item(product_id: int, order_id: int | None = None) -> str | None:
    """
    Ambil 1 item stok akun yang ready (FIFO), langsung singkirkan/hapus dari pool
    stok aktif, dan kembalikan isi info akunnya untuk disimpan di riwayat order.
    """
    with get_db() as conn:
        item = conn.execute(
            "SELECT id, content FROM product_stocks WHERE product_id = ? AND is_used = 0 ORDER BY id ASC LIMIT 1",
            (product_id,),
        ).fetchone()
        if item:
            conn.execute("DELETE FROM product_stocks WHERE id = ?", (item["id"],))
            content = item["content"]
        else:
            content = None
    sync_product_stock_count(product_id)
    return content


def reserve_stock_for_order(product_id: int, order_id: int, qty: int = 1) -> bool:
    """
    Kunci/reservasi sejumlah `qty` unit stok untuk order yang baru dibuat (tahap pending/QRIS).
    Stok yang di-reserve (is_used = 2) langsung tidak dihitung lagi di katalog,
    sehingga pembeli lain tidak akan bisa membeli unit yang sama saat proses transfer.
    """
    if qty <= 0:
        return False

    with get_db() as conn:
        prod = conn.execute("SELECT stock FROM products WHERE id = ?", (product_id,)).fetchone()
        if not prod:
            return False

        # Jika produk unlimited, tidak perlu kunci stok pool
        if prod["stock"] == -1:
            return True

        # Cek apakah produk memiliki item di pool stock
        pool_items = conn.execute(
            "SELECT id FROM product_stocks WHERE product_id = ? AND is_used = 0 ORDER BY id ASC LIMIT ?",
            (product_id, qty),
        ).fetchall()

        if pool_items:
            if len(pool_items) < qty:
                return False  # Stok ready tidak cukup

            item_ids = [it["id"] for it in pool_items]
            placeholders = ",".join("?" for _ in item_ids)
            conn.execute(
                f"UPDATE product_stocks SET is_used = 2, order_id = ? WHERE id IN ({placeholders})",
                [order_id] + item_ids,
            )
            # Hitung sisa stok yang benar-benar ready (is_used = 0)
            avail = conn.execute(
                "SELECT COUNT(*) AS avail FROM product_stocks WHERE product_id = ? AND is_used = 0",
                (product_id,),
            ).fetchone()["avail"]
            conn.execute("UPDATE products SET stock = ? WHERE id = ?", (avail, product_id))
            return True
        elif prod["stock"] >= qty:
            # Jika produk tanpa pool akun tapi punya manual stock counter
            conn.execute("UPDATE products SET stock = stock - ? WHERE id = ? AND stock >= ?", (qty, product_id, qty))
            return True
        else:
            return False


def claim_reserved_stock_items(product_id: int, order_id: int, qty: int = 1) -> list[str]:
    """
    Klaim semua stok yang sudah di-reservasi untuk order ini saat pembayaran sukses (PAID).
    Hapus unit dari pool dan kembalikan daftar string isi info akunnya.
    """
    contents: list[str] = []
    with get_db() as conn:
        items = conn.execute(
            "SELECT id, content FROM product_stocks WHERE order_id = ? AND is_used = 2 ORDER BY id ASC",
            (order_id,),
        ).fetchall()
        if items:
            item_ids = [it["id"] for it in items]
            placeholders = ",".join("?" for _ in item_ids)
            conn.execute(f"DELETE FROM product_stocks WHERE id IN ({placeholders})", item_ids)
            contents = [it["content"] for it in items]
        else:
            # Fallback jika order belum sempat di-reserve atau produk lama
            fallback_items = conn.execute(
                "SELECT id, content FROM product_stocks WHERE product_id = ? AND is_used = 0 ORDER BY id ASC LIMIT ?",
                (product_id, qty),
            ).fetchall()
            if fallback_items:
                f_ids = [it["id"] for it in fallback_items]
                placeholders = ",".join("?" for _ in f_ids)
                conn.execute(f"DELETE FROM product_stocks WHERE id IN ({placeholders})", f_ids)
                contents = [it["content"] for it in fallback_items]

    sync_product_stock_count(product_id)
    return contents


def claim_reserved_stock_item(product_id: int, order_id: int) -> str | None:
    """Wrapper single-item untuk kompatibilitas."""
    items = claim_reserved_stock_items(product_id, order_id, qty=1)
    return items[0] if items else None


def release_order_stock(order_ref: str) -> None:
    """
    Lepaskan / kembalikan stok yang di-reservasi jika order dibatalkan (CANCELLED),
    gagal (FAILED), atau kadaluarsa (EXPIRED).
    Stok akan langsung kembali bertambah dan ready untuk dibeli pembeli lain.
    """
    with get_db() as conn:
        order = conn.execute("SELECT id, product_id, qty, status FROM orders WHERE order_ref = ?", (order_ref,)).fetchone()
        if not order:
            return
        if order["status"] in ("PAID", "COMPLETED"):
            return

        order_id = order["id"]
        pid = order["product_id"]
        qty = order["qty"] if ("qty" in order.keys() and order["qty"]) else 1

        # 1. Kembalikan item pool yang statusnya reserved (is_used = 2) menjadi ready (is_used = 0)
        cursor = conn.execute(
            "UPDATE product_stocks SET is_used = 0, order_id = NULL WHERE order_id = ? AND is_used = 2",
            (order_id,),
        )
        released_pool_count = cursor.rowcount

        # 2. Jika tidak ada di pool dan produk bukan unlimited (-1), kembalikan manual stock counter
        prod = conn.execute("SELECT stock FROM products WHERE id = ?", (pid,)).fetchone()
        if prod and prod["stock"] != -1 and released_pool_count == 0:
            conn.execute("UPDATE products SET stock = stock + ? WHERE id = ?", (qty, pid))

    sync_product_stock_count(pid)


def sync_product_stock_count(product_id: int) -> int:
    """
    Sinkronisasi kolom stock di tabel products sesuai jumlah item di product_stocks.
    Jika produk bertipe pool atau stock >= 0:
    update stock = COUNT(is_used = 0).
    Jika tidak ada item ready, stock = 0.
    """
    with get_db() as conn:
        prod = conn.execute("SELECT stock FROM products WHERE id = ?", (product_id,)).fetchone()
        if not prod:
            return 0

        avail = conn.execute(
            "SELECT COUNT(*) AS avail FROM product_stocks WHERE product_id = ? AND is_used = 0",
            (product_id,),
        ).fetchone()["avail"]

        # Jika produk bukan unlimited (-1), atau jika ada item pool:
        if prod["stock"] != -1 or avail > 0:
            conn.execute("UPDATE products SET stock = ? WHERE id = ?", (avail, product_id))
            return avail
        return -1


def sync_all_products_stock() -> None:
    """Sinkronisasi stok semua produk aktif dalam SATU transaksi (BUG-06: hindari nested connections)."""
    with get_db() as conn:
        prods = conn.execute("SELECT id, stock FROM products WHERE is_active = 1").fetchall()
        for p in prods:
            pid = p["id"]
            avail = conn.execute(
                "SELECT COUNT(*) AS avail FROM product_stocks WHERE product_id = ? AND is_used = 0",
                (pid,),
            ).fetchone()["avail"]
            has_ever_had_pool = conn.execute(
                "SELECT COUNT(*) AS cnt FROM product_stocks WHERE product_id = ?", (pid,)
            ).fetchone()["cnt"]
            if p["stock"] != -1 or avail > 0 or has_ever_had_pool > 0:
                conn.execute("UPDATE products SET stock = ? WHERE id = ?", (avail, pid))


# ── Helper: Orders ────────────────────────────────────────────────────────────

def create_order(
    order_ref: str,
    user_id: int,
    product_id: int,
    qty: int,
    base_amount: int,
) -> int:
    """Buat order baru dan kembalikan ID-nya."""
    with get_db() as conn:
        cursor = conn.execute(
            """
            INSERT INTO orders (order_ref, user_id, product_id, qty, base_amount)
            VALUES (?, ?, ?, ?, ?)
            """,
            (order_ref, user_id, product_id, qty, base_amount),
        )
        return cursor.lastrowid  # type: ignore[return-value]


def update_order_paykita(
    order_ref: str,
    paykita_id: str,
    final_amount: int | None,
    qris_data: str | None,
    checkout_url: str | None,
    payment_info: str,
) -> None:
    """Simpan data PayKita ke order setelah berhasil dibuat."""
    with get_db() as conn:
        conn.execute(
            """
            UPDATE orders
            SET paykita_id   = ?,
                final_amount = ?,
                qris_data    = ?,
                checkout_url = ?,
                payment_info = ?
            WHERE order_ref = ?
            """,
            (paykita_id, final_amount, qris_data, checkout_url, payment_info, order_ref),
        )


def update_order_status(order_ref: str, status: str) -> None:
    """Perbarui status order."""
    now = datetime.now(timezone.utc).isoformat()
    with get_db() as conn:
        if status == "PAID":
            conn.execute(
                "UPDATE orders SET status = ?, paid_at = ? WHERE order_ref = ?",
                (status, now, order_ref),
            )
        elif status == "COMPLETED":
            conn.execute(
                "UPDATE orders SET status = ?, completed_at = ? WHERE order_ref = ?",
                (status, now, order_ref),
            )
        else:
            conn.execute(
                "UPDATE orders SET status = ? WHERE order_ref = ?",
                (status, order_ref),
            )


def mark_order_processing_if_pending(order_ref: str) -> bool:
    """
    BUG-01 / BUG-11 / BUG-12 — Atomic idempotency guard.
    Update status ke PROCESSING hanya jika status saat ini masih PENDING.
    Return True  = berhasil diklaim → lanjutkan fulfillment.
    Return False = order sudah diproses proses lain → skip.
    """
    now = datetime.now(timezone.utc).isoformat()
    with get_db() as conn:
        cursor = conn.execute(
            "UPDATE orders SET status = 'PROCESSING', paid_at = ? "
            "WHERE order_ref = ? AND status = 'PENDING'",
            (now, order_ref),
        )
        return cursor.rowcount > 0


def get_user_pending_order_count(user_db_id: int) -> int:
    """BUG-18: Hitung jumlah order PENDING milik user (untuk rate limiting)."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS cnt FROM orders WHERE user_id = ? AND status = 'PENDING'",
            (user_db_id,),
        ).fetchone()
        return row["cnt"] if row else 0


def update_order_fulfillment(order_ref: str, fulfillment: str) -> None:
    """Simpan hasil fulfillment ke order dan tandai COMPLETED."""
    now = datetime.now(timezone.utc).isoformat()
    with get_db() as conn:
        conn.execute(
            "UPDATE orders SET fulfillment = ?, status = 'COMPLETED', completed_at = ? WHERE order_ref = ?",
            (fulfillment, now, order_ref),
        )


def get_order_by_ref(order_ref: str) -> sqlite3.Row | None:
    with get_db() as conn:
        return conn.execute(
            "SELECT * FROM orders WHERE order_ref = ?", (order_ref,)
        ).fetchone()


def get_order_by_paykita_id(paykita_id: str) -> sqlite3.Row | None:
    with get_db() as conn:
        return conn.execute(
            "SELECT * FROM orders WHERE paykita_id = ?", (paykita_id,)
        ).fetchone()


def update_order_telegram_msg(order_ref: str, chat_id: int, message_id: int) -> None:
    """Simpan chat_id dan message_id pesan order Telegram untuk auto update & pin."""
    with get_db() as conn:
        conn.execute(
            "UPDATE orders SET chat_id = ?, message_id = ? WHERE order_ref = ?",
            (chat_id, message_id, order_ref),
        )


def get_pending_orders_with_msg() -> list[sqlite3.Row]:
    """Ambil order yang masih PENDING dan memiliki paykita_id untuk auto-check."""
    with get_db() as conn:
        return conn.execute(
            """
            SELECT * FROM orders
            WHERE status = 'PENDING'
              AND paykita_id IS NOT NULL
              AND chat_id IS NOT NULL
              AND message_id IS NOT NULL
            ORDER BY created_at DESC
            """
        ).fetchall()


def get_user_orders(user_db_id: int, limit: int = 10) -> list[sqlite3.Row]:
    """Ambil daftar order terbaru milik pengguna."""
    with get_db() as conn:
        return conn.execute(
            """
            SELECT o.*, p.name AS product_name
            FROM orders o
            JOIN products p ON o.product_id = p.id
            WHERE o.user_id = ?
            ORDER BY o.created_at DESC
            LIMIT ?
            """,
            (user_db_id, limit),
        ).fetchall()


# ── Helper: Persistent Admin State ───────────────────────────────────────────

def set_admin_state(telegram_id: int, state: str, data: dict | None = None) -> None:
    """Simpan state admin ke database agar tidak hilang saat bot restart."""
    now = datetime.now(timezone.utc).isoformat()
    data_json = json.dumps(data) if data else "{}"
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO admin_states (telegram_id, state, data, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(telegram_id) DO UPDATE SET state = excluded.state, data = excluded.data, updated_at = excluded.updated_at
            """,
            (telegram_id, state, data_json, now),
        )


def get_admin_state(telegram_id: int) -> tuple[str, dict]:
    """Ambil state admin yang aktif dari database."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT state, data FROM admin_states WHERE telegram_id = ?", (telegram_id,)
        ).fetchone()
        if row:
            try:
                data = json.loads(row["data"]) if row["data"] else {}
            except Exception:
                data = {}
            return row["state"], data
    return "", {}


def clear_admin_state(telegram_id: int) -> None:
    """Hapus state admin dari database."""
    with get_db() as conn:
        conn.execute("DELETE FROM admin_states WHERE telegram_id = ?", (telegram_id,))
