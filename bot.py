"""
bot.py - Telegram Bot menggunakan python-telegram-bot v20+

Handler:
  /start         - Sambutan + menu utama
  /products      - Daftar produk
  /orders        - Riwayat pesanan
  /status <ref>  - Cek status pesanan
  Callback query - Navigasi menu, detail produk, pembelian
"""

import sys
import os
import io
import asyncio
import logging
import uuid
import json
import re
from datetime import datetime, timezone
import qrcode
from PIL import Image, ImageDraw, ImageFont
from telegram import (
    Update,
    Bot,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    BotCommand,
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from telegram.constants import ParseMode, ChatAction

import config
import database as db
import paykita

logger = logging.getLogger(__name__)

# Referensi global ke Application (dipakai oleh webhook.py)
_app: Application | None = None


# ══════════════════════════════════════════════════════════════════════════════
# ── Telegram Message Effects & Banner Assets ──────────────────────────────────
EFFECT_FIRE = "5104841245755180586"      # 🔥 Efek partikel api di sekitar pesan / layar
EFFECT_PARTY = "5046509860389126442"     # 🎉 Efek kembang api / celebration burst
MENU_IMAGE_PATH = os.path.join(os.path.dirname(__file__), "menu.png")


async def _send_with_effect(
    bot_or_msg,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
    parse_mode: str = ParseMode.HTML,
    effect_id: str | None = None,
    chat_id: int | None = None,
    photo_path: str | None = None,
):
    """
    Kirim pesan teks atau foto dengan efek partikel native Telegram (Message Effect ID).
    Jika effect_id tidak didukung / terjadi error effect, fallback kirim normal.
    """
    if photo_path and os.path.exists(photo_path):
        kwargs = {
            "caption": text,
            "reply_markup": reply_markup,
            "parse_mode": parse_mode,
        }
        if effect_id:
            kwargs["message_effect_id"] = effect_id

        try:
            with open(photo_path, "rb") as f:
                if hasattr(bot_or_msg, "reply_photo"):
                    return await bot_or_msg.reply_photo(photo=f, **kwargs)
                elif hasattr(bot_or_msg, "send_photo"):
                    return await bot_or_msg.send_photo(chat_id=chat_id, photo=f, **kwargs)
        except Exception as e:
            kwargs.pop("message_effect_id", None)
            with open(photo_path, "rb") as f:
                if hasattr(bot_or_msg, "reply_photo"):
                    return await bot_or_msg.reply_photo(photo=f, **kwargs)
                elif hasattr(bot_or_msg, "send_photo"):
                    return await bot_or_msg.send_photo(chat_id=chat_id, photo=f, **kwargs)

    # Kirim pesan teks jika tanpa foto
    kwargs = {
        "text": text,
        "reply_markup": reply_markup,
        "parse_mode": parse_mode,
    }
    if effect_id:
        kwargs["message_effect_id"] = effect_id

    try:
        if hasattr(bot_or_msg, "reply_text"):
            return await bot_or_msg.reply_text(**kwargs)
        elif hasattr(bot_or_msg, "send_message"):
            return await bot_or_msg.send_message(chat_id=chat_id, **kwargs)
    except Exception as e:
        # Fallback tanpa effect jika bot/chat tidak mendukung message_effect_id
        kwargs.pop("message_effect_id", None)
        if hasattr(bot_or_msg, "reply_text"):
            return await bot_or_msg.reply_text(**kwargs)
        elif hasattr(bot_or_msg, "send_message"):
            return await bot_or_msg.send_message(chat_id=chat_id, **kwargs)


def generate_qris_image(qris_string: str) -> io.BytesIO:
    """Generate QRIS image as JPEG BytesIO."""
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=2,
    )
    qr.add_data(qris_string)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    bio = io.BytesIO()
    bio.name = "QRIS.jpg"
    img.save(bio, "JPEG")
    bio.seek(0)
    return bio


async def _safe_edit_or_send_text(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
    parse_mode: str = ParseMode.HTML,
    force_new: bool = False,
) -> None:
    """
    Helper untuk menampilkan teks menu:
    - Jika force_new=True, atau pesan sebelumnya adalah FOTO, atau pesan sebelumnya adalah
      INVOICE PEMBAYARAN SUKSES / PESANAN SELESAI (agar info akun pembeli tetap aman & tidak terhapus):
      Kirim menu baru sebagai pesan teks baru di bawahnya.
    - Selain itu: edit pesan di tempat.
    """
    query = update.callback_query
    if query and query.message:
        is_invoice = False
        # BUG-15: Deteksi invoice lebih robust — cek keywords pembayaran sukses
        if query.message.text:
            msg_txt = query.message.text
            if any(k in msg_txt for k in [
                "PEMBAYARAN DITERIMA",
                "INFORMASI / DETAIL AKUN",
                "PAID (SELESAI)",
                "Pesanan Selesai",
                "Terima kasih telah berbelanja",
                "Detail Akun / Lisensi:",
                "Pembayaran Berhasil!",
            ]):
                is_invoice = True
        # Cek di caption gambar juga
        if not is_invoice and query.message.caption:
            cap_txt = query.message.caption
            if any(k in cap_txt for k in [
                "Tagihan Pembayaran QRIS",
                "Total Bayar:",
                "Order ID:",
            ]):
                # Ini adalah pesan QRIS foto — jangan edit, biarkan auto-check yang tangani
                is_invoice = True

        if force_new or is_invoice or (query.data and ":new" in query.data):
            # Pesan invoice / info akun tetap dipertahankan, kirim pesan menu baru di bawahnya
            new_msg = await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=text,
                reply_markup=reply_markup,
                parse_mode=parse_mode,
            )
            return

        try:
            if query.message.animation or query.message.photo:
                await query.edit_message_caption(caption=text, reply_markup=reply_markup, parse_mode=parse_mode)
            else:
                await query.edit_message_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
        except Exception as err:
            if "Message is not modified" not in str(err):
                logger.warning("_safe_edit_or_send_text error: %s", err)
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=text,
                    reply_markup=reply_markup,
                    parse_mode=parse_mode,
                )
    elif update.message:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode=parse_mode)


def _fmt_rupiah(amount: int) -> str:
    """Format angka ke format Rupiah. Contoh: 45000 → Rp 45.000"""
    return f"Rp {amount:,.0f}".replace(",", ".")


def _make_order_ref() -> str:
    """Buat referensi order unik. Contoh: ORD-20260825-A1B2"""
    now = datetime.now(timezone.utc).strftime("%Y%m%d")
    uid = uuid.uuid4().hex[:6].upper()
    return f"ORD-{now}-{uid}"


def _status_emoji(status: str) -> str:
    return {
        "PENDING":    "⏳",
        "PAID":       "✅",
        "PROCESSING": "⚙️",
        "COMPLETED":  "🎉",
        "FAILED":     "❌",
        "EXPIRED":    "🕐",
    }.get(status, "❓")


def _is_admin(user_id: int) -> bool:
    """Periksa apakah user adalah Owner / Admin."""
    return user_id == config.ADMIN_TELEGRAM_ID


def _build_main_menu_keyboard(user_id: int) -> InlineKeyboardMarkup:
    """Buat keyboard menu utama yang rapi dan compact."""
    buttons = [
        [InlineKeyboardButton("🛍️ Katalog Produk", callback_data="menu:products")],
        [InlineKeyboardButton("ℹ️ Bantuan", callback_data="menu:help")],
    ]
    if _is_admin(user_id):
        buttons.append([InlineKeyboardButton("⚙️ Panel Owner", callback_data="admin:stock")])
    return InlineKeyboardMarkup(buttons)


async def _is_user_subscribed(bot: Bot, user_id: int) -> bool:
    """
    Periksa apakah user sudah bergabung ke channel wajib (Force Sub).
    Mengembalikan True jika:
    - Fitur FORCE_SUB_CHANNEL dinonaktifkan / kosong
    - User berstatus member, administrator, atau creator di channel tersebut
    """
    channel = getattr(config, "FORCE_SUB_CHANNEL", "").strip()
    if not channel:
        return True

    try:
        member = await bot.get_chat_member(chat_id=channel, user_id=user_id)
        if member.status in ("creator", "administrator", "member"):
            return True
        if member.status == "restricted" and getattr(member, "is_member", False):
            return True
        return False
    except Exception as e:
        err_msg = str(e).lower()
        if "member list is inaccessible" in err_msg or "chat_admin_required" in err_msg:
            logger.error(
                "❌ PERINGATAN: Bot @sonelzbot belum diangkat menjadi Admin di channel %s! "
                "Jadikan bot sebagai Administrator di channel agar bot bisa memeriksa keanggotaan pembeli.",
                channel,
            )
            return False
        if "user not found" in err_msg or "participant_id_invalid" in err_msg or "user_not_participant" in err_msg:
            # User memang bukan member di channel
            return False
        logger.warning(
            "Gagal memeriksa keanggotaan user %s di channel %s: %s",
            user_id,
            channel,
            e,
        )
        return False


def _build_force_sub_keyboard() -> InlineKeyboardMarkup:
    """Buat keyboard untuk wajib join channel."""
    channel = getattr(config, "FORCE_SUB_CHANNEL", "@nelstores").strip()
    clean_channel = channel.lstrip("@")
    channel_url = f"https://t.me/{clean_channel}"
    buttons = [
        [InlineKeyboardButton(f"📢 Gabung Channel {channel}", url=channel_url)],
        [InlineKeyboardButton("🔄 Saya Sudah Bergabung", callback_data="check_sub")],
    ]
    return InlineKeyboardMarkup(buttons)


# ══════════════════════════════════════════════════════════════════════════════
# COMMAND HANDLERS
# ══════════════════════════════════════════════════════════════════════════════

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler /start"""
    user = update.effective_user
    if user is None:
        return

    try:
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    except Exception:
        pass

    # Simpan/perbarui user di database
    db.upsert_user(
        telegram_id=user.id,
        username=user.username,
        full_name=user.full_name,
    )

    # Cek keanggotaan channel wajib (Force Subscribe)
    if not await _is_user_subscribed(context.bot, user.id):
        channel_name = getattr(config, "FORCE_SUB_CHANNEL", "@nelstores")
        sub_text = (
            f"👋 Halo, <b>{user.first_name}</b>!\n\n"
            f"⚠️ <b>Wajib Bergabung ke Channel</b>\n"
            f"Sebelum dapat menggunakan bot dan melihat katalog produk, silakan bergabung ke channel resmi kami terlebih dahulu:\n\n"
            f"👉 <b>{channel_name}</b>\n\n"
            f"Setelah bergabung, klik tombol <b>'🔄 Saya Sudah Bergabung'</b> di bawah untuk membuka menu utama."
        )
        await _send_with_effect(
            update.message,
            text=sub_text,
            reply_markup=_build_force_sub_keyboard(),
            effect_id=EFFECT_FIRE,
            photo_path=MENU_IMAGE_PATH,
        )
        return

    keyboard = _build_main_menu_keyboard(user.id)

    text = (
        f"👋 Halo, <b>{user.first_name}</b>!\n\n"
        f"Selamat datang di <b>Sonelz Store</b>.\n"
        f"Silakan pilih produk yang Anda butuhkan melalui tombol di bawah:"
    )

    # Kirim pesan /start dengan gambar menu.png + Efek Partikel Api
    await _send_with_effect(
        update.message,
        text=text,
        reply_markup=keyboard,
        effect_id=EFFECT_FIRE,
        photo_path=MENU_IMAGE_PATH,
    )


async def cmd_products(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler /products - tampilkan daftar produk"""
    user = update.effective_user
    if user and not await _is_user_subscribed(context.bot, user.id):
        channel_name = getattr(config, "FORCE_SUB_CHANNEL", "@nelstores")
        text = (
            f"⚠️ <b>Wajib Bergabung ke Channel</b>\n"
            f"Silakan bergabung ke channel <b>{channel_name}</b> terlebih dahulu untuk melihat katalog produk kami."
        )
        await _send_with_effect(
            update.message,
            text=text,
            reply_markup=_build_force_sub_keyboard(),
            effect_id=EFFECT_FIRE,
            photo_path=MENU_IMAGE_PATH,
        )
        return
    await _show_product_list(update, context, edit=False)


async def cmd_orders(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler /orders - tampilkan riwayat pesanan"""
    user = update.effective_user
    if user is None:
        return
    if not await _is_user_subscribed(context.bot, user.id):
        channel_name = getattr(config, "FORCE_SUB_CHANNEL", "@nelstores")
        text = (
            f"⚠️ <b>Wajib Bergabung ke Channel</b>\n"
            f"Silakan bergabung ke channel <b>{channel_name}</b> terlebih dahulu."
        )
        await _send_with_effect(
            update.message,
            text=text,
            reply_markup=_build_force_sub_keyboard(),
            effect_id=EFFECT_FIRE,
            photo_path=MENU_IMAGE_PATH,
        )
        return
    await _show_orders(update, context, telegram_id=user.id, edit=False)


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler /status <order_ref> - cek status pesanan tertentu"""
    user = update.effective_user
    if user and not await _is_user_subscribed(context.bot, user.id):
        channel_name = getattr(config, "FORCE_SUB_CHANNEL", "@nelstores")
        text = (
            f"⚠️ <b>Wajib Bergabung ke Channel</b>\n"
            f"Silakan bergabung ke channel <b>{channel_name}</b> terlebih dahulu."
        )
        await _send_with_effect(
            update.message,
            text=text,
            reply_markup=_build_force_sub_keyboard(),
            effect_id=EFFECT_FIRE,
            photo_path=MENU_IMAGE_PATH,
        )
        return

    if not context.args:
        await update.message.reply_text(
            "❓ Gunakan format: <code>/status ORD-20260825-XXXX</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    order_ref = context.args[0].upper()
    await _show_order_detail(update, context, order_ref=order_ref, edit=False)


async def cmd_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler /admin - Menu khusus Owner / Admin untuk kelola stok"""
    user = update.effective_user
    if user is None or not _is_admin(user.id):
        await update.message.reply_text("⛔ Anda bukan owner/admin bot ini.")
        return
    await _show_admin_stock_list(update, context, edit=False)


async def cmd_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler /broadcast <pesan> - Kirim pesan broadcast ke semua pengguna (Owner only)"""
    user = update.effective_user
    if user is None or not _is_admin(user.id):
        await update.message.reply_text("⛔ Anda bukan owner/admin bot ini.")
        return

    if context.args:
        text = " ".join(context.args)
        context.user_data["broadcast_text"] = text
        context.user_data["admin_state"] = "BROADCAST_CONFIRM"
        db.set_admin_state(user.id, "BROADCAST_CONFIRM", {"broadcast_text": text})

        user_count = db.get_user_count()
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🚀 Ya, Kirim Broadcast", callback_data="admin_bcast:send")],
            [InlineKeyboardButton("❌ Batal", callback_data="admin_cancel:stock:0")],
        ])
        await update.message.reply_text(
            f"📢 <b>Pratinjau Pesan Broadcast</b>\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"{text}\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"👥 Target Penerima: <b>{user_count} Pengguna</b>\n\n"
            f"Apakah Anda yakin ingin mengirim pesan broadcast ini sekarang?",
            reply_markup=keyboard,
            parse_mode=ParseMode.HTML,
        )
    else:
        await _handle_admin_broadcast_start(update, context)


