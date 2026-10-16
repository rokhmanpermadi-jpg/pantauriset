#!/usr/bin/env python3
"""
PantauRiset - pemindai artikel open access terbaru untuk Dr. Rokhman Permadi.

Alur:
  1. Tarik artikel baru dari OpenAlex per topik (hanya OA, hanya jurnal "core"
     = proksi jurnal terindeks Scopus/WoS).
  2. Buang duplikat terhadap basis data lokal (data/articles.json).
  3. Rekonstruksi abstrak, hitung skor relevansi, buat ringkasan Bahasa
     Indonesia (bila ANTHROPIC_API_KEY tersedia).
  4. Simpan, bangun ulang pembaca HTML (docs/index.html).
  5. Kirim digest WhatsApp lewat CallMeBot.

Hanya memakai pustaka standar Python (>= 3.9). Tidak ada pip install.

Pakai:
  python3 scan.py                 # pemindaian normal
  python3 scan.py --dry-run       # tanpa kirim WhatsApp, tanpa simpan
  python3 scan.py --lookback 30   # paksa jendela 30 hari ke belakang
  python3 scan.py --test-notify   # kirim pesan uji (WhatsApp dan/atau Telegram)
  python3 scan.py --telegram-id   # cari chat_id Telegram setelah menyapa bot
  python3 scan.py --no-summary    # lewati ringkasan AI
  python3 scan.py --rebuild-site  # hanya bangun ulang HTML
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BASE = Path(__file__).resolve().parent
DATA_DIR = BASE / "data"
DOCS_DIR = BASE / "docs"
ARTICLES_PATH = DATA_DIR / "articles.json"
STATE_PATH = DATA_DIR / "state.json"
CONFIG_PATH = BASE / "config.json"
ENV_PATH = BASE / ".env"

OPENALEX = "https://api.openalex.org/works"
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
CALLMEBOT_URL = "https://api.callmebot.com/whatsapp.php"

USER_AGENT = "PantauRiset/1.0 (pemantau literatur akademik; kontak via mailto di config)"


# --------------------------------------------------------------------------- #
# Utilitas
# --------------------------------------------------------------------------- #
def log(msg: str) -> None:
    ts = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def load_env(path: Path = ENV_PATH) -> None:
    """Muat .env sederhana (KEY=VALUE) ke os.environ tanpa menimpa yang ada."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        os.environ.setdefault(k, v)


def load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        log(f"PERINGATAN: {path.name} rusak ({e}); dipakai nilai default.")
        return default


def save_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


def http_get_json(url: str, retries: int = 3, timeout: int = 60) -> dict:
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            last_err = e
            if e.code == 401 and "openalex" in url:
                raise RuntimeError("OpenAlex 401: anggaran harian gratis per IP habis. "
                                   "Isi OPENALEX_API_KEY (gratis) di .env / secrets.") from e
            if e.code == 429 or e.code >= 500:
                time.sleep(2 * attempt)
                continue
            raise
        except (urllib.error.URLError, TimeoutError) as e:
            last_err = e
            time.sleep(2 * attempt)
    raise RuntimeError(f"Gagal mengambil {url[:120]}...: {last_err}")


