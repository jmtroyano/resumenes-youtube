"""Almacenamiento en archivos del repositorio.

Toda la persistencia pasa por aquí: si algún día se migra a una base de datos,
solo hay que cambiar este módulo.

Reparto para evitar conflictos al sincronizar con GitHub:
  - GitHub Actions escribe: state/, data/resumenes/ (automáticos), data/informes/, CSVs
  - La app local escribe: config.yaml, transcripts/, data/resumenes/ (manuales), data/analisis/
Cada resumen es un archivo propio, así que nunca chocan.
"""
from __future__ import annotations

import csv
import json
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .bloqueo import repo as _bloqueo
from .rutas import (CSV_RESUMENES, CSV_SENTIMIENTO, DIR_ANALISIS, DIR_RESUMENES,
                    RUTA_ESTADO)


def ahora_utc() -> datetime:
    return datetime.now(timezone.utc)


def slug(texto: str, largo: int = 50) -> str:
    t = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode()
    t = re.sub(r"[^a-zA-Z0-9]+", "-", t).strip("-").lower()
    return t[:largo] or "sin-titulo"


def parse_fecha(valor: str | None) -> datetime | None:
    if not valor:
        return None
    try:
        f = datetime.fromisoformat(valor.replace("Z", "+00:00"))
        return f if f.tzinfo else f.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


# ------------------------------------------------------------------ estado
def estado_vacio() -> dict:
    return {"ids_canales": {}, "canales_vistos": [], "avisos_canal": [],
            "procesados": {}, "cola": [], "fallidos": {}, "aviso_config": None}


def cargar_estado() -> dict:
    base = estado_vacio()
    if RUTA_ESTADO.exists():
        with open(RUTA_ESTADO, encoding="utf-8") as f:
            base.update(json.load(f))
    return base


def guardar_estado(estado: dict) -> None:
    RUTA_ESTADO.parent.mkdir(parents=True, exist_ok=True)
    tmp = RUTA_ESTADO.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(estado, f, ensure_ascii=False, indent=1)
    tmp.replace(RUTA_ESTADO)


# ------------------------------------------------------------------ resúmenes
def ruta_resumen(registro: dict) -> Path:
    fecha = (registro.get("fecha_publicacion") or registro["fecha_resumen"])[:10]
    return DIR_RESUMENES / fecha[:4] / fecha[5:7] / f"{fecha}_{registro['video_id']}.json"


def buscar_ruta_resumen(video_id: str) -> Path | None:
    if not DIR_RESUMENES.exists():
        return None
    for ruta in DIR_RESUMENES.rglob(f"*_{video_id}.json"):
        return ruta
    return None


def existe_resumen(video_id: str) -> bool:
    return buscar_ruta_resumen(video_id) is not None


def cargar_resumen(video_id: str) -> dict | None:
    ruta = buscar_ruta_resumen(video_id)
    if not ruta:
        return None
    with open(ruta, encoding="utf-8") as f:
        return json.load(f)


def guardar_resumen(registro: dict) -> Path:
    ruta = ruta_resumen(registro)
    with _bloqueo:
        ruta.parent.mkdir(parents=True, exist_ok=True)
        with open(ruta, "w", encoding="utf-8") as f:
            json.dump(registro, f, ensure_ascii=False, indent=2)
    return ruta


def listar_resumenes(dias: int | None = None, canal: str | None = None,
                     solo_mercados: bool = False) -> list[dict]:
    if not DIR_RESUMENES.exists():
        return []
    desde = ahora_utc() - timedelta(days=dias) if dias else None
    canal_l = (canal or "").lower()
    salida = []
    for ruta in DIR_RESUMENES.rglob("*.json"):
        try:
            with open(ruta, encoding="utf-8") as f:
                reg = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        if canal_l and canal_l not in (reg.get("canal", "").lower(), reg.get("handle", "").lower()):
            continue
        if desde:
            fecha = parse_fecha(reg.get("fecha_publicacion")) or parse_fecha(reg.get("fecha_resumen"))
            if not fecha or fecha < desde:
                continue
        if solo_mercados and not reg["resumen"].get("es_contenido_de_mercados", True):
            continue
        salida.append(reg)
    return sorted(salida, key=lambda r: r.get("fecha_publicacion", ""), reverse=True)


COLUMNAS_CSV = ["video_id", "fecha_publicacion", "fecha_resumen", "canal", "idioma_canal",
                "region", "tipo_canal", "titulo", "url", "fuente", "sentimiento_general",
                "puntuacion_sentimiento", "nivel_conviccion", "temas", "activos_mencionados",
                "tesis_principal", "resumen_breve", "ideas_clave", "num_predicciones",
                "es_contenido_de_mercados"]
