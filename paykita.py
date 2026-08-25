"""
paykita.py - Klien PayKita REST API

Dokumentasi resmi: https://pay.digikita.id/documentation
API Base URL     : https://pay.digikita.id/api

Catatan penting:
- API key TIDAK boleh muncul di log, response, atau output apapun.
- Semua endpoint, field, dan struktur mengacu pada dokumentasi resmi PayKita.
"""

import logging
import hashlib
import hmac
import json
from dataclasses import dataclass

import httpx

import config

logger = logging.getLogger(__name__)

# Timeout untuk request ke PayKita (detik)
_TIMEOUT = httpx.Timeout(30.0, connect=10.0)


# ── Data class response ───────────────────────────────────────────────────────

@dataclass
class OrderResult:
    """Hasil pembuatan order dari PayKita."""
    success: bool
    paykita_id: str | None        # ID order dari PayKita
    final_amount: int | None      # nominal akhir (bisa berbeda dari base_amount)
    qris_data: str | None         # string QRIS (untuk ditampilkan sebagai QR)
    checkout_url: str | None      # URL halaman bayar PayKita
    raw: dict                     # respons mentah (untuk disimpan ke DB)
    error: str | None             # pesan error jika gagal


# ── Fungsi utama ──────────────────────────────────────────────────────────────

