# Sonel Store - Telegram Auto Order Bot

Bot Telegram Toko Digital Otomatis untuk **Sonel Store** dengan sistem pembayaran QRIS Real-Time (PayKita Gateway), pengiriman instan produk digital, pembuatan gambar struk/invoice HD otomatis ke channel Telegram, serta panel manajemen produk & stok bagi Owner.

---

## Fitur Utama

### 1. Pembelian & Transaksi
| Fitur | Deskripsi |
|---|---|
| **Akses Terbuka & Cepat** | Pembeli dapat langsung mengakses bot dan melihat katalog produk tanpa syarat wajib gabung ke channel. |
| **QRIS Real-Time** | Pembuatan tagihan QRIS dinamis otomatis yang mendukung seluruh e-wallet (GoPay, OVO, Dana, ShopeePay) dan m-Banking. |
| **Instant Delivery** | Pengiriman otomatis data akun, lisensi, atau produk digital langsung ke chat pembeli setelah pembayaran lunas. |
| **Auto-Pin Invoice** | Menyematkan pesan invoice dan detail akun secara otomatis di ruang chat pembeli dengan efek perayaan 🎉. |
| **Bulk Order & Custom Qty** | Memungkinkan pembeli memilih jumlah cepat atau memasukkan jumlah unit produk kustom yang ingin dibeli. |
| **Riwayat Pesanan** | Memudahkan pembeli mengecek riwayat dan status transaksi sebelumnya via perintah `/orders`. |

### 2. Notifikasi Channel & Promosi
| Fitur | Deskripsi |
|---|---|
| **Struk Visual HD (1080x1080)** | Otomatis membuat gambar struk beresolusi tinggi dengan tipografi jelas, kontras tinggi, dan mempostingnya ke channel Telegram. |
| **Sensor Privasi** | Menyensor username pembeli (contoh: `@n***l`) dan menjaga kerahasiaan data akun/lisensi di channel publik. |
| **Tombol Belanja Cepat** | Menyertakan tombol tautan langsung ke bot pada setiap postingan struk di channel Telegram. |

### 3. Pengelolaan Toko (Owner / Admin)
| Fitur | Deskripsi |
|---|---|
| **Panel Produk (`/admin`)** | Menambah, mengubah nama, harga, deskripsi, serta menghapus produk langsung dari Telegram. |
| **Manajemen Stok** | Mendukung pengaturan angka stok, stok tak terbatas (Unlimited), serta pool stok akun unik per baris. |
| **Pesan Siaran (`/broadcast`)** | Mengirimkan pengumuman atau pesan promosi ke seluruh pengguna yang terdaftar di database. |
| **Sistem Reservasi Stok** | Mengunci stok saat tagihan dibuat dan mengembalikannya otomatis jika transaksi batal atau kedaluwarsa. |
| **Verifikasi Pembayaran Ganda** | Kombinasi Webhook FastAPI dan background worker otomatis untuk pengecekan status tanpa jeda. |

---

## Struktur File

```text
auto-order-bot/
├── bot.py          # Logika utama bot (Menu, Navigasi, Katalog, Struk Generator)
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
| `FORCE_SUB_CHANNEL` | Username channel Telegram Anda untuk posting gambar invoice bukti transaksi (contoh: `@nelstores`). |
| `PAYKITA_API_KEY` | API Key dari dashboard PayKita (pay.digikita.id → API Keys). |
| `PAYKITA_WEBHOOK_SECRET` | Webhook secret dari dashboard PayKita (Settings → Webhook). |
| `PUBLIC_URL` | Domain HTTPS server Anda untuk menerima webhook (opsional jika menggunakan auto-check). |

---

## Pengaturan Channel Telegram (Live Feed Invoice)

Agar bot dapat memposting gambar struk/invoice transaksi sukses secara otomatis ke channel Telegram Anda:
1. Buka channel Telegram Anda.
2. Masuk ke pengaturan channel, pilih menu **Administrators**.
3. Tambahkan bot Anda sebagai **Administrator**.
4. Berikan izin standar (**Post Messages / Posting Pesan**).

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
   Description=Sonel Store Auto Order Telegram Bot
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
| `/start` | Semua Pengguna | Membuka pesan sambutan dan menu katalog produk Sonel Store. |
| `/products` | Semua Pengguna | Menampilkan daftar produk yang tersedia. |
| `/orders` | Semua Pengguna | Melihat riwayat transaksi pengguna. |
| `/status <REF>` | Semua Pengguna | Mengecek status pesanan tertentu (contoh: `/status ORD-20260825-XXXX`). |
| `/admin` | Owner Only | Membuka panel pengelolaan produk, stok, dan akun pool. |
| `/broadcast <pesan>` | Owner Only | Mengirimkan pesan siaran ke seluruh pengguna bot. |

---

## Bantuan
Jika membutuhkan bantuan lebih lanjut atau kustomisasi, silakan hubungi owner melalui Telegram.