# ══════════════════════════════════════════════════════════════════════════════
# CALLBACK QUERY HANDLERS
# ══════════════════════════════════════════════════════════════════════════════

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Router untuk semua callback query dari InlineKeyboard."""
    query = update.callback_query
    await query.answer()

    data: str = query.data or ""
    parts = data.split(":")
    action = parts[0]

    # Khusus verifikasi keanggotaan channel
    if action == "check_sub":
        await _handle_check_sub(update, context)
        return

    # Proteksi: Pembeli TIDAK boleh klik tombol apapun di bot jika belum join channel
    user = update.effective_user
    if user and not await _is_user_subscribed(context.bot, user.id):
        channel_name = getattr(config, "FORCE_SUB_CHANNEL", "@nelstores")
        await query.answer(
            f"⚠️ Akses ditolak!\n\nAnda belum bergabung ke channel {channel_name}.\nSilakan bergabung ke channel terlebih dahulu untuk mengakses menu!",
            show_alert=True,
        )
        return

    match action:
        case "menu":
            force_new = ("new" in parts)
            await _handle_menu(update, context, parts[1] if len(parts) > 1 else "", force_new=force_new)
        case "product":
            await _handle_product(update, context, parts[1] if len(parts) > 1 else "")
        case "buy":
            await _handle_buy(update, context, parts[1] if len(parts) > 1 else "")
        case "buy_qty":
            if len(parts) >= 3 and parts[1].isdigit() and parts[2].isdigit():
                await _show_order_confirmation(update, context, product_id=int(parts[1]), qty=int(parts[2]))
        case "buy_custom":
            if len(parts) >= 2 and parts[1].isdigit():
                await _handle_buy_custom_start(update, context, product_id=int(parts[1]))
        case "buy_confirm":
            if len(parts) >= 3 and parts[1].isdigit() and parts[2].isdigit():
                await _process_purchase(update, context, product_id=int(parts[1]), qty=int(parts[2]))
            elif len(parts) == 2 and parts[1].isdigit():
                await _process_purchase(update, context, product_id=int(parts[1]), qty=1)
        case "order":
            await _handle_order_detail_cb(update, context, parts[1] if len(parts) > 1 else "")
        case "cancel_order":
            ref = parts[1] if len(parts) > 1 else ""
            await _handle_cancel_order(update, context, ref)
        case "back":
            await _handle_back(update, context, parts[1] if len(parts) > 1 else "")
        case "admin":
            context.user_data.pop("admin_state", None)
            context.user_data.pop("new_product", None)
            if update.effective_user:
                db.clear_admin_state(update.effective_user.id)
            await _show_admin_stock_list(update, context, edit=True)
        case "admin_prod":
            context.user_data.pop("admin_state", None)
            context.user_data.pop("new_product", None)
            if update.effective_user:
                db.clear_admin_state(update.effective_user.id)
            if len(parts) > 1 and parts[1].isdigit():
                await _show_admin_product_detail(update, context, int(parts[1]))
        case "admin_stock":
            if len(parts) >= 4:
                # format: admin_stock:<action>:<val>:<product_id>
                await _handle_admin_stock_action(
                    update, context, action=parts[1], val_str=parts[2], prod_id_str=parts[3]
                )
        case "admin_add":
            sub_action = parts[1] if len(parts) > 1 else ""
            if sub_action == "start":
                await _handle_admin_add_start(update, context)
            elif sub_action == "skip_desc":
                await _handle_admin_add_skip_desc(update, context)
            elif sub_action == "unlim_stock":
                await _handle_admin_add_unlim_stock(update, context)
        case "admin_bcast":
            sub_action = parts[1] if len(parts) > 1 else ""
            if sub_action == "start":
                await _handle_admin_broadcast_start(update, context)
            elif sub_action == "send":
                await _handle_admin_broadcast_send(update, context)
        case "admin_edit":
            if len(parts) >= 3 and parts[2].isdigit():
                await _handle_admin_edit_start(update, context, field=parts[1], product_id=int(parts[2]))
        case "admin_stk":
            context.user_data.pop("admin_state", None)
            context.user_data.pop("new_product", None)
            if update.effective_user:
                db.clear_admin_state(update.effective_user.id)
            sub_action = parts[1] if len(parts) > 1 else ""
            target_id = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
            if sub_action == "add":
                await _handle_admin_stock_item_add_start(update, context, product_id=target_id)
            elif sub_action == "list":
                await _show_admin_stock_items_list(update, context, product_id=target_id)
            elif sub_action == "view":
                await _show_admin_stock_item_detail(update, context, stock_id=target_id)
            elif sub_action == "edit":
                await _handle_admin_stock_item_edit_start(update, context, stock_id=target_id)
            elif sub_action == "del":
                await _handle_admin_stock_item_delete(update, context, stock_id=target_id)
        case "admin_cancel":
            context.user_data.pop("admin_state", None)
            context.user_data.pop("new_product", None)
            if update.effective_user:
                db.clear_admin_state(update.effective_user.id)
            await query.answer("↩️ Dibatalkan")
            sub_target = parts[1] if len(parts) > 1 else ""
            target_id = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
            if sub_target == "stk_view":
                await _show_admin_stock_item_detail(update, context, stock_id=target_id)
            elif sub_target == "stk_list":
                await _show_admin_stock_items_list(update, context, product_id=target_id)
            elif sub_target == "prod":
                await _show_admin_product_detail(update, context, product_id=target_id)
            else:
                await _show_admin_stock_list(update, context, edit=True)
        case "admin_del":
            context.user_data.pop("admin_state", None)
            if update.effective_user:
                db.clear_admin_state(update.effective_user.id)
            if len(parts) >= 3 and parts[2].isdigit():
                sub_action = parts[1]
                pid = int(parts[2])
                if sub_action == "ask":
                    await _handle_admin_delete_ask(update, context, pid)
                elif sub_action == "do":
                    await _handle_admin_delete_do(update, context, pid)
        case _:
            await _safe_edit_or_send_text(update, context, text="❓ Aksi tidak dikenali.")


async def _handle_check_sub(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler tombol verifikasi keanggotaan channel (Force Sub)."""
    query = update.callback_query
    user = update.effective_user
    if not query or not user:
        return

    is_subbed = await _is_user_subscribed(context.bot, user.id)
    if is_subbed:
        await query.answer("✅ Verifikasi berhasil! Selamat datang.", show_alert=False)
        await _show_main_menu(update, context, force_new=False)
    else:
        channel_name = getattr(config, "FORCE_SUB_CHANNEL", "@nelstores")
        await query.answer(
            f"❌ Anda belum bergabung ke channel {channel_name}!\n\n"
            f"Silakan klik tombol '📢 Gabung Channel' terlebih dahulu, lalu klik tombol ini lagi.",
            show_alert=True,
        )


# ── Sub-handler menu ──────────────────────────────────────────────────────────

async def _handle_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, sub: str, force_new: bool = False) -> None:
    match sub:
        case "products":
            await _show_product_list(update, context, edit=(not force_new), force_new=force_new)
        case "orders":
            user = update.effective_user
            await _show_orders(update, context, telegram_id=user.id if user else 0, edit=(not force_new), force_new=force_new)
        case "help":
            await _show_help(update, context)
        case "main":
            await _show_main_menu(update, context, force_new=force_new)


async def _handle_product(update: Update, context: ContextTypes.DEFAULT_TYPE, product_id_str: str) -> None:
    try:
        product_id = int(product_id_str)
    except ValueError:
        return
    await _show_product_detail(update, context, product_id=product_id)


async def _handle_buy(update: Update, context: ContextTypes.DEFAULT_TYPE, product_id_str: str) -> None:
    try:
        product_id = int(product_id_str)
    except ValueError:
        return

    product = db.get_product(product_id)
    if product is None:
        await _safe_edit_or_send_text(update, context, text="❌ Produk tidak ditemukan.")
        return

    if product["stock"] == 0:
        await _safe_edit_or_send_text(update, context, text="😔 Maaf, stok produk ini habis.")
        return

    # Jika stok hanya 1 unit, langsung proses pembelian
    if product["stock"] == 1:
        await _process_purchase(update, context, product_id=product_id, qty=1)
    else:
        # Jika stok > 1 atau unlimited (-1), tampilkan pemilih jumlah (Quantity Selector)
        await _show_quantity_selector(update, context, product_id=product_id)


async def _show_quantity_selector(
    update: Update, context: ContextTypes.DEFAULT_TYPE, product_id: int
) -> None:
    """Tampilan pemilihan jumlah unit (bulk order) saat stok > 1 atau unlimited."""
    product = db.get_product(product_id)
    if not product:
        await _safe_edit_or_send_text(update, context, text="❌ Produk tidak ditemukan.")
        return

    stock = product["stock"]
    if stock == -1:
        stock_badge = "♾️ Unlimited"
        options = [1, 2, 3, 5, 10]
    else:
        stock_badge = f"{stock} unit ready"
        if stock <= 5:
            options = list(range(1, stock + 1))
        else:
            options = [1, 2, 3, 5]
            if stock not in options:
                options.append(stock)

    text = (
        f"🔢 <b>Pilih Jumlah Pembelian</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"📦 <b>Produk:</b> {product['name']}\n"
        f"💰 <b>Harga:</b> {_fmt_rupiah(product['price'])} / unit\n"
        f"📊 <b>Stok:</b> {stock_badge}\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"Silakan pilih jumlah unit yang ingin dibeli:"
    )

    buttons = []
    row = []
    for q in options:
        label = f"{q} unit" if q != stock or stock <= 5 else f"Max ({q})"
        row.append(InlineKeyboardButton(label, callback_data=f"buy_qty:{product_id}:{q}"))
        if len(row) == 3:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    # Tombol ketik jumlah manual jika stok banyak atau unlimited
    if stock == -1 or stock > 3:
        buttons.append([InlineKeyboardButton("✏️ Ketik Jumlah Manual", callback_data=f"buy_custom:{product_id}")])

    buttons.append([
        InlineKeyboardButton("⬅️ Kembali", callback_data=f"product:{product_id}"),
        InlineKeyboardButton("🏠 Menu Utama", callback_data="menu:main"),
    ])

    await _safe_edit_or_send_text(update, context, text=text, reply_markup=InlineKeyboardMarkup(buttons))


async def _show_order_confirmation(
    update: Update, context: ContextTypes.DEFAULT_TYPE, product_id: int, qty: int
) -> None:
    """Tampilan konfirmasi total harga dan jumlah sebelum membuat invoice QRIS."""
    product = db.get_product(product_id)
    if not product:
        await _safe_edit_or_send_text(update, context, text="❌ Produk tidak ditemukan.")
        return

    total_price = product["price"] * qty

    text = (
        f"🧾 <b>Konfirmasi Rincian Pesanan</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"📦 <b>Produk:</b> {product['name']}\n"
        f"🔢 <b>Jumlah:</b> <b>{qty} unit</b>\n"
        f"💰 <b>Harga Satuan:</b> {_fmt_rupiah(product['price'])}\n"
        f"💵 <b>Total Pembayaran:</b> <b>{_fmt_rupiah(total_price)}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"<i>Klik tombol di bawah untuk melanjutkan ke pembayaran QRIS.</i>"
    )

    buttons = [
        [InlineKeyboardButton(f"💳 Lanjut Pembayaran – {_fmt_rupiah(total_price)}", callback_data=f"buy_confirm:{product_id}:{qty}")],
        [
            InlineKeyboardButton("🔢 Ganti Jumlah", callback_data=f"buy:{product_id}"),
            InlineKeyboardButton("❌ Batal", callback_data="menu:products"),
        ],
    ]

    await _safe_edit_or_send_text(update, context, text=text, reply_markup=InlineKeyboardMarkup(buttons))


async def _handle_buy_custom_start(
    update: Update, context: ContextTypes.DEFAULT_TYPE, product_id: int
) -> None:
    """Minta pembeli mengetikkan jumlah unit yang diinginkan."""
    product = db.get_product(product_id)
    if not product:
        await _safe_edit_or_send_text(update, context, text="❌ Produk tidak ditemukan.")
        return

    context.user_data["user_state"] = f"BUY_QTY_{product_id}"

    stock_badge = "♾️ Unlimited" if product["stock"] == -1 else f"{product['stock']} unit"
    text = (
        f"🔢 <b>Masukkan Jumlah Pembelian</b>\n\n"
        f"📦 Produk: <b>{product['name']}</b>\n"
        f"📊 Stok Tersedia: <b>{stock_badge}</b>\n\n"
        f"Silakan ketik dan kirimkan angka jumlah yang ingin dibeli (Contoh: <code>2</code>):"
    )

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ Batal", callback_data=f"buy:{product_id}")]
    ])

    await _safe_edit_or_send_text(update, context, text=text, reply_markup=keyboard)


async def _handle_order_detail_cb(update: Update, context: ContextTypes.DEFAULT_TYPE, ref: str) -> None:
    await _show_order_detail(update, context, order_ref=ref, edit=True)


