"""
webhook.py - FastAPI server untuk menerima webhook dari PayKita

Endpoint  : POST /webhook/paykita
Keamanan  : Verifikasi HMAC-SHA256 (header signature)

TODO: Konfirmasi nama header signature dari dashboard PayKita:
      - Kemungkinan: X-Signature | X-PayKita-Signature | X-Hub-Signature-256
      Sesuaikan konstanta SIGNATURE_HEADER di bawah jika berbeda.

Cara menjalankan:
  uvicorn webhook:app --host 0.0.0.0 --port 8000
"""

import logging

from fastapi import FastAPI, Request, HTTPException, status
from fastapi.responses import JSONResponse

import config
import database as db
import paykita

logger = logging.getLogger(__name__)

app = FastAPI(
    title="AutoOrderBot Webhook",
    description="Webhook receiver untuk PayKita payment gateway",
    version="1.0.0",
    docs_url=None,    # Sembunyikan Swagger UI di production
    redoc_url=None,
)

# ── Konstanta ─────────────────────────────────────────────────────────────────
# Daftar kemungkinan nama header signature dari webhook PayKita
SIGNATURE_HEADERS = [
    "x-signature",
    "x-paykita-signature",
    "x-hub-signature-256",
    "signature",
    "paykita-signature",
]


# ── Startup ───────────────────────────────────────────────────────────────────

@app.on_event("startup")
async def on_startup() -> None:
    """Inisialisasi database saat FastAPI startup."""
    db.init_db()
    logger.info("Webhook server siap. Menunggu event dari PayKita...")


# ── Health check ──────────────────────────────────────────────────────────────

@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "AutoOrderBot Webhook"}


# ── Webhook PayKita ───────────────────────────────────────────────────────────

@app.post("/webhook/paykita")
async def webhook_paykita(request: Request) -> JSONResponse:
    """
    Menerima notifikasi pembayaran dari PayKita.

    PayKita mengirim POST request dengan:
    - Header: signature HMAC-SHA256
    - Body  : JSON dengan informasi order yang berubah status
    """
    # 1. Baca raw body SEBELUM parse JSON (penting untuk kalkulasi HMAC)
    raw_body = await request.body()

    # 2. Ambil signature dari header (cek semua variasi umum)
    sig_value = ""
    for h in SIGNATURE_HEADERS:
        val = request.headers.get(h)
        if val:
            sig_value = val
            break

    # 3. Verifikasi HMAC-SHA256
    if not paykita.verify_webhook_signature(raw_body, sig_value):
        client_ip = request.client.host if request.client else "unknown"
        logger.warning("Webhook: signature tidak valid dari IP=%s", client_ip)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Signature tidak valid",
        )

    # 4. Parse payload
    payload = paykita.parse_webhook_payload(raw_body)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Payload tidak valid",
        )

    logger.info(
        "Webhook diterima: ref=%s status=%s",
        payload.get("reference"),
        payload.get("status"),
    )

    # 5. Proses event secara async (tidak block response)
    await _process_webhook_event(payload)

    # PayKita mengharapkan response 200 OK dengan cepat
    return JSONResponse({"received": True})


async def _process_webhook_event(payload: dict) -> None:
    """
    Proses event dari webhook PayKita.

    Field yang digunakan:
    - id        : ID order dari PayKita
    - reference : referensi order kita (order_ref)
    - status    : status baru ("PAID", "EXPIRED", dsb.)

    TODO: Sesuaikan field name jika dokumentasi PayKita menunjukkan nama berbeda.
    """
    # Mendukung payload yang dibungkus 'data' maupun flat
    data = payload.get("data", payload) if isinstance(payload.get("data"), dict) else payload

    paykita_id = str(data.get("id", ""))
    reference  = str(data.get("reference", ""))
    new_status = str(data.get("status", "")).upper()

    if not new_status:
        logger.warning("Webhook: payload tanpa field 'status', diabaikan.")
        return

    # Cari order di database (prioritas by reference, fallback by paykita_id)
    order = None
    if reference:
        order = db.get_order_by_ref(reference)
    if order is None and paykita_id:
        order = db.get_order_by_paykita_id(paykita_id)

    if order is None:
        logger.warning(
            "Webhook: order tidak ditemukan ref=%s pk_id=%s", reference, paykita_id
        )
        return

    order_ref   = order["order_ref"]
    curr_status = order["status"]

    # BUG-11: Jangan proses ulang jika order sudah di-fulfil atau sedang diproses
    if curr_status in ("COMPLETED", "PROCESSING", "PAID"):
        logger.info(
            "Webhook: order %s sudah berstatus %s, skip fulfillment.",
            order_ref, curr_status
        )
        return

    # Hindari memproses ulang status yang sama
    if curr_status == new_status:
        logger.info("Webhook: status %s tidak berubah untuk ref=%s, skip.", new_status, order_ref)
        return

    logger.info(
        "Webhook: order %s berubah %s → %s", order_ref, curr_status, new_status
    )

    # Update status di database
    db.update_order_status(order_ref, new_status)

    # Proses fulfillment jika pembayaran berhasil
    if new_status == "PAID":
        await _run_fulfillment(order_ref, order)


async def _run_fulfillment(order_ref: str, order) -> None:
    """
    Jalankan fulfillment setelah pembayaran berhasil (status PAID).
    BUG-03: Menggunakan execute_order_fulfillment dari bot.py untuk menghindari
    duplikasi logika antara webhook dan auto-check polling.
    """
    # Impor lazy untuk menghindari circular import antara bot.py ↔ webhook.py
    try:
        from bot import execute_order_fulfillment, send_payment_notification

        # BUG-01/11: execute_order_fulfillment sudah punya idempotency guard internal
        delivery = await execute_order_fulfillment(
            order_ref=order_ref,
            order=order,
            send_notification=True,   # webhook path → kirim notif ke user
        )
        logger.info("Webhook: fulfillment selesai untuk order %s", order_ref)
    except Exception:
        logger.exception(
            "Gagal mengirim notifikasi ke user untuk order %s", order_ref
        )
