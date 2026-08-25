# Telegram Auto Order Bot

Bot Telegram Toko Digital Otomatis dengan pembayaran QRIS Real-Time (PayKita Gateway), fitur Wajib Join Channel (Force Subscribe), serta pembuatan gambar struk/invoice otomatis ke channel setiap transaksi sukses.

---

## Fitur Utama

### Pengalaman Pembeli
* **Wajib Join Channel (Force Subscribe)**: Pengunjung wajib bergabung ke channel Telegram Anda sebelum dapat mengakses menu belanja dan melihat katalog produk.
* **Pembayaran QRIS Real-Time**: Tagihan QRIS dinamis langsung muncul di chat Telegram. Mendukung pembayaran dari seluruh e-wallet (GoPay, OVO, Dana, ShopeePay, LinkAja) dan m-Banking (BCA, Mandiri, BRI, BNI, dll).
* **Pengiriman Instan (Instant Delivery)**: Akun, lisensi, atau produk digital langsung dikirimkan ke pembeli otomatis setelah pembayaran terverifikasi.
* **Auto-Pin Pesan**: Invoice dan data akun otomatis di-pin di ruang chat pembeli agar mudah ditemukan.
* **Pilihan Jumlah Pembelian (Bulk Order)**: Pembeli dapat memilih jumlah unit yang ingin dibeli secara fleksibel.
* **Riwayat Pesanan (`/orders`)**: Pembeli dapat mengecek riwayat pesanan mereka kapan saja.

### Notifikasi Channel & Promosi
* **Auto Generate Gambar Struk (JPG HD)**: Bot otomatis membuat gambar struk beresolusi tinggi (1000x1000) dan mempostingnya ke channel Telegram sebagai bukti transaksi sukses.
* **Proteksi Privasi Pembeli**: Username pembeli disensor otomatis dan data akun/lisensi pembeli tetap privat (tidak dikirim ke channel publik).
* **Tombol Beli di Channel**: Dilengkapi tombol tautan langsung ke bot untuk mempermudah anggota channel melakukan pembelian berikutnya.

### Panel Owner / Admin
* **Panel Kontrol Produk (`/admin`)**:
  * Tambah produk baru (nama, deskripsi, harga, stok, pesan pengiriman).
  * Edit data produk (nama, deskripsi, harga, info akun).
  * Pengaturan stok cepat (tambah, kurangi, kosongkan, atau set Unlimited).
  * Manajemen stok akun unik (Account Pool) untuk mendistribusikan akun berbeda per pembeli.
* **Kirim Pesan Broadcast (`/broadcast`)**: Mengirim pengumuman atau promosi ke seluruh database pengguna bot.
* **Keamanan Stok & Anti-Duplikasi**: Reservasi stok otomatis saat order dibuat dan dikembalikan jika pembayaran kedaluwarsa atau dibatalkan.
* **Sistem Verifikasi Ganda**: Menggunakan Webhook FastAPI dan background worker otomatis untuk memastikan status pembayaran terdeteksi tanpa jeda.

---

## Struktur File

```text
auto-order-bot/
├── bot.py          # Logika utama bot (Menu, Navigasi, Force Sub, Struk Generator)
├── webhook.py      # Server Webhook FastAPI untuk menerima callback dari PayKita
├── paykita.py      # Klien REST API PayKita (Generate QRIS & cek status transaksi)
├── database.py     # Manajemen Database SQLite (Users, Produk, Pesanan, Stok Akun)
├── config.py       # Loader konfigurasi dari file .env
├── requirements.txt# Daftar dependensi Python
├── .env.example    # Template konfigurasi environment
├── menu.png        # Banner menu utama bot
└── data/
    └── orders.db   # File database SQLite (dibuat otomatis)
```

---

## Konfigurasi (.env)

Salin file `.env.example` menjadi `.env` lalu sesuaikan nilainya:

