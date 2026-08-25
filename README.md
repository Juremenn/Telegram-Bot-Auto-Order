# Telegram Auto Order Bot

Bot Telegram Toko Digital Otomatis dengan pembayaran QRIS Real-Time (PayKita Gateway), fitur Wajib Join Channel (Force Subscribe), serta pembuatan gambar struk/invoice otomatis ke channel setiap transaksi sukses.

---

## Fitur Utama

### 1. Pembelian & Transaksi
* **Force Subscribe**: Membatasi akses menu bot hanya untuk pengguna yang telah bergabung ke channel Telegram yang ditentukan.
* **QRIS Real-Time**: Pembuatan tagihan QRIS dinamis secara otomatis yang dapat dibayar melalui seluruh e-wallet dan m-Banking.
* **Pengiriman Otomatis (Instant Delivery)**: Mengirimkan data akun, lisensi, atau file digital langsung ke pembeli setelah status pembayaran terkonfirmasi lunas.
* **Auto-Pin Invoice**: Menyematkan pesan invoice dan detail akun secara otomatis di ruang obrolan pembeli.
* **Pilihan Jumlah (Bulk Order)**: Memungkinkan pembeli memilih atau memasukkan jumlah unit produk yang ingin dibeli.
* **Riwayat Pesanan**: Memudahkan pembeli melacak riwayat dan status transaksi melalui perintah `/orders`.

### 2. Notifikasi Channel & Promosi
* **Auto Generate Struk Visual (JPG)**: Membuat gambar struk transaksi secara dinamis (1000x1000) dan mempostingnya ke channel sebagai bukti transaksi sukses.
* **Sensor Privasi**: Menyensor username pembeli dan menyembunyikan detail akun/lisensi agar keamanan data pembeli tetap terjaga di channel publik.
* **Tombol Belanja Cepat**: Menyertakan tombol tautan langsung ke bot pada setiap postingan struk di channel.

### 3. Pengelolaan Toko (Owner / Admin)
* **Panel Kontrol Produk (`/admin`)**: Menambah, mengubah nama, harga, deskripsi, serta menghapus produk langsung dari Telegram.
* **Manajemen Stok**: Mendukung pengaturan angka stok, stok tak terbatas (unlimited), serta pool stok akun unik per baris.
* **Pesan Siaran (`/broadcast`)**: Mengirimkan pengumuman atau pesan promosi ke seluruh pengguna yang terdaftar di database.
* **Sistem Reservasi Stok**: Mengunci stok sementara saat tagihan dibuat dan mengembalikannya otomatis jika transaksi batal atau kedaluwarsa.
* **Verifikasi Pembayaran Ganda**: Menggabungkan Webhook FastAPI dan background worker otomatis untuk pengecekan status pembayaran tanpa keterlambatan.

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