async def _handle_cancel_order(
    update: Update, context: ContextTypes.DEFAULT_TYPE, order_ref: str
) -> None:
    """Batalkan order PENDING."""
    query = update.callback_query
    user = update.effective_user
    if not query or not user:
        return

    order = db.get_order_by_ref(order_ref)
    if not order:
        await query.answer("❌ Pesanan tidak ditemukan.", show_alert=True)
        return

    # Cek apakah order sudah dibayar
    if order["status"] in ("PAID", "COMPLETED"):
        await query.answer("⚠️ Pesanan sudah dibayar, tidak dapat dibatalkan.", show_alert=True)
        return

    if order["status"] == "CANCELLED":
        await query.answer("Pesanan ini sudah dibatalkan.")
        return

    # Update status order menjadi CANCELLED & lepaskan stok yang di-reservasi
    db.update_order_status(order_ref, "CANCELLED")
    db.release_order_stock(order_ref)

    text = (
        f"❌ <b>Pesanan Dibatalkan</b>\n\n"
        f"Order ID <code>{order_ref}</code> berhasil dibatalkan.\n"
        f"Tagihan pembayaran untuk pesanan ini sudah ditutup dan stok telah dikembalikan."
    )
    buttons = [
        [InlineKeyboardButton("🛍️ Katalog Produk", callback_data="menu:products")],
        [InlineKeyboardButton("🏠 Menu Utama", callback_data="menu:main")],
    ]

    await query.answer("❌ Pesanan berhasil dibatalkan!")

    # Jika pesan sebelumnya adalah foto QRIS, hapus foto dan kirim pesan konfirmasi pembatalan
    if query.message and query.message.photo:
        try:
            await query.message.delete()
        except Exception:
            pass
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=text,
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode=ParseMode.HTML,
        )
    else:
        await _safe_edit_or_send_text(
            update, context, text=text, reply_markup=InlineKeyboardMarkup(buttons)
        )


async def _handle_back(update: Update, context: ContextTypes.DEFAULT_TYPE, dest: str) -> None:
    match dest:
        case "products":
            await _show_product_list(update, context, edit=True)
        case "main":
            await _show_main_menu(update, context)


# ══════════════════════════════════════════════════════════════════════════════
# UI BUILDERS
# ══════════════════════════════════════════════════════════════════════════════

async def _show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, force_new: bool = False) -> None:
    user = update.effective_user
    keyboard = _build_main_menu_keyboard(user.id if user else 0)
    text = (
        f"👋 Halo, <b>{user.first_name if user else 'Kak'}</b>!\n\n"
        f"Selamat datang di <b>Sonelz Store</b>.\n"
        f"Silakan pilih produk yang Anda butuhkan melalui tombol di bawah:"
    )
    query = update.callback_query
    if query and query.message and not force_new:
        if query.message.photo:
            try:
                await query.edit_message_caption(caption=text, reply_markup=keyboard, parse_mode=ParseMode.HTML)
                return
            except Exception:
                pass
        try:
            await query.edit_message_text(text=text, reply_markup=keyboard, parse_mode=ParseMode.HTML)
            return
        except Exception:
            pass

    # Jika force_new (misal dari pesan invoice setelah bayar):
    if os.path.exists(MENU_IMAGE_PATH):
        with open(MENU_IMAGE_PATH, "rb") as f:
            await context.bot.send_photo(
                chat_id=update.effective_chat.id,
                photo=f,
                caption=text,
                reply_markup=keyboard,
                parse_mode=ParseMode.HTML,
            )
    else:
        await _safe_edit_or_send_text(update, context, text=text, reply_markup=keyboard, force_new=force_new)


# ── Owner / Admin UI ──────────────────────────────────────────────────────────

async def _show_admin_stock_list(
    update: Update, context: ContextTypes.DEFAULT_TYPE, edit: bool = False
) -> None:
    user = update.effective_user
    if user is None or not _is_admin(user.id):
        return

    products = db.get_all_products()
    user_count = db.get_user_count()

    text = (
        "👑 <b>Panel Owner – Kelola Produk & Stok</b>\n\n"
        f"👥 Total Pengguna Bot: <b>{user_count} User</b>\n\n"
        "Pilih produk untuk mengedit nama/harga/stok atau gunakan menu di bawah:\n\n"
    )

    buttons = [
        [
            InlineKeyboardButton("➕ Tambah Produk", callback_data="admin_add:start"),
            InlineKeyboardButton("📢 Broadcast Pesan", callback_data="admin_bcast:start"),
        ]
    ]

    if products:
        for p in products:
            if p["stock"] == -1:
                stock_badge = "♾️ Unlimited"
            elif p["stock"] == 0:
                stock_badge = "❌ Habis"
            else:
                stock_badge = f"📦 {p['stock']} unit"

            text += (
                f"• <b>{p['name']}</b>\n"
                f"  💰 {_fmt_rupiah(p['price'])} | Stok: <b>{stock_badge}</b>\n\n"
            )
            buttons.append([
                InlineKeyboardButton(
                    f"⚙️ {p['name'][:24]} ({stock_badge})",
                    callback_data=f"admin_prod:{p['id']}",
                )
            ])
    else:
        text += "<i>Belum ada produk aktif. Klik tombol di bawah untuk menambahkan.</i>\n\n"

    buttons.append([InlineKeyboardButton("🏠 Menu Utama", callback_data="menu:main")])
    keyboard = InlineKeyboardMarkup(buttons)

    await _safe_edit_or_send_text(update, context, text=text, reply_markup=keyboard)


def _build_admin_product_detail_content(product, feedback_msg: str | None = None) -> tuple[str, InlineKeyboardMarkup]:
    """Helper untuk membuat teks dan keyboard panel detail produk admin."""
    pid = product["id"]
    avail_stocks = db.get_available_stock_items(pid)
    # BUG-17: Stok terjual sudah dihapus dari pool — hitung dari tabel orders
    with db.get_db() as conn:
        sold_count = conn.execute(
            "SELECT COUNT(*) AS cnt FROM orders WHERE product_id = ? AND status IN ('COMPLETED', 'PAID', 'PROCESSING')",
            (pid,),
        ).fetchone()["cnt"]

    if avail_stocks or sold_count:
        stock_badge = f"📦 {len(avail_stocks)} unit ready ({sold_count} terjual)"
    elif product["stock"] == -1:
        stock_badge = "♾️ Unlimited (-1)"
    elif product["stock"] == 0:
        stock_badge = "❌ HABIS (0)"
    else:
        stock_badge = f"{product['stock']} unit"

    text = ""
    if feedback_msg:
        text += f"{feedback_msg}\n\n"

    desc_text = product["description"] if product["description"] else "<i>(Belum ada deskripsi)</i>"

    text += (
        f"👑 <b>Kelola Produk & Stok (Owner)</b>\n\n"
        f"📦 <b>{product['name']}</b>\n"
        f"📝 Deskripsi : {desc_text}\n"
        f"💰 Harga : <b>{_fmt_rupiah(product['price'])}</b>\n"
        f"📊 Stok Ready : <b>{stock_badge}</b>\n\n"
    )

    if avail_stocks:
        text += f"📬 <b>Stok Akun Ready ({len(avail_stocks)} item):</b>\n"
        for idx, item in enumerate(avail_stocks[:4], 1):
            preview = item["content"].replace("\n", " ")[:35]
            text += f" {idx}. <code>{preview}...</code>\n"
        if len(avail_stocks) > 4:
            text += f" <i>...dan {len(avail_stocks) - 4} akun lainnya</i>\n"
        text += "\n"
    else:
        deliv_text = product["delivery_content"] if ("delivery_content" in product.keys() and product["delivery_content"]) else "<i>(Belum ada stok akun di pool)</i>"
        text += (
            f"📬 <b>Pesan Default (Jika Tanpa Pool Stok):</b>\n"
            f"<code>{deliv_text}</code>\n\n"
        )

    text += "👇 <i>Pilih aksi yang ingin dilakukan:</i>"

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("➕ Tambah Stok Akun", callback_data=f"admin_stk:add:{pid}"),
            InlineKeyboardButton(f"📋 Kelola Tiap Stok ({len(avail_stocks)})", callback_data=f"admin_stk:list:{pid}"),
        ],
        [
            InlineKeyboardButton("✏️ Edit Nama", callback_data=f"admin_edit:name:{pid}"),
            InlineKeyboardButton("📝 Edit Deskripsi", callback_data=f"admin_edit:desc:{pid}"),
        ],
        [
            InlineKeyboardButton("💰 Edit Harga", callback_data=f"admin_edit:price:{pid}"),
            InlineKeyboardButton("📬 Edit Pesan Default", callback_data=f"admin_edit:delivery:{pid}"),
        ],
        [
            InlineKeyboardButton("❌ Hapus Produk Ini", callback_data=f"admin_del:ask:{pid}"),
        ],
        [
            InlineKeyboardButton("⬅️ Kembali ke Daftar", callback_data="admin:stock"),
            InlineKeyboardButton("🏠 Menu Utama", callback_data="menu:main"),
        ],
    ])
    return text, keyboard


# ── Handler Per-Stock Item (Akun Pool) ────────────────────────────────────────

async def _handle_admin_stock_item_add_start(
    update: Update, context: ContextTypes.DEFAULT_TYPE, product_id: int
) -> None:
    user = update.effective_user
    if user is None or not _is_admin(user.id):
        return

    product = db.get_product(product_id)
    if not product:
        await _safe_edit_or_send_text(update, context, text="❌ Produk tidak ditemukan.")
        return

    context.user_data["admin_state"] = f"ADD_STOCK_ITEM_{product_id}"
    db.set_admin_state(user.id, f"ADD_STOCK_ITEM_{product_id}")

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ Batal", callback_data=f"admin_cancel:stk_list:{product_id}")]
    ])

    await _safe_edit_or_send_text(
        update, context,
        text=(
            f"➕ <b>Tambah Stok Akun Baru</b>\n\n"
            f"Produk: <b>{product['name']}</b>\n\n"
            f"Silakan kirimkan <b>Info Akun / Lisensi</b> yang ingin dimasukkan ke stok:\n\n"
            f"💡 <i>Tips:</i>\n"
            f"• Bisa kirim 1 akun (format bebas: Email, Password, 2FA, dll).\n"
            f"• Atau kirim beberapa akun sekaligus dengan pemisah baris <code>---</code>."
        ),
        reply_markup=keyboard,
    )


async def _show_admin_stock_items_list(
    update: Update, context: ContextTypes.DEFAULT_TYPE, product_id: int
) -> None:
    user = update.effective_user
    if user is None or not _is_admin(user.id):
        return

    product = db.get_product(product_id)
    if not product:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📦 Panel Kelola Stok", callback_data="admin:stock")],
            [InlineKeyboardButton("🏠 Menu Utama", callback_data="menu:main")],
        ])
        await _safe_edit_or_send_text(update, context, text="❌ Produk tidak ditemukan.", reply_markup=keyboard)
        return

    items = db.get_available_stock_items(product_id)

    text = (
        f"📋 <b>Daftar Stok Akun Ready: {product['name']}</b>\n\n"
        f"Stok Tersedia: <b>{len(items)} unit</b>\n\n"
    )

    buttons = [
        [InlineKeyboardButton("➕ Tambah Stok Akun Baru", callback_data=f"admin_stk:add:{product_id}")]
    ]

    if items:
        for idx, item in enumerate(items, 1):
            preview = item["content"].replace("\n", " ")[:24]
            buttons.append([
                InlineKeyboardButton(
                    f"#{idx} [Ready] {preview}...",
                    callback_data=f"admin_stk:view:{item['id']}",
                )
            ])
    else:
        text += "<i>Saat ini tidak ada stok akun yang tersedia di pool.</i>\n\n"

    buttons.append([
        InlineKeyboardButton("⚙️ Detail Produk", callback_data=f"admin_prod:{product_id}"),
        InlineKeyboardButton("📦 Panel Kelola Stok", callback_data="admin:stock"),
    ])
    buttons.append([
        InlineKeyboardButton("🏠 Menu Utama", callback_data="menu:main"),
    ])

    await _safe_edit_or_send_text(update, context, text=text, reply_markup=InlineKeyboardMarkup(buttons))


async def _show_admin_stock_item_detail(
    update: Update, context: ContextTypes.DEFAULT_TYPE, stock_id: int
) -> None:
    user = update.effective_user
    if user is None or not _is_admin(user.id):
        return

    item = db.get_stock_item(stock_id)
    if not item:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📦 Panel Kelola Stok", callback_data="admin:stock")],
            [InlineKeyboardButton("🏠 Menu Utama", callback_data="menu:main")],
        ])
        await _safe_edit_or_send_text(update, context, text="❌ Stok tidak ditemukan.", reply_markup=keyboard)
        return

    status_str = "✅ Ready (Belum Terjual)" if item["is_used"] == 0 else f"🔴 Terjual (Order #{item['order_id']})"

    text = (
        f"🔍 <b>Detail Stok Akun #{item['id']}</b>\n\n"
        f"📊 Status: <b>{status_str}</b>\n"
        f"📅 Dibuat: {item['created_at'][:19]}\n\n"
        f"📬 <b>Isi Info Akun:</b>\n"
        f"<code>{item['content']}</code>"
    )

    buttons = []
    if item["is_used"] == 0:
        buttons.append([
            InlineKeyboardButton("✏️ Edit Info Akun Ini", callback_data=f"admin_stk:edit:{item['id']}"),
            InlineKeyboardButton("🗑️ Hapus Stok Ini", callback_data=f"admin_stk:del:{item['id']}"),
        ])
    buttons.append([
        InlineKeyboardButton("📋 Daftar Stok Akun", callback_data=f"admin_stk:list:{item['product_id']}"),
        InlineKeyboardButton("⚙️ Detail Produk", callback_data=f"admin_prod:{item['product_id']}"),
    ])
    buttons.append([
        InlineKeyboardButton("📦 Panel Kelola Stok", callback_data="admin:stock"),
        InlineKeyboardButton("🏠 Menu Utama", callback_data="menu:main"),
    ])

    await _safe_edit_or_send_text(update, context, text=text, reply_markup=InlineKeyboardMarkup(buttons))