def http_post_json(url: str, payload: dict, headers: dict, timeout: int = 120) -> dict:
    data = json.dumps(payload).encode("utf-8")
    hdrs = {"Content-Type": "application/json", "User-Agent": USER_AGENT}
    hdrs.update(headers)
    req = urllib.request.Request(url, data=data, headers=hdrs, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def norm_issn(s: str | None) -> str:
    return (s or "").replace("-", "").upper().strip()


# --------------------------------------------------------------------------- #
# OpenAlex
# --------------------------------------------------------------------------- #
def reconstruct_abstract(inv: dict | None) -> str:
    """OpenAlex menyimpan abstrak sebagai inverted index; susun kembali."""
    if not inv:
        return ""
    positions: list[tuple[int, str]] = []
    for word, idxs in inv.items():
        for i in idxs:
            positions.append((i, word))
    positions.sort()
    text = " ".join(w for _, w in positions)
    return re.sub(r"\s+", " ", text).strip()


def build_filter(topic_query: str, since: str, cfg: dict) -> str:
    parts = [
        "is_oa:true",
        f"from_publication_date:{since}",
        "type:article",
    ]
    if cfg.get("only_core_sources", True):
        parts.append("primary_location.source.is_core:true")
    if cfg.get("language"):
        parts.append(f"language:{cfg['language']}")
    # tanda koma dalam query harus di-escape karena koma memisahkan filter
    q = topic_query.replace(",", " ")
    parts.append(f"title_and_abstract.search:{q}")
    return ",".join(parts)


def fetch_topic(topic: dict, since: str, cfg: dict) -> list[dict]:
    """Ambil semua karya untuk satu topik, dengan cursor paging."""
    select = ",".join([
        "id", "doi", "title", "publication_date", "type", "language",
        "primary_location", "open_access", "authorships", "abstract_inverted_index",
        "cited_by_count", "keywords", "best_oa_location",
    ])
    params = {
        "filter": build_filter(topic["query"], since, cfg),
        "select": select,
        "per-page": 50,
        "sort": "publication_date:desc",
        "cursor": "*",
    }
    if cfg.get("mailto"):
        params["mailto"] = cfg["mailto"]
    # API key OpenAlex (gratis, anggaran $1/hari sendiri). Tanpa key, anggaran dibagi per IP
    # dan di server bersama (GitHub Actions) sering habis -> HTTP 401.
    if os.environ.get("OPENALEX_API_KEY"):
        params["api_key"] = os.environ["OPENALEX_API_KEY"].strip()
    out: list[dict] = []
    max_items = int(cfg.get("max_per_topic", 100))
    pages = 0
    while params["cursor"] and len(out) < max_items and pages < 10:
        url = OPENALEX + "?" + urllib.parse.urlencode(params, safe=":,|*()\"")
        data = http_get_json(url)
        results = data.get("results", [])
        out.extend(results)
        params["cursor"] = data.get("meta", {}).get("next_cursor")
        pages += 1
        if not results:
            break
        time.sleep(0.3)  # sopan terhadap API
    return out[:max_items]


def normalize_work(w: dict, topic_name: str, cfg: dict) -> dict:
    loc = w.get("primary_location") or {}
    src = loc.get("source") or {}
    issns = [norm_issn(x) for x in (src.get("issn") or [])]
    if src.get("issn_l"):
        issns.append(norm_issn(src["issn_l"]))
    priority = {norm_issn(j["issn"]): j for j in cfg.get("priority_journals", [])}
    is_priority = any(i in priority for i in issns)

    authors = []
    for a in (w.get("authorships") or [])[:12]:
        nm = (a.get("author") or {}).get("display_name")
        if nm:
            authors.append(nm)

    best = w.get("best_oa_location") or {}
    oa = w.get("open_access") or {}
    pdf = best.get("pdf_url") or loc.get("pdf_url")
    oa_url = oa.get("oa_url") or best.get("landing_page_url") or loc.get("landing_page_url")

    return {
        "id": w.get("id", "").replace("https://openalex.org/", ""),
        "doi": (w.get("doi") or "").replace("https://doi.org/", ""),
        "title": (w.get("title") or "").strip(),
        "date": w.get("publication_date") or "",
        "year": (w.get("publication_date") or "")[:4],
        "journal": src.get("display_name") or "",
        "issn": issns[0] if issns else "",
        "publisher": src.get("host_organization_name") or "",
        "authors": authors,
        "abstract": reconstruct_abstract(w.get("abstract_inverted_index")),
        "oa_url": oa_url or "",
        "pdf_url": pdf or "",
        "oa_status": oa.get("oa_status") or "",
        "cited_by": w.get("cited_by_count") or 0,
        "keywords": [k.get("display_name") for k in (w.get("keywords") or []) if k.get("display_name")][:8],
        "topics": [topic_name],
        "priority_journal": is_priority,
        "language": w.get("language") or "",
        "found_at": dt.datetime.now().strftime("%Y-%m-%d"),
        "summary_id": None,     # ringkasan Bahasa Indonesia (dict) bila ada
        "relevance": 0,         # 0-100
    }


# --------------------------------------------------------------------------- #
# Skor relevansi (tanpa AI) dan ringkasan (dengan AI, opsional)
# --------------------------------------------------------------------------- #
def keyword_relevance(a: dict, cfg: dict) -> int:
    text = f"{a['title']} {a['abstract']} {' '.join(a['keywords'])}".lower()
    score = 0
    for kw, w in cfg.get("relevance_keywords", {}).items():
        if kw.lower() in text:
            score += int(w)
    score += 10 * (len(a["topics"]) - 1)        # cocok lebih dari satu topik
    if a["priority_journal"]:
        score += 15
    if a["pdf_url"]:
        score += 3
    # kompresi lunak agar skor tidak cepat jenuh di 100: 50 -> 50, 130 -> 72
    return int(round(100 * score / (score + 50))) if score > 0 else 0


def fetch_fulltext(a: dict, cfg: dict) -> str:
    """Unduh PDF OA dan ekstrak teksnya. Kembalikan '' bila gagal/tidak layak."""
    if not cfg.get("use_fulltext", True):
        return ""
    try:
        from pypdf import PdfReader  # noqa: WPS433
    except ImportError:
        log("  pypdf tidak terpasang; ringkasan memakai abstrak (pip install pypdf)")
        return ""
    import io  # noqa: WPS433
    candidates = [u for u in (a.get("pdf_url"), a.get("oa_url")) if u]
    for url in candidates:
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
                "Accept": "application/pdf,*/*;q=0.8"})
            with urllib.request.urlopen(req, timeout=60) as r:
                raw = r.read(int(cfg.get("fulltext_max_pdf_mb", 15)) * 1024 * 1024)
            if not raw.startswith(b"%PDF"):
                continue
            reader = PdfReader(io.BytesIO(raw))
            pages = []
            for pg in reader.pages[: int(cfg.get("fulltext_max_pages", 40))]:
                try:
                    pages.append(pg.extract_text() or "")
                except Exception:  # noqa: BLE001
                    pages.append("")
            text = re.sub(r"[ \t]+", " ", "\n".join(pages))
            text = re.sub(r"\n{3,}", "\n\n", text).strip()
            # buang daftar pustaka bila judulnya berada di paruh kedua teks
            m = None
            for mm in re.finditer(r"\n\s*(References|REFERENCES|Bibliography|Daftar Pustaka|Literature Cited)\s*\n", text):
                m = mm
            if m and m.start() > len(text) * 0.4:
                text = text[: m.start()]
            if len(text) < int(cfg.get("fulltext_min_chars", 6000)):
                continue  # terlalu pendek: kemungkinan PDF pindaian atau hanya halaman sampul
            return text[: int(cfg.get("fulltext_max_chars", 45000))]
        except Exception as e:  # noqa: BLE001
            log(f"  Teks penuh gagal ({url[:60]}...): {str(e)[:80]}")
    return ""


