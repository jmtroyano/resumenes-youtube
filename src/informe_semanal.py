"""Informe semanal: compara los resúmenes de los últimos días por tema y sentimiento.

Uso:
  python src/informe_semanal.py            # últimos 7 días
  python src/informe_semanal.py --dias 14  # otro periodo
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from statistics import mean

sys.path.insert(0, str(Path(__file__).resolve().parent))
import comun  # noqa: E402
from comun import esc  # noqa: E402
import gemini  # noqa: E402

MAX_CARACTERES_PROMPT = 400_000  # margen holgado dentro del contexto de Gemini


def _fecha(reg: dict) -> datetime | None:
    for campo in ("fecha_publicacion", "fecha_resumen"):
        valor = reg.get(campo)
        if valor:
            try:
                f = datetime.fromisoformat(valor.replace("Z", "+00:00"))
                return f if f.tzinfo else f.replace(tzinfo=comun.ahora_utc().tzinfo)
            except ValueError:
                continue
    return None


def cargar_periodo(dias: int) -> list[dict]:
    desde = comun.ahora_utc() - timedelta(days=dias)
    registros = []
    for ruta in comun.DIR_RESUMENES.rglob("*.json"):
        with open(ruta, encoding="utf-8") as f:
            reg = json.load(f)
        fecha = _fecha(reg)
        if fecha and fecha >= desde and reg["resumen"].get("es_contenido_de_mercados", True):
            registros.append(reg)
    return sorted(registros, key=lambda r: r.get("fecha_publicacion", ""))


def estadisticas(registros: list[dict]) -> dict:
    por_tema = defaultdict(list)
    por_canal = defaultdict(list)
    por_region = defaultdict(list)
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
        "canales": sorted(((c, mean(v), len(v)) for c, v in por_canal.items()),
                          key=lambda x: x[1]),
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
            "canal": reg["canal"], "region": reg.get("region"), "fecha": reg["fecha_publicacion"][:10],
            "titulo": reg["titulo"], "tesis": r["tesis_principal"], "ideas": r["ideas_clave"],
            "sentimiento": r["sentimiento_general"], "puntuacion": r["puntuacion_sentimiento"],
            "por_tema": [(s["tema"], s["puntuacion"]) for s in r["sentimiento_por_tema"]],
            "predicciones": [(p["afirmacion"], p["horizonte"]) for p in r["predicciones"]],
            "riesgos": r["riesgos_mencionados"],
        }, ensure_ascii=False))
    texto = "\n".join(partes)
    return texto[:MAX_CARACTERES_PROMPT]


def mensaje_cabecera(est: dict, desde: str, hasta: str) -> str:
    def barra(v: float) -> str:
        return "🟢" if v > 0.2 else "🔴" if v < -0.2 else "⚪"
    p = [f"📊 <b>Informe semanal</b> · {desde} → {hasta}",
         f"{est['videos']} vídeos · sentimiento medio {barra(est['media_global'])} "
         f"<b>{est['media_global']:+.2f}</b>",
         "<b>Temas más tratados</b>\n" + "\n".join(
             f"{barra(t['media'])} {esc(t['tema'])}: {t['media']:+.2f} ({t['menciones']})"
             for t in est["temas"][:10]),
         "<b>Canales más alcistas</b>\n" + "\n".join(
             f"🟢 {esc(c)}: {m:+.2f}" for c, m, _ in reversed(est["canales"][-3:])),
         "<b>Canales más bajistas</b>\n" + "\n".join(
             f"🔴 {esc(c)}: {m:+.2f}" for c, m, _ in est["canales"][:3])]
    return "\n\n".join(p)


def main(dias: int) -> None:
    cfg = comun.cargar_config()
    registros = cargar_periodo(dias)
    if len(registros) < 2:
        comun.enviar_telegram(f"📊 Informe semanal: solo hay {len(registros)} resumen(es) en los "
                              f"últimos {dias} días; no hay suficiente para comparar.")
        return
    est = estadisticas(registros)
    hasta = comun.ahora_utc()
    desde = hasta - timedelta(days=dias)
    texto_est = texto_estadisticas(est)

    analisis = gemini.generar_texto(
        gemini.prompt_informe(bloque_resumenes(registros), texto_est, cfg["idioma_resumen"]),
        cfg["modelo"])

    # Guardar el informe para consultas futuras
    semana = hasta.strftime("%G-S%V")
    comun.DIR_INFORMES.mkdir(parents=True, exist_ok=True)
    with open(comun.DIR_INFORMES / f"{semana}.md", "w", encoding="utf-8") as f:
        f.write(f"# Informe {semana} ({desde:%Y-%m-%d} a {hasta:%Y-%m-%d})\n\n")
        f.write("## Estadísticas\n\n```\n" + texto_est + "\n```\n\n## Análisis\n\n" + analisis + "\n")
    with open(comun.DIR_INFORMES / f"{semana}.json", "w", encoding="utf-8") as f:
        json.dump(est, f, ensure_ascii=False, indent=2)

    cabecera = mensaje_cabecera(est, f"{desde:%d/%m}", f"{hasta:%d/%m}")
    comun.notificar(f"Informe semanal {semana}", cabecera + "\n\n" + esc(analisis))
    print("Informe enviado.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dias", type=int, default=7)
    main(ap.parse_args().dias)
