"""Análisis y comparación de varios vídeos con la IA."""
from __future__ import annotations

import json

from . import almacen, config, ia as modulo_ia, transcripts, youtube
from .esquemas import INSTRUCCION_ANALISIS_POR_DEFECTO, prompt_analisis

# Límite de texto enviado a la IA en un análisis (~150.000 tokens).
MAX_CARACTERES = 600_000


def _bloque_resumen(reg: dict) -> str:
    r = reg["resumen"]
    return json.dumps({
        "resumen": r["resumen_breve"], "tesis": r["tesis_principal"], "ideas": r["ideas_clave"],
        "sentimiento": f"{r['sentimiento_general']} ({r['puntuacion_sentimiento']:+.2f})",
        "por_tema": [f"{s['tema']}: {s['puntuacion']:+.1f} ({s['justificacion']})"
                     for s in r["sentimiento_por_tema"]],
        "predicciones": [f"{p['afirmacion']} ({p['horizonte']})" for p in r["predicciones"]],
        "datos": r["datos_y_argumentos"], "riesgos": r["riesgos_mencionados"],
    }, ensure_ascii=False, indent=1)


def construir_contexto(video_ids: list[str], modo: str = "auto",
                       max_caracteres: int = MAX_CARACTERES) -> tuple[str, list[dict], list[str]]:
    """modo: 'auto' (transcript completo si existe), 'transcript' o 'resumen'.
    Si no cabe todo, los transcripts más largos se sustituyen por su resumen o se recortan.
    Devuelve (texto, vídeos usados, avisos)."""
    avisos, piezas = [], []
    for vid in dict.fromkeys(video_ids):
        t = transcripts.cargar(vid)
        reg = almacen.cargar_resumen(vid)
        if not t and not reg:
            avisos.append(f"{vid}: sin transcript ni resumen, se omite")
            continue
        meta = t or reg
        if t and (modo != "resumen" or not reg):
            cuerpo, fuente = transcripts.texto_con_marcas(t), "transcript"
        else:
            cuerpo, fuente = _bloque_resumen(reg), "resumen"
        piezas.append({"vid": vid, "meta": meta, "reg": reg, "cuerpo": cuerpo, "fuente": fuente})

    def total() -> int:
        return sum(len(p["cuerpo"]) + 200 for p in piezas)

    # 1) Transcripts más largos -> su resumen, si lo tienen
    for p in sorted(piezas, key=lambda p: len(p["cuerpo"]), reverse=True):
        if total() <= max_caracteres:
            break
        if p["fuente"] == "transcript" and p["reg"]:
            p["cuerpo"], p["fuente"] = _bloque_resumen(p["reg"]), "resumen"
            avisos.append(f"{p['meta'].get('titulo', p['vid'])}: demasiado largo, se usa su resumen")
    # 2) Si aún no cabe, recorte proporcional de los transcripts
    exceso = total() - max_caracteres
    if exceso > 0:
        largos = [p for p in piezas if p["fuente"] == "transcript"]
        suma = sum(len(p["cuerpo"]) for p in largos) or 1
        for p in largos:
            quitar = int(exceso * len(p["cuerpo"]) / suma) + 1
            p["cuerpo"] = p["cuerpo"][: max(1000, len(p["cuerpo"]) - quitar)] + " [...recortado]"
            p["fuente"] = "transcript (recortado)"
            avisos.append(f"{p['meta'].get('titulo', p['vid'])}: transcript recortado por longitud")

    bloques, usados = [], []
    for p in piezas:
        m = p["meta"]
        bloques.append(f"=== VÍDEO: {m.get('canal', '')} | {(m.get('fecha_publicacion') or '')[:10]} | "
                       f"{m.get('titulo', '')} | id={p['vid']} | fuente: {p['fuente']} ===\n"
                       f"{p['cuerpo']}\n")
        usados.append({"video_id": p["vid"], "titulo": m.get("titulo", ""),
                       "canal": m.get("canal", ""), "fuente": p["fuente"],
                       "fecha_publicacion": m.get("fecha_publicacion", "")})
    return "\n".join(bloques), usados, avisos


def analizar(video_ids: list[str], instruccion: str = "", titulo: str = "",
             modo: str = "auto") -> dict:
    cfg = config.cargar()
    instruccion = (instruccion or "").strip() or INSTRUCCION_ANALISIS_POR_DEFECTO
    contexto, usados, avisos = construir_contexto(video_ids, modo)
    if not usados:
        raise ValueError("Ninguno de los vídeos elegidos tiene transcript ni resumen")
    texto = modulo_ia.crear(cfg).generar(prompt_analisis(instruccion, contexto,
                                                         cfg["idioma_resumen"]))
    titulo = titulo.strip() or f"Análisis de {len(usados)} vídeos"
    res = almacen.guardar_analisis(titulo, texto, usados, instruccion, autor=cfg["modelo"])
    res["avisos"] = avisos
    return res


def info_basica(video_id: str) -> dict:
    """Datos mínimos de un vídeo a partir de lo guardado, o de YouTube."""
    t = transcripts.cargar(video_id)
    if t:
        return {k: t.get(k) for k in ("video_id", "titulo", "canal", "url", "fecha_publicacion")}
    reg = almacen.cargar_resumen(video_id)
    if reg:
        return {k: reg.get(k) for k in ("video_id", "titulo", "canal", "url", "fecha_publicacion")}
    return youtube.info_video(video_id)
