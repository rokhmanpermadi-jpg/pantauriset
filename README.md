# PantauRiset

Pemantau artikel **open access terbaru** bidang agribisnis, ekonomi pertanian, pemasaran pertanian, kelembagaan petani, ketahanan pangan, kelapa sawit, adopsi teknologi, dan pembangunan pedesaan, dengan **ringkasan Bahasa Indonesia** dan **notifikasi WhatsApp** harian.

## Cara kerja

1. Setiap pagi, `scan.py` menanyakan **OpenAlex** (indeks terbuka yang mencakup jurnal Scopus/WoS) untuk 10 topik yang didefinisikan di `config.json`. Hanya artikel *open access* dari jurnal "core" (proksi jurnal terindeks Scopus/WoS) yang diambil.
2. Artikel baru (belum ada di `data/articles.json`) diberi skor relevansi dan, bila `ANTHROPIC_API_KEY` diisi, diringkas dalam Bahasa Indonesia: tujuan, metode, temuan, relevansi untuk riset Anda, skor 1–5.
3. Pembaca web `docs/index.html` dibangun ulang: filter topik/jurnal, pencarian, tandai dibaca/simpan, tautan PDF/DOI, salin sitasi.
4. Digest dikirim ke WhatsApp Anda lewat **CallMeBot**: judul, jurnal, satu paragraf temuan, dan tautan, maksimal 8 artikel paling relevan.

Tidak ada pustaka tambahan yang perlu dipasang; cukup Python 3.9+ bawaan macOS.

## Pemasangan di Mac (sekali saja, ±10 menit)

Setelah ini, **Anda tidak perlu melakukan apa pun**: setiap pagi aplikasi memindai sendiri dan mengirim notifikasi bila ada artikel baru.

Pilih kanal notifikasi (boleh lebih dari satu):

| Kanal | Biaya | Keandalan | Persiapan |
|---|---|---|---|
| **WhatsApp via Fonnte** (disarankan) | ±Rp 50–100 rb/bulan | tinggi | daftar di fonnte.com, Add Device, scan QR dari WhatsApp pengirim (disarankan nomor kedua), salin Token |
| **Telegram** | gratis | tinggi (resmi) | @BotFather → /newbot → salin token; tekan Start di bot |
| **WhatsApp via CallMeBot** | gratis | rendah | kirim `I allow callmebot to send me messages` ke +34 644 43 38 04, tunggu APIKEY |

Lalu di Terminal:

```bash
cd "$HOME/Claude/Projects/Asisten Penelitian Dr. Rokhman Permadi/PantauRiset"
bash setup.sh
```

Skrip menanyakan kanal dan kredensialnya, mengirim pesan uji, melakukan pemindaian pertama, memasang jadwal harian, dan membuka pembaca.

