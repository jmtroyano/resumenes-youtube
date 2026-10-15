"""Descarga y lectura de transcripciones (subtítulos) de YouTube.

La descarga solo funciona desde una conexión doméstica (tu ordenador): YouTube
bloquea las IPs de servidores en la nube. Leer transcripts ya guardados
funciona en cualquier sitio.
"""
from __future__ import annotations

import json

from . import youtube
from .almacen import ahora_utc
from .bloqueo import repo as _bloqueo
from .rutas import DIR_TRANSCRIPTS


class ErrorTranscript(Exception):
    pass


def ruta(video_id: str):
    return DIR_TRANSCRIPTS / f"{video_id}.json"


def existe(video_id: str) -> bool:
    return ruta(video_id).exists()


def cargar(video_id: str) -> dict | None:
    p = ruta(video_id)
    if not p.exists():
        return None
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def listar() -> list[dict]:
    """Metadatos de todos los transcripts guardados (sin el texto)."""
    if not DIR_TRANSCRIPTS.exists():
        return []
    salida = []
    for p in DIR_TRANSCRIPTS.glob("*.json"):
        try:
            with open(p, encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        d.pop("segmentos", None)
        d.pop("texto", None)
        salida.append(d)
    return sorted(salida, key=lambda d: d.get("fecha_publicacion") or d.get("fecha_descarga", ""),
                  reverse=True)


def _mmss(segundos: float) -> str:
    s = int(segundos)
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60:02d}:{s % 60:02d}"


def texto_con_marcas(t: dict, cada: int = 60) -> str:
    """Texto continuo con una marca [mm:ss] aproximadamente cada `cada` segundos."""
    partes, siguiente = [], 0.0
    for seg in t.get("segmentos", []):
        if seg["t"] >= siguiente:
            partes.append(f"\n[{_mmss(seg['t'])}] ")
            siguiente = seg["t"] + cada
        partes.append(seg["texto"].replace("\n", " ") + " ")
    return "".join(partes).strip() or t.get("texto", "")


def _elegir(lista, idiomas: list[str]):
    """Prefiere subtítulos manuales en los idiomas dados, luego automáticos, luego cualquiera."""
    disponibles = list(lista)
    for manual in (True, False):
        for idioma in idiomas:
            for tr in disponibles:
                if tr.is_generated != manual and tr.language_code.split("-")[0] == idioma:
                    return tr
    for manual in (True, False):
        for tr in disponibles:
            if tr.is_generated != manual:
                return tr
    raise ErrorTranscript("El vídeo no tiene subtítulos")


def descargar(video_id: str, idiomas: list[str] | None = None, meta: dict | None = None,
              forzar: bool = False) -> dict:
    """Descarga el transcript, lo guarda en transcripts/ y lo devuelve."""
    if existe(video_id) and not forzar:
        return cargar(video_id)
    try:
        from youtube_transcript_api import YouTubeTranscriptApi  # noqa: PLC0415
    except ImportError as e:
        raise ErrorTranscript("Falta la librería youtube-transcript-api") from e

    idiomas = [i for i in (idiomas or []) if i] + ["es", "en"]
    try:
        api = YouTubeTranscriptApi()
        lista = api.list(video_id) if hasattr(api, "list") else \
            YouTubeTranscriptApi.list_transcripts(video_id)
        elegido = _elegir(lista, idiomas)
        obtenido = elegido.fetch()
        crudo = obtenido.to_raw_data() if hasattr(obtenido, "to_raw_data") else obtenido
    except ErrorTranscript:
        raise
    except Exception as e:  # noqa: BLE001
        nombre = type(e).__name__
        mensajes = {
            "TranscriptsDisabled": "El vídeo tiene los subtítulos desactivados",
            "NoTranscriptFound": "El vídeo no tiene subtítulos",
            "VideoUnavailable": "El vídeo no está disponible",
            "RequestBlocked": "YouTube ha bloqueado la petición (demasiadas descargas seguidas; espera un rato)",
            "IpBlocked": "YouTube ha bloqueado temporalmente tu IP (espera un rato)",
            "AgeRestricted": "El vídeo tiene restricción de edad",
            "PoTokenRequired": "YouTube exige verificación para este vídeo",
        }
        raise ErrorTranscript(mensajes.get(nombre, f"{nombre}: {str(e)[:200]}")) from e

    segmentos = [{"t": round(float(s["start"]), 1), "d": round(float(s.get("duration", 0)), 1),
                  "texto": s["text"]} for s in crudo if s.get("text", "").strip()]
    meta = meta or {}
    if not meta.get("titulo"):
        meta = {**youtube.info_video(video_id), **{k: v for k, v in meta.items() if v}}
    datos = {
        "video_id": video_id,
        "url": youtube.url_video(video_id),
        "titulo": meta.get("titulo", ""),
        "canal": meta.get("canal", ""),
        "fecha_publicacion": meta.get("publicado") or meta.get("fecha_publicacion", ""),
        "fecha_descarga": ahora_utc().isoformat(),
        "idioma": elegido.language_code,
        "es_automatico": bool(elegido.is_generated),
        "duracion_segundos": int(segmentos[-1]["t"] + segmentos[-1]["d"]) if segmentos else 0,
        "palabras": sum(len(s["texto"].split()) for s in segmentos),
        "segmentos": segmentos,
    }
    with _bloqueo:
        DIR_TRANSCRIPTS.mkdir(parents=True, exist_ok=True)
        with open(ruta(video_id), "w", encoding="utf-8") as f:
            json.dump(datos, f, ensure_ascii=False, separators=(",", ":"))
    return datos
