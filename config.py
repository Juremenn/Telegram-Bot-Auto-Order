"""
config.py - Konfigurasi terpusat dari .env
"""

import os
from dotenv import load_dotenv

# Muat variabel dari file .env
load_dotenv()


def _require(key: str) -> str:
    """Ambil env var wajib; raise ValueError jika kosong."""
    value = os.getenv(key, "").strip()
    if not value:
        raise ValueError(
            f"[config] Environment variable '{key}' tidak ditemukan atau kosong. "
            f"Pastikan file .env sudah dikonfigurasi."
        )
    return value


def _optional(key: str, default: str = "") -> str:
    return os.getenv(key, default).strip()


# ── Telegram ──────────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN: str = _require("TELEGRAM_BOT_TOKEN")
ADMIN_TELEGRAM_ID: int = int(_require("ADMIN_TELEGRAM_ID"))

# ── PayKita ───────────────────────────────────────────────────────────────────
# API key TIDAK boleh di-log, ditampilkan, atau di-hardcode
PAYKITA_API_KEY: str = _require("PAYKITA_API_KEY")

# Base URL REST API PayKita (paykita.biz.id adalah backend resmi pay.digikita.id)
PAYKITA_BASE_URL: str = _optional("PAYKITA_BASE_URL", "https://pay.digikita.id/api")

# Webhook secret untuk verifikasi HMAC-SHA256
# TODO: Ambil nilai ini dari dashboard PayKita → Settings → Webhook
PAYKITA_WEBHOOK_SECRET: str = _optional("PAYKITA_WEBHOOK_SECRET", "")

# ── FastAPI Webhook Server ────────────────────────────────────────────────────
WEBHOOK_HOST: str = _optional("WEBHOOK_HOST", "0.0.0.0")
WEBHOOK_PORT: int = int(_optional("WEBHOOK_PORT", "8000"))

# URL publik server ini (digunakan untuk registrasi webhook ke PayKita jika ada)
# Contoh: https://yourdomain.com
PUBLIC_URL: str = _optional("PUBLIC_URL", "")

# ── Database ──────────────────────────────────────────────────────────────────
DB_PATH: str = _optional("DB_PATH", "data/orders.db")

# ── Order ─────────────────────────────────────────────────────────────────────
# Durasi kedaluwarsa order dalam menit
ORDER_EXPIRY_MINUTES: int = int(_optional("ORDER_EXPIRY_MINUTES", "30"))
