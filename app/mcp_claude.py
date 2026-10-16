"""Servidor MCP: conecta tus vídeos, transcripts y resúmenes con Claude.

La app de escritorio de Claude lo arranca sola (ver windows/configurar_claude.py).
Después puedes pedirle a Claude, por ejemplo:
  "Compara lo que dicen Cárpatos y Los Locos de Wall Street sobre la Fed esta semana"

Importante: en un servidor MCP por stdio no se puede imprimir nada en la salida
estándar; los mensajes de diagnóstico van a stderr.
"""
from __future__ import annotations

import contextlib
import functools
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

with contextlib.redirect_stdout(sys.stderr):
    from agente import (almacen, analisis, canales, config, entorno, informe,  # noqa: E402
                        sync, transcripts, youtube)

try:
    from mcp.server.mcpserver import MCPServer as Servidor  # mcp 2.x
except ImportError:  # pragma: no cover
    from mcp.server.fastmcp import FastMCP as Servidor  # mcp 1.x

INSTRUCCIONES = """Datos del usuario sobre vídeos de YouTube de economía, inversión y mercados:
canales seguidos, transcripts descargados (texto completo), resúmenes estructurados con
sentimiento por tema (-1 muy bajista a +1 muy alcista) y análisis anteriores.
Flujo típico para comparar vídeos: buscar_videos o videos_recientes -> leer_transcript /
leer_resumen de los relevantes -> razonar -> (opcional) guardar_analisis con las conclusiones.
Si un vídeo no tiene transcript, descargar_transcripts lo baja (desde el ordenador del usuario).
Atribuye siempre las ideas a su canal y no inventes datos que no estén en el contenido."""

mcp = Servidor("agente-youtube", instructions=INSTRUCCIONES)


def _salida(func):
    """Evita que cualquier print de la librería rompa el protocolo stdio."""
    @functools.wraps(func)
    def envoltura(*a, **k):
        with contextlib.redirect_stdout(sys.stderr):
            return func(*a, **k)
    return envoltura


@mcp.tool()
@_salida
def listar_canales() -> list[dict]:
    """Lista los canales configurados. 'activo' = se resumen automáticamente cada 3 h;
    si es false están en pausa (solo bajo demanda)."""
    return [{"nombre": c["nombre"], "handle": c.get("handle"), "channel_id": c.get("channel_id"),
             "region": c.get("region"), "idioma": c.get("idioma"), "tipo": c.get("tipo"),
             "activo": c.get("activo", True)} for c in canales.listar()]


@mcp.tool()
@_salida
def videos_recientes(canal: str, incluir_estado: bool = True) -> list[dict]:
    """Últimos ~15 vídeos publicados por un canal (nombre, @handle o ID), con si ya tienen
    transcript o resumen guardado."""
    cfg = config.cargar()
    c = canales.buscar(cfg, canal)
    cid = c.get("channel_id") if c else None
    if not cid:
        cid = youtube.info_canal(canal)["channel_id"]
    salida = []
    for v in youtube.listar_videos(cid, 15, (c or {}).get("idioma") or ""):
        if v["es_short"]:
            continue
        d = {"video_id": v["video_id"], "titulo": v["titulo"], "publicado": v["publicado"],
             "canal": c["nombre"] if c else canal}
        if incluir_estado:
            d["tiene_transcript"] = transcripts.existe(v["video_id"])
            d["tiene_resumen"] = almacen.existe_resumen(v["video_id"])
        salida.append(d)
    return salida


@mcp.tool()
@_salida
def buscar_videos(texto: str = "", canal: str = "", dias: int = 30) -> list[dict]:
    """Busca entre los vídeos GUARDADOS (con transcript o resumen) por texto en título, tema,
    tesis o ideas. Filtra por canal y por antigüedad en días (0 = sin límite)."""
    q = texto.lower().strip()
    vistos: dict[str, dict] = {}
    for reg in almacen.listar_resumenes(dias=dias or None, canal=canal or None):
        r = reg["resumen"]
        pajar = " ".join([reg.get("titulo", ""), reg.get("canal", ""), r["tesis_principal"],
                          " ".join(r["temas"]), " ".join(r["ideas_clave"])]).lower()
        if q and q not in pajar:
            continue
        vistos[reg["video_id"]] = {
            "video_id": reg["video_id"], "titulo": reg["titulo"], "canal": reg["canal"],
            "fecha": (reg.get("fecha_publicacion") or "")[:10], "temas": r["temas"],
            "sentimiento": r["sentimiento_general"], "puntuacion": r["puntuacion_sentimiento"],
            "tesis": r["tesis_principal"], "tiene_transcript": transcripts.existe(reg["video_id"])}
    desde = almacen.ahora_utc().timestamp() - dias * 86400 if dias else None
    for t in transcripts.listar():
        if t["video_id"] in vistos:
            continue
        if canal and canal.lower() not in t.get("canal", "").lower():
            continue
        f = almacen.parse_fecha(t.get("fecha_publicacion") or t.get("fecha_descarga"))
        if desde and (not f or f.timestamp() < desde):
            continue
        if q and q not in (t.get("titulo", "") + " " + t.get("canal", "")).lower():
            continue
        vistos[t["video_id"]] = {"video_id": t["video_id"], "titulo": t.get("titulo"),
                                 "canal": t.get("canal"), "fecha": (t.get("fecha_publicacion") or "")[:10],
                                 "tiene_transcript": True, "sin_resumen": True}
    return sorted(vistos.values(), key=lambda d: d.get("fecha") or "", reverse=True)[:100]


