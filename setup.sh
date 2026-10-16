#!/bin/bash
# Pemasangan satu langkah PantauRiset. Jalankan sekali:  bash setup.sh
cd "$(dirname "$0")" || exit 1
echo "=============================================="
echo "  PantauRiset - pemasangan satu kali"
echo "=============================================="
[ -f .env ] && . ./.env

echo
echo "Kanal notifikasi:"
echo "  1) WhatsApp via Fonnte   (berbayar ~Rp 50-100rb/bln, andal, aktivasi scan QR)  <- disarankan"
echo "  2) Telegram              (resmi, gratis, aktif dalam 2 menit)"
echo "  3) WhatsApp via CallMeBot (gratis, perlu balasan APIKEY dari bot)"
echo "  Boleh lebih dari satu, pisahkan dengan koma, mis. 1,2"
read -r -p "Pilih [default 1]: " CH; CH="${CH:-1}"
has(){ case ",$CH," in *",$1,"*) return 0;; *) return 1;; esac; }

FN_TOKEN="$FONNTE_TOKEN"; PHONE="$WHATSAPP_PHONE"; KEY="$CALLMEBOT_APIKEY"
TG_TOKEN="$TELEGRAM_BOT_TOKEN"; TG_ID="$TELEGRAM_CHAT_ID"

if has 1; then
  echo
  echo "Fonnte: daftar di https://fonnte.com -> Dashboard -> Add Device -> scan QR dari WhatsApp"
  echo "        yang akan jadi PENGIRIM (disarankan nomor kedua) -> salin Token perangkat."
  read -r -p "Token Fonnte [${FONNTE_TOKEN:+tersimpan}]: " T; FN_TOKEN="${T:-$FONNTE_TOKEN}"
  [ -z "$FN_TOKEN" ] && { echo "Token Fonnte wajib diisi."; exit 1; }
fi

if has 1 || has 3; then
  echo
  read -r -p "Nomor WhatsApp PENERIMA (contoh +6281234567890) [${WHATSAPP_PHONE:-kosong}]: " P; PHONE="${P:-$WHATSAPP_PHONE}"
  [ -z "$PHONE" ] && { echo "Nomor WhatsApp wajib diisi."; exit 1; }
fi

if has 3; then
  echo
  echo "CallMeBot: pastikan sudah mengirim 'I allow callmebot to send me messages' ke +34 644 43 38 04"
  echo "           dari nomor penerima di atas, dan menerima APIKEY."
  read -r -p "APIKEY CallMeBot [${CALLMEBOT_APIKEY:-kosong}]: " K; KEY="${K:-$CALLMEBOT_APIKEY}"
  [ -z "$KEY" ] && { echo "APIKEY wajib diisi untuk CallMeBot."; exit 1; }
fi

if has 2; then
  echo
  echo "Telegram: cari @BotFather -> /newbot -> beri nama (mis. PantauRiset) -> salin token (123456789:AAH...)."
  read -r -p "Token bot Telegram [${TELEGRAM_BOT_TOKEN:+tersimpan}]: " T; TG_TOKEN="${T:-$TELEGRAM_BOT_TOKEN}"
  [ -z "$TG_TOKEN" ] && { echo "Token Telegram wajib diisi."; exit 1; }
  echo "Buka bot baru Anda di Telegram dan tekan START (atau kirim 'halo')."
  read -r -p "Tekan Enter setelah itu..." _
  TG_ID="$(TELEGRAM_BOT_TOKEN="$TG_TOKEN" python3 scan.py --telegram-id 2>/dev/null | sed -n 's/.*TELEGRAM_CHAT_ID=\([-0-9]*\).*/\1/p' | tail -1)"
  [ -z "$TG_ID" ] && { echo "chat_id belum terdeteksi. Tekan Start di bot, lalu ulangi bash setup.sh"; exit 1; }
  echo "-> chat_id terdeteksi: $TG_ID"
fi

echo
read -r -p "Anthropic API key untuk ringkasan Bahasa Indonesia (Enter untuk lewati) [${ANTHROPIC_API_KEY:+tersimpan}]: " A
AKEY="${A:-$ANTHROPIC_API_KEY}"
read -r -p "Jam kirim digest setiap pagi (0-23) [7]: " HOUR; HOUR="${HOUR:-7}"

cat > .env <<EOF
FONNTE_TOKEN=$FN_TOKEN
TELEGRAM_BOT_TOKEN=$TG_TOKEN
TELEGRAM_CHAT_ID=$TG_ID
WHATSAPP_PHONE=$PHONE
CALLMEBOT_APIKEY=$KEY
ANTHROPIC_API_KEY=$AKEY
SITE_URL=
EOF
chmod 600 .env
echo; echo "-> Konfigurasi tersimpan di .env"

echo; echo "-> Mengirim pesan uji..."
if python3 scan.py --test-notify; then
  echo "   Periksa HP Anda; pesan uji seharusnya sudah masuk."
else
  echo "   Pesan uji gagal. Periksa token/nomor/APIKEY, lalu jalankan lagi: bash setup.sh"; exit 1
fi

echo; echo "-> Pemindaian pertama (30 hari terakhir); ini bisa 1-3 menit..."
python3 scan.py --lookback 30 || { echo "Pemindaian gagal; lihat pesan di atas."; exit 1; }

echo; echo "-> Memasang jadwal otomatis pukul $HOUR:00 setiap hari..."
HOUR="$HOUR" MINUTE=0 bash install_mac.sh

echo
echo "=============================================="
echo "  Selesai. Mulai besok pukul $HOUR:00, artikel baru"
echo "  dikirim otomatis ke HP Anda."
echo "  Pembaca lengkap: docs/index.html (dibuka sekarang)"
echo "=============================================="
open docs/index.html 2>/dev/null || true
