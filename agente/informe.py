"""Informe semanal comparativo (lo ejecuta GitHub Actions los domingos)."""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import timedelta
from statistics import mean

from . import almacen, config, entorno, ia as modulo_ia
from .notificar import esc, notificar, telegram
from .rutas import DIR_INFORMES

MAX_CARACTERES_PROMPT = 400_000


def estadisticas(registros: list[dict]) -> dict:
    por_tema, por_canal, por_region = defaultdict(list), defaultdict(list), defaultdict(list)
    for reg in registros:
        r = reg["resumen"]
        por_canal[reg["canal"]].append(r["puntuacion_sentimiento"])
        por_region[reg.get("region") or "?"].append(r["puntuacion_sentimiento"])
        for s in r["sentimiento_por_tema"]:
            por_tema[s["tema"]].append((s["puntuacion"], reg["canal"]))
    temas = []
    for tema, valores in por_tema.items():
        puntos = [v for v, _ in valores]
        temas.append({"tema": tema, "menciones": len(puntos), "media": mean(puntos),
                      "min": min(puntos), "max": max(puntos),
                      "canales": sorted({c for _, c in valores})})
    temas.sort(key=lambda t: t["menciones"], reverse=True)
    return {
        "videos": len(registros),
        "media_global": mean(r["resumen"]["puntuacion_sentimiento"] for r in registros),
        "temas": temas,
        "canales": sorted(((c, mean(v), len(v)) for c, v in por_canal.items()), key=lambda x: x[1]),
        "regiones": {k: mean(v) for k, v in por_region.items()},
    }


def texto_estadisticas(est: dict) -> str:
    lineas = [f"Vídeos analizados: {est['videos']}",
              f"Sentimiento medio global: {est['media_global']:+.2f}", "",
              "Por tema (menciones, media, rango):"]
    for t in est["temas"][:15]:
        lineas.append(f"- {t['tema']}: {t['menciones']} menciones, media {t['media']:+.2f}, "
                      f"rango {t['min']:+.1f} a {t['max']:+.1f} ({', '.join(t['canales'])})")
    lineas += ["", "Por canal (media, vídeos):"]
    lineas += [f"- {c}: {m:+.2f} ({n})" for c, m, n in est["canales"]]
    lineas += ["", "Por región:"] + [f"- {k}: {v:+.2f}" for k, v in est["regiones"].items()]
    return "\n".join(lineas)


def bloque_resumenes(registros: list[dict]) -> str:
    partes = []
    for reg in registros:
        r = reg["resumen"]
        partes.append(json.dumps({
            "canal": reg["canal"], "region": reg.get("region"),
            "fecha": (reg.get("fecha_publicacion") or "")[:10], "titulo": reg["titulo"],
            "tesis": r["tesis_principal"], "ideas": r["ideas_clave"],
            "sentimiento": r["sentimiento_general"], "puntuacion": r["puntuacion_sentimiento"],
            "por_tema": [(s["tema"], s["puntuacion"]) for s in r["sentimiento_por_tema"]],
            "predicciones": [(p["afirmacion"], p["horizonte"]) for p in r["predicciones"]],
            "riesgos": r["riesgos_mencionados"],
        }, ensure_ascii=False))
    return "\n".join(partes)[:MAX_CARACTERES_PROMPT]


def mensaje_cabecera(est: dict, desde: str, hasta: str) -> str:
    def color(v: float) -> str:
        return "🟢" if v > 0.2 else "🔴" if v < -0.2 else "⚪"
    p = [f"📊 <b>Informe semanal</b> · {desde} → {hasta}",
         f"{est['videos']} vídeos · sentimiento medio {color(est['media_global'])} "
         f"<b>{est['media_global']:+.2f}</b>",
         "<b>Temas más tratados</b>\n" + "\n".join(
             f"{color(t['media'])} {esc(t['tema'])}: {t['media']:+.2f} ({t['menciones']})"
             for t in est["temas"][:10]),
         "<b>Canales más alcistas</b>\n" + "\n".join(
             f"🟢 {esc(c)}: {m:+.2f}" for c, m, _ in reversed(est["canales"][-3:])),
         "<b>Canales más bajistas</b>\n" + "\n".join(
             f"🔴 {esc(c)}: {m:+.2f}" for c, m, _ in est["canales"][:3])]
    return "\n\n".join(p)


def generar(dias: int = 7) -> None:
    cfg = config.cargar()
    registros = sorted(almacen.listar_resumenes(dias=dias, solo_mercados=True),
                       key=lambda r: r.get("fecha_publicacion", ""))
    if len(registros) < 2:
        telegram(f"📊 Informe semanal: solo hay {len(registros)} resumen(es) en los "
                 f"últimos {dias} días; no hay suficiente para comparar.")
        return
    est = estadisticas(registros)
    hasta = almacen.ahora_utc()
    desde = hasta - timedelta(days=dias)
    texto_est = texto_estadisticas(est)
    from .esquemas import prompt_informe  # noqa: PLC0415
    analisis = modulo_ia.crear(cfg).generar(
        prompt_informe(bloque_resumenes(registros), texto_est, cfg["idioma_resumen"]))
    semana = hasta.strftime("%G-S%V")
    DIR_INFORMES.mkdir(parents=True, exist_ok=True)
    with open(DIR_INFORMES / f"{semana}.md", "w", encoding="utf-8") as f:
        f.write(f"# Informe {semana} ({desde:%Y-%m-%d} a {hasta:%Y-%m-%d})\n\n")
        f.write("## Estadísticas\n\n```\n" + texto_est + "\n```\n\n## Análisis\n\n" + analisis + "\n")
    with open(DIR_INFORMES / f"{semana}.json", "w", encoding="utf-8") as f:
        json.dump(est, f, ensure_ascii=False, indent=2)
    notificar(f"Informe semanal {semana}",
              mensaje_cabecera(est, f"{desde:%d/%m}", f"{hasta:%d/%m}") + "\n\n" + esc(analisis))
    print("Informe enviado.")


def main(argv: list[str] | None = None) -> None:
    entorno.cargar()
    ap = argparse.ArgumentParser()
    ap.add_argument("--dias", type=int, default=7)
    generar(ap.parse_args(argv).dias)
