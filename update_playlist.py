#!/usr/bin/env python3
"""
Gerador de lista M3U otimizada para SS IPTV
Fonte: https://www.cxtv.com.br/tv/paises/tvs-brasil
Atualiza a cada 6h via GitHub Actions
Mantém canais ativos, remove inativos e adiciona novos
"""

import json
import os
import re
import concurrent.futures
from datetime import datetime, timezone
from urllib.parse import urljoin

import cloudscraper
from bs4 import BeautifulSoup

# ==================== CONFIGURAÇÕES ====================
BASE_URL = "https://www.cxtv.com.br"
LIST_URL = f"{BASE_URL}/tv/paises/tvs-brasil"
STATE_FILE = "channels_state.json"
OUTPUT_M3U = "brasil.m3u"
MAX_WORKERS = 12
TIMEOUT = 12
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

# Categorias oficiais do site (group-title do SS IPTV)
CATEGORIES_MAP = {
    "filmes": "Filmes",
    "seriados": "Seriados",
    "noticias": "Notícias",
    "notícias": "Notícias",
    "esportes": "Esportes",
    "futebol": "Futebol",
    "variedades": "Variedades",
    "cultura": "Cultura",
    "desenhos": "Desenhos",
    "educativos": "Educativos",
    "musica": "Música",
    "música": "Música",
    "documentarios": "Documentários",
    "documentários": "Documentários",
    "evangelica": "Evangélica",
    "evangélica": "Evangélica",
    "catolica": "Católica",
    "católica": "Católica",
    "alta definicao": "Alta Definição",
    "alta definição": "Alta Definição",
    "publicos": "Públicos",
    "públicos": "Públicos",
    "novelas": "Novelas",
    "culinaria": "Culinária",
    "culinária": "Culinária",
    "agronegocio": "Agronegócio",
    "agronegócio": "Agronegócio",
    "televendas": "Televendas",
    "tempo": "Tempo",
    "carros": "Carros",
    "moda": "Moda",
    "etnicos": "Étnicos",
    "étnicos": "Étnicos",
}

scraper = cloudscraper.create_scraper(
    browser={"browser": "chrome", "platform": "windows", "mobile": False}
)
scraper.headers.update({"User-Agent": USER_AGENT})


def normalize_category(raw: str) -> str:
    if not raw:
        return "Variedades"
    raw_lower = raw.lower().strip()
    for key, value in CATEGORIES_MAP.items():
        if key in raw_lower:
            return value
    for part in re.split(r"[\s,;/|]+", raw_lower):
        if part in CATEGORIES_MAP:
            return CATEGORIES_MAP[part]
    return "Variedades"


def is_stream_alive(url: str) -> bool:
    """Verifica se o stream responde (HEAD ou GET parcial)."""
    if not url or not url.startswith("http"):
        return False
    try:
        r = scraper.head(url, timeout=TIMEOUT, allow_redirects=True)
        if r.status_code in (200, 206, 302, 301):
            return True
        r = scraper.get(url, timeout=TIMEOUT, stream=True, allow_redirects=True)
        return r.status_code in (200, 206)
    except Exception:
        return False


def extract_stream_from_channel_page(channel_url: str) -> str | None:
    """Tenta extrair a URL do stream (m3u8/HLS) da página do canal."""
    try:
        r = scraper.get(channel_url, timeout=TIMEOUT)
        if r.status_code != 200:
            return None
        html = r.text

        patterns = [
            r'["\'](https?://[^"\']+\.m3u8[^"\']*)["\']',
            r'source\s*:\s*["\'](https?://[^"\']+)["\']',
            r'file\s*:\s*["\'](https?://[^"\']+)["\']',
            r'src\s*=\s*["\'](https?://[^"\']+\.m3u8[^"\']*)["\']',
            r'hlsUrl\s*[:=]\s*["\'](https?://[^"\']+)["\']',
        ]
        for pat in patterns:
            m = re.search(pat, html, re.I)
            if m:
                return m.group(1).strip()

        soup = BeautifulSoup(html, "lxml")
        for iframe in soup.find_all("iframe"):
            src = iframe.get("src") or ""
            if "player" in src or "embed" in src:
                if src.startswith("//"):
                    src = "https:" + src
                elif src.startswith("/"):
                    src = urljoin(BASE_URL, src)
                try:
                    ir = scraper.get(src, timeout=TIMEOUT)
                    for pat in patterns:
                        m = re.search(pat, ir.text, re.I)
                        if m:
                            return m.group(1).strip()
                except Exception:
                    pass
        return None
    except Exception:
        return None


