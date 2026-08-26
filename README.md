# ⚡ Sonel Store - Telegram Auto Order Bot v2.0

<p align="center">
  <img src="menu.png" alt="Sonel Store Banner" width="600"/>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10%2B-blue?style=for-the-badge&logo=python" alt="Python Version"/>
  <img src="https://img.shields.io/badge/Telegram_Bot-v20%2B-2CA5E0?style=for-the-badge&logo=telegram" alt="Telegram Bot"/>
  <img src="https://img.shields.io/badge/Payment-PayKita_QRIS-00C853?style=for-the-badge" alt="PayKita Gateway"/>
  <img src="https://img.shields.io/badge/Database-SQLite_WAL-003B57?style=for-the-badge&logo=sqlite" alt="SQLite"/>
  <img src="https://img.shields.io/badge/License-MIT-green?style=for-the-badge" alt="License"/>
</p>

**Sonel Store Telegram Bot** adalah sistem bot e-commerce otomatis untuk penjualan produk digital (seperti akun premium, lisensi software, kupon, voucher, dsb) dengan integrasi gateway pembayaran **QRIS Real-Time (PayKita)**, pengiriman instan (*instant delivery*), dashboard terminal interaktif berwarna, serta generator struk transaksi HD otomatis ke channel Telegram.

---

## 🌟 Fitur Unggulan

### 🛍️ 1. Pengalaman Belanja Customer
- **Navigasi Cepat & Rapi:** Tombol pilihan produk berbentuk nomor grid (`1`, `2`, `3`, `4`) yang bersih tanpa teks panjang yang berantakan.
- **QRIS Dinamis Otomatis:** Menghasilkan kode QRIS (PNG lossless) langsung di chat. Mendukung semua e-wallet (GoPay, DANA, OVO, ShopeePay) dan m-Banking (BCA, Mandiri, BRI, BNI, dll).
- **Pengiriman Instan (Instant Delivery):** Informasi akun / lisensi langsung dikirimkan ke chat begitu transfer terdeteksi lunas.
- **Auto-Pin Pesan Invoice:** Invoice pembelian disematkan (*pinned message*) otomatis di chat pembeli lengkap dengan efek animasi perayaan 🎉.
- **Pilihan Jumlah & Custom Qty:** Pembeli dapat memilih jumlah pembelian satuan, banyak (*bulk*), atau mengetik angka sendiri.
- **Anti-Double Claim:** Sistem penguncian stok atomik (*atomic lock*) mencegah produk yang sama terbeli oleh dua orang secara bersamaan.

### 👑 2. Panel Kontrol Owner / Admin (`/admin`)
- **Manajemen Produk Interaktif:** Tambah produk baru, ubah nama, ganti deskripsi, serta atur harga (mulai dari Rp 1).
- **Multi-Mode Stok:**
  - **Pool Stok Akun Unik:** Memasukkan banyak akun sekaligus dengan pemisah `---` (stok otomatis bertambah sesuai jumlah baris dan diberikan secara FIFO).
  - **Unlimited Stock:** Untuk produk berupa link/pesan tetap tanpa batas.
  - **Counter Stok Manual:** Pengaturan kuota angka stok biasa.
- **Kelola Tiap Stok Akun:** Melihat, mengedit isi akun tertentu, atau menghapus item stok dari pool.
- **Broadcast Pengumuman (`/broadcast`):** Mengirimkan pesan promosi/informasi ke seluruh pengguna bot dengan validasi sintaks HTML & fitur *fail-safe plain text*.

### 📢 3. Live Feed Struk Otomatis ke Channel
- **Gambar Struk HD (1080x1080):** Generator gambar struk modern dengan format kartu *glassmorphism*, rincian nominal, cap *VERIFIED*, dan waktu WIB.
- **Sensor Privasi:** Otomatis menyamarkan username pembeli (contoh: `@j***e`) demi keamanan dan kenyamanan pembeli.
- **Tombol Direct Link:** Tombol belanja instan terpasang pada setiap postingan invoice di channel.

### 💻 4. Terminal Dashboard Keren (ANSI Color Output)
- Banner status modern saat startup.
- Badges berwarna real-time untuk setiap aktivitas:
  - `[👤 CUSTOMER]` untuk aktivitas pembeli.
  - `[👑 ADMIN]` untuk aktivitas owner di panel.
  - `[🛍️ ORDER]` saat ada tagihan baru dibuat.
  - `[💳 PAYMENT]` saat pembayaran terkonfirmasi LUNAS.
  - `[📢 INVOICE]` saat struk berhasil diposting ke channel.
  - `[❌ ERROR]` untuk informasi error yang jelas dan mencolok.