async def create_order(base_amount: int, reference: str) -> OrderResult:
    """
    Buat order pembayaran di PayKita.

    Endpoint : POST /api/orders
    Auth     : header x-api-key
    Payload  : { "base_amount": <int>, "reference": "<str>" }

    Respons sukses (200):
    {
        "id"          : "...",
        "reference"   : "INV-001",
        "base_amount" : 10000,
        "final_amount": 10327,   # nominal akhir (jika ada nominal unik)
        "qris"        : "...",   # string QRIS dinamis
        "checkout_url": "https://pay.digikita.id/...",
        "status"      : "PENDING",
        ...
    }
    """
    # Strip trailing '/api' agar tidak dobel jika BASE_URL sudah mengandung /api
    _base = config.PAYKITA_BASE_URL.rstrip("/")
    if _base.endswith("/api"):
        _base = _base[:-4]
    url = f"{_base}/api/orders"
    payload = {
        "base_amount": base_amount,
        "reference": reference,
    }
    headers = {
        "x-api-key": config.PAYKITA_API_KEY,   # API key hanya di header, tidak di-log
        "content-type": "application/json",
        "accept": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(url, json=payload, headers=headers)

        # Catat HTTP status tanpa menampilkan API key
        logger.info("PayKita create_order → status=%s ref=%s", resp.status_code, reference)

        if not resp.is_success:
            # Coba ambil pesan error dari respons
            try:
                err_body = resp.json()
                err_msg = err_body.get("message") or err_body.get("error") or str(err_body)
            except Exception:
                err_msg = resp.text or f"HTTP {resp.status_code}"

            logger.error("PayKita error ref=%s (HTTP %s): %s", reference, resp.status_code, err_msg)
            return OrderResult(
                success=False,
                paykita_id=None,
                final_amount=None,
                qris_data=None,
                checkout_url=None,
                raw={},
                error=err_msg,
            )

        body = resp.json()
        if not isinstance(body, dict):
            return OrderResult(
                success=False,
                paykita_id=None,
                final_amount=None,
                qris_data=None,
                checkout_url=None,
                raw={},
                error="Format respons PayKita tidak valid",
            )

        # Cek jika PayKita mengembalikan ok=False di body
        if body.get("ok") is False:
            err_msg = body.get("message") or body.get("error") or "Gagal membuat order di PayKita"
            return OrderResult(
                success=False,
                paykita_id=None,
                final_amount=None,
                qris_data=None,
                checkout_url=None,
                raw=body,
                error=err_msg,
            )

        # PayKita membungkus data di dalam property "data": {"ok": true, "data": {...}}
        data = body.get("data", body) if isinstance(body.get("data"), dict) else body

        # Ambil nominal pembayaran (PayKita menggunakan 'pay_amount' yang sudah termasuk fee/kode unik)
        amount_val = data.get("pay_amount") or data.get("final_amount") or data.get("base_amount")
        try:
            final_amount = int(amount_val) if amount_val is not None else None
        except (ValueError, TypeError):
            final_amount = None

        return OrderResult(
            success=True,
            paykita_id=str(data.get("id", "")),
            final_amount=final_amount,
            qris_data=data.get("qris"),
            checkout_url=data.get("checkout_url"),
            raw=body,
            error=None,
        )

    except httpx.TimeoutException:
        logger.error("PayKita timeout saat membuat order ref=%s", reference)
        return OrderResult(
            success=False,
            paykita_id=None,
            final_amount=None,
            qris_data=None,
            checkout_url=None,
            raw={},
            error="Timeout saat menghubungi PayKita. Coba lagi.",
        )
    except Exception as exc:
        logger.exception("PayKita error tidak terduga ref=%s", reference)
        return OrderResult(
            success=False,
            paykita_id=None,
            final_amount=None,
            qris_data=None,
            checkout_url=None,
            raw={},
            error=f"Error tidak terduga: {exc}",
        )


async def get_order_status(paykita_id: str) -> dict | None:
    """
    Cek status order langsung ke PayKita.

    Endpoint: GET /api/orders/{id}

    TODO: Verifikasi nama endpoint ini di dokumentasi dashboard PayKita Anda.
    Jika endpoint berbeda, sesuaikan path di bawah ini.
    """
    _base = config.PAYKITA_BASE_URL.rstrip("/")
    if _base.endswith("/api"):
        _base = _base[:-4]
    url = f"{_base}/api/orders/{paykita_id}"
    headers = {
        "x-api-key": config.PAYKITA_API_KEY,
        "accept": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(url, headers=headers)

        if resp.is_success:
            body = resp.json()
            data = body.get("data", body) if isinstance(body.get("data"), dict) else body
            return data

        logger.warning("PayKita get_order status=%s id=%s: %s", resp.status_code, paykita_id, resp.text)
        return None

    except Exception:
        logger.exception("PayKita get_order error id=%s", paykita_id)
        return None


# ── Verifikasi Webhook ────────────────────────────────────────────────────────

def verify_webhook_signature(raw_body: bytes, received_signature: str) -> bool:
    """
    Verifikasi signature HMAC-SHA256 dari webhook PayKita.

    PayKita mengirim signature dalam header webhook.
    Secret diambil dari PAYKITA_WEBHOOK_SECRET di .env.

    TODO: Konfirmasi nama header signature di dashboard PayKita
          (kemungkinan: X-Signature, X-PayKita-Signature, atau X-Hub-Signature-256).

    Cara kerja:
      expected = HMAC-SHA256(secret, raw_body).hex()
      lalu bandingkan dengan received_signature (constant-time compare).
    """
    secret = config.PAYKITA_WEBHOOK_SECRET
    if not secret:
        # BUG-19: Secret wajib dikonfigurasi di production!
        # Tolak semua request webhook jika secret belum diset — jangan izinkan bypass.
        logger.error(
            "PAYKITA_WEBHOOK_SECRET belum dikonfigurasi di .env! "
            "Semua webhook DITOLAK untuk keamanan. Set variabel ini sebelum go-live!"
        )
        return False

    expected = hmac.new(
        secret.encode("utf-8"),
        raw_body,
        hashlib.sha256,
    ).hexdigest()

    # Gunakan compare_digest untuk mencegah timing attack
    return hmac.compare_digest(expected, received_signature.lower())


def parse_webhook_payload(raw_body: bytes) -> dict | None:
    """Parse JSON body webhook. Return None jika tidak valid."""
    try:
        return json.loads(raw_body)
    except json.JSONDecodeError:
        logger.error("Webhook: body bukan JSON valid")
        return None