SUMMARY_PROMPT = """Anda adalah asisten riset untuk seorang dosen agribisnis/ekonomi pertanian di Kalimantan Tengah, Indonesia, yang meneliti pemasaran pertanian, akses pasar petani kecil, kelembagaan petani, ketahanan pangan, rantai nilai, kelapa sawit, adopsi teknologi digital, dan pembangunan pedesaan.

Baca {sumber_label} berikut, lalu balas HANYA dengan JSON valid (tanpa teks lain) berformat:
{{"tujuan": "...", "metode": "...", "temuan": "...", "keterbatasan": "...", "relevansi": "...", "skor": 1-5}}

Aturan:
- Tulis dalam Bahasa Indonesia akademik yang padat; tiap bidang maksimal 2 kalimat (temuan maksimal 3), seluruh JSON di bawah 230 kata. Jangan menambahkan teks di luar JSON.
- "metode": sebut desain, data, lokasi, periode, ukuran sampel, dan teknik analisis bila disebutkan; jangan mengarang yang tidak ada di teks.
- "temuan": hasil utama yang konkret dengan angka kunci bila ada; bedakan asosiasi dari kausalitas sesuai desain.
- "keterbatasan": keterbatasan yang diakui penulis atau yang tampak dari desain; bila teks tidak menyebut, tulis "Tidak disebutkan".
- "relevansi": kaitan langsung dengan agenda riset dosen di atas (apa yang bisa dipelajari, dibandingkan, atau diuji ulang di konteks Indonesia/Kalimantan). Jika tidak relevan, katakan demikian.
- "skor": 1 (tidak relevan) sampai 5 (sangat relevan), berdasarkan kedekatan dengan agenda riset tersebut.

Judul: {title}
Jurnal: {journal} ({year})
{sumber_label_cap}: {body}
"""