```env
# Telegram
TELEGRAM_BOT_TOKEN=TokenBotKamu
ADMIN_TELEGRAM_ID=OwnerIDKamu
FORCE_SUB_CHANNEL=@ChannelKamu

# PayKita Payment Gateway
PAYKITA_API_KEY=pk_live_YOUR_API_KEY
PAYKITA_BASE_URL=https://pay.digikita.id/api
PAYKITA_WEBHOOK_SECRET=

# Webhook Server & Domain
WEBHOOK_HOST=0.0.0.0
WEBHOOK_PORT=8000
PUBLIC_URL=https://yourdomain.com

# Pengaturan Tambahan
DB_PATH=data/orders.db
ORDER_EXPIRY_MINUTES=30
```

### Penjelasan Variabel:
| Variabel | Deskripsi |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Token bot yang didapatkan dari @BotFather. |
| `ADMIN_TELEGRAM_ID` | Telegram User ID Anda sebagai owner bot (cek via @userinfobot). |
| `FORCE_SUB_CHANNEL` | Username channel Telegram Anda (contoh: `@nelstores`). |
| `PAYKITA_API_KEY` | API Key dari dashboard PayKita (pay.digikita.id → API Keys). |
| `PAYKITA_WEBHOOK_SECRET` | Webhook secret dari dashboard PayKita (Settings → Webhook). |
| `PUBLIC_URL` | Domain HTTPS server Anda untuk menerima webhook (opsional jika menggunakan auto-check). |

---

## Pengaturan Channel Telegram

Agar fitur Wajib Join Channel dan pengiriman gambar struk dapat berjalan:
1. Buka channel Telegram Anda.
2. Masuk ke pengaturan channel, pilih menu **Administrators**.
3. Tambahkan bot Anda sebagai **Administrator**.
4. Berikan izin standar (Posting pesan dan kelola anggota).

---

## Panduan Menjalankan Bot

### 1. Menjalankan di Komputer Lokal (Windows / Mac / Linux)

1. Pasang dependensi yang diperlukan:
   ```bash
   pip install -r requirements.txt
   ```
2. Jalankan bot:
   ```bash
   python bot.py
   ```

---

### 2. Menjalankan di Server VPS (Ubuntu / Debian)

1. Perbarui sistem dan pasang dependensi:
   ```bash
   sudo apt update && sudo apt upgrade -y
   sudo apt install -y python3 python3-venv python3-pip git curl
   ```

2. Buat virtual environment:
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   pip install --upgrade pip
   pip install -r requirements.txt
   ```

3. Buat service systemd agar bot berjalan di latar belakang:
   ```bash
   sudo nano /etc/systemd/system/telegram-bot.service
   ```

   Isi konfigurasi service:
   ```ini
   [Unit]
   Description=Auto Order Telegram Bot
   After=network.target

   [Service]
   Type=simple
   User=root
   WorkingDirectory=/path/ke/auto-order-bot
   Environment="PATH=/path/ke/auto-order-bot/venv/bin"
   ExecStart=/path/ke/auto-order-bot/venv/bin/python bot.py
   Restart=always
   RestartSec=5

   [Install]
   WantedBy=multi-user.target
   ```

4. Aktifkan dan jalankan service:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable telegram-bot
   sudo systemctl start telegram-bot
   sudo systemctl status telegram-bot
   ```

---

## Daftar Perintah (Commands)

| Perintah | Hak Akses | Keterangan |
|---|---|---|
| `/start` | Semua Pengguna | Membuka menu utama dan katalog produk (wajib join channel). |
| `/products` | Semua Pengguna | Menampilkan daftar produk yang tersedia. |
| `/orders` | Semua Pengguna | Melihat riwayat transaksi pengguna. |
| `/status <REF>` | Semua Pengguna | Mengecek status pesanan tertentu (contoh: `/status ORD-20260825-XXXX`). |
| `/admin` | Owner Only | Membuka panel pengelolaan produk, stok, dan akun pool. |
| `/broadcast <pesan>` | Owner Only | Mengirimkan pesan siaran ke seluruh pengguna bot. |

---

## Bantuan
Jika membutuhkan bantuan lebih lanjut atau kustomisasi, silakan hubungi owner melalui Telegram.