async def _handle_admin_stock_item_edit_start(
    update: Update, context: ContextTypes.DEFAULT_TYPE, stock_id: int
) -> None:
    user = update.effective_user
    if user is None or not _is_admin(user.id):
        return

    item = db.get_stock_item(stock_id)
    if not item:
        await _safe_edit_or_send_text(update, context, text="❌ Stok tidak ditemukan.")
        return

    context.user_data["admin_state"] = f"EDIT_STOCK_ITEM_{stock_id}"
    db.set_admin_state(user.id, f"EDIT_STOCK_ITEM_{stock_id}")

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ Batal", callback_data=f"admin_cancel:stk_view:{stock_id}")]
    ])

    await _safe_edit_or_send_text(
        update, context,
        text=(
            f"✏️ <b>Edit Info Akun Stok #{item['id']}</b>\n\n"
            f"Isi saat ini:\n"
            f"<code>{item['content']}</code>\n\n"
            f"Silakan ketik dan kirimkan <b>Info Akun Baru</b> yang sudah diperbaiki:"
        ),
        reply_markup=keyboard,
    )


async def _handle_admin_stock_item_delete(
    update: Update, context: ContextTypes.DEFAULT_TYPE, stock_id: int
) -> None:
    user = update.effective_user
    if user is None or not _is_admin(user.id):
        return

    item = db.get_stock_item(stock_id)
    if not item:
        await update.callback_query.answer("❌ Stok tidak ditemukan.", show_alert=True)
        return

    pid = item["product_id"]
    db.delete_stock_item(stock_id)
    await update.callback_query.answer("🗑️ Stok akun berhasil dihapus!")
    await _show_admin_stock_items_list(update, context, product_id=pid)


async def _show_admin_product_detail(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    product_id: int,
    feedback_msg: str | None = None,
) -> None:
    user = update.effective_user
    if user is None or not _is_admin(user.id):
        return

    product = db.get_product(product_id)
    if product is None:
        await _safe_edit_or_send_text(update, context, text="❌ Produk tidak ditemukan.")
        return

    text, keyboard = _build_admin_product_detail_content(product, feedback_msg)
    await _safe_edit_or_send_text(update, context, text=text, reply_markup=keyboard)


async def _show_admin_product_detail_msg(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    product_id: int,
    feedback_msg: str | None = None,
) -> None:
    product = db.get_product(product_id)
    if product is None:
        await update.message.reply_text("❌ Produk tidak ditemukan.")
        return

    text, keyboard = _build_admin_product_detail_content(product, feedback_msg)
    await update.message.reply_text(
        text, reply_markup=keyboard, parse_mode=ParseMode.HTML
    )


# ── Handler Broadcast Pesan (Owner) ───────────────────────────────────────────

async def _handle_admin_broadcast_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if user is None or not _is_admin(user.id):
        return

    context.user_data["admin_state"] = "BROADCAST_INPUT"
    db.set_admin_state(user.id, "BROADCAST_INPUT", {})

    user_count = db.get_user_count()
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ Batal", callback_data="admin_cancel:stock:0")]
    ])

    text = (
        f"📢 <b>Kirim Pesan Broadcast (Owner)</b>\n\n"
        f"👥 Total Sasaran: <b>{user_count} Pengguna Terdaftar</b>\n\n"
        f"Silakan ketik dan kirimkan <b>Teks Pesan Broadcast</b> yang ingin dikirimkan ke semua pengguna:\n\n"
        f"💡 <i>Mendukung format HTML seperti <b>tebal</b>, <i>miring</i>, <a href='https://example.com'>link</a>, dan <code>kode</code>.</i>"
    )

    await _safe_edit_or_send_text(
        update, context, text=text, reply_markup=keyboard
    )


async def _handle_admin_broadcast_send(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if user is None or not _is_admin(user.id):
        return

    bcast_text = context.user_data.get("broadcast_text", "")
    if not bcast_text:
        state, state_data = db.get_admin_state(user.id)
        if state_data:
            bcast_text = state_data.get("broadcast_text", "")

    if not bcast_text:
        await _safe_edit_or_send_text(update, context, text="❌ Pesan broadcast tidak ditemukan atau sudah kadaluarsa.")
        return

    context.user_data.pop("admin_state", None)
    context.user_data.pop("broadcast_text", None)
    db.clear_admin_state(user.id)

    all_users = db.get_all_users()
    total_users = len(all_users)

    await _safe_edit_or_send_text(
        update, context,
        text=(
            f"⏳ <b>Sedang Mengirim Broadcast...</b>\n\n"
            f"👥 Target: <b>{total_users} Pengguna</b>\n"
            f"<i>Mohon tunggu hingga proses selesai.</i>"
        ),
    )

    success_cnt = 0
    fail_cnt = 0

    for u in all_users:
        tg_id = u["telegram_id"]
        try:
            await context.bot.send_message(
                chat_id=tg_id,
                text=bcast_text,
                parse_mode=ParseMode.HTML,
            )
            success_cnt += 1
            await asyncio.sleep(0.04)  # Mencegah rate-limit Telegram (maks 30 msg/detik)
        except Exception:
            fail_cnt += 1

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("⚙️ Panel Owner", callback_data="admin:stock")],
        [InlineKeyboardButton("🏠 Menu Utama", callback_data="menu:main")],
    ])

    await context.bot.send_message(
        chat_id=user.id,
        text=(
            f"🎉 <b>Laporan Pengiriman Broadcast Selesai!</b>\n\n"
            f"✅ Berhasil Terkirim : <b>{success_cnt}</b>\n"
            f"❌ Gagal / Diblokir : <b>{fail_cnt}</b>\n"
            f"📊 Total Sasaran : <b>{total_users} Pengguna</b>"
        ),
        reply_markup=keyboard,
        parse_mode=ParseMode.HTML,
    )


# ── Handler Tambah Produk ─────────────────────────────────────────────────────

async def _handle_admin_add_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if user is None or not _is_admin(user.id):
        return

    context.user_data["admin_state"] = "ADD_NAME"
    context.user_data["new_product"] = {}
    db.set_admin_state(user.id, "ADD_NAME", {})

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ Batal", callback_data="admin_cancel:stock:0")]
    ])

    await _safe_edit_or_send_text(
        update, context,
        text=(
            "➕ <b>Tambah Produk Baru (Langkah 1/4)</b>\n\n"
            "Silakan ketik dan kirimkan <b>Nama Produk</b> baru:"
        ),
        reply_markup=keyboard,
    )


async def _handle_admin_add_skip_desc(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if context.user_data.get("admin_state") != "ADD_DESC":
        return

    context.user_data["new_product"]["desc"] = ""
    context.user_data["admin_state"] = "ADD_PRICE"
    if user:
        db.set_admin_state(user.id, "ADD_PRICE", context.user_data["new_product"])

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ Batal", callback_data="admin_cancel:stock:0")]
    ])

    await _safe_edit_or_send_text(
        update, context,
        text=(
            "➕ <b>Tambah Produk Baru (Langkah 3/4)</b>\n\n"
            "Silakan ketik dan kirimkan <b>Harga Produk</b> dalam rupiah (angka saja, contoh: <code>45000</code>):"
        ),
        reply_markup=keyboard,
    )


async def _handle_admin_add_unlim_stock(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if context.user_data.get("admin_state") != "ADD_STOCK":
        return

    context.user_data["admin_state"] = "ADD_UNLIM_DELIVERY"
    if user:
        db.set_admin_state(user.id, "ADD_UNLIM_DELIVERY", context.user_data["new_product"])

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ Batal", callback_data="admin_cancel:stock:0")]
    ])

    await _safe_edit_or_send_text(
        update, context,
        text=(
            "♾️ <b>Pesan Pengiriman Produk Unlimited</b>\n\n"
            "Silakan ketik dan kirimkan <b>Pesan / Link / Lisensi Tetap</b> yang akan otomatis dikirimkan ke pembeli setiap kali ada pembayaran berhasil (PAID):"
        ),
        reply_markup=keyboard,
    )


# ── Handler Edit Field Produk ─────────────────────────────────────────────────

async def _handle_admin_edit_start(
    update: Update, context: ContextTypes.DEFAULT_TYPE, field: str, product_id: int
) -> None:
    user = update.effective_user
    if user is None or not _is_admin(user.id):
        return

    product = db.get_product(product_id)
    if not product:
        await _safe_edit_or_send_text(update, context, text="❌ Produk tidak ditemukan.")
        return

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ Batal", callback_data=f"admin_cancel:prod:{product_id}")]
    ])

    match field:
        case "name":
            context.user_data["admin_state"] = f"EDIT_NAME_{product_id}"
            db.set_admin_state(user.id, f"EDIT_NAME_{product_id}")
            await _safe_edit_or_send_text(
                update, context,
                text=(
                    f"✏️ <b>Edit Nama Produk</b>\n\n"
                    f"Nama saat ini: <b>{product['name']}</b>\n\n"
                    f"Silakan ketik dan kirimkan <b>Nama Baru</b>:"
                ),
                reply_markup=keyboard,
            )
        case "desc":
            context.user_data["admin_state"] = f"EDIT_DESC_{product_id}"
            db.set_admin_state(user.id, f"EDIT_DESC_{product_id}")
            await _safe_edit_or_send_text(
                update, context,
                text=(
                    f"📝 <b>Edit Deskripsi Produk</b>\n\n"
                    f"Deskripsi saat ini:\n{product['description'] or '<i>(Kosong)</i>'}\n\n"
                    f"Silakan ketik dan kirimkan <b>Deskripsi Baru</b>:"
                ),
                reply_markup=keyboard,
            )
        case "price":
            context.user_data["admin_state"] = f"EDIT_PRICE_{product_id}"
            db.set_admin_state(user.id, f"EDIT_PRICE_{product_id}")
            await _safe_edit_or_send_text(
                update, context,
                text=(
                    f"💰 <b>Edit Harga Produk</b>\n\n"
                    f"Harga saat ini: <b>{_fmt_rupiah(product['price'])}</b>\n\n"
                    f"Silakan ketik dan kirimkan <b>Harga Baru</b> (angka, contoh: <code>50000</code>):"
                ),
                reply_markup=keyboard,
            )
        case "stock_num":
            context.user_data["admin_state"] = f"EDIT_STOCK_NUM_{product_id}"
            db.set_admin_state(user.id, f"EDIT_STOCK_NUM_{product_id}")
            stock_badge = "♾️ Unlimited" if product["stock"] == -1 else f"{product['stock']} unit"
            await _safe_edit_or_send_text(
                update, context,
                text=(
                    f"🔢 <b>Set Angka Stok Produk</b>\n\n"
                    f"Stok saat ini: <b>{stock_badge}</b>\n\n"
                    f"Silakan ketik dan kirimkan <b>Jumlah Stok Baru</b> (angka, contoh: <code>25</code>, atau ketik <code>-1</code> untuk Unlimited):"
                ),
                reply_markup=keyboard,
            )
        case "delivery":
            context.user_data["admin_state"] = f"EDIT_DELIVERY_{product_id}"
            db.set_admin_state(user.id, f"EDIT_DELIVERY_{product_id}")
            deliv_curr = product["delivery_content"] if ("delivery_content" in product.keys() and product["delivery_content"]) else "<i>(Belum diatur)</i>"
            await _safe_edit_or_send_text(
                update, context,
                text=(
                    f"📬 <b>Edit Pesan Setelah Bayar (Info Akun / Lisensi)</b>\n\n"
                    f"Produk: <b>{product['name']}</b>\n\n"
                    f"Pesan saat ini:\n{deliv_curr}\n\n"
                    f"Silakan ketik dan kirimkan <b>Pesan / Info Akun / Link</b> yang akan dikirim otomatis ke pembeli setelah pembayaran berhasil (PAID):"
                ),
                reply_markup=keyboard,
            )


# ── Handler Hapus Produk ──────────────────────────────────────────────────────

async def _handle_admin_delete_ask(
    update: Update, context: ContextTypes.DEFAULT_TYPE, product_id: int
) -> None:
    user = update.effective_user
    if user is None or not _is_admin(user.id):
        return

    product = db.get_product(product_id)
    if not product:
        await _safe_edit_or_send_text(update, context, text="❌ Produk tidak ditemukan.")
        return

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🗑️ Ya, Hapus Produk", callback_data=f"admin_del:do:{product_id}")],
        [InlineKeyboardButton("❌ Batal", callback_data=f"admin_cancel:prod:{product_id}")],
    ])

    await _safe_edit_or_send_text(
        update, context,
        text=(
            f"⚠️ <b>Konfirmasi Hapus Produk</b>\n\n"
            f"Apakah Anda yakin ingin menghapus produk:\n"
            f"📦 <b>{product['name']}</b>?\n\n"
            f"<i>Produk tidak akan ditampilkan lagi kepada pembeli.</i>"
        ),
        reply_markup=keyboard,
    )


async def _handle_admin_delete_do(
    update: Update, context: ContextTypes.DEFAULT_TYPE, product_id: int
) -> None:
    user = update.effective_user
    if user is None or not _is_admin(user.id):
        return

    product = db.get_product(product_id)
    prod_name = product["name"] if product else "Produk"

    db.delete_product(product_id)
    await update.callback_query.answer("🗑️ Produk berhasil dihapus!", show_alert=False)
    await _show_admin_stock_list(update, context, edit=True)


# ── Handler Tombol Cepat Stok ─────────────────────────────────────────────────

async def _handle_admin_stock_action(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    action: str,
    val_str: str,
    prod_id_str: str,
) -> None:
    user = update.effective_user
    if user is None or not _is_admin(user.id):
        await update.callback_query.answer("⛔ Akses ditolak", show_alert=True)
        return

    try:
        val = int(val_str)
        product_id = int(prod_id_str)
    except ValueError:
        return

    feedback = ""
    match action:
        case "add":
            new_val = db.adjust_product_stock(product_id, val)
            feedback = f"✅ Ditambahkan <b>+{val}</b>. Stok sekarang: <b>{new_val}</b>"
            await update.callback_query.answer(f"Stok ditambah +{val}!")
        case "sub":
            new_val = db.adjust_product_stock(product_id, -val)
            feedback = f"🔻 Dikurangi <b>-{val}</b>. Stok sekarang: <b>{new_val}</b>"
            await update.callback_query.answer(f"Stok dikurangi -{val}!")
        case "zero":
            db.update_product_stock(product_id, 0)
            feedback = "🗑️ Stok berhasil <b>dikosongkan (0)</b>."
            await update.callback_query.answer("Stok dikosongkan (0)!")
        case "unlim":
            db.update_product_stock(product_id, -1)
            feedback = "♾️ Stok diubah menjadi <b>Unlimited</b>."
            await update.callback_query.answer("Stok diubah ke Unlimited!")

    await _show_admin_product_detail(update, context, product_id, feedback_msg=feedback)