---

## 📁 Struktur Direktori

```text
auto-order-bot/
├── bot.py              # Logika utama bot Telegram, UI keyboard, & Image Generator
├── webhook.py          # Server Webhook FastAPI untuk menerima callback PayKita
├── paykita.py          # Klien REST API PayKita (API request, QRIS, Signature check)
├── database.py         # Lapisan database SQLite (WAL mode, foreign keys, atomic locking)
├── config.py           # Loader variabel environment (.env)
├── requirements.txt    # Dependensi library Python
├── .env.example        # Template konfigurasi environment
├── .gitignore          # File yang diabaikan oleh Git
├── menu.png            # Banner gambar menu utama
└── data/
    └── orders.db       # Database SQLite (terbuat otomatis saat dijalankan)
```

---

## ⚙️ Persiapan & Konfigurasi (.env)

1. Duplikasi file `.env.example` menjadi `.env`:
   ```bash
   cp .env.example .env
   ```

2. Buka dan edit file `.env`:
   ```env
   # ── Telegram ──
   TELEGRAM_BOT_TOKEN=8603366934:AAEJ2T7oUiyQnNs6NjzLGUTPrIXYwTlBaOs
   ADMIN_TELEGRAM_ID=5712863496
   FORCE_SUB_CHANNEL=@nelstores

   # ── PayKita Gateway ──
   PAYKITA_API_KEY=pk_live_your_api_key_here
   PAYKITA_BASE_URL=https://pay.digikita.id/api
   PAYKITA_WEBHOOK_SECRET=your_webhook_secret_here

   # ── FastAPI Webhook Server ──
   WEBHOOK_HOST=0.0.0.0
   WEBHOOK_PORT=8000
   PUBLIC_URL=https://yourdomain.com

   # ── Database & Order ──
   DB_PATH=data/orders.db
   ORDER_EXPIRY_MINUTES=30
   ```

