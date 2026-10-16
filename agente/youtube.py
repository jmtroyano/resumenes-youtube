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
    r = requests.get(f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}",
                     headers=CABECERAS, timeout=20)
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


_UNIDADES = {"segundo": 1, "second": 1, "minuto": 60, "minute": 60, "hora": 3600, "hour": 3600,
             "día": 86400, "dia": 86400, "day": 86400, "semana": 604800, "week": 604800,
             "mes": 2592000, "month": 2592000, "año": 31536000, "ano": 31536000, "year": 31536000}


def _fecha_relativa(texto: str) -> str:
    """'hace 3 horas' / '3 hours ago' -> fecha ISO aproximada ('' si no se entiende)."""
    from datetime import datetime, timedelta, timezone  # noqa: PLC0415
    m = re.search(r"(\d+)\s+([a-zñí]+)", (texto or "").lower())
    if not m:
        return ""
    unidad = next((v for k, v in _UNIDADES.items() if m.group(2).startswith(k)), None)
    if not unidad:
        return ""
    cuando = datetime.now(timezone.utc) - timedelta(seconds=int(m.group(1)) * unidad)
    return cuando.isoformat(timespec="seconds")


def _iso_desde_entrada(e: dict) -> str:
    from datetime import datetime, timezone  # noqa: PLC0415
    for k in ("timestamp", "release_timestamp"):
        if e.get(k):
            return datetime.fromtimestamp(e[k], tz=timezone.utc).isoformat(timespec="seconds")
    if e.get("upload_date"):
        d = e["upload_date"]
        return f"{d[:4]}-{d[4:6]}-{d[6:8]}T00:00:00+00:00"
    return ""


def _ytdlp_entradas(channel_id: str, limite: int, idioma: str | None) -> list[dict]:
    try:
        import yt_dlp  # noqa: PLC0415
    except ImportError as e:
        raise ErrorYouTube("yt-dlp no está instalado") from e
    opciones = {"extract_flat": True, "playlistend": limite, "quiet": True,
                "no_warnings": True, "skip_download": True, "noprogress": True,
                "extractor_args": {"youtubetab": {"approximate_date": [""]}}}
    if idioma:  # sin idioma: configuración por defecto de yt-dlp (inglés, fechas fiables)
        opciones["extractor_args"]["youtube"] = {"lang": [idioma]}
        opciones["http_headers"] = {"Accept-Language": f"{idioma};q=1.0"}
    try:
        with yt_dlp.YoutubeDL(opciones) as ydl:
            info = ydl.extract_info(f"https://www.youtube.com/channel/{channel_id}/videos",
                                    download=False)
    except Exception as e:  # noqa: BLE001
        raise ErrorYouTube(f"yt-dlp: {str(e)[:200]}") from e
    return [e for e in (info or {}).get("entries") or [] if e.get("id")]


def videos_ytdlp(channel_id: str, limite: int = 15, idioma: str = "") -> list[dict]:
    """Lista los vídeos del canal con yt-dlp.
    Los títulos se piden en el idioma del canal (si no, YouTube los traduce) y las fechas
    aproximadas en inglés, que es el único idioma en que yt-dlp sabe calcularlas."""
    idioma = (idioma or "es").split("-")[0]
    entradas = _ytdlp_entradas(channel_id, limite, None if idioma == "en" else idioma)
    fechas = {e["id"]: _iso_desde_entrada(e) for e in entradas}
    if idioma != "en" and not any(fechas.values()):
        try:
            fechas = {e["id"]: _iso_desde_entrada(e) for e in _ytdlp_entradas(channel_id, limite, None)}
        except ErrorYouTube:
            pass
    videos = []
    for e in entradas:
        if e.get("live_status") in ("is_upcoming", "is_live"):
            continue
        vid = e["id"]
        videos.append({"video_id": vid, "titulo": e.get("title") or "", "url": url_video(vid),
                       "publicado": fechas.get(vid, ""), "duracion": e.get("duration"),
                       "es_short": False, "descripcion": (e.get("description") or "")[:500]})
    return videos[:limite]


def _recorrer(obj):
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from _recorrer(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _recorrer(v)


def videos_html(channel_id: str, limite: int = 15, idioma: str = "") -> list[dict]:
    """Último recurso: lee la página /videos del canal (sin dependencias)."""
    import json  # noqa: PLC0415
    r = _get(f"https://www.youtube.com/channel/{channel_id}/videos",
             params={"hl": idioma or "es"})
    if r.status_code != 200:
        raise ErrorYouTube(f"página del canal: HTTP {r.status_code}")
    m = re.search(r"var ytInitialData\s*=\s*(\{.*?\});\s*</script>", r.text, re.S)
    if not m:
        raise ErrorYouTube("página del canal sin datos")
    datos = json.loads(m.group(1))
    videos, vistos = [], set()
    for d in _recorrer(datos):
        vid = titulo = cuando = None
        if "videoRenderer" in d:
            v = d["videoRenderer"]
            vid = v.get("videoId")
            titulo = "".join(x.get("text", "") for x in v.get("title", {}).get("runs", []))
            cuando = (v.get("publishedTimeText") or {}).get("simpleText", "")
            if v.get("upcomingEventData"):
                continue
        elif "lockupViewModel" in d and d["lockupViewModel"].get("contentType", "").endswith("VIDEO"):
            v = d["lockupViewModel"]
            vid = v.get("contentId")
            meta = v.get("metadata", {}).get("lockupMetadataViewModel", {})
            titulo = meta.get("title", {}).get("content", "")
            textos = [p.get("text", {}).get("content", "") for f in
                      meta.get("metadata", {}).get("contentMetadataViewModel", {}).get("metadataRows", [])
                      for p in f.get("metadataParts", [])]
            cuando = next((t for t in textos if re.search(r"\d+\s+\w+", t) and ("hace" in t or "ago" in t)), "")
        if vid and vid not in vistos:
            vistos.add(vid)
            videos.append({"video_id": vid, "titulo": titulo or "", "url": url_video(vid),
                           "publicado": _fecha_relativa(cuando), "es_short": False, "descripcion": ""})
    if not videos:
        raise ErrorYouTube("no se encontraron vídeos en la página del canal")
    return videos[:limite]


def listar_videos(channel_id: str, limite: int = 15, idioma: str = "") -> list[dict]:
    """Vídeos recientes del canal: RSS (fechas exactas) -> yt-dlp -> página web.
    YouTube a veces deja de servir el RSS; por eso hay alternativas."""
    errores = []
    for metodo in (leer_feed, videos_ytdlp, videos_html):
        try:
            videos = metodo(channel_id) if metodo is leer_feed else metodo(channel_id, limite, idioma)
            if videos:
                return videos[:limite]
        except Exception as e:  # noqa: BLE001
            errores.append(f"{metodo.__name__}: {str(e)[:120]}")
    raise ErrorYouTube("No se pudieron listar los vídeos (" + " | ".join(errores) + ")")


def mas_videos(channel_id: str, limite: int = 50, idioma: str = "") -> list[dict]:
    """Más vídeos del canal (hasta `limite`)."""
    try:
        return videos_ytdlp(channel_id, limite, idioma)
    except ErrorYouTube:
        return videos_html(channel_id, limite, idioma)


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