def ai_summary(a: dict, cfg: dict) -> dict | None:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key or not a.get("abstract"):
        return None
    model = cfg.get("summary_model", "claude-haiku-5-5")
    fulltext = fetch_fulltext(a, cfg)
    if fulltext:
        body, sumber = f"{a['abstract'][:3000]}\n\n[TEKS PENUH]\n{fulltext}", "teks penuh"
        label, label_cap = "abstrak dan teks penuh artikel", "Teks"
    else:
        body, sumber = a["abstract"][:6000], "abstrak"
        label, label_cap = "judul dan abstrak", "Abstrak"
    prompt = SUMMARY_PROMPT.format(
        title=a["title"], journal=a["journal"], year=a["year"],
        sumber_label=label, sumber_label_cap=label_cap, body=body,
    )
    payload = {
        "model": model,
        "max_tokens": 2500,
        "messages": [{"role": "user", "content": prompt}],
    }
    headers = {"x-api-key": key, "anthropic-version": "2023-06-01"}
    for attempt in range(3):
        try:
            resp = http_post_json(ANTHROPIC_URL, payload, headers)
            text = "".join(b.get("text", "") for b in resp.get("content", []) if b.get("type") == "text")
            m = re.search(r"\{.*\}", text, re.S)
            if not m:
                log(f"  Ringkasan: tidak ada JSON (stop_reason={resp.get('stop_reason')}): {text[:200]!r}")
                return None
            try:
                out = json.loads(m.group(0))
            except json.JSONDecodeError as e:
                log(f"  Ringkasan: JSON rusak ({e}; stop_reason={resp.get('stop_reason')}): {m.group(0)[:200]!r}")
                return None
            skor = re.search(r"\d", str(out.get("skor", 3)))
            out["skor"] = max(1, min(5, int(skor.group(0)) if skor else 3))
            out["model"] = model
            out["sumber"] = sumber
            return out
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "ignore")[:300]
            log(f"  Anthropic HTTP {e.code}: {body}")
            if e.code in (429, 529) or e.code >= 500:
                time.sleep(5 * (attempt + 1))
                continue
            return None
        except Exception as e:  # noqa: BLE001
            log(f"  Ringkasan gagal: {e}")
            return None
    return None


# --------------------------------------------------------------------------- #
# WhatsApp (CallMeBot)
# --------------------------------------------------------------------------- #
def split_text(text: str, max_len: int) -> list[str]:
    """Pecah teks panjang pada batas paragraf agar tiap bagian <= max_len."""
    parts, cur = [], ""
    for para in text.split("\n\n"):
        if cur and len(cur) + len(para) + 2 > max_len:
            parts.append(cur); cur = para
        else:
            cur = (cur + "\n\n" + para) if cur else para
    if cur:
        parts.append(cur)
    return parts


def send_whatsapp(text: str) -> bool:
    phone = os.environ.get("WHATSAPP_PHONE", "").strip()
    apikey = os.environ.get("CALLMEBOT_APIKEY", "").strip()
    if not phone or not apikey:
        log("WhatsApp dilewati: WHATSAPP_PHONE / CALLMEBOT_APIKEY belum diisi di .env")
        return False
    # CallMeBot memakai URL GET: pecah bila panjang (batas aman ~1200 karakter)
    if len(text) > 1200:
        ok_all = True
        for part in split_text(text, 1200):
            ok_all = send_whatsapp(part) and ok_all
            time.sleep(3)
        return ok_all
    url = CALLMEBOT_URL + "?" + urllib.parse.urlencode({"phone": phone, "text": text, "apikey": apikey})
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=60) as r:
            body = r.read().decode("utf-8", "ignore")
            low = body.lower()
            ok = r.status == 200 and ("queued" in low or "sent" in low) and "error" not in low
            if not ok:
                snippet = re.sub(r"<[^>]+>", " ", body)
                snippet = re.sub(r"\s+", " ", snippet)[:250]
                log(f"CallMeBot balasan tak terduga: {snippet}")
            return ok
    except Exception as e:  # noqa: BLE001
        log(f"WhatsApp gagal: {e}")
        return False


