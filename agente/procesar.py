"""Resumir un vídeo (desde su transcript si existe, si no viendo el vídeo)."""
from __future__ import annotations

from . import almacen, transcripts
from .notificar import esc

EMOJI = {"muy bajista": "🔴🔴", "bajista": "🔴", "neutral": "⚪",
         "alcista": "🟢", "muy alcista": "🟢🟢"}

# Por encima de esto (≈ 3 h de vídeo hablado) se recorta el transcript.
MAX_CARACTERES_TRANSCRIPT = 180_000


def resumir(item: dict, cfg: dict, ia, canal: dict | None = None,
            permitir_video: bool = True) -> dict:
    """item: {video_id, titulo, canal, url, publicado}. Guarda y devuelve el registro."""
    canal = canal or {}
    t = transcripts.cargar(item["video_id"])
    if t:
        texto = transcripts.texto_con_marcas(t)[:MAX_CARACTERES_TRANSCRIPT]
        resumen = ia.resumir_texto(texto, item.get("titulo") or t.get("titulo", ""),
                                   item.get("canal") or t.get("canal", ""), cfg["idioma_resumen"])
        fuente = "transcript"
    elif permitir_video:
        resumen = ia.resumir_video(item["url"], item.get("titulo", ""), item.get("canal", ""),
                                   cfg["idioma_resumen"], cfg["fps_video"])
        fuente = "video"
    else:
        raise ValueError("Este vídeo no tiene transcript descargado")
    registro = {
        "video_id": item["video_id"], "url": item["url"],
        "titulo": item.get("titulo") or (t or {}).get("titulo", ""),
        "canal": item.get("canal") or (t or {}).get("canal", ""),
        "handle": canal.get("handle", ""), "idioma_canal": canal.get("idioma", ""),
        "region": canal.get("region", ""), "tipo_canal": canal.get("tipo", ""),
        "fecha_publicacion": item.get("publicado") or (t or {}).get("fecha_publicacion", ""),
        "fecha_resumen": almacen.ahora_utc().isoformat(), "modelo": getattr(ia, "modelo", ""),
        "fuente": fuente, "resumen": resumen,
    }
    almacen.guardar_resumen(registro)
    return registro


def formatear_mensaje(reg: dict) -> str:
    r = reg["resumen"]
    fecha = (reg.get("fecha_publicacion") or "")[:10]
    fuente = " · 📝 transcript" if reg.get("fuente") == "transcript" else ""
    p = [f"📺 <b>{esc(reg['titulo'])}</b>\n<i>{esc(reg['canal'])} · {fecha}{fuente}</i>",
         f"{EMOJI.get(r['sentimiento_general'], '')} Sentimiento: <b>{esc(r['sentimiento_general'])}</b> "
         f"({r['puntuacion_sentimiento']:+.1f}) · Convicción: {esc(r['nivel_conviccion'])}",
         esc(r["resumen_breve"]),
         "<b>Ideas clave</b>\n" + "\n".join(f"• {esc(i)}" for i in r["ideas_clave"]),
         f"<b>Tesis</b>\n{esc(r['tesis_principal'])}"]
    if r["sentimiento_por_tema"]:
        p.append("<b>Por tema</b>\n" + "\n".join(
            f"{EMOJI.get(s['sentimiento'], '')} {esc(s['tema'])} ({s['puntuacion']:+.1f})"
            for s in r["sentimiento_por_tema"]))
    if r["predicciones"]:
        p.append("<b>Predicciones</b>\n" + "\n".join(
            f"• {esc(x['afirmacion'])} <i>({esc(x['horizonte'])})</i>" for x in r["predicciones"]))
    if r["riesgos_mencionados"]:
        p.append("<b>Riesgos</b>\n" + "\n".join(f"• {esc(x)}" for x in r["riesgos_mencionados"]))
    p.append(f"🏷 {esc(', '.join(r['temas']))}\n🔗 {esc(reg['url'])}")
    return "\n\n".join(p)