### 🔑 Cara Mendapatkan Kredensial:
| Variabel | Sumber |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Chat dengan **[@BotFather](https://t.me/BotFather)** di Telegram -> `/newbot`. |
| `ADMIN_TELEGRAM_ID` | Chat dengan **[@userinfobot](https://t.me/userinfobot)** di Telegram untuk melihat User ID angka Anda. |
| `FORCE_SUB_CHANNEL` | Username channel Telegram Anda (Bot **wajib dijadikan Administrator** di channel tersebut). |
| `PAYKITA_API_KEY` | Dashboard **[PayKita](https://pay.digikita.id)** -> Menu *API Keys*. |
| `PAYKITA_WEBHOOK_SECRET`| Dashboard **[PayKita](https://pay.digikita.id)** -> Menu *Settings* -> *Webhook*. |

---

## 🚀 Panduan Instalasi & Menjalankan

---

### A. 🖥️ Instalasi di Windows (Lokal / PC)

#### 1. Prasyarat
- Pastikan sudah menginstal **Python 3.10+** (Centang *"Add Python to PATH"* saat instalasi).
- Pastikan sudah menginstal **Git**.

#### 2. Langkah-Langkah:
1. Buka **Command Prompt (CMD)** atau **PowerShell**, lalu clone repository:
   ```cmd
   git clone https://github.com/username/auto-order-bot.git
   cd auto-order-bot
   ```

2. Buat dan aktifkan Virtual Environment:
   ```cmd
   python -m venv venv
   venv\Scripts\activate
   ```

3. Pasang semua dependensi library:
   ```cmd
   pip install --upgrade pip
   pip install -r requirements.txt
   ```

4. Konfigurasi file `.env` (isi token dan kredensial Anda).

5. Jalankan Bot:
   ```cmd
   python bot.py
   ```

*(Opsional) Untuk membuat shortcut klik ganda di Windows, buat file `run_bot.bat`:*
```bat
@echo off
call venv\Scripts\activate
python bot.py
pause
```

---

### B. 🐧 Instalasi di Server VPS Linux (Ubuntu / Debian)

Panduan deployment lengkap di VPS Ubuntu 20.04 / 22.04 / 24.04 LTS.

#### 1. Update Server & Pasang Paket Dasar:
```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3 python3-venv python3-pip git curl fonts-dejavu-core fonts-freefont-ttf
```

#### 2. Clone Repository & Setup Virtualenv:
```bash
# Clone project ke direktori tujuan (contoh: /opt/auto-order-bot)
cd /opt
git clone https://github.com/username/auto-order-bot.git
cd auto-order-bot

# Buat virtual environment
python3 -m venv venv
source venv/bin/activate

# Upgrade pip & install requirements
pip install --upgrade pip
pip install -r requirements.txt
```

#### 3. Konfigurasi `.env`:
```bash
cp .env.example .env
nano .env
```
*(Tekan `Ctrl + O` lalu `Enter` untuk simpan, `Ctrl + X` untuk keluar dari nano).*

---

#### 4. Menjalankan Bot di Background (Pilih Salah Satu Metode):

---

#### 📌 Opsi 1: Menggunakan Systemd Service (Sangat Direkomendasikan untuk Server)

1. Buat file service systemd baru:
   ```bash
   sudo nano /etc/systemd/system/telegram-bot.service
   ```

2. Tempelkan konfigurasi berikut (sesuaikan path folder jika berbeda):
   ```ini
   [Unit]
   Description=Sonel Store Telegram Auto-Order Bot
   After=network.target

   [Service]
   Type=simple
   User=root
   WorkingDirectory=/opt/auto-order-bot
   Environment="PATH=/opt/auto-order-bot/venv/bin"
   ExecStart=/opt/auto-order-bot/venv/bin/python bot.py
   Restart=always
   RestartSec=5

   [Install]
   WantedBy=multi-user.target
   ```

3. Reload daemon dan aktifkan service:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable telegram-bot
   sudo systemctl start telegram-bot
   ```

4. Cek status dan log bot:
   ```bash
   # Cek status running
   sudo systemctl status telegram-bot

   # Cek log live
   sudo journalctl -u telegram-bot -f
   ```

---

#### 📌 Opsi 2: Menggunakan PM2 Process Manager

Jika Anda terbiasa dengan Node.js / PM2:

1. Pasang PM2:
   ```bash
   sudo apt install -y npm
   sudo npm install -g pm2
   ```

2. Jalankan bot dengan PM2:
   ```bash
   cd /opt/auto-order-bot
   pm2 start venv/bin/python --name "telegram-bot" -- bot.py
   pm2 save
   pm2 startup
   ```

3. Perintah PM2 yang sering digunakan:
   ```bash
   pm2 status          # Cek status bot
   pm2 logs telegram-bot # Pantau live log berwarna di terminal
   pm2 restart telegram-bot # Restart bot
   ```

---

## 🌐 (Opsional) Menjalankan Webhook Server FastAPI

Bot ini sudah memiliki worker **Background Auto-Check** bawaan yang secara otomatis mendeteksi pembayaran setiap beberapa detik tanpa perlu webhook.

Namun jika Anda ingin menggunakan **Instant Webhook Push**:

1. Jalankan server webhook FastAPI:
   ```bash
   uvicorn webhook:app --host 0.0.0.0 --port 8000
   ```
2. Hubungkan domain Anda ke port 8000 menggunakan Nginx Reverse Proxy dengan SSL (Certbot/Cloudflare).
3. Daftarkan URL webhook Anda ke PayKita: `https://yourdomain.com/webhook/paykita`.

---

## 📋 Daftar Perintah Bot

| Command | Hak Akses | Deskripsi |
|---|---|---|
| `/start` | Semua Pengguna | Membuka menu utama toko dan sapaan. |
| `/products` | Semua Pengguna | Menampilkan daftar produk aktif dengan grid nomor. |
| `/status <REF>` | Semua Pengguna | Mengecek status pesanan (contoh: `/status ORD-20260826-XXXX`). |
| `/admin` | 👑 Owner Only | Membuka panel owner (tambah produk, edit stok, ganti harga, dll). |
| `/broadcast <pesan>` | 👑 Owner Only | Mengirimkan pesan siaran ke semua pembeli terdaftar. |

---

## 📄 Lisensi
Didistribusikan di bawah **MIT License**. Bebas digunakan dan dimodifikasi untuk keperluan komersial maupun pribadi.