def send_fonnte(text: str) -> bool:
    """Kirim WhatsApp lewat Fonnte (https://fonnte.com). Token dari dashboard perangkat."""
    token = os.environ.get("FONNTE_TOKEN", "").strip()
    target = os.environ.get("WHATSAPP_PHONE", "").strip().lstrip("+")
    if not token or not target:
        return False
    data = urllib.parse.urlencode({"target": target, "message": text, "countryCode": "62"}).encode("utf-8")
    req = urllib.request.Request("https://api.fonnte.com/send", data=data, method="POST",
                                 headers={"Authorization": token, "User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            resp = json.loads(r.read().decode("utf-8", "ignore"))
        if resp.get("status"):
            return True
        log(f"Fonnte menolak: {resp.get('reason') or resp.get('detail')}")
    except urllib.error.HTTPError as e:
        log(f"Fonnte HTTP {e.code}: {e.read().decode('utf-8', 'ignore')[:200]}")
    except Exception as e:  # noqa: BLE001
        log(f"Fonnte gagal: {e}")
    return False


def send_telegram(text: str) -> bool:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        return False
    # format WhatsApp (*tebal*, _miring_) dipetakan ke HTML Telegram
    html = re.sub(r"\*(.+?)\*", r"<b>\1</b>", text)
    html = re.sub(r"(?<![\w/])_(.+?)_(?!\w)", r"<i>\1</i>", html)
    html = html.replace("&", "&amp;")
    html = re.sub(r"<(?!/?[bi]>)", "&lt;", html)
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        ok = True
        for part in split_text(html, 4000):
            resp = http_post_json(url, {"chat_id": chat_id, "text": part, "parse_mode": "HTML",
                                        "disable_web_page_preview": True}, {})
            ok = ok and bool(resp.get("ok"))
        return ok
    except urllib.error.HTTPError as e:
        log(f"Telegram HTTP {e.code}: {e.read().decode('utf-8', 'ignore')[:200]}")
    except Exception as e:  # noqa: BLE001
        log(f"Telegram gagal: {e}")
    return False


def telegram_find_chat_id() -> None:
    """Bantu pengguna menemukan chat_id: baca pesan terakhir yang masuk ke bot."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        log("TELEGRAM_BOT_TOKEN belum diisi di .env"); return
    data = http_get_json(f"https://api.telegram.org/bot{token}/getUpdates")
    ids = {}
    for u in data.get("result", []):
        msg = u.get("message") or u.get("channel_post") or {}
        chat = msg.get("chat") or {}
        if chat.get("id"):
            ids[chat["id"]] = chat.get("first_name") or chat.get("title") or chat.get("username") or ""
    if not ids:
        log("Belum ada pesan masuk. Buka bot Anda di Telegram, tekan Start atau kirim 'halo', lalu jalankan lagi.")
    for cid, name in ids.items():
        log(f"TELEGRAM_CHAT_ID={cid}   ({name})")


def notify(text: str) -> bool:
    """Kirim ke semua kanal yang terkonfigurasi. Berhasil bila minimal satu kanal terkirim."""
    channels = []
    if os.environ.get("FONNTE_TOKEN"):
        channels.append(("Fonnte", send_fonnte))
    if os.environ.get("CALLMEBOT_APIKEY"):
        channels.append(("CallMeBot", send_whatsapp))
    if os.environ.get("TELEGRAM_BOT_TOKEN"):
        channels.append(("Telegram", send_telegram))
    if not channels:
        log("Notifikasi dilewati: belum ada kanal (Fonnte/CallMeBot/Telegram) di .env")
        return False
    results = []
    for name, fn in channels:
        ok = fn(text)
        results.append(ok)
        if not ok:
            log(f"  kanal {name}: gagal")
    return any(results)


def short_doi_link(a: dict, site_url: str | None = None) -> str:
    """Tautan di pesan: ke kartu artikel di aplikasi bila SITE_URL ada, selain itu DOI."""
    if site_url:
        return f"{site_url.rstrip('/')}/#{a['id']}"
    if a.get("doi"):
        return f"https://doi.org/{a['doi']}"
    return a.get("oa_url") or ""


def one_line_summary(a: dict) -> str:
    s = a.get("summary_id")
    if s and s.get("temuan"):
        return s["temuan"]
    ab = a.get("abstract") or ""
    sents = re.split(r"(?<=[.!?])\s+", ab)
    out = " ".join(sents[:2])
    limit = 220
    if len(out) > limit:
        out = out[:limit].rsplit(" ", 1)[0] + "..."
    return out


def build_digest_messages(new_articles: list[dict], cfg: dict, site_url: str | None) -> list[str]:
    """Pecah digest menjadi beberapa pesan agar aman untuk URL GET CallMeBot."""
    max_items = int(cfg.get("whatsapp_max_items", 8))
    max_len = int(cfg.get("whatsapp_max_chars", 6000))  # satu pesan; CallMeBot/Telegram memecah sendiri
    today = dt.date.today().strftime("%d %b %Y")
    ranked = sorted(new_articles, key=lambda x: (x.get("relevance", 0), x.get("date", "")), reverse=True)

    header = f"*PantauRiset* {today}: {len(new_articles)} artikel OA baru."
    if len(ranked) > max_items:
        header += " Paling relevan hari ini:" if max_items == 1 else f" {max_items} paling relevan:"
    if site_url:
        header += f"\nSemua artikel + ringkasan: {site_url}"

    blocks = []
    for i, a in enumerate(ranked[:max_items], 1):
        tag = "[Prioritas] " if a.get("priority_journal") else ""
        skor = ""
        if a.get("summary_id") and a["summary_id"].get("skor"):
            skor = f" (relevansi {a['summary_id']['skor']}/5)"
        line = (
            f"{i}. {tag}*{a['title']}*\n"
            f"_{a['journal']}_ · {a['date']}{skor}\n"
            f"{one_line_summary(a)}\n"
            f"{short_doi_link(a, site_url)}"
        )
        blocks.append(line)

    messages, cur = [], header
    for b in blocks:
        if len(cur) + len(b) + 2 > max_len:
            messages.append(cur)
            cur = b
        else:
            cur = cur + "\n\n" + b
    messages.append(cur)
    return messages


# --------------------------------------------------------------------------- #
# Pipeline utama
# --------------------------------------------------------------------------- #
def run(args: argparse.Namespace) -> int:
    load_env()
    cfg = load_json(CONFIG_PATH, None)
    if cfg is None:
        log("config.json tidak ditemukan."); return 2

    articles: list[dict] = load_json(ARTICLES_PATH, [])
    state: dict = load_json(STATE_PATH, {})
    known = {a["id"] for a in articles}
    known_doi = {a["doi"] for a in articles if a.get("doi")}

    if args.rebuild_site:
        from build_site import build_site  # noqa: WPS433
        build_site(articles, cfg, DOCS_DIR / "index.html")
        log("HTML dibangun ulang."); return 0

    if args.telegram_id:
        telegram_find_chat_id(); return 0

    if args.backfill:
        # ringkas artikel lama yang belum punya ringkasan, mulai dari yang paling relevan
        if not os.environ.get("ANTHROPIC_API_KEY"):
            log("ANTHROPIC_API_KEY belum ada."); return 1
        todo = [a for a in articles if not a.get("summary_id") and a.get("abstract")]
        todo.sort(key=lambda x: (x.get("relevance", 0), x.get("date", "")), reverse=True)
        n_ok = 0
        for a in todo[:args.backfill]:
            s = ai_summary(a, cfg)
            if s:
                a["summary_id"] = s
                a["relevance"] = int(round(0.6 * a["relevance"] + 0.4 * (s["skor"] * 20)))
                n_ok += 1
                log(f"  ringkas [{s['skor']}/5] {a['title'][:80]}")
            time.sleep(0.5)
        log(f"Ringkasan susulan selesai: {n_ok}/{min(args.backfill, len(todo))}")
        save_json(ARTICLES_PATH, articles)
        from build_site import build_site  # noqa: WPS433
        build_site(articles, cfg, DOCS_DIR / "index.html")
        return 0

    if args.test_whatsapp or args.test_notify:
        ok = notify("*PantauRiset* terhubung. Notifikasi artikel baru akan dikirim ke sini setiap pagi.")
        log("Pesan uji terkirim." if ok else "Pesan uji GAGAL."); return 0 if ok else 1

    # jendela waktu: tumpang tindih 2 hari supaya artikel yang terlambat terindeks tidak terlewat
    if args.lookback:
        since_date = dt.date.today() - dt.timedelta(days=args.lookback)
    elif state.get("last_run"):
        since_date = dt.date.fromisoformat(state["last_run"]) - dt.timedelta(days=2)
    else:
        since_date = dt.date.today() - dt.timedelta(days=int(cfg.get("initial_lookback_days", 14)))
    since = since_date.isoformat()
    log(f"Memindai artikel terbit sejak {since} untuk {len(cfg['topics'])} topik...")

    new_map: dict[str, dict] = {}
    for topic in cfg["topics"]:
        try:
            works = fetch_topic(topic, since, cfg)
        except Exception as e:  # noqa: BLE001
            log(f"  Topik '{topic['name']}' gagal: {e}")
            continue
        n_new = 0
        for w in works:
            a = normalize_work(w, topic["name"], cfg)
            if not a["id"] or not a["title"]:
                continue
            if a["id"] in known or (a["doi"] and a["doi"] in known_doi):
                # artikel lama: tambahkan tag topik baru bila belum ada
                for old in articles:
                    if old["id"] == a["id"] and topic["name"] not in old["topics"]:
                        old["topics"].append(topic["name"])
                continue
            if a["id"] in new_map:
                if topic["name"] not in new_map[a["id"]]["topics"]:
                    new_map[a["id"]]["topics"].append(topic["name"])
                continue
            new_map[a["id"]] = a
            n_new += 1
        log(f"  {topic['name']}: {len(works)} hasil, {n_new} baru")

    new_articles = list(new_map.values())
    if cfg.get("only_priority_journals"):
        new_articles = [a for a in new_articles if a["priority_journal"]]
    min_abs = int(cfg.get("min_abstract_chars", 200))
    new_articles = [a for a in new_articles if len(a["abstract"]) >= min_abs or a["priority_journal"]]

    # skor + ringkasan
    use_ai = not args.no_summary and bool(os.environ.get("ANTHROPIC_API_KEY"))
    max_ai = int(cfg.get("max_ai_summaries_per_run", 25))
    for a in new_articles:
        a["relevance"] = keyword_relevance(a, cfg)
    new_articles.sort(key=lambda x: x["relevance"], reverse=True)
    if use_ai:
        log(f"Membuat ringkasan AI untuk maks. {max_ai} artikel...")
        for a in new_articles[:max_ai]:
            s = ai_summary(a, cfg)
            if s:
                a["summary_id"] = s
                a["relevance"] = int(round(0.6 * a["relevance"] + 0.4 * (s["skor"] * 20)))
            time.sleep(0.5)
        new_articles.sort(key=lambda x: x["relevance"], reverse=True)
    else:
        log("Ringkasan AI dilewati (tidak ada ANTHROPIC_API_KEY atau --no-summary).")

    log(f"Total artikel baru: {len(new_articles)}")

    if args.dry_run:
        for a in new_articles[:15]:
            log(f"  [{a['relevance']:3d}] {a['date']} | {a['journal']} | {a['title'][:90]}")
        log("Dry run: tidak menyimpan, tidak mengirim."); return 0

    # simpan
    articles = new_articles + articles
    articles.sort(key=lambda x: x.get("date", ""), reverse=True)
    keep = int(cfg.get("max_articles_kept", 3000))
    articles = articles[:keep]
    save_json(ARTICLES_PATH, articles)
    state["last_run"] = dt.date.today().isoformat()
    state["last_new"] = len(new_articles)
    state.setdefault("history", []).append({"date": state["last_run"], "new": len(new_articles)})
    state["history"] = state["history"][-90:]
    save_json(STATE_PATH, state)

    # bangun situs
    from build_site import build_site  # noqa: WPS433
    build_site(articles, cfg, DOCS_DIR / "index.html")

    # WhatsApp
    site_url = os.environ.get("SITE_URL") or cfg.get("site_url") or None
    if new_articles:
        msgs = build_digest_messages(new_articles, cfg, site_url)
        for i, m in enumerate(msgs, 1):
            ok = notify(m)
            log(f"Notifikasi {i}/{len(msgs)}: {'terkirim' if ok else 'gagal'}")
            time.sleep(3)
    elif cfg.get("whatsapp_notify_when_empty", False):
        notify(f"*PantauRiset* {dt.date.today():%d %b %Y}: tidak ada artikel OA baru hari ini.")
    return 0


def main() -> None:
    p = argparse.ArgumentParser(description="PantauRiset - pemindai artikel OA terbaru")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--lookback", type=int, default=0, help="hari ke belakang (menimpa state)")
    p.add_argument("--test-whatsapp", action="store_true", help="sama dengan --test-notify")
    p.add_argument("--test-notify", action="store_true", help="kirim pesan uji ke semua kanal")
    p.add_argument("--telegram-id", action="store_true", help="tampilkan chat_id Telegram Anda")
    p.add_argument("--no-summary", action="store_true")
    p.add_argument("--rebuild-site", action="store_true")
    p.add_argument("--backfill", type=int, default=0, help="ringkas N artikel lama yang belum punya ringkasan")
    args = p.parse_args()
    sys.path.insert(0, str(BASE))
    sys.exit(run(args))


if __name__ == "__main__":
    main()
