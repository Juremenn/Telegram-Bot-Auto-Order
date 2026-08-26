<div align="center">

# ⚡ SONEL STORE AUTO-ORDER BOT
### *Next-Generation Telegram E-Commerce Bot with Real-Time QRIS*

[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![Telegram](https://img.shields.io/badge/Telegram_Bot-v20+-24A1DE?style=for-the-badge&logo=telegram&logoColor=white)](https://core.telegram.org/bots)
[![PayKita](https://img.shields.io/badge/Gateway-PayKita_QRIS-00C853?style=for-the-badge)](https://pay.digikita.id)
[![SQLite](https://img.shields.io/badge/Database-SQLite_WAL-003B57?style=for-the-badge&logo=sqlite&logoColor=white)](https://sqlite.org)
[![License](https://img.shields.io/badge/License-MIT-F59E0B?style=for-the-badge)](LICENSE)

<br/>

<img src="menu.png" alt="Sonel Store Banner" width="620" style="border-radius: 12px; box-shadow: 0 8px 24px rgba(0,0,0,0.25);"/>

<br/>
<br/>

[✨ Fitur Utama](#-fitur-utama) • [⚙️ Konfigurasi](#-konfigurasi-env) • [🚀 Panduan Windows](#-instalasi-di-windows) • [🐧 Panduan Linux VPS](#-instalasi-di-linux-vps) • [📖 Command List](#-daftar-perintah)

</div>

---

## 🌟 Fitur Utama

### 🛍️ Untuk Pembeli (Customer)
| Fitur | Deskripsi |
| :--- | :--- |
| 🔢 **Clean Number Grid** | Tombol navigasi produk hanya berupa angka (`1`, `2`, `3`, `4`) yang rapi dan elegan. |
| 💳 **QRIS Dinamis Otomatis** | Mendukung pembayaran dari semua Bank (BCA, BRI, Mandiri, BNI) & E-Wallet (GoPay, DANA, OVO, ShopeePay). |
| ⚡ **Instant Auto Delivery** | Akun, voucher, atau lisensi otomatis dikirimkan detik itu juga setelah pembayaran berhasil. |
| 📌 **Auto-Pin Invoice** | Pesan struk dan informasi akun otomatis disematkan (*pinned*) di chat pembeli dengan efek animasi perayaan 🎉. |
| 📦 **Pilihan Jumlah & Custom Qty** | Pembeli bisa memilih preset jumlah atau memasukkan kuantiti pesanan secara custom. |
| 🔒 **Anti-Double Claim** | Penguncian stok atomik tingkat database agar tidak terjadi bentrok stok antar pembeli. |

### 👑 Untuk Pemilik Toko (Owner / Admin)
| Fitur | Deskripsi |
| :--- | :--- |
| 🎛️ **Panel Owner (`/admin`)** | Tambah produk, ubah nama, deskripsi, hingga atur harga produk (bebas mulai dari Rp 1). |
| 📦 **Multi-Mode Stock Pool** | Dukungan stok tak terbatas (*Unlimited*), stok hitungan angka, dan **Pool Akun Unik** (pemisah baris `---`). |
| 📢 **Broadcast Engine (`/broadcast`)** | Kirim pesan siaran ke seluruh pengguna dengan preview & validasi format HTML. |
| 🧾 **Visual Invoice Generator HD** | Otomatis membuat gambar struk beresolusi 1080x1080 (*glassmorphism style*) dan mempostingnya ke channel Telegram. |
| 🕶️ **Privasi Terjaga** | Otomatis menyensor username pembeli (contoh: `@j***e`) pada struk yang terposting ke publik. |
| 💻 **Terminal Dashboard** | Log aktivitas real-time dengan warna ANSI dan badge status (`CUSTOMER`, `ADMIN`, `PAYMENT`, `ORDER`). |

---

## 📁 Struktur Direktori

```text
auto-order-bot/
├── bot.py              # Core logic bot, router handler, & invoice renderer
├── database.py         # SQLite WAL layer, atomic locking, & transaction manager
├── paykita.py          # PayKita API client, dynamic QRIS, & signature checker
├── webhook.py          # FastAPI webhook server (alternatif auto-check)
├── config.py           # Environment loader (.env)
├── requirements.txt    # Daftar dependensi Python
├── .env.example        # Template konfigurasi environment
├── menu.png            # Banner gambar menu utama
└── data/
    └── orders.db       # Database SQLite (dibuat otomatis)
```

---

## ⚙️ Konfigurasi `.env`

Salin template `.env.example` ke `.env`:

```bash
cp .env.example .env
```

Isi variabel konfigurasi di dalam file `.env`:

```env
# ── Kredensial Telegram ──
TELEGRAM_BOT_TOKEN=8603366934:AAEJ2T7oUiyQnNs6NjzLGUTPrIXYwTlBaOs
ADMIN_TELEGRAM_ID=5712863496
FORCE_SUB_CHANNEL=@nelstores

# ── Payment Gateway (PayKita) ──
PAYKITA_API_KEY=pk_live_your_api_key_here
PAYKITA_BASE_URL=https://pay.digikita.id/api
PAYKITA_WEBHOOK_SECRET=your_webhook_secret_here

# ── Webhook Server (Opsional) ──
WEBHOOK_HOST=0.0.0.0
WEBHOOK_PORT=8000
PUBLIC_URL=https://yourdomain.com

# ── Database & Order Expiry ──
DB_PATH=data/orders.db
ORDER_EXPIRY_MINUTES=30
```

> [!TIP]
> **Di mana mendapatkan kredensial?**
> - **Bot Token:** Dari [@BotFather](https://t.me/BotFather) (`/newbot`).
> - **Admin ID:** Dari [@userinfobot](https://t.me/userinfobot) (User ID berupa angka).
> - **Channel:** Username channel Anda. Pastikan bot sudah diangkat menjadi **Administrator** (izin *Post Messages*).
> - **PayKita API:** Dari menu *API Keys* & *Webhook* di [Dashboard PayKita](https://pay.digikita.id).

---

## 🚀 Panduan Instalasi

<details open>
<summary><h3>🖥️ A. Instalasi di Windows (PC / Laptop)</h3></summary>

#### 1. Clone & Masuk ke Folder
```cmd
git clone https://github.com/username/auto-order-bot.git
cd auto-order-bot
```

#### 2. Buat & Aktifkan Virtual Environment
```cmd
python -m venv venv
venv\Scripts\activate
```

#### 3. Install Dependensi
```cmd
pip install --upgrade pip
pip install -r requirements.txt
```

#### 4. Jalankan Bot
```cmd
python bot.py
```

*(Opsional)* Anda juga dapat membuat file `start.bat` berisi:
```bat
@echo off
call venv\Scripts\activate
python bot.py
pause
```
</details>

<br/>

<details open>
<summary><h3>🐧 B. Instalasi di Linux VPS (Ubuntu / Debian)</h3></summary>

#### 1. Update Server & Pasang Paket Dasar
```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3 python3-venv python3-pip git curl fonts-dejavu-core fonts-freefont-ttf
```

#### 2. Clone Repository & Setup Virtualenv
```bash
cd /opt
git clone https://github.com/username/auto-order-bot.git
cd auto-order-bot

python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

#### 3. Siapkan Konfigurasi `.env`
```bash
cp .env.example .env
nano .env
```
*(Simpan: `Ctrl + O` lalu `Enter`, Keluar: `Ctrl + X`)*

---

#### 4. Menjalankan 24/7 di Background

##### 📌 Opsi 1: Systemd Service (Rekomendasi Utama)

1. Buat file service:
   ```bash
   sudo nano /etc/systemd/system/telegram-bot.service
   ```
2. Isi konfigurasi berikut:
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
3. Aktifkan & Jalankan:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable telegram-bot
   sudo systemctl start telegram-bot
   ```
4. Perintah Berguna:
   ```bash
   sudo systemctl status telegram-bot   # Cek status
   sudo journalctl -u telegram-bot -f   # Pantau live log
   sudo systemctl restart telegram-bot  # Restart bot
   ```

##### 📌 Opsi 2: Menggunakan PM2

```bash
sudo apt install -y npm
sudo npm install -g pm2

cd /opt/auto-order-bot
pm2 start venv/bin/python --name "telegram-bot" -- bot.py
pm2 save
pm2 startup
```
</details>

---

## 📖 Daftar Perintah Bot

| Perintah | Otoritas | Deskripsi |
| :--- | :---: | :--- |
| `/start` | 👥 Publik | Membuka sapaan awal dan menu katalog produk. |
| `/products` | 👥 Publik | Menampilkan daftar produk yang tersedia dalam grid nomor. |
| `/status <REF>` | 👥 Publik | Mengecek status pesanan (contoh: `/status ORD-20260826-XXXX`). |
| `/admin` | 👑 Owner | Membuka panel kontrol owner (kelola produk, harga, & pool stok). |
| `/broadcast <teks>` | 👑 Owner | Mengirim pesan siaran ke semua pengguna bot. |

---

## 🛡️ Keamanan & Arsitektur

- **SQL Injection Prevention:** 100% menggunakan *parameterized queries* pada SQLite.
- **XSS & HTML Injection Prevention:** Semua nama pengguna dan parameter dinamis di-escape dengan `html.escape()`.
- **HMAC-SHA256 Multi-Header Verification:** Verifikasi keaslian payload webhook secara aman dengan *constant-time comparison* (`hmac.compare_digest`).
- **Zero Token Leak:** Log sensitif dari library `httpx` & `httpcore` disupresi agar token Telegram tidak bocor ke terminal.

---

## 📄 Lisensi
Proyek ini dilisensikan di bawah [MIT License](LICENSE). Bebas digunakan, dikembangkan, dan dimodifikasi.