# ── Handler Input Teks Admin ──────────────────────────────────────────────────

async def handle_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler untuk input teks dari pengguna (pembeli atau owner)."""
    user = update.effective_user
    if user is None:
        return

    text = (update.message.text or "").strip()
    if not text:
        return

    # Proteksi channel untuk pembeli
    if not _is_admin(user.id) and not await _is_user_subscribed(context.bot, user.id):
        channel_name = getattr(config, "FORCE_SUB_CHANNEL", "@nelstores")
        sub_text = (
            f"⚠️ <b>Wajib Bergabung ke Channel</b>\n\n"
            f"Anda harus bergabung ke channel <b>{channel_name}</b> terlebih dahulu untuk menggunakan bot ini."
        )
        await _send_with_effect(
            update.message,
            text=sub_text,
            reply_markup=_build_force_sub_keyboard(),
            effect_id=EFFECT_FIRE,
            photo_path=MENU_IMAGE_PATH,
        )
        return

    # ── 0. Input Jumlah Pembelian oleh Pembeli (Buyer Custom QTY) ─────────────
    user_state = context.user_data.get("user_state", "")
    if user_state.startswith("BUY_QTY_"):
        pid = int(user_state.replace("BUY_QTY_", ""))
        product = db.get_product(pid)
        if not product:
            await update.message.reply_text("❌ Produk tidak ditemukan.")
            return

        digits = re.sub(r"[^0-9]", "", text)
        if not digits:
            await update.message.reply_text(
                "❌ Mohon kirimkan angka jumlah yang valid. Contoh: <code>2</code>",
                parse_mode=ParseMode.HTML,
            )
            return

        qty = int(digits)
        if qty <= 0:
            await update.message.reply_text("❌ Jumlah pembelian minimal adalah 1 unit.")
            return

        if product["stock"] != -1 and qty > product["stock"]:
            await update.message.reply_text(
                f"❌ Jumlah melebihi stok yang tersedia!\nStok ready saat ini: <b>{product['stock']} unit</b>.",
                parse_mode=ParseMode.HTML,
            )
            return

        context.user_data.pop("user_state", None)
        await _show_order_confirmation(update, context, product_id=pid, qty=qty)
        return

    # ── Input Khusus Owner / Admin ────────────────────────────────────────────
    if not _is_admin(user.id):
        return

    # Ambil state dari memory atau persistent database
    state: str = context.user_data.get("admin_state", "")
    data = context.user_data.get("new_product", {})
    if not state:
        state, db_data = db.get_admin_state(user.id)
        if db_data and not data:
            context.user_data["new_product"] = db_data
            data = db_data

    if not state:
        return

    # 1. Tambah Produk: Nama
    if state == "ADD_NAME":
        context.user_data["new_product"] = {"name": text}
        context.user_data["admin_state"] = "ADD_DESC"
        db.set_admin_state(user.id, "ADD_DESC", context.user_data["new_product"])
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("⏩ Lewati Deskripsi", callback_data="admin_add:skip_desc")],
            [InlineKeyboardButton("❌ Batal", callback_data="admin_cancel:stock:0")],
        ])
        await update.message.reply_text(
            f"📦 Nama: <b>{text}</b>\n\n"
            f"➕ <b>Tambah Produk (Langkah 2/4)</b>\n"
            f"Silakan kirimkan <b>Deskripsi Produk</b> (atau klik tombol Lewati):",
            reply_markup=keyboard,
            parse_mode=ParseMode.HTML,
        )
        return

    # 2. Tambah Produk: Deskripsi
    if state == "ADD_DESC":
        context.user_data["new_product"]["desc"] = text
        context.user_data["admin_state"] = "ADD_PRICE"
        db.set_admin_state(user.id, "ADD_PRICE", context.user_data["new_product"])
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ Batal", callback_data="admin_cancel:stock:0")],
        ])
        await update.message.reply_text(
            f"➕ <b>Tambah Produk (Langkah 3/4)</b>\n\n"
            f"Silakan kirimkan <b>Harga Produk</b> dalam rupiah (angka saja, contoh: <code>45000</code>):",
            reply_markup=keyboard,
            parse_mode=ParseMode.HTML,
        )
        return

    # 3. Tambah Produk: Harga
    if state == "ADD_PRICE":
        digits = re.sub(r"[^0-9]", "", text)
        if not digits:
            await update.message.reply_text(
                "❌ Mohon kirimkan angka harga yang valid. Contoh: <code>45000</code>",
                parse_mode=ParseMode.HTML,
            )
            return
        price = int(digits)
        context.user_data["new_product"]["price"] = price
        context.user_data["admin_state"] = "ADD_STOCK"
        db.set_admin_state(user.id, "ADD_STOCK", context.user_data["new_product"])
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("♾️ Set Pesan Tetap (Unlimited)", callback_data="admin_add:unlim_stock")],
            [InlineKeyboardButton("❌ Batal", callback_data="admin_cancel:stock:0")],
        ])
        await update.message.reply_text(
            f"💰 Harga: <b>{_fmt_rupiah(price)}</b>\n\n"
            f"➕ <b>Tambah Produk (Langkah 4/4 – Masukkan Stok Akun)</b>\n\n"
            f"Silakan kirimkan <b>Info Akun / Lisensi</b> untuk produk ini:\n\n"
            f"💡 <i>Tips:</i>\n"
            f"• Kirim 1 akun (format bebas: Email, Password, 2FA, dll).\n"
            f"• Atau kirim beberapa akun sekaligus dengan pemisah baris <code>---</code> (stok otomatis bertambah sesuai jumlah akun).\n"
            f"• Jika produk berupa link/pesan tetap tanpa stok akun unik, klik tombol <b>♾️ Set Pesan Tetap (Unlimited)</b>.",
            reply_markup=keyboard,
            parse_mode=ParseMode.HTML,
        )
        return

    # 4. Tambah Produk: Info Akun Stok Awal
    if state == "ADD_STOCK":
        new_prod = context.user_data.get("new_product", {})
        name = new_prod.get("name", "Produk Baru")
        desc = new_prod.get("desc", "")
        price = new_prod.get("price", 0)

        # Pisahkan jika ada beberapa akun dengan ---
        if "\n---\n" in text or "\n---\r\n" in text or "\n---" in text:
            raw_items = re.split(r"\n\s*---\s*\n|\n---", text)
        else:
            raw_items = [text]

        clean_items = [it.strip() for it in raw_items if it.strip()]
        if not clean_items:
            await update.message.reply_text(
                "❌ Info akun tidak boleh kosong. Silakan kirimkan info akun atau klik Batal.",
                parse_mode=ParseMode.HTML,
            )
            return

        prod_id = db.add_product(name=name, description=desc, price=price, stock=0)
        added_cnt = db.add_stock_items(prod_id, clean_items)

        context.user_data.pop("admin_state", None)
        context.user_data.pop("new_product", None)
        db.clear_admin_state(user.id)

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("⚙️ Kelola Produk Ini", callback_data=f"admin_prod:{prod_id}")],
            [InlineKeyboardButton("📋 Panel Kelola Produk", callback_data="admin:stock")],
            [InlineKeyboardButton("🏠 Menu Utama", callback_data="menu:main")],
        ])
        await update.message.reply_text(
            f"🎉 <b>Produk & Stok Berhasil Ditambahkan!</b>\n\n"
            f"📦 Nama: <b>{name}</b>\n"
            f"📝 Deskripsi: {desc or '–'}\n"
            f"💰 Harga: <b>{_fmt_rupiah(price)}</b>\n"
            f"📊 Stok Ready: <b>{added_cnt} unit akun</b>\n\n"
            f"📬 <i>{added_cnt} info akun berhasil dimasukkan ke pool stok!</i>",
            reply_markup=keyboard,
            parse_mode=ParseMode.HTML,
        )
        return

    # 4b. Tambah Produk: Pesan Pengiriman Unlimited
    if state == "ADD_UNLIM_DELIVERY":
        new_prod = context.user_data.get("new_product", {})
        name = new_prod.get("name", "Produk Baru")
        desc = new_prod.get("desc", "")
        price = new_prod.get("price", 0)

        prod_id = db.add_product(name=name, description=desc, price=price, stock=-1, delivery_content=text)
        context.user_data.pop("admin_state", None)
        context.user_data.pop("new_product", None)
        db.clear_admin_state(user.id)

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("⚙️ Kelola Produk Ini", callback_data=f"admin_prod:{prod_id}")],
            [InlineKeyboardButton("📋 Panel Kelola Produk", callback_data="admin:stock")],
            [InlineKeyboardButton("🏠 Menu Utama", callback_data="menu:main")],
        ])
        await update.message.reply_text(
            f"🎉 <b>Produk Unlimited Berhasil Ditambahkan!</b>\n\n"
            f"📦 Nama: <b>{name}</b>\n"
            f"📝 Deskripsi: {desc or '–'}\n"
            f"💰 Harga: <b>{_fmt_rupiah(price)}</b>\n"
            f"📊 Stok: <b>♾️ Unlimited</b>\n\n"
            f"📬 <b>Pesan Pengiriman:</b>\n<code>{text}</code>",
            reply_markup=keyboard,
            parse_mode=ParseMode.HTML,
        )
        return

    # 5. Edit Nama Produk
    if state.startswith("EDIT_NAME_"):
        pid = int(state.replace("EDIT_NAME_", ""))
        db.update_product_name(pid, text)
        context.user_data.pop("admin_state", None)
        db.clear_admin_state(user.id)
        await _show_admin_product_detail_msg(
            update, context, pid, feedback_msg=f"✅ Nama produk berhasil diubah menjadi: <b>{text}</b>"
        )
        return

    # 6. Edit Deskripsi Produk
    if state.startswith("EDIT_DESC_"):
        pid = int(state.replace("EDIT_DESC_", ""))
        db.update_product_description(pid, text)
        context.user_data.pop("admin_state", None)
        db.clear_admin_state(user.id)
        await _show_admin_product_detail_msg(
            update, context, pid, feedback_msg="✅ Deskripsi produk berhasil diperbarui!"
        )
        return

    # 7. Edit Harga Produk
    if state.startswith("EDIT_PRICE_"):
        pid = int(state.replace("EDIT_PRICE_", ""))
        digits = re.sub(r"[^0-9]", "", text)
        if not digits:
            await update.message.reply_text(
                "❌ Mohon kirimkan angka harga yang valid. Contoh: <code>50000</code>",
                parse_mode=ParseMode.HTML,
            )
            return
        price = int(digits)
        db.update_product_price(pid, price)
        context.user_data.pop("admin_state", None)
        db.clear_admin_state(user.id)
        await _show_admin_product_detail_msg(
            update, context, pid, feedback_msg=f"✅ Harga produk berhasil diubah menjadi: <b>{_fmt_rupiah(price)}</b>"
        )
        return

    # 8. Edit Stok Akun Tertentu (Pool Item)
    if state.startswith("EDIT_STOCK_ITEM_"):
        sid = int(state.replace("EDIT_STOCK_ITEM_", ""))
        db.update_stock_item_content(sid, text)
        context.user_data.pop("admin_state", None)
        db.clear_admin_state(user.id)
        item = db.get_stock_item(sid)
        if item:
            status_str = "✅ Ready (Belum Terjual)" if item["is_used"] == 0 else f"🔴 Terjual (Order #{item['order_id']})"
            msg_text = (
                f"✅ <b>Info Akun Berhasil Diperbarui!</b>\n\n"
                f"🔍 <b>Detail Stok Akun #{item['id']}</b>\n\n"
                f"📊 Status: <b>{status_str}</b>\n"
                f"📅 Dibuat: {item['created_at'][:19]}\n\n"
                f"📬 <b>Isi Info Akun Terbaru:</b>\n"
                f"<code>{item['content']}</code>"
            )
            buttons = []
            if item["is_used"] == 0:
                buttons.append([
                    InlineKeyboardButton("✏️ Edit Info Akun Ini", callback_data=f"admin_stk:edit:{item['id']}"),
                    InlineKeyboardButton("🗑️ Hapus Stok Ini", callback_data=f"admin_stk:del:{item['id']}"),
                ])
            buttons.append([
                InlineKeyboardButton("📋 Daftar Stok Akun", callback_data=f"admin_stk:list:{item['product_id']}"),
                InlineKeyboardButton("⚙️ Detail Produk", callback_data=f"admin_prod:{item['product_id']}"),
            ])
            buttons.append([
                InlineKeyboardButton("📦 Panel Kelola Stok", callback_data="admin:stock"),
                InlineKeyboardButton("🏠 Menu Utama", callback_data="menu:main"),
            ])
            await update.message.reply_text(
                msg_text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode=ParseMode.HTML
            )
        else:
            await _show_admin_stock_list(update, context, edit=False)
        return

    # 9. Set Angka Stok Produk (Manual Stock Number)
    if state.startswith("EDIT_STOCK_NUM_") or (state.startswith("EDIT_STOCK_") and not state.startswith("EDIT_STOCK_ITEM_")):
        prefix = "EDIT_STOCK_NUM_" if state.startswith("EDIT_STOCK_NUM_") else "EDIT_STOCK_"
        pid = int(state.replace(prefix, ""))
        if text.strip() == "-1":
            stock = -1
        else:
            digits = re.sub(r"[^0-9]", "", text)
            stock = int(digits) if digits else 0
        db.update_product_stock(pid, stock)
        context.user_data.pop("admin_state", None)
        db.clear_admin_state(user.id)
        stock_badge = "♾️ Unlimited" if stock == -1 else f"{stock} unit"
        await _show_admin_product_detail_msg(
            update, context, pid, feedback_msg=f"✅ Stok produk berhasil diubah menjadi: <b>{stock_badge}</b>"
        )
        return

    # 10. Edit Pesan Pengiriman / Info Akun Default Setelah Bayar
    if state.startswith("EDIT_DELIVERY_"):
        pid = int(state.replace("EDIT_DELIVERY_", ""))
        db.update_product_delivery_content(pid, text)
        context.user_data.pop("admin_state", None)
        db.clear_admin_state(user.id)
        await _show_admin_product_detail_msg(
            update, context, pid, feedback_msg="✅ Pesan default setelah bayar (info akun) berhasil disimpan!"
        )
        return

    # 11. Tambah Stok Akun ke Pool (Bisa 1 atau banyak dipisah ---)
    if state.startswith("ADD_STOCK_ITEM_"):
        pid = int(state.replace("ADD_STOCK_ITEM_", ""))
        if "\n---\n" in text or "\n---\r\n" in text or "\n---" in text:
            raw_items = re.split(r"\n\s*---\s*\n|\n---", text)
        else:
            raw_items = [text]

        added_cnt = db.add_stock_items(pid, raw_items)
        context.user_data.pop("admin_state", None)
        db.clear_admin_state(user.id)
        await _show_admin_product_detail_msg(
            update, context, pid, feedback_msg=f"🎉 Berhasil menambahkan <b>+{added_cnt}</b> stok akun ke pool!"
        )
        return

    # 12. Input Pesan Broadcast ke Semua Pengguna
    if state == "BROADCAST_INPUT":
        context.user_data["broadcast_text"] = text
        context.user_data["admin_state"] = "BROADCAST_CONFIRM"
        db.set_admin_state(user.id, "BROADCAST_CONFIRM", {"broadcast_text": text})

        user_count = db.get_user_count()
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🚀 Ya, Kirim Broadcast", callback_data="admin_bcast:send")],
            [InlineKeyboardButton("❌ Batal", callback_data="admin_cancel:stock:0")],
        ])
        await update.message.reply_text(
            f"📢 <b>Pratinjau Pesan Broadcast</b>\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"{text}\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"👥 Target Penerima: <b>{user_count} Pengguna</b>\n\n"
            f"Apakah Anda yakin ingin mengirim pesan broadcast ini sekarang?",
            reply_markup=keyboard,
            parse_mode=ParseMode.HTML,
        )
        return


async def _show_product_list(
    update: Update, context: ContextTypes.DEFAULT_TYPE, edit: bool = False, force_new: bool = False
) -> None:
    products = db.get_all_products()

    if not products:
        msg = "😔 Saat ini belum ada produk yang tersedia di katalog."
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🏠 Menu Utama", callback_data="menu:main")]
        ])
        await _safe_edit_or_send_text(update, context, text=msg, reply_markup=keyboard, force_new=force_new)
        return

    text_lines = [
        "🛍️ <b>Katalog Produk Sonelz Store</b>",
        "━━━━━━━━━━━━━━━━━━━━━",
    ]
    buttons = []

    for i, p in enumerate(products, 1):
        if p["stock"] == 0:
            stock_str = "❌ Stok Habis"
            btn_badge = "(Habis)"
        elif p["stock"] == -1:
            stock_str = "♾️ Unlimited"
            btn_badge = ""
        else:
            stock_str = f"📦 {p['stock']} unit"
            btn_badge = f"({p['stock']} unit)"

        text_lines.append(
            f"<b>{i}. {p['name']}</b>\n"
            f"   💰 {_fmt_rupiah(p['price'])} | {stock_str}\n"
        )

        p_name_short = p['name'][:22]
        btn_label = f"{i}. {p_name_short} {btn_badge}".strip()

        buttons.append([
            InlineKeyboardButton(
                btn_label,
                callback_data=f"product:{p['id']}",
            )
        ])

    text_lines.append("━━━━━━━━━━━━━━━━━━━━━")
    text_lines.append("👇 <i>Pilih salah satu produk di bawah:</i>")

    buttons.append([InlineKeyboardButton("🏠 Menu Utama", callback_data="menu:main")])
    keyboard = InlineKeyboardMarkup(buttons)
    text = "\n".join(text_lines)

    await _safe_edit_or_send_text(update, context, text=text, reply_markup=keyboard, force_new=force_new)


async def _show_product_detail(
    update: Update, context: ContextTypes.DEFAULT_TYPE, product_id: int
) -> None:
    product = db.get_product(product_id)
    if product is None:
        await _safe_edit_or_send_text(update, context, text="❌ Produk tidak ditemukan.")
        return

    if product["stock"] == -1:
        stock_text = "♾️ Unlimited"
    elif product["stock"] == 0:
        stock_text = "❌ Stok Habis"
    else:
        stock_text = f"📦 {product['stock']} unit ready"

    desc_line = f"\n📝 <b>Deskripsi:</b>\n{product['description']}\n" if product["description"] else ""

    text = (
        f"📦 <b>{product['name']}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━"
        f"{desc_line}\n"
        f"💰 <b>Harga:</b> <b>{_fmt_rupiah(product['price'])}</b>\n"
        f"📊 <b>Stok:</b> {stock_text}\n"
        f"━━━━━━━━━━━━━━━━━━━━━"
    )

    buttons = []
    if product["stock"] != 0:
        buttons.append([
            InlineKeyboardButton(f"🛒 Beli Sekarang – {_fmt_rupiah(product['price'])}", callback_data=f"buy:{product_id}")
        ])
    buttons.append([
        InlineKeyboardButton("⬅️ Kembali ke Katalog", callback_data="back:products"),
        InlineKeyboardButton("🏠 Menu Utama", callback_data="menu:main"),
    ])

    await _safe_edit_or_send_text(update, context, text=text, reply_markup=InlineKeyboardMarkup(buttons))


async def _process_purchase(
    update: Update, context: ContextTypes.DEFAULT_TYPE, product_id: int, qty: int = 1
) -> None:
    """Proses pembelian: buat order → panggil PayKita API → tampilkan gambar QRIS dinamis."""
    query = update.callback_query
    user  = update.effective_user

    # Cek produk
    product = db.get_product(product_id)
    if product is None:
        await _safe_edit_or_send_text(update, context, text="❌ Produk tidak ditemukan.")
        return

    if product["stock"] == 0:
        await _safe_edit_or_send_text(update, context, text="😔 Maaf, stok produk ini habis.")
        return

    if product["stock"] != -1 and qty > product["stock"]:
        await _safe_edit_or_send_text(
            update, context,
            text=f"😔 Maaf, stok tidak mencukupi untuk membeli <b>{qty} unit</b>.\nSisa stok: <b>{product['stock']} unit</b>."
        )
        return

    # BUG-09/13: Validasi bahwa produk punya sesuatu untuk dikirim ke pembeli
    avail_items = db.get_available_stock_items(product_id)
    has_delivery = bool("delivery_content" in product.keys() and product["delivery_content"] and product["delivery_content"].strip())
    if not avail_items and not has_delivery and product["stock"] != -1:
        await _safe_edit_or_send_text(
            update, context,
            text="⚠️ Stok akun produk ini sedang dalam persiapan.\nSilakan coba lagi nanti atau hubungi admin."
        )
        return

    # Pastikan user ada di database
    db.upsert_user(telegram_id=user.id, username=user.username, full_name=user.full_name)
    user_db_id = db.get_user_db_id(user.id)

    # BUG-18: Rate limit — maksimal 3 order PENDING per user
    MAX_PENDING = 3
    pending_count = db.get_user_pending_order_count(user_db_id)
    if pending_count >= MAX_PENDING:
        await _safe_edit_or_send_text(
            update, context,
            text=(
                f"⏳ Anda masih memiliki <b>{pending_count}</b> pesanan yang belum dibayar.\n\n"
                f"Silakan selesaikan pembayaran pesanan sebelumnya terlebih dahulu."
            ),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🏠 Menu Utama", callback_data="menu:main")],
            ])
        )
        return

    # Hitung total harga sesuai jumlah (qty)
    total_price = product["price"] * qty

    # Buat referensi order unik
    order_ref = _make_order_ref()

    # Simpan order ke database (status PENDING)
    order_id = db.create_order(
        order_ref=order_ref,
        user_id=user_db_id,
        product_id=product_id,
        qty=qty,
        base_amount=total_price,
    )

    # 🔒 RESERVASI STOK INSTAN: Kunci `qty` unit stok agar tidak bisa dibeli user lain
    reserved = db.reserve_stock_for_order(product_id=product_id, order_id=order_id, qty=qty)
    if not reserved:
        db.update_order_status(order_ref, "CANCELLED")
        await _safe_edit_or_send_text(
            update, context,
            text="😔 Maaf, stok produk tidak mencukupi untuk jumlah yang diminta karena baru saja diambil pembeli lain."
        )
        return

    # Panggil PayKita API
    result = await paykita.create_order(
        base_amount=total_price,
        reference=order_ref,
    )

    if not result.success:
        db.update_order_status(order_ref, "FAILED")
        db.release_order_stock(order_ref)  # 🔓 Lepaskan stok kembali jika API gagal
        await _safe_edit_or_send_text(
            update,
            context,
            text=(
                f"❌ Gagal membuat pembayaran.\n\n"
                f"Error: {result.error}\n\n"
                f"Order Ref: <code>{order_ref}</code>\n"
                f"Hubungi admin jika masalah berlanjut."
            ),
        )
        return

    # Simpan data PayKita ke database
    db.update_order_paykita(
        order_ref=order_ref,
        paykita_id=result.paykita_id,
        final_amount=result.final_amount,
        qris_data=result.qris_data,
        checkout_url=result.checkout_url,
        payment_info=json.dumps(result.raw, ensure_ascii=False),
    )

    amount_text = _fmt_rupiah(result.final_amount) if result.final_amount else _fmt_rupiah(total_price)
    qty_info = f" ({qty} unit)" if qty > 1 else ""

    text = (
        f"🧾 <b>Tagihan Pembayaran QRIS</b>\n\n"
        f"🆔 <b>Order ID:</b> <code>{order_ref}</code>\n"
        f"📦 <b>Produk:</b> {product['name']}{qty_info}\n"
        f"🔢 <b>Jumlah:</b> <b>{qty} unit</b>\n"
        f"💰 <b>Total Bayar:</b> <b>{amount_text}</b>\n\n"
        f"📱 Scan gambar QRIS di atas menggunakan BCA, DANA, GoPay, OVO, ShopeePay, atau m-Banking apa saja.\n\n"
        f"<i>Status pembayaran akan otomatis terkonfirmasi saat transfer selesai.</i>"
    )

    buttons = [
        [
            InlineKeyboardButton("🔄 Cek Status", callback_data=f"order:{order_ref}"),
            InlineKeyboardButton("❌ Batalkan", callback_data=f"cancel_order:{order_ref}"),
        ],
        [InlineKeyboardButton("🏠 Menu Utama", callback_data="menu:main")],
    ]

    # Kirim foto QRIS langsung ke chat
    if result.qris_data:
        try:
            if query and query.message:
                await query.message.delete()
        except Exception:
            pass
        msg = await context.bot.send_photo(
            chat_id=update.effective_chat.id,
            photo=generate_qris_image(result.qris_data),
            caption=text,
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode=ParseMode.HTML,
        )
        if msg:
            db.update_order_telegram_msg(order_ref, msg.chat_id, msg.message_id)
            asyncio.create_task(_auto_check_payment(order_ref, msg.chat_id, msg.message_id))
    else:
        await _safe_edit_or_send_text(
            update,
            context,
            text=text,
            reply_markup=InlineKeyboardMarkup(buttons),
        )

    # Kirim notifikasi ke admin
    await _notify_admin_new_order(order_ref, user, product, amount_text, qty=qty)


async def _auto_check_payment(order_ref: str, chat_id: int, message_id: int) -> None:
    """
    Background polling worker yang mengecek pembayaran ke PayKita secara otomatis tiap 3-4 detik.
    Begitu terdeteksi PAID:
    1. Eksekusi fulfillment (klaim stok akun unik dari pool).
    2. Hapus foto QRIS (agar QRIS hilang bersih dari chat).
    3. Kirim pesan teks invoice & akun baru yang rapi.
    4. Otomatis PIN pesan teks invoice tersebut di chat pembeli!
    """
    max_checks = (config.ORDER_EXPIRY_MINUTES * 60) // 4
    for _ in range(max_checks):
        await asyncio.sleep(4)
        order = db.get_order_by_ref(order_ref)
        if not order or order["status"] != "PENDING":
            break

        if not order["paykita_id"]:
            continue

        try:
            pk_data = await paykita.get_order_status(order["paykita_id"])
            if pk_data:
                pk_status = str(pk_data.get("status", "")).upper()
                if pk_status == "PAID":
                    delivery_text = await execute_order_fulfillment(order_ref, order, send_notification=False)
                    order = db.get_order_by_ref(order_ref)
                    produk_obj = db.get_product(order["product_id"])
                    produk_nama = produk_obj["name"] if produk_obj else "–"

                    text = (
                        f"🎉 <b>Pembayaran Berhasil!</b>\n\n"
                        f"🆔 <b>Order ID:</b> <code>{order['order_ref']}</code>\n"
                        f"📦 <b>Produk:</b> {produk_nama}\n"
                        f"💰 <b>Total:</b> {_fmt_rupiah(order['final_amount'] or order['base_amount'])}\n"
                        f"📅 <b>Waktu:</b> {order['created_at'][:19]}\n\n"
                        f"📬 <b>Detail Akun / Lisensi:</b>\n"
                        f"<code>{delivery_text or 'Pesanan Anda telah berhasil diproses.'}</code>\n\n"
                        f"<i>Terima kasih telah berbelanja di Sonelz Store!</i>"
                    )
                    buttons = [
                        [InlineKeyboardButton("🛍️ Beli Produk Lain", callback_data="menu:products:new")],
                        [InlineKeyboardButton("🏠 Menu Utama", callback_data="menu:main:new")],
                    ]

                    bot_instance = _app.bot if _app is not None else Bot(token=config.TELEGRAM_BOT_TOKEN)

                    # Hapus foto QRIS agar tidak menutupi chat
                    try:
                        await bot_instance.delete_message(chat_id=chat_id, message_id=message_id)
                    except Exception:
                        pass

                    # Kirim pesan teks invoice & akun baru dengan Efek Partikel Celebration (Telegram Message Effect)
                    new_msg = await _send_with_effect(
                        bot_instance,
                        chat_id=chat_id,
                        text=text,
                        reply_markup=InlineKeyboardMarkup(buttons),
                        effect_id=EFFECT_PARTY,
                    )

                    # Simpan pesan baru & otomatis PIN di chat
                    if new_msg:
                        db.update_order_telegram_msg(order_ref, new_msg.chat_id, new_msg.message_id)
                        try:
                            await bot_instance.pin_chat_message(
                                chat_id=chat_id,
                                message_id=new_msg.message_id,
                                disable_notification=False,
                            )
                            logger.info("Order %s berhasil di-pin di chat %s", order_ref, chat_id)
                        except Exception as e:
                            logger.warning("Gagal pin pesan order %s: %s", order_ref, e)

                    break
                elif pk_status in ("EXPIRED", "FAILED", "CANCELLED"):
                    db.update_order_status(order_ref, pk_status)
                    db.release_order_stock(order_ref)
                    break
        except Exception:
            logger.exception("Error auto check status ref=%s", order_ref)

    # Jika loop polling selesai dan order masih PENDING (kadaluarsa), tandai EXPIRED dan kembalikan stok
    final_check = db.get_order_by_ref(order_ref)
    if final_check and final_check["status"] == "PENDING":
        db.update_order_status(order_ref, "EXPIRED")
        db.release_order_stock(order_ref)


async def _show_orders(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    telegram_id: int,
    edit: bool = False,
    force_new: bool = False,
) -> None:
    user_db_id = db.get_user_db_id(telegram_id)
    if user_db_id is None:
        msg = "❓ Data pengguna tidak ditemukan. Ketik /start untuk memulai."
        await _safe_edit_or_send_text(update, context, text=msg, force_new=force_new)
        return

    orders = db.get_user_orders(user_db_id, limit=10)

    if not orders:
        text = "📋 Belum ada riwayat pesanan.\n\nSilakan lihat katalog untuk mulai belanja!"
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🛍️ Katalog Produk", callback_data="menu:products")],
            [InlineKeyboardButton("🏠 Menu Utama", callback_data="menu:main")],
        ])
    else:
        text = "📋 <b>Riwayat Pesanan Anda</b>:\n\nPilih salah satu untuk melihat detail:"
        buttons = []
        for o in orders:
            emoji = _status_emoji(o["status"])
            buttons.append([
                InlineKeyboardButton(
                    f"{emoji} {o['order_ref']} · {o['product_name'][:18]}",
                    callback_data=f"order:{o['order_ref']}",
                )
            ])
        buttons.append([
            InlineKeyboardButton("🛍️ Katalog", callback_data="menu:products"),
            InlineKeyboardButton("🏠 Menu Utama", callback_data="menu:main"),
        ])
        keyboard = InlineKeyboardMarkup(buttons)

    await _safe_edit_or_send_text(update, context, text=text, reply_markup=keyboard, force_new=force_new)


async def execute_order_fulfillment(order_ref: str, order, send_notification: bool = False) -> str:
    """
    Proses fulfillment order yang sudah berstatus PAID/PENDING.

    BUG-01/02/11/12 — IDEMPOTENCY GUARD:
    Menggunakan atomic DB transition PENDING→PROCESSING sehingga hanya SATU
    proses (auto-check, cek-status, atau webhook) yang berhasil menjalankan
    fulfillment. Proses lain akan menemukan status bukan PENDING dan langsung
    return fulfillment yang sudah ada.
    """
    # Re-read fresh dari DB untuk menghindari stale data
    fresh_order = db.get_order_by_ref(order_ref)
    if not fresh_order:
        return ""

    # Jika sudah diproses (bukan PENDING), kembalikan fulfillment yang ada
    if fresh_order["status"] in ("COMPLETED", "PROCESSING", "PAID"):
        logger.info("execute_order_fulfillment: order %s sudah %s, skip.", order_ref, fresh_order["status"])
        return (fresh_order["fulfillment"] or "") if "fulfillment" in fresh_order.keys() else ""

    # Atomic lock: PENDING → PROCESSING (hanya satu coroutine yang berhasil)
    if not db.mark_order_processing_if_pending(order_ref):
        # Proses lain sudah mengklaim order ini
        fresh_order = db.get_order_by_ref(order_ref)
        return (fresh_order["fulfillment"] or "") if (fresh_order and "fulfillment" in fresh_order.keys()) else ""

    # Re-read setelah mark (untuk mendapatkan data terbaru)
    order = db.get_order_by_ref(order_ref) or order

    product = db.get_product(order["product_id"])
    product_name = product["name"] if product else "Produk"
    qty = order["qty"] if ("qty" in order.keys() and order["qty"]) else 1

    # Klaim akun unik dari pool stock (klaim sejumlah qty unit yang sudah di-reserve untuk order ini)
    claimed_items = db.claim_reserved_stock_items(product_id=order["product_id"], order_id=order["id"], qty=qty)
    if claimed_items:
        if len(claimed_items) == 1:
            delivery = claimed_items[0]
        else:
            blocks = []
            for idx, item_content in enumerate(claimed_items, 1):
                blocks.append(f"📦 <b>[ Akun #{idx} ]</b>\n<code>{item_content}</code>")
            delivery = "\n\n━━━━━━━━━━━━━━━━━━━━━\n\n".join(blocks)
    elif product and "delivery_content" in product.keys() and product["delivery_content"] and product["delivery_content"].strip():
        base_deliv = product["delivery_content"].strip()
        if qty > 1:
            delivery = f"🔢 <b>Jumlah:</b> {qty} unit\n\n{base_deliv}"
        else:
            delivery = base_deliv
    else:
        delivery = "⚠️ <i>Stok akun sedang kosong. Silakan hubungi admin toko dengan mengirimkan Order ID ini untuk klaim akun Anda.</i>"

    # BUG-02: Satu kali DB write untuk fulfillment + COMPLETED (bukan 3x update terpisah)
    db.update_order_fulfillment(order_ref, delivery)

    # 📢 Kirim invoice bukti pembelian ke channel @nelstores (hanya 1x per order berkat atomic DB lock)
    try:
        asyncio.create_task(_send_channel_invoice(order_ref, order))
    except Exception as err:
        logger.warning("Gagal memicu pengiriman invoice channel untuk ref %s: %s", order_ref, err)

    if send_notification:
        msg = (
            f"🎉 <b>Pembayaran Berhasil!</b>\n\n"
            f"🆔 <b>Order ID:</b> <code>{order_ref}</code>\n"
            f"📦 <b>Produk:</b> {product_name}\n"
            f"💰 <b>Total:</b> {_fmt_rupiah(order['final_amount'] or order['base_amount'])}\n"
            f"✅ <b>Status:</b> PAID (SELESAI)\n\n"
            f"📬 <b>Detail Akun / Lisensi:</b>\n"
            f"<code>{delivery}</code>\n\n"
            f"<i>Terima kasih telah berbelanja di Sonelz Store!</i>"
        )
        await send_payment_notification(order["user_id"], order_ref, msg)

    return delivery


async def _show_order_detail(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    order_ref: str,
    edit: bool = False,
) -> None:
    order = db.get_order_by_ref(order_ref)

    if order is None:
        msg = f"❌ Order <code>{order_ref}</code> tidak ditemukan."
        await _safe_edit_or_send_text(update, context, text=msg)
        return

    # Sinkronisasi status live ke PayKita API jika saat ini masih PENDING
    status_updated = False
    if order["status"] == "PENDING" and order["paykita_id"]:
        try:
            pk_data = await paykita.get_order_status(order["paykita_id"])
            if pk_data:
                pk_status = str(pk_data.get("status", "")).upper()
                if pk_status == "PAID":
                    # BUG-12: Cek dulu apakah sudah COMPLETED sebelum fulfillment
                    fresh = db.get_order_by_ref(order_ref)
                    if fresh and fresh["status"] not in ("COMPLETED", "PROCESSING", "PAID"):
                        await execute_order_fulfillment(order_ref, fresh, send_notification=False)
                    order = db.get_order_by_ref(order_ref)
                    status_updated = True
                elif pk_status in ("EXPIRED", "FAILED", "CANCELLED"):
                    db.update_order_status(order_ref, pk_status)
                    db.release_order_stock(order_ref)  # 🔓 Lepaskan stok kembali jika expired/failed/cancelled
                    order = db.get_order_by_ref(order_ref)
                    status_updated = True
        except Exception:
            logger.exception("Gagal sinkronisasi status live ke PayKita ref=%s", order_ref)

    produk_obj = db.get_product(order["product_id"])
    produk_nama = produk_obj["name"] if produk_obj else "–"

    # JIKA SUDAH PAID / COMPLETED: Tampilkan info akun & selesai
    if order["status"] in ("PAID", "COMPLETED"):
        delivery_text = order["fulfillment"] or (produk_obj["delivery_content"] if produk_obj and "delivery_content" in produk_obj.keys() else "") or "Pesanan berhasil diproses."
        text = (
            f"🎉 <b>Pembayaran Berhasil!</b>\n\n"
            f"🆔 <b>Order ID:</b> <code>{order['order_ref']}</code>\n"
            f"📦 <b>Produk:</b> {produk_nama}\n"
            f"💰 <b>Total:</b> {_fmt_rupiah(order['final_amount'] or order['base_amount'])}\n"
            f"📅 <b>Waktu:</b> {order['created_at'][:19]}\n\n"
            f"📬 <b>Detail Akun / Lisensi:</b>\n"
            f"<code>{delivery_text}</code>\n\n"
            f"<i>Terima kasih telah berbelanja di Sonelz Store!</i>"
        )
        buttons = [
            [InlineKeyboardButton("🛍️ Beli Produk Lain", callback_data="menu:products:new")],
            [InlineKeyboardButton("🏠 Menu Utama", callback_data="menu:main:new")],
        ]
    else:
        # PENDING / EXPIRED / FAILED
        emoji = _status_emoji(order["status"])
        dibayar_line = f"💳 <b>Dibayar:</b> {_fmt_rupiah(order['final_amount'])}\n" if order["final_amount"] else ""
        text = (
            f"🧾 <b>Detail Pesanan</b>\n\n"
            f"🆔 <b>Order ID:</b> <code>{order['order_ref']}</code>\n"
            f"📦 <b>Produk:</b> {produk_nama}\n"
            f"💰 <b>Total:</b> {_fmt_rupiah(order['final_amount'] or order['base_amount'])}\n"
            f"{dibayar_line}"
            f"📊 <b>Status:</b> {emoji} {order['status']}\n"
            f"📅 <b>Waktu:</b> {order['created_at'][:19]}"
        )
        buttons = [
            [
                InlineKeyboardButton("🔄 Refresh Status", callback_data=f"order:{order_ref}"),
                InlineKeyboardButton("❌ Batalkan", callback_data=f"cancel_order:{order_ref}"),
            ],
            [InlineKeyboardButton("🏠 Menu Utama", callback_data="menu:main")],
        ]

    query = update.callback_query
    if edit and query and query.message:
        # Jika status baru saja terkonfirmasi PAID dari pesan foto QRIS, hapus foto dan kirim pesan teks bersih + PIN
        if status_updated and order["status"] in ("PAID", "COMPLETED") and query.message.photo:
            try:
                await query.message.delete()
            except Exception:
                pass
            new_msg = await _send_with_effect(
                query.bot,
                chat_id=query.message.chat_id,
                text=text,
                reply_markup=InlineKeyboardMarkup(buttons),
                effect_id=EFFECT_PARTY,
            )
            if new_msg:
                db.update_order_telegram_msg(order_ref, new_msg.chat_id, new_msg.message_id)
                try:
                    await query.bot.pin_chat_message(
                        chat_id=query.message.chat_id,
                        message_id=new_msg.message_id,
                        disable_notification=False,
                    )
                except Exception as e:
                    logger.warning("Gagal pin pesan: %s", e)
            await query.answer("🎉 Pembayaran Anda berhasil dikonfirmasi!")
            return

        try:
            if query.message.photo:
                await query.edit_message_caption(
                    caption=text,
                    reply_markup=InlineKeyboardMarkup(buttons),
                    parse_mode=ParseMode.HTML,
                )
            else:
                await query.edit_message_text(
                    text,
                    reply_markup=InlineKeyboardMarkup(buttons),
                    parse_mode=ParseMode.HTML,
                )
            if status_updated and order["status"] in ("PAID", "COMPLETED"):
                await query.answer("🎉 Pembayaran Anda berhasil dikonfirmasi!")
                try:
                    await query.bot.pin_chat_message(
                        chat_id=query.message.chat_id,
                        message_id=query.message.message_id,
                        disable_notification=False,
                    )
                except Exception as e:
                    logger.warning("Gagal pin pesan di _show_order_detail: %s", e)
        except Exception as err:
            if "Message is not modified" in str(err):
                if order["status"] == "PENDING":
                    await query.answer("⏳ Status masih PENDING, silakan bayar terlebih dahulu.")
                else:
                    await query.answer("✅ Status pesanan sudah yang terbaru.")
            else:
                logger.warning("edit message error: %s", err)
    else:
        if order["status"] == "PENDING" and order["qris_data"]:
            await update.message.reply_photo(
                photo=generate_qris_image(order["qris_data"]),
                caption=text,
                reply_markup=InlineKeyboardMarkup(buttons),
                parse_mode=ParseMode.HTML,
            )
        else:
            await update.message.reply_text(
                text,
                reply_markup=InlineKeyboardMarkup(buttons),
                parse_mode=ParseMode.HTML,
            )


async def _show_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    admin_line = "\n/admin    – Panel kelola stok\n" if user and _is_admin(user.id) else ""
    text = (
        "ℹ️ <b>Panduan & Bantuan</b>\n\n"
        "<b>Cara Membeli:</b>\n"
        "1. Pilih produk di menu <b>Katalog Produk</b>\n"
        "2. Klik <b>Beli Sekarang</b> untuk membuat tagihan\n"
        "3. Scan foto QRIS dinamis menggunakan e-wallet atau m-Banking apa saja\n"
        "4. Setelah transfer, sistem otomatis memverifikasi dan mengirimkan info akun langsung ke chat ini.\n\n"
        "<b>Perintah Bot:</b>\n"
        "/start    – Menu utama\n"
        "/products – Katalog produk\n"
        f"/status &lt;ref&gt; – Cek status pesanan{admin_line}\n"
        "<i>Hubungi admin jika Anda membutuhkan bantuan lebih lanjut.</i>"
    )
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🛍️ Katalog", callback_data="menu:products"),
            InlineKeyboardButton("🏠 Menu Utama", callback_data="menu:main"),
        ]
    ])
    await _safe_edit_or_send_text(update, context, text=text, reply_markup=keyboard)


# ══════════════════════════════════════════════════════════════════════════════
# ADMIN NOTIFICATIONS
# ══════════════════════════════════════════════════════════════════════════════

async def _notify_admin_new_order(order_ref: str, user, product, amount_text: str, qty: int = 1) -> None:
    """Kirim notifikasi order baru ke admin (hanya jika pembeli bukan admin sendiri)."""
    global _app
    if _app is None:
        return
    # Hindari spam jika admin sendiri yang sedang belanja/testing
    if user.id == config.ADMIN_TELEGRAM_ID:
        return
    try:
        qty_str = f" (x{qty} unit)" if qty > 1 else ""
        text = (
            f"🔔 <b>Order Baru Masuk!</b>\n\n"
            f"👤 User   : {user.full_name} (@{user.username or '–'})\n"
            f"🆔 Ref    : <code>{order_ref}</code>\n"
            f"📦 Produk : {product['name']}{qty_str}\n"
            f"💰 Nominal: {amount_text}\n"
            f"⏳ Status : PENDING"
        )
        await _app.bot.send_message(
            chat_id=config.ADMIN_TELEGRAM_ID,
            text=text,
            parse_mode=ParseMode.HTML,
        )
    except Exception:
        logger.exception("Gagal kirim notifikasi order baru ke admin")


async def send_payment_notification(user_db_id: int, order_ref: str, fulfillment: str) -> None:
    """
    Kirim notifikasi pembayaran berhasil + hasil fulfillment ke user.
    Dipanggil dari webhook.py setelah PAID.
    """
    # Cari telegram_id dari database
    from database import get_db
    with get_db() as conn:
        row = conn.execute(
            "SELECT telegram_id FROM users WHERE id = ?", (user_db_id,)
        ).fetchone()

    if row is None:
        logger.warning("send_payment_notification: user_db_id=%s tidak ditemukan", user_db_id)
        return

    telegram_id = row["telegram_id"]
    bot_instance = _app.bot if _app is not None else Bot(token=config.TELEGRAM_BOT_TOKEN)

    try:
        await _send_with_effect(
            bot_instance,
            chat_id=telegram_id,
            text=fulfillment,
            effect_id=EFFECT_PARTY,
        )
        # Notifikasi ke admin (hanya jika pembeli bukan admin sendiri)
        if telegram_id != config.ADMIN_TELEGRAM_ID:
            await bot_instance.send_message(
                chat_id=config.ADMIN_TELEGRAM_ID,
                text=(
                    f"✅ <b>Order Selesai Dibayar</b>\n\n"
                    f"🆔 Ref: <code>{order_ref}</code>\n"
                    f"👤 User ID: {telegram_id}"
                ),
                parse_mode=ParseMode.HTML,
            )
    except Exception:
        logger.exception("Gagal kirim notifikasi ke user telegram_id=%s", telegram_id)


def generate_invoice_image(
    order_ref: str,
    product_name: str,
    qty: int,
    total_amount: int,
    buyer_name: str,
    waktu_str: str,
) -> io.BytesIO:
    """Generate gambar struk invoice modern & profesional menggunakan Pillow."""
    width, height = 1000, 1000
    img = Image.new("RGB", (width, height), color=(15, 23, 42))
    draw = ImageDraw.Draw(img)

    # Background gradient halus
    for y in range(height):
        r = int(15 + (30 - 15) * (y / height))
        g = int(23 + (27 - 23) * (y / height))
        b = int(42 + (75 - 42) * (y / height))
        draw.line([(0, y), (width, y)], fill=(r, g, b))

    # Garis aksen atas
    draw.rectangle([0, 0, width, 12], fill=(99, 102, 241))

    # Font setup
    try:
        font_store = ImageFont.truetype("arialbd.ttf", 36)
        font_sub = ImageFont.truetype("arial.ttf", 20)
        font_badge = ImageFont.truetype("arialbd.ttf", 22)
        font_prod_title = ImageFont.truetype("arialbd.ttf", 38)
        font_label = ImageFont.truetype("arial.ttf", 24)
        font_val = ImageFont.truetype("arialbd.ttf", 24)
        font_total_lbl = ImageFont.truetype("arialbd.ttf", 22)
        font_total_val = ImageFont.truetype("arialbd.ttf", 50)
        font_footer = ImageFont.truetype("arial.ttf", 20)
    except Exception:
        font_store = ImageFont.load_default()
        font_sub = font_store
        font_badge = font_store
        font_prod_title = font_store
        font_label = font_store
        font_val = font_store
        font_total_lbl = font_store
        font_total_val = font_store
        font_footer = font_store

    # Header Toko & Subtitle
    draw.text((70, 50), "SONELZ STORE", fill=(255, 255, 255), font=font_store)
    draw.text((70, 96), "BUKTI TRANSAKSI RESMI & LIVE FEED", fill=(148, 163, 184), font=font_sub)

    # Badge Hijau Status LUNAS
    badge_w, badge_h = 230, 46
    badge_x, badge_y = width - 70 - badge_w, 55
    draw.rounded_rectangle(
        [badge_x, badge_y, badge_x + badge_w, badge_y + badge_h],
        radius=23,
        fill=(16, 185, 129),
    )
    draw.text((badge_x + 22, badge_y + 10), "● LUNAS / PAID", fill=(255, 255, 255), font=font_badge)

    # Kartu Utama (Container)
    card_x1, card_y1, card_x2, card_y2 = 70, 160, width - 70, 880
    draw.rounded_rectangle(
        [card_x1, card_y1, card_x2, card_y2],
        radius=20,
        fill=(30, 41, 59),
        outline=(51, 65, 85),
        width=2,
    )

    # Nama Produk
    draw.text((card_x1 + 40, card_y1 + 35), "PRODUK YANG DIBELI", fill=(148, 163, 184), font=font_sub)
    display_prod_name = product_name if len(product_name) <= 34 else product_name[:32] + "..."
    draw.text((card_x1 + 40, card_y1 + 65), display_prod_name, fill=(248, 250, 252), font=font_prod_title)
    draw.line([(card_x1 + 40, card_y1 + 130), (card_x2 - 40, card_y1 + 130)], fill=(51, 65, 85), width=2)

    # Baris Rincian
    rows = [
        ("Order ID", order_ref),
        ("Jumlah Unit", f"{qty} unit"),
        ("Metode Pembayaran", "QRIS Real-Time (Instant)"),
        ("Waktu Transaksi", waktu_str),
        ("Pembeli", buyer_name),
    ]

    curr_y = card_y1 + 155
    row_spacing = 58
    for label, val in rows:
        draw.text((card_x1 + 40, curr_y), label, fill=(148, 163, 184), font=font_label)
        draw.text((card_x1 + 340, curr_y), f":  {val}", fill=(241, 245, 249), font=font_val)
        curr_y += row_spacing

    # Kotak Total Pembayaran
    tot_box_y1 = card_y2 - 170
    tot_box_y2 = card_y2 - 30
    draw.rounded_rectangle(
        [card_x1 + 30, tot_box_y1, card_x2 - 30, tot_box_y2],
        radius=16,
        fill=(15, 23, 42),
        outline=(99, 102, 241),
        width=2,
    )

    fmt_rupiah = f"Rp {total_amount:,.0f}".replace(",", ".")
    draw.text((card_x1 + 60, tot_box_y1 + 22), "TOTAL DIBAYAR", fill=(148, 163, 184), font=font_total_lbl)
    draw.text((card_x1 + 60, tot_box_y1 + 55), fmt_rupiah, fill=(56, 189, 248), font=font_total_val)
    draw.text((card_x2 - 150, tot_box_y1 + 42), "VERIFIED", fill=(16, 185, 129), font=font_badge)

    draw.text((width // 2 - 200, height - 80), "🔐 Terverifikasi Otomatis | @sonelzbot", fill=(100, 116, 139), font=font_footer)

    bio = io.BytesIO()
    bio.name = "invoice.jpg"
    img.save(bio, "JPEG", quality=95)
    bio.seek(0)
    return bio


async def _send_channel_invoice(order_ref: str, order) -> None:
    """
    Kirim invoice / struk transaksi sukses beserta gambar JPG ke channel Telegram (@nelstores).
    Otomatis menyensor username pembeli dan menjaga privasi detail akun/lisensi.
    """
    channel = getattr(config, "FORCE_SUB_CHANNEL", "@nelstores").strip()
    if not channel:
        return

    bot_instance = _app.bot if _app is not None else Bot(token=config.TELEGRAM_BOT_TOKEN)

    try:
        product = db.get_product(order["product_id"])
        prod_name = product["name"] if product else "Produk"
        qty = order["qty"] if ("qty" in order.keys() and order["qty"]) else 1
        total_amount = (order["final_amount"] if "final_amount" in order.keys() else None) or (order["base_amount"] if "base_amount" in order.keys() else 0) or 0
        created_at = order["created_at"] if "created_at" in order.keys() else ""
        if created_at and len(created_at) >= 19:
            waktu_str = created_at[:19]
        else:
            waktu_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

        # Ambil data buyer dari DB
        buyer_text = "Pelanggan Setia"
        with db.get_db() as conn:
            user_row = conn.execute("SELECT full_name, username FROM users WHERE id = ?", (order["user_id"],)).fetchone()
            if user_row:
                if user_row["username"]:
                    uname = user_row["username"]
                    if len(uname) > 2:
                        masked = uname[0] + "***" + uname[-1]
                    else:
                        masked = uname[0] + "***"
                    buyer_text = f"@{masked}"
                elif user_row["full_name"]:
                    fname = user_row["full_name"]
                    buyer_text = fname[:15]

        qty_str = f"{qty} unit" if qty > 1 else "1 unit"

        invoice_text = (
            f"🧾 <b>INVOICE PEMBELIAN BERHASIL</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"🆔 <b>Order ID:</b> <code>{order_ref}</code>\n"
            f"📦 <b>Produk:</b> {prod_name}\n"
            f"🔢 <b>Jumlah:</b> {qty_str}\n"
            f"💰 <b>Total Bayar:</b> <b>{_fmt_rupiah(total_amount)}</b>\n"
            f"💳 <b>Metode:</b> QRIS Real-Time\n"
            f"👤 <b>Pembeli:</b> {buyer_text}\n"
            f"📅 <b>Waktu:</b> {waktu_str}\n"
            f"📊 <b>Status:</b> ✅ <b>PAID / LUNAS</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"✨ <i>Pesanan telah diproses & dikirim otomatis oleh bot.</i>\n"
            f"🛍️ <i>Mau order juga? Klik tombol di bawah:</i>"
        )

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🛒 Beli Sekarang via Bot", url="https://t.me/sonelzbot")]
        ])

        # Generate gambar struk JPG otomatis
        photo_bio = generate_invoice_image(
            order_ref=order_ref,
            product_name=prod_name,
            qty=qty,
            total_amount=total_amount,
            buyer_name=buyer_text,
            waktu_str=f"{waktu_str} WIB",
        )

        await bot_instance.send_photo(
            chat_id=channel,
            photo=photo_bio,
            caption=invoice_text,
            reply_markup=keyboard,
            parse_mode=ParseMode.HTML,
        )
        logger.info("Foto Invoice order %s berhasil diposting ke channel %s", order_ref, channel)
    except Exception as e:
        logger.exception("Gagal mengirim foto invoice order %s ke channel %s: %s", order_ref, channel, e)


# ══════════════════════════════════════════════════════════════════════════════
# INISIALISASI BOT
# ══════════════════════════════════════════════════════════════════════════════

async def post_init(application: Application) -> None:
    """Daftarkan command ke BotFather dan aktifkan auto-check untuk order PENDING."""
    from telegram import BotCommandScopeDefault, BotCommandScopeChat

    # BUG-08: Daftarkan command publik (tanpa /admin) untuk semua user
    public_commands = [
        BotCommand("start",    "Menu utama"),
        BotCommand("products", "Lihat daftar produk"),
        BotCommand("status",   "Cek status pesanan"),
    ]
    # Command khusus admin (termasuk /admin & /broadcast) hanya untuk Owner
    admin_commands = public_commands + [
        BotCommand("admin",     "👑 Panel Owner (Kelola Produk & Stok)"),
        BotCommand("broadcast", "📢 Broadcast pesan ke semua pengguna"),
    ]
    try:
        await application.bot.set_my_commands(public_commands, scope=BotCommandScopeDefault())
        await application.bot.set_my_commands(
            admin_commands,
            scope=BotCommandScopeChat(chat_id=config.ADMIN_TELEGRAM_ID),
        )
        logger.info("Bot commands berhasil didaftarkan (publik + admin scope).")
    except Exception:
        logger.exception("Gagal mendaftarkan bot commands ke Telegram")

    # Lanjutkan auto-check untuk pending orders jika bot sempat restart
    try:
        pending_list = db.get_pending_orders_with_msg()
        for po in pending_list:
            asyncio.create_task(_auto_check_payment(po["order_ref"], po["chat_id"], po["message_id"]))
        if pending_list:
            logger.info("Auto-check pembayaran diaktifkan untuk %d order PENDING.", len(pending_list))
    except Exception:
        logger.exception("Gagal inisialisasi auto check pending orders")


def create_application() -> Application:
    """Buat dan konfigurasi Application bot."""
    global _app

    application = (
        Application.builder()
        .token(config.TELEGRAM_BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    # Register handlers
    application.add_handler(CommandHandler("start",     cmd_start))
    application.add_handler(CommandHandler("products",  cmd_products))
    application.add_handler(CommandHandler("orders",    cmd_orders))
    application.add_handler(CommandHandler("status",    cmd_status))
    application.add_handler(CommandHandler("admin",     cmd_admin))
    application.add_handler(CommandHandler("broadcast", cmd_broadcast))
    application.add_handler(CallbackQueryHandler(callback_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_input))

    _app = application
    return application


# ══════════════════════════════════════════════════════════════════════════════
# ENTRYPOINT (jalankan bot secara standalone)
# ══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    logging.basicConfig(
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        level=logging.INFO,
    )

    # Inisialisasi event loop di MainThread (diperlukan untuk Python 3.12+)
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    db.init_db()

    application = create_application()

    logger.info("Bot mulai berjalan (polling)...")
    try:
        application.run_polling(allowed_updates=Update.ALL_TYPES)
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot dihentikan oleh pengguna.")


if __name__ == "__main__":
    main()
