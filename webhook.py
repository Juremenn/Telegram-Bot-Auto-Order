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

from contextlib import asynccontextmanager
import logging

from fastapi import BackgroundTasks, FastAPI, Request, HTTPException, status
from fastapi.responses import JSONResponse

import database as db
import paykita

logger = logging.getLogger(__name__)


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    """Inisialisasi DB saat startup dan tutup resource HTTP/Bot saat shutdown."""
    db.init_db()
    logger.info("Webhook server siap. Menunggu event dari PayKita...")
    yield
    try:
        from bot import close_standalone_bot
        await close_standalone_bot()
    except Exception:
        logger.exception("Gagal menutup standalone Bot client saat shutdown")
    try:
        await paykita.close_client()
    except Exception:
        logger.exception("Gagal menutup PayKita HTTP client saat shutdown")


app = FastAPI(
    title="AutoOrderBot Webhook",
    description="Webhook receiver untuk PayKita payment gateway",
    version="1.0.0",
    docs_url=None,    # Sembunyikan Swagger UI di production
    redoc_url=None,
    lifespan=_lifespan,
)

# ── Konstanta ─────────────────────────────────────────────────────────────────
# Daftar kemungkinan nama header signature dari webhook PayKita
SIGNATURE_HEADERS = (
    "x-signature",
    "x-paykita-signature",
    "x-hub-signature-256",
    "signature",
    "paykita-signature",
)


# ── Health check ──────────────────────────────────────────────────────────────

@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "AutoOrderBot Webhook"}


# ── Webhook PayKita ───────────────────────────────────────────────────────────

@app.post("/webhook/paykita")
async def webhook_paykita(
    request: Request,
    background_tasks: BackgroundTasks,
) -> JSONResponse:
    """
    Menerima notifikasi pembayaran dari PayKita.

    PayKita mengirim POST request dengan:
    - Header: `x-paykita-timestamp` dan `x-paykita-signature` (`v1=<hex>`)
    - Body  : JSON dengan informasi event & order
    """
    # 1. Baca raw body SEBELUM parse JSON (penting untuk kalkulasi HMAC)
    raw_body = await request.body()

    # 2. Ambil signature & timestamp dari header
    sig_value = next(
        (request.headers[h] for h in SIGNATURE_HEADERS if request.headers.get(h)),
        "",
    )
    timestamp = request.headers.get("x-paykita-timestamp", "")

    # 3. Verifikasi HMAC-SHA256 (timestamp + "." + raw_body)
    if not paykita.verify_webhook_signature(raw_body, sig_value, timestamp=timestamp):
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

    event_name = str(payload.get("event", "")).lower()
    if event_name == "webhook.test":
        logger.info("Webhook test diterima dari PayKita: id=%s", payload.get("id", ""))
        return JSONResponse({"ok": True, "received": True, "event": "webhook.test"})

    data = payload.get("data", payload) if isinstance(payload.get("data"), dict) else payload
    logger.info(
        "Webhook diterima: event=%s ref=%s order_id=%s status=%s",
        event_name or "-",
        data.get("reference"),
        data.get("order_id") or data.get("id"),
        data.get("status"),
    )

    # 5. Balas 200 OK secepatnya (<10s timeout PayKita) dan proses fulfillment di background
    background_tasks.add_task(_process_webhook_event, payload)
    return JSONResponse({"ok": True, "received": True})


async def _process_webhook_event(payload: dict) -> None:
    """
    Proses event dari webhook PayKita di background.

    Field yang digunakan (sesuai dokumentasi PayKita):
    - event          : "order.paid" (opsional)
    - data.order_id  : ID order dari PayKita (pay_...)
    - data.reference : referensi order kita (order_ref)
    - data.status    : status baru ("paid", "expired", dsb.)
    """
    try:
        event_name = str(payload.get("event", "")).lower()
        data = payload.get("data", payload) if isinstance(payload.get("data"), dict) else payload

        paykita_id = str(data.get("order_id") or data.get("id") or "")
        reference  = str(data.get("reference", ""))
        new_status = str(data.get("status", "")).upper()
        if not new_status and event_name == "order.paid":
            new_status = "PAID"

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

        # Jalankan fulfillment SEBELUM update status agar atomic guard
        # PENDING → PROCESSING di execute_order_fulfillment berjalan semestinya.
        if new_status == "PAID":
            await _run_fulfillment(order_ref, order)
        elif new_status in ("EXPIRED", "FAILED", "CANCELLED"):
            db.update_order_status(order_ref, new_status)
            db.release_order_stock(order_ref)
        else:
            db.update_order_status(order_ref, new_status)
    except Exception:
        logger.exception("Webhook: gagal memproses event payload=%s", payload)


async def _run_fulfillment(order_ref: str, order) -> None:
    """
    Jalankan fulfillment setelah pembayaran berhasil (status PAID).
    BUG-03: Menggunakan execute_order_fulfillment dari bot.py untuk menghindari
    duplikasi logika antara webhook dan auto-check polling.
    """
    # Impor lazy untuk menghindari circular import antara bot.py ↔ webhook.py
    try:
        from bot import execute_order_fulfillment

        # BUG-01/11: execute_order_fulfillment sudah punya idempotency guard internal
        await execute_order_fulfillment(
            order_ref=order_ref,
            order=order,
            send_notification=True,   # webhook path → kirim notif ke user
        )
        logger.info("Webhook: fulfillment selesai untuk order %s", order_ref)
    except Exception:
        logger.exception(
            "Gagal mengirim notifikasi ke user untuk order %s", order_ref
        )
