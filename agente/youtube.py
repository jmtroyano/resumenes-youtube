"""Acceso público a YouTube: canales, feeds RSS y datos de vídeos (sin claves)."""
from __future__ import annotations

import html
import re
import xml.etree.ElementTree as ET

import requests

CABECERAS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
}
COOKIES = {"CONSENT": "YES+cb", "SOCS": "CAI"}
NS = {"a": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015",
      "media": "http://search.yahoo.com/mrss/"}

RE_ID_VIDEO = re.compile(r"(?:v=|youtu\.be/|shorts/|live/|embed/)([\w-]{11})")
RE_ID_CANAL = re.compile(r"(UC[\w-]{22})")


class ErrorYouTube(Exception):
    pass


def extraer_id_video(texto: str) -> str | None:
    texto = (texto or "").strip()
    m = RE_ID_VIDEO.search(texto)
    if m:
        return m.group(1)
    if re.fullmatch(r"[\w-]{11}", texto):
        return texto
    return None


def url_video(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


def miniatura(video_id: str) -> str:
    return f"https://i.ytimg.com/vi/{video_id}/mqdefault.jpg"


def _get(url: str, **kw) -> requests.Response:
    return requests.get(url, headers=CABECERAS, cookies=COOKIES, timeout=30, **kw)


def _url_canal(entrada: str) -> str:
    e = entrada.strip()
    if e.startswith("http"):
        return e.split("?")[0].rstrip("/")
    if e.startswith("@"):
        return f"https://www.youtube.com/{e}"
    m = RE_ID_CANAL.fullmatch(e)
    if m:
        return f"https://www.youtube.com/channel/{e}"
    return f"https://www.youtube.com/@{e}"


def info_canal(entrada: str) -> dict:
    """Resuelve @handle, URL o ID 'UC...' -> {channel_id, nombre, handle}."""
    url = _url_canal(entrada)
    try:
        r = _get(url)
    except requests.RequestException as e:
        raise ErrorYouTube(f"Error de red al abrir {url}: {e}") from e
    if r.status_code != 200:
        raise ErrorYouTube(f"YouTube devolvió {r.status_code} para {url}")
    t = r.text
    cid = None
    for patron in (r'<link rel="canonical" href="https://www\.youtube\.com/channel/(UC[\w-]{22})"',
                   r'"externalId":"(UC[\w-]{22})"',
                   r'<meta itemprop="identifier" content="(UC[\w-]{22})"'):
        m = re.search(patron, t)
        if m:
            cid = m.group(1)
            break
    if not cid:
        raise ErrorYouTube(f"No encuentro el canal {entrada}")
    m = re.search(r'<meta property="og:title" content="([^"]*)"', t)
    nombre = html.unescape(m.group(1)) if m else entrada
    handle = None
    for patron in (r'"vanityChannelUrl":"https?://www\.youtube\.com/(@[^"]+)"',
                   r'"canonicalBaseUrl":"/(@[^"]+)"',
                   r'<link itemprop="url" href="https?://www\.youtube\.com/(@[^"]+)"'):
        m = re.search(patron, t)
        if m:
            handle = requests.utils.unquote(m.group(1))
            break
    if not handle and entrada.strip().startswith("@"):
        handle = entrada.strip()
    return {"channel_id": cid, "nombre": nombre, "handle": handle}


def leer_feed(channel_id: str) -> list[dict]:
    """Últimos ~15 vídeos del canal (del más nuevo al más antiguo)."""
    r = _get(f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}")
    r.raise_for_status()
    raiz = ET.fromstring(r.content)
    videos = []
    for e in raiz.findall("a:entry", NS):
        vid = e.findtext("yt:videoId", default="", namespaces=NS)
        if not vid:
            continue
        enlace = e.find("a:link", NS)
        url = enlace.get("href") if enlace is not None else url_video(vid)
        desc = e.findtext("media:group/media:description", default="", namespaces=NS)
        videos.append({
            "video_id": vid,
            "titulo": e.findtext("a:title", default="", namespaces=NS),
            "url": url,
            "publicado": e.findtext("a:published", default="", namespaces=NS),
            "es_short": "/shorts/" in (url or ""),
            "descripcion": (desc or "")[:500],
        })
    return videos


def mas_videos(channel_id: str, limite: int = 50) -> list[dict]:
    """Lista más vídeos del canal con yt-dlp (solo en la app local)."""
    try:
        import yt_dlp  # noqa: PLC0415
    except ImportError as e:
        raise ErrorYouTube("yt-dlp no está instalado") from e
    opciones = {"extract_flat": True, "playlistend": limite, "quiet": True,
                "no_warnings": True, "skip_download": True}
    with yt_dlp.YoutubeDL(opciones) as ydl:
        info = ydl.extract_info(f"https://www.youtube.com/channel/{channel_id}/videos",
                                download=False)
    videos = []
    for e in (info or {}).get("entries") or []:
        vid = e.get("id")
        if not vid:
            continue
        videos.append({"video_id": vid, "titulo": e.get("title") or "",
                       "url": url_video(vid), "publicado": "",
                       "duracion": e.get("duration"), "es_short": False, "descripcion": ""})
    return videos


def info_video(video_id: str) -> dict:
    """Título y canal de un vídeo (oEmbed público)."""
    try:
        r = requests.get("https://www.youtube.com/oembed",
                         params={"url": url_video(video_id), "format": "json"},
                         headers=CABECERAS, timeout=20)
        if r.ok:
            d = r.json()
            return {"video_id": video_id, "titulo": d.get("title", ""),
                    "canal": d.get("author_name", ""), "url": url_video(video_id)}
    except requests.RequestException:
        pass
    return {"video_id": video_id, "titulo": "", "canal": "", "url": url_video(video_id)}