@mcp.tool()
@_salida
def leer_resumen(video_id: str) -> dict:
    """Resumen estructurado de un vídeo: ideas clave, tesis, sentimiento general y por tema,
    predicciones, datos, riesgos y participantes."""
    reg = almacen.cargar_resumen(video_id)
    if not reg:
        return {"error": "Este vídeo no tiene resumen guardado"}
    return reg


@mcp.tool()
@_salida
def leer_transcript(video_id: str, desde_caracter: int = 0, max_caracteres: int = 60000) -> dict:
    """Texto completo del vídeo (subtítulos) con marcas [mm:ss]. Para vídeos largos, pide más
    trozos usando desde_caracter con el valor 'siguiente' devuelto."""
    t = transcripts.cargar(video_id)
    if not t:
        return {"error": "Sin transcript. Usa descargar_transcripts primero."}
    texto = transcripts.texto_con_marcas(t)
    trozo = texto[desde_caracter:desde_caracter + max_caracteres]
    fin = desde_caracter + len(trozo)
    return {"video_id": video_id, "titulo": t.get("titulo"), "canal": t.get("canal"),
            "fecha": t.get("fecha_publicacion"), "idioma": t.get("idioma"),
            "subtitulos_automaticos": t.get("es_automatico"), "caracteres_totales": len(texto),
            "texto": trozo, "siguiente": fin if fin < len(texto) else None}


@mcp.tool()
@_salida
def descargar_transcripts(videos: list[str]) -> list[dict]:
    """Descarga los transcripts de una lista de vídeos (IDs o URLs de YouTube) y los guarda.
    Funciona porque se ejecuta en el ordenador del usuario."""
    cfg = config.cargar()
    idioma_por_canal = {c["nombre"]: c.get("idioma") for c in cfg["canales"]}
    salida = []
    for entrada in videos:
        vid = youtube.extraer_id_video(entrada)
        if not vid:
            salida.append({"entrada": entrada, "ok": False, "error": "No es un vídeo de YouTube"})
            continue
        try:
            meta = youtube.info_video(vid)
            t = transcripts.descargar(vid, [idioma_por_canal.get(meta.get("canal"), "")], meta)
            salida.append({"video_id": vid, "ok": True, "titulo": t.get("titulo"),
                           "palabras": t.get("palabras")})
        except transcripts.ErrorTranscript as e:
            salida.append({"video_id": vid, "ok": False, "error": str(e)})
    if any(s["ok"] for s in salida):
        sync.subir_en_segundo_plano("Claude: transcripts descargados")
    return salida


@mcp.tool()
@_salida
def sentimiento_por_tema(dias: int = 7, tema: str = "") -> dict:
    """Estadísticas de sentimiento de los resúmenes de los últimos días: media por tema,
    por canal y por región (escala -1 a +1). Opcionalmente filtra un tema."""
    regs = almacen.listar_resumenes(dias=dias, solo_mercados=True)
    if not regs:
        return {"videos": 0}
    est = informe.estadisticas(regs)
    if tema:
        est["temas"] = [t for t in est["temas"] if tema.lower() in t["tema"].lower()]
    est["canales"] = [{"canal": c, "media": round(m, 2), "videos": n} for c, m, n in est["canales"]]
    return est


@mcp.tool()
@_salida
def listar_analisis() -> list[dict]:
    """Análisis comparativos guardados anteriormente (de Gemini o de Claude)."""
    return almacen.listar_analisis()


@mcp.tool()
@_salida
def leer_analisis(id_analisis: str) -> dict:
    """Contenido completo de un análisis guardado."""
    return almacen.cargar_analisis(id_analisis) or {"error": "No existe"}


@mcp.tool()
@_salida
def guardar_analisis(titulo: str, contenido_markdown: str, video_ids: list[str],
                     peticion: str = "") -> dict:
    """Guarda tus conclusiones en la biblioteca del usuario (se verán en la app web y en GitHub)."""
    videos = []
    for vid in video_ids:
        info = analisis.info_basica(vid)
        videos.append({"video_id": vid, "titulo": info.get("titulo", ""),
                       "canal": info.get("canal", ""),
                       "fuente": "transcript" if transcripts.existe(vid) else "resumen"})
    res = almacen.guardar_analisis(titulo, contenido_markdown, videos, peticion, autor="Claude")
    sync.subir_en_segundo_plano(f"Claude: análisis «{titulo}»")
    return {"ok": True, "id": res["id"]}


@mcp.tool()
@_salida
def configurar_canal(canal: str, activo: bool) -> dict:
    """Activa (resumen automático cada 3 h) o pone en pausa un canal existente."""
    c = canales.actualizar(canal, activo=activo)
    sync.subir_en_segundo_plano(f"Claude: canal {c['nombre']} {'activado' if activo else 'en pausa'}")
    return {"ok": True, "canal": c["nombre"], "activo": c["activo"]}


@mcp.tool()
@_salida
def anadir_canal(entrada: str, idioma: str = "es", region: str = "", tipo: str = "",
                 activo: bool = False) -> dict:
    """Añade un canal a la lista (@handle, URL o ID). Por defecto queda en pausa."""
    c = canales.anadir(entrada, idioma, region, tipo, activo)
    sync.subir_en_segundo_plano(f"Claude: canal añadido ({c['nombre']})")
    return {"ok": True, "canal": c}


def main():
    entorno.cargar()
    mcp.run()


if __name__ == "__main__":
    main()