Jadwal berjalan **saat Mac menyala** (bila tertidur, dijalankan segera setelah bangun). Log di `logs/`. Untuk berjalan 24 jam tanpa Mac, lihat bagian GitHub Actions (tambahkan secret `FONNTE_TOKEN`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` sesuai kanal).

## Ringkasan AI Bahasa Indonesia (opsional, disarankan)

Tanpa API key, pembaca dan WhatsApp menampilkan **abstrak asli** (bahasa Inggris). Dengan `ANTHROPIC_API_KEY` di `.env`, setiap artikel baru (maks. 25 per hari, dapat diubah di `config.json`) diringkas terstruktur dalam Bahasa Indonesia dengan model `claude-haiku-5-5`. Biaya kira-kira Rp 200–500 per artikel. Buat key di https://console.anthropic.com.

Pengingat metodologis: ringkasan dibuat **dari abstrak**, bukan teks penuh. Gunakan untuk penyaringan, bukan sebagai pengganti membaca artikel yang akan Anda sitasi.

## Menyesuaikan topik dan jurnal

**API key OpenAlex (gratis, wajib untuk GitHub Actions).** OpenAlex membatasi pemakaian tanpa key pada anggaran $0,10/hari per alamat IP; di server bersama anggaran itu cepat habis dan permintaan ditolak (HTTP 401). Daftar key gratis ($1/hari, kebutuhan PantauRiset ±$0,02/hari) di https://openalex.org/settings/api, lalu isi `OPENALEX_API_KEY` di `.env` (Mac) atau sebagai *secret* (GitHub).

Semua ada di `config.json`:

- `topics`: nama dan *query* (sintaks OpenAlex: `AND`, `OR`, `NOT`, tanda kutip untuk frasa; hindari koma).
- `priority_journals`: daftar ISSN jurnal prioritas; artikel dari jurnal ini diberi label dan bonus skor. Daftar awal disusun dari jurnal utama bidang Anda; **verifikasi status indeksasi** Scopus/WoS secara berkala karena dapat berubah.
- `only_priority_journals`: `true` bila ingin **hanya** jurnal dalam daftar (lebih sempit, lebih bersih).
- `only_core_sources`: `false` bila ingin membuka ke semua sumber OA (lebih luas, lebih berisik).
- `relevance_keywords`: kata kunci dan bobotnya untuk skor relevansi.
- `whatsapp_max_items`, `whatsapp_max_chars`: ukuran digest.
- `whatsapp_notify_when_empty`: kirim pesan walau tidak ada artikel baru.

## Opsi 24 jam: GitHub Actions + GitHub Pages (gratis)

Agar pemindaian berjalan tanpa Mac dan pembaca bisa dibuka dari HP:

1. Buat repositori **privat** di GitHub, unggah seluruh folder ini (tanpa `.env`). Pindahkan berkas `github_workflow_scan.yml` ke `.github/workflows/scan.yml` di dalam repo (folder `.github` tidak bisa saya tulis langsung ke Mac Anda).
2. *Settings → Secrets and variables → Actions*: tambahkan secret `WHATSAPP_PHONE`, `CALLMEBOT_APIKEY`, dan (opsional) `ANTHROPIC_API_KEY`.
3. *Settings → Pages*: Source = **GitHub Actions**. Setelah run pertama, salin URL Pages ke variabel `SITE_URL` (*Variables*) agar tercantum di pesan WhatsApp.
4. *Actions → PantauRiset → Run workflow* untuk uji pertama (isi `lookback` = 30).

Catatan: GitHub Pages pada repositori privat memerlukan paket GitHub Pro; alternatifnya jadikan repositori publik (basis data artikel OA tidak bersifat rahasia) atau cukup unduh `docs/index.html` dari repo.

## Batasan yang perlu diketahui

- **Bukan API Scopus/WoS resmi.** OpenAlex mencakup hampir semua jurnal Scopus/WoS, tetapi penanda "core" adalah proksi, bukan jaminan indeksasi. Untuk kepastian, cek di Scopus Sources / Master Journal List.
- **Keterlambatan indeks.** OpenAlex biasanya mengindeks 1–7 hari setelah terbit; pemindaian memakai jendela tumpang tindih 2 hari supaya tidak ada yang terlewat.
- **Fonnte dan CallMeBot** bukan API resmi Meta; ada risiko kecil nomor pengirim dibatasi WhatsApp, karena itu untuk Fonnte disarankan nomor kedua sebagai pengirim. Telegram adalah satu-satunya kanal resmi di sini.
- Status "dibaca/disimpan" tersimpan di peramban (localStorage), per perangkat.

## Perintah ringkas

| Perintah | Fungsi |
|---|---|
| `python3 scan.py` | pemindaian normal |
| `python3 scan.py --dry-run` | lihat hasil tanpa simpan/kirim |
| `python3 scan.py --lookback 30` | paksa jendela 30 hari |
| `python3 scan.py --no-summary` | lewati ringkasan AI |
| `python3 scan.py --test-whatsapp` | kirim pesan uji |
| `python3 scan.py --rebuild-site` | bangun ulang HTML saja |