def scrape_channel_list() -> list[dict]:
    """Coleta a lista de canais da página principal."""
    channels = []
    seen_slugs = set()

    print("[*] Acessando lista de canais...")
    try:
        r = scraper.get(LIST_URL, timeout=20)
        if r.status_code != 200:
            print(f"[!] Erro HTTP {r.status_code} na lista principal")
            return []
    except Exception as e:
        print(f"[!] Falha ao acessar lista: {e}")
        return []

    soup = BeautifulSoup(r.text, "lxml")

    for card in soup.select("h4, .channel, .tv-item, a[href*='/tv-ao-vivo/']"):
        a = card if card.name == "a" else card.find("a")
        if not a:
            continue
        href = a.get("href", "")
        if "/tv-ao-vivo/" not in href:
            continue
        slug = href.rstrip("/").split("/")[-1]
        if slug in seen_slugs:
            continue
        seen_slugs.add(slug)

        name = a.get_text(strip=True) or slug.replace("-", " ").title()
        parent = a.find_parent()
        cats_text = ""
        if parent:
            cats_text = parent.get_text(" ", strip=True)

        category = normalize_category(cats_text)
        logo = ""
        img = a.find("img") or (parent.find("img") if parent else None)
        if img:
            logo = img.get("src") or img.get("data-src") or ""
            if logo.startswith("//"):
                logo = "https:" + logo
            elif logo.startswith("/"):
                logo = urljoin(BASE_URL, logo)

        channels.append({
            "name": name,
            "slug": slug,
            "url": urljoin(BASE_URL, href),
            "category": category,
            "logo": logo,
            "stream": None,
        })

    print(f"[*] Encontrados {len(channels)} canais na listagem inicial")

    print("[*] Extraindo streams das páginas dos canais...")
    def process(ch):
        stream = extract_stream_from_channel_page(ch["url"])
        ch["stream"] = stream
        return ch

    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as exe:
        channels = list(exe.map(process, channels))

    with_stream = [c for c in channels if c.get("stream")]
    print(f"[*] {len(with_stream)} canais com stream extraído")
    return with_stream


def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"channels": {}, "last_update": None}


def save_state(state: dict):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def update_and_generate():
    state = load_state()
    old_channels = state.get("channels", {})

    scraped = scrape_channel_list()

    print("[*] Verificando canais ativos...")
    active = {}
    def check(ch):
        alive = is_stream_alive(ch["stream"])
        return ch, alive

    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as exe:
        results = list(exe.map(check, scraped))

    for ch, alive in results:
        if alive:
            key = ch["slug"]
            active[key] = {
                "name": ch["name"],
                "stream": ch["stream"],
                "category": ch["category"],
                "logo": ch.get("logo", ""),
                "url": ch["url"],
                "last_seen": datetime.now(timezone.utc).isoformat(),
            }

    final = {}
    for key, data in old_channels.items():
        if key in active:
            final[key] = active[key]
        else:
            if is_stream_alive(data.get("stream", "")):
                data["last_seen"] = datetime.now(timezone.utc).isoformat()
                final[key] = data

    for key, data in active.items():
        final[key] = data

    print(f"[*] Total final de canais ativos: {len(final)}")

    lines = [
        "#EXTM3U",
        f"# Gerado em {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC",
        f"# Fonte: {LIST_URL}",
        f"# Total de canais: {len(final)}",
        "",
    ]

    sorted_channels = sorted(
        final.values(),
        key=lambda x: (x.get("category", "Z"), x.get("name", "").lower())
    )

    for ch in sorted_channels:
        logo = ch.get("logo") or ""
        group = ch.get("category") or "Variedades"
        name = ch.get("name") or "Canal"
        stream = ch.get("stream")

        extinf = (
            f'#EXTINF:-1 tvg-id="{ch.get("slug", "")}" '
            f'tvg-name="{name}" '
            f'tvg-logo="{logo}" '
            f'group-title="{group}",{name}'
        )
        lines.append(extinf)
        lines.append(stream)
        lines.append("")

    with open(OUTPUT_M3U, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    state["channels"] = final
    state["last_update"] = datetime.now(timezone.utc).isoformat()
    save_state(state)

    print(f"[+] Lista gerada: {OUTPUT_M3U}")
    print(f"[+] Estado salvo: {STATE_FILE}")


if __name__ == "__main__":
    update_and_generate()
