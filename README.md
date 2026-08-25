# AutoOrderBot

> **Stack:** Python 3.12+, python-telegram-bot, FastAPI, uvicorn, httpx, SQLite  
> **Payment:** PayKita (pay.digikita.id)

---

## Struktur Project

```
auto-order-bot/
├── bot.py          # Telegram bot (mode polling)
├── webhook.py      # FastAPI webhook receiver dari PayKita
├── paykita.py      # Klien REST API PayKita
├── database.py     # SQLite: users, products, orders
├── config.py       # Loader .env
├── requirements.txt
├── .env.example
└── data/
    └── orders.db   # Dibuat otomatis
```

---

## 1. Persiapan Server Ubuntu

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3.12 python3.12-venv python3.12-dev \
     git curl nginx certbot python3-certbot-nginx
```

---

## 2. Upload & Setup Project

```bash
# Buat direktori
sudo mkdir -p /opt/autoorderbot
sudo chown $USER:$USER /opt/autoorderbot
cd /opt/autoorderbot

# Copy semua file ke sini (via scp, git clone, dsb.)

# Buat virtual environment
python3.12 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

---

## 3. Konfigurasi .env

```bash
cp .env.example .env
nano .env
chmod 600 .env   # Amankan file
```

| Variable | Keterangan |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Dari @BotFather |
| `ADMIN_TELEGRAM_ID` | ID Telegram Anda (chat @userinfobot) |
| `PAYKITA_API_KEY` | Dari dashboard pay.digikita.id → API Keys |
| `PAYKITA_WEBHOOK_SECRET` | Dari dashboard PayKita → Settings → Webhook |
| `PUBLIC_URL` | Domain HTTPS Anda (misal `https://bot.domain.com`) |

---

## 4. Nginx + HTTPS

```bash
sudo nano /etc/nginx/sites-available/autoorderbot
```

```nginx
server {
    listen 80;
    server_name yourdomain.com;

    location /webhook/ {
        proxy_pass         http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header   Host              $host;
        proxy_set_header   X-Real-IP         $remote_addr;
        proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;
        proxy_pass_request_headers on;
        client_max_body_size 1m;
    }

    location /health {
        proxy_pass http://127.0.0.1:8000;
    }
}
```

```bash
sudo ln -s /etc/nginx/sites-available/autoorderbot /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
sudo certbot --nginx -d yourdomain.com
```

Webhook URL Anda: `https://yourdomain.com/webhook/paykita`

---

## 5. Systemd Services

### Bot (Telegram polling)

```bash
sudo nano /etc/systemd/system/autoorderbot-bot.service
```

```ini
[Unit]
Description=AutoOrderBot Telegram Bot
After=network.target

[Service]
Type=simple
User=www-data
WorkingDirectory=/opt/autoorderbot
Environment="PATH=/opt/autoorderbot/venv/bin"
ExecStart=/opt/autoorderbot/venv/bin/python bot.py
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```

### Webhook (FastAPI)

```bash
sudo nano /etc/systemd/system/autoorderbot-webhook.service
```

```ini
[Unit]
Description=AutoOrderBot Webhook Server
After=network.target

[Service]
Type=simple
User=www-data
WorkingDirectory=/opt/autoorderbot
Environment="PATH=/opt/autoorderbot/venv/bin"
ExecStart=/opt/autoorderbot/venv/bin/uvicorn webhook:app --host 127.0.0.1 --port 8000 --workers 1
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```

### Aktifkan service

```bash
sudo chown -R www-data:www-data /opt/autoorderbot
sudo systemctl daemon-reload
sudo systemctl enable autoorderbot-bot autoorderbot-webhook
sudo systemctl start autoorderbot-bot autoorderbot-webhook
sudo systemctl status autoorderbot-bot autoorderbot-webhook
```

---

## 6. Monitoring Log

```bash
sudo journalctl -u autoorderbot-bot -f
sudo journalctl -u autoorderbot-webhook -f
```

---

## 7. Registrasi Webhook di PayKita

1. Login ke [pay.digikita.id](https://pay.digikita.id)
2. Buka **Settings → Webhook**
3. Isi URL: `https://yourdomain.com/webhook/paykita`
4. Salin **Webhook Secret** → isi ke `.env` sebagai `PAYKITA_WEBHOOK_SECRET`
5. Catat nama **header signature** yang digunakan PayKita
6. Update konstanta `SIGNATURE_HEADER` di `webhook.py` jika berbeda dari `x-signature`

---

## 8. Perintah Berguna

```bash
# Restart setelah update kode
sudo systemctl restart autoorderbot-bot autoorderbot-webhook

# Cek database
sqlite3 /opt/autoorderbot/data/orders.db ".tables"
sqlite3 /opt/autoorderbot/data/orders.db \
  "SELECT order_ref, status, base_amount, created_at FROM orders ORDER BY created_at DESC LIMIT 10;"

# Test health endpoint
curl https://yourdomain.com/health
```

---

## 9. TODO setelah Setup

- [ ] Isi semua nilai `.env` termasuk `PAYKITA_WEBHOOK_SECRET`
- [ ] Konfirmasi nama header signature PayKita → update `SIGNATURE_HEADER` di `webhook.py`
- [ ] Daftarkan webhook URL ke dashboard PayKita
- [ ] Ganti logika fulfillment di `webhook.py` → fungsi `_run_fulfillment()`
- [ ] Edit produk di database (`INSERT INTO products ...`) sesuai bisnis Anda
- [ ] Test end-to-end: buat order → bayar QRIS → terima notifikasi Telegram