COLUMNAS_SENT = ["video_id", "fecha_publicacion", "canal", "region", "tema",
                 "sentimiento", "puntuacion", "justificacion"]


def regenerar_csv() -> int:
    """Reconstruye los CSV a partir de todos los JSON (orden estable)."""
    registros = sorted(listar_resumenes(), key=lambda r: (r.get("fecha_publicacion", ""),
                                                          r["video_id"]))
    filas, filas_sent = [], []
    for reg in registros:
        r = reg["resumen"]
        filas.append({
            "video_id": reg["video_id"], "fecha_publicacion": reg.get("fecha_publicacion", ""),
            "fecha_resumen": reg.get("fecha_resumen", ""), "canal": reg.get("canal", ""),
            "idioma_canal": reg.get("idioma_canal", ""), "region": reg.get("region", ""),
            "tipo_canal": reg.get("tipo_canal", ""), "titulo": reg.get("titulo", ""),
            "url": reg.get("url", ""), "fuente": reg.get("fuente", "video"),
            "sentimiento_general": r["sentimiento_general"],
            "puntuacion_sentimiento": r["puntuacion_sentimiento"],
            "nivel_conviccion": r["nivel_conviccion"], "temas": " | ".join(r["temas"]),
            "activos_mencionados": " | ".join(r["activos_mencionados"]),
            "tesis_principal": r["tesis_principal"], "resumen_breve": r["resumen_breve"],
            "ideas_clave": " | ".join(r["ideas_clave"]),
            "num_predicciones": len(r["predicciones"]),
            "es_contenido_de_mercados": r["es_contenido_de_mercados"],
        })
        for s in r["sentimiento_por_tema"]:
            filas_sent.append({
                "video_id": reg["video_id"], "fecha_publicacion": reg.get("fecha_publicacion", ""),
                "canal": reg.get("canal", ""), "region": reg.get("region", ""),
                "tema": s["tema"], "sentimiento": s["sentimiento"],
                "puntuacion": s["puntuacion"], "justificacion": s["justificacion"]})
    for ruta, columnas, datos in ((CSV_RESUMENES, COLUMNAS_CSV, filas),
                                  (CSV_SENTIMIENTO, COLUMNAS_SENT, filas_sent)):
        ruta.parent.mkdir(parents=True, exist_ok=True)
        with open(ruta, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=columnas)
            w.writeheader()
            w.writerows(datos)
    return len(filas)


# ------------------------------------------------------------------ análisis
def guardar_analisis(titulo: str, markdown: str, videos: list[dict], instruccion: str,
                     autor: str = "gemini") -> dict:
    ahora = ahora_utc()
    ident = f"{ahora:%Y-%m-%d_%H%M%S}_{slug(titulo, 40)}"
    meta = {"id": ident, "titulo": titulo, "fecha": ahora.isoformat(), "autor": autor,
            "instruccion": instruccion, "videos": videos}
    cabecera = [f"# {titulo}", "", f"*{ahora:%Y-%m-%d %H:%M} UTC · autor: {autor}*", "",
                "**Vídeos analizados:**", ""]
    cabecera += [f"- {v.get('canal', '')} — [{v.get('titulo', v['video_id'])}]"
                 f"(https://www.youtube.com/watch?v={v['video_id']}) ({v.get('fuente', '')})"
                 for v in videos]
    cabecera += ["", f"**Petición:** {instruccion}", "", "---", ""]
    with _bloqueo:
        DIR_ANALISIS.mkdir(parents=True, exist_ok=True)
        (DIR_ANALISIS / f"{ident}.md").write_text("\n".join(cabecera) + markdown + "\n",
                                                  encoding="utf-8")
        with open(DIR_ANALISIS / f"{ident}.json", "w", encoding="utf-8") as f:
            json.dump({**meta, "markdown": markdown}, f, ensure_ascii=False, indent=2)
    return {**meta, "markdown": markdown}


def listar_analisis() -> list[dict]:
    if not DIR_ANALISIS.exists():
        return []
    salida = []
    for ruta in DIR_ANALISIS.glob("*.json"):
        try:
            with open(ruta, encoding="utf-8") as f:
                d = json.load(f)
            d.pop("markdown", None)
            salida.append(d)
        except (OSError, json.JSONDecodeError):
            continue
    return sorted(salida, key=lambda d: d.get("fecha", ""), reverse=True)


def cargar_analisis(ident: str) -> dict | None:
    ruta = DIR_ANALISIS / f"{Path(ident).name}.json"
    if not ruta.exists():
        return None
    with open(ruta, encoding="utf-8") as f:
        return json.load(f)
