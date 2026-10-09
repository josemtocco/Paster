#!/usr/bin/env python3
"""
Gerador de lista M3U otimizada para SS IPTV
Fonte: https://www.cxtv.com.br/tv/paises/tvs-brasil
Atualiza a cada 6h via GitHub Actions
Mantém canais ativos, remove inativos e adiciona novos
Busca TODOS os canais via endpoint de paginação (Carregar Mais)
"""

import json
import os
import re
import time
import concurrent.futures
from datetime import datetime, timezone
from urllib.parse import urljoin

import cloudscraper
from bs4 import BeautifulSoup

# ==================== CONFIGURAÇÕES ====================
BASE_URL = "https://www.cxtv.com.br"
LIST_URL = f"{BASE_URL}/tv/paises/tvs-brasil"
# Endpoint real do "Carregar Mais"
LOAD_URL = f"{BASE_URL}/data/tv_paises_list_load.php"
STATE_FILE = "channels_state.json"
OUTPUT_M3U = "brasil.m3u"
MAX_WORKERS = 10
TIMEOUT = 15
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

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
scraper.headers.update({
    "User-Agent": USER_AGENT,
    "Referer": LIST_URL,
    "X-Requested-With": "XMLHttpRequest",
})


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
    if not url or not url.startswith("http"):
        return False
    try:
        r = scraper.head(url, timeout=TIMEOUT, allow_redirects=True)
        if r.status_code in (200, 206, 301, 302):
            return True
        r = scraper.get(url, timeout=TIMEOUT, stream=True, allow_redirects=True)
        return r.status_code in (200, 206)
    except Exception:
        return False


def extract_stream_from_channel_page(channel_url: str) -> str | None:
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
            r'data-src\s*=\s*["\'](https?://[^"\']+\.m3u8[^"\']*)["\']',
        ]
        for pat in patterns:
            m = re.search(pat, html, re.I)
            if m:
                return m.group(1).strip()

        soup = BeautifulSoup(html, "lxml")
        for iframe in soup.find_all("iframe"):
            src = iframe.get("src") or ""
            if "player" in src.lower() or "embed" in src.lower():
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


def parse_channel_cards(html: str) -> list[dict]:
    """Extrai canais do HTML parcial retornado pelo endpoint de load."""
    channels = []
    soup = BeautifulSoup(html, "lxml")

    for a in soup.select("a[href*='/tv-ao-vivo/']"):
        href = a.get("href", "")
        if "/tv-ao-vivo/" not in href:
            continue
        slug = href.rstrip("/").split("/")[-1]
        if not slug:
            continue

        name = a.get_text(strip=True)
        if not name:
            h4 = a.find_parent("h4") or a.find("h4")
            if h4:
                name = h4.get_text(strip=True)
        if not name:
            name = slug.replace("-", " ").title()

        parent = a.find_parent(["div", "article", "li", "section"]) or a.parent
        cats_text = ""
        if parent:
            cats_text = parent.get_text(" ", strip=True)

        category = normalize_category(cats_text)

        logo = ""
        img = a.find("img")
        if not img and parent:
            img = parent.find("img")
        if img:
            logo = img.get("src") or img.get("data-src") or img.get("data-lazy-src") or ""
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

    return channels


def scrape_all_channels() -> list[dict]:
    """Pagina o endpoint tv_paises_list_load.php até não retornar mais canais."""
    all_channels = []
    seen_slugs = set()
    next_page = 1
    max_pages = 80  # 938 canais / ~15 por página ≈ 63 páginas

    print("[*] Iniciando coleta de TODOS os canais via endpoint de paginação...")

    while next_page <= max_pages:
        params = {
            "paisurl": "tvs-brasil",
            "short": "mo",
            "next": next_page,
        }
        try:
            r = scraper.get(LOAD_URL, params=params, timeout=20)
            if r.status_code != 200:
                print(f"[!] Página {next_page}: HTTP {r.status_code}")
                break

            html = r.text.strip()
            if not html or len(html) < 50:
                print(f"[*] Página {next_page}: vazia — fim da listagem")
                break

            batch = parse_channel_cards(html)
            if not batch:
                print(f"[*] Página {next_page}: nenhum canal parseado — fim")
                break

            new_count = 0
            for ch in batch:
                if ch["slug"] not in seen_slugs:
                    seen_slugs.add(ch["slug"])
                    all_channels.append(ch)
                    new_count += 1

            print(f"[*] Página {next_page}: +{new_count} canais (total acumulado: {len(all_channels)})")

            if new_count == 0:
                break

            next_page += 1
            time.sleep(0.4)

        except Exception as e:
            print(f"[!] Erro na página {next_page}: {e}")
            break

    print(f"[*] Total de canais únicos encontrados: {len(all_channels)}")
    return all_channels


def scrape_channel_list() -> list[dict]:
    channels = scrape_all_channels()

    if not channels:
        print("[!] Nenhum canal encontrado. Tentando fallback na página principal...")
        try:
            r = scraper.get(LIST_URL, timeout=20)
            if r.status_code == 200:
                channels = parse_channel_cards(r.text)
        except Exception:
            pass

    print("[*] Extraindo streams das páginas individuais dos canais...")
    def process(ch):
        stream = extract_stream_from_channel_page(ch["url"])
        ch["stream"] = stream
        return ch

    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as exe:
        channels = list(exe.map(process, channels))

    with_stream = [c for c in channels if c.get("stream")]
    print(f"[*] {len(with_stream)} canais com stream extraído de {len(channels)} totais")
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

    print("[*] Verificando quais streams estão ativos...")
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

    print(f"[*] Total final de canais ativos na lista: {len(final)}")

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
        slug = ch.get("slug", "")

        extinf = (
            f'#EXTINF:-1 tvg-id="{slug}" '
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
