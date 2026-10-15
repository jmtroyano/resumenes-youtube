"""Agente de resúmenes de YouTube.

Uso:
  python src/resumir.py                      # ejecución normal (la que lanza GitHub)
  python src/resumir.py --comprobar-canales  # verifica que todos los canales se encuentran
  python src/resumir.py --prueba URL         # resume un vídeo concreto y lo envía
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

import feedparser
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
import comun  # noqa: E402
from comun import esc  # noqa: E402
import gemini  # noqa: E402

CABECERAS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
}
COOKIES = {"CONSENT": "YES+cb", "SOCS": "CAI"}
EMOJI = {"muy bajista": "🔴🔴", "bajista": "🔴", "neutral": "⚪",
         "alcista": "🟢", "muy alcista": "🟢🟢"}


# ------------------------------------------------------------------ canales
def resolver_id_canal(canal: dict, estado: dict) -> str | None:
    if canal.get("channel_id"):
        return canal["channel_id"]
    handle = canal.get("handle", "").strip()
    if not handle:
        return None
    if handle in estado["ids_canales"]:
        return estado["ids_canales"][handle]
    if not handle.startswith("@"):
        handle = "@" + handle
    try:
        r = requests.get(f"https://www.youtube.com/{handle}", headers=CABECERAS,
                         cookies=COOKIES, timeout=30)
    except requests.RequestException as e:
        print(f"  [canal] Error de red con {handle}: {e}")
        return None
    if r.status_code != 200:
        print(f"  [canal] {handle} -> HTTP {r.status_code}")
        return None
    patrones = [
        r'<link rel="canonical" href="https://www\.youtube\.com/channel/(UC[\w-]{22})"',
        r'"externalId":"(UC[\w-]{22})"',
        r'<meta itemprop="identifier" content="(UC[\w-]{22})"',
    ]
    for p in patrones:
        m = re.search(p, r.text)
        if m:
            estado["ids_canales"][canal.get("handle")] = m.group(1)
            return m.group(1)
    print(f"  [canal] No encuentro el ID de {handle}")
    return None


def leer_feed(channel_id: str) -> list[dict]:
    url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
    r = requests.get(url, headers=CABECERAS, timeout=30)
    r.raise_for_status()
    feed = feedparser.parse(r.content)
    videos = []
    for e in feed.entries:
        vid = e.get("yt_videoid")
        if not vid:
            continue
        videos.append({
            "video_id": vid,
            "titulo": e.get("title", ""),
            "url": e.get("link") or f"https://www.youtube.com/watch?v={vid}",
            "publicado": e.get("published", ""),
        })
    # el feed viene del más nuevo al más antiguo
    return videos


# ------------------------------------------------------------------ cola
def actualizar_cola(cfg: dict, estado: dict) -> list[str]:
    """Revisa los feeds y añade a la cola los vídeos nuevos.
    Devuelve los canales que no se han podido encontrar."""
    hoy = comun.ahora_utc().isoformat()
    en_cola = {v["video_id"] for v in estado["cola"]}
    fallidos_canal = []

    for canal in cfg["canales"]:
        clave = comun.clave_canal(canal)
        cid = resolver_id_canal(canal, estado)
        if not cid:
            fallidos_canal.append(canal["nombre"])
            continue
        try:
            videos = leer_feed(cid)
        except Exception as e:  # noqa: BLE001
            print(f"  [feed] {canal['nombre']}: {e}")
            continue

        if cfg["saltar_shorts"]:
            videos = [v for v in videos if "/shorts/" not in v["url"]]
        nuevos = [v for v in videos
                  if v["video_id"] not in estado["procesados"]
                  and v["video_id"] not in en_cola
                  and v["video_id"] not in estado["fallidos"]]

        primera_vez = clave not in estado["canales_vistos"]
        limite = cfg["videos_iniciales_por_canal"] if primera_vez else canal.get("max_por_revision", 15)
        aceptados, omitidos = nuevos[:limite], nuevos[limite:]

        for v in aceptados:
            estado["cola"].append({**v, "canal": canal["nombre"], "clave_canal": clave,
                                   "intentos": 0, "en_cola_desde": hoy})
            en_cola.add(v["video_id"])
        for v in omitidos:  # se marcan para no volver a cogerlos
            estado["procesados"][v["video_id"]] = hoy
        if primera_vez:
            estado["canales_vistos"].append(clave)
        if aceptados:
            print(f"  + {canal['nombre']}: {len(aceptados)} vídeo(s) nuevo(s)")

    # Caducar vídeos que llevan demasiado tiempo esperando
    limite_cola = comun.ahora_utc() - timedelta(days=cfg["dias_maximos_en_cola"])
    vivos = []
    for v in estado["cola"]:
        if datetime.fromisoformat(v["en_cola_desde"]) < limite_cola:
            estado["procesados"][v["video_id"]] = hoy
        else:
            vivos.append(v)
    estado["cola"] = vivos

    # Limpiar el registro de procesados antiguos (el feed solo trae los últimos 15)
    limite_reg = (comun.ahora_utc() - timedelta(days=120)).isoformat()
    estado["procesados"] = {k: f for k, f in estado["procesados"].items() if f >= limite_reg}
    return fallidos_canal


def elegir_lote(cola: list[dict], n: int) -> list[dict]:
    """Reparte el cupo entre canales (turnos), empezando por lo más reciente."""
    por_canal: dict[str, list[dict]] = {}
    for v in sorted(cola, key=lambda x: x.get("publicado", ""), reverse=True):
        por_canal.setdefault(v["clave_canal"], []).append(v)
    lote = []
    while len(lote) < n and any(por_canal.values()):
        for lista in por_canal.values():
            if lista and len(lote) < n:
                lote.append(lista.pop(0))
    return lote


# ------------------------------------------------------------------ guardado
COLUMNAS_CSV = ["video_id", "fecha_publicacion", "fecha_resumen", "canal", "idioma_canal",
                "region", "tipo_canal", "titulo", "url", "sentimiento_general",
                "puntuacion_sentimiento", "nivel_conviccion", "temas", "activos_mencionados",
                "tesis_principal", "resumen_breve", "ideas_clave", "num_predicciones",
                "es_contenido_de_mercados"]
COLUMNAS_SENT = ["video_id", "fecha_publicacion", "canal", "region", "tema",
                 "sentimiento", "puntuacion", "justificacion"]


def _append_csv(ruta: Path, columnas: list[str], filas: list[dict]) -> None:
    nuevo = not ruta.exists()
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with open(ruta, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=columnas)
        if nuevo:
            w.writeheader()
        w.writerows(filas)


def guardar_resumen(registro: dict) -> Path:
    r = registro["resumen"]
    fecha = (registro["fecha_publicacion"] or registro["fecha_resumen"])[:10]
    ruta = comun.DIR_RESUMENES / fecha[:4] / fecha[5:7] / f"{fecha}_{registro['video_id']}.json"
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(registro, f, ensure_ascii=False, indent=2)

    _append_csv(comun.CSV_RESUMENES, COLUMNAS_CSV, [{
        "video_id": registro["video_id"], "fecha_publicacion": registro["fecha_publicacion"],
        "fecha_resumen": registro["fecha_resumen"], "canal": registro["canal"],
        "idioma_canal": registro["idioma_canal"], "region": registro["region"],
        "tipo_canal": registro["tipo_canal"], "titulo": registro["titulo"],
        "url": registro["url"], "sentimiento_general": r["sentimiento_general"],
        "puntuacion_sentimiento": r["puntuacion_sentimiento"],
        "nivel_conviccion": r["nivel_conviccion"], "temas": " | ".join(r["temas"]),
        "activos_mencionados": " | ".join(r["activos_mencionados"]),
        "tesis_principal": r["tesis_principal"], "resumen_breve": r["resumen_breve"],
        "ideas_clave": " | ".join(r["ideas_clave"]),
        "num_predicciones": len(r["predicciones"]),
        "es_contenido_de_mercados": r["es_contenido_de_mercados"],
    }])
    _append_csv(comun.CSV_SENTIMIENTO, COLUMNAS_SENT, [{
        "video_id": registro["video_id"], "fecha_publicacion": registro["fecha_publicacion"],
        "canal": registro["canal"], "region": registro["region"], "tema": s["tema"],
        "sentimiento": s["sentimiento"], "puntuacion": s["puntuacion"],
        "justificacion": s["justificacion"],
    } for s in r["sentimiento_por_tema"]])
    return ruta


# ------------------------------------------------------------------ mensaje
def formatear_mensaje(reg: dict) -> str:
    r = reg["resumen"]
    fecha = (reg["fecha_publicacion"] or "")[:10]
    p = [f"📺 <b>{esc(reg['titulo'])}</b>\n<i>{esc(reg['canal'])} · {fecha}</i>",
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


# ------------------------------------------------------------------ proceso
def procesar_video(item: dict, cfg: dict, canal: dict | None) -> dict:
    print(f"  > Resumiendo: [{item['canal']}] {item['titulo']}")
    resumen = gemini.resumir_video(item["url"], item["titulo"], item["canal"],
                                   cfg["modelo"], cfg["idioma_resumen"], cfg["fps_video"])
    canal = canal or {}
    registro = {
        "video_id": item["video_id"], "url": item["url"], "titulo": item["titulo"],
        "canal": item["canal"], "handle": canal.get("handle", ""),
        "idioma_canal": canal.get("idioma", ""), "region": canal.get("region", ""),
        "tipo_canal": canal.get("tipo", ""), "fecha_publicacion": item.get("publicado", ""),
        "fecha_resumen": comun.ahora_utc().isoformat(), "modelo": cfg["modelo"],
        "resumen": resumen,
    }
    guardar_resumen(registro)
    comun.notificar(f"Resumen: {item['titulo']}", formatear_mensaje(registro))
    return registro


def ejecucion_normal() -> None:
    cfg = comun.cargar_config()
    estado = comun.cargar_estado()
    canales = {comun.clave_canal(c): c for c in cfg["canales"]}

    print("Revisando canales...")
    no_encontrados = actualizar_cola(cfg, estado)
    nuevos_avisos = [c for c in no_encontrados if c not in estado["avisos_canal"]]
    if nuevos_avisos:
        comun.enviar_telegram("⚠️ <b>No encuentro estos canales</b> (revisa su handle o pon el "
                              "channel_id en config.yaml):\n" +
                              "\n".join(f"• {esc(c)}" for c in nuevos_avisos))
        estado["avisos_canal"].extend(nuevos_avisos)
    comun.guardar_estado(estado)
    print(f"Vídeos en cola: {len(estado['cola'])}")

    lote = elegir_lote(estado["cola"], cfg["max_videos_por_ejecucion"])
    hechos = 0
    for item in lote:
        try:
            procesar_video(item, cfg, canales.get(item["clave_canal"]))
            estado["procesados"][item["video_id"]] = comun.ahora_utc().isoformat()
            estado["cola"] = [v for v in estado["cola"] if v["video_id"] != item["video_id"]]
            hechos += 1
            estado["aviso_config"] = None
        except gemini.CupoAgotado:
            print("Cupo gratuito de Gemini agotado por ahora. El resto queda en cola.")
            break
        except gemini.ErrorConfiguracion as e:
            print(f"Error de configuración de Gemini (no se gastan intentos): {e}")
            aviso = str(e)[:200]
            if estado.get("aviso_config") != aviso:
                comun.enviar_telegram("⚠️ <b>Gemini rechaza la configuración</b> (clave o modelo). "
                                      "No se ha gastado ningún intento de los vídeos.\n\n"
                                      f"<code>{esc(str(e)[:600])}</code>")
                estado["aviso_config"] = aviso
            break
        except Exception as e:  # noqa: BLE001
            item["intentos"] = item.get("intentos", 0) + 1
            print(f"  ! Error ({item['intentos']}/{cfg['max_intentos']}): {e}")
            if item["intentos"] >= cfg["max_intentos"]:
                estado["fallidos"][item["video_id"]] = str(e)[:300]
                estado["cola"] = [v for v in estado["cola"] if v["video_id"] != item["video_id"]]
        finally:
            comun.guardar_estado(estado)
    print(f"Hecho: {hechos} resumen(es). Quedan {len(estado['cola'])} en cola.")


def comprobar_canales() -> None:
    cfg = comun.cargar_config()
    estado = comun.cargar_estado()
    ok, mal = [], []
    for canal in cfg["canales"]:
        cid = resolver_id_canal(canal, estado)
        (ok if cid else mal).append((canal["nombre"], canal.get("handle", ""), cid))
    comun.guardar_estado(estado)
    texto = f"✅ <b>Canales encontrados: {len(ok)}</b>\n"
    texto += "\n".join(f"• {esc(n)}" for n, _, _ in ok)
    if mal:
        texto += f"\n\n❌ <b>No encontrados: {len(mal)}</b>\n"
        texto += "\n".join(f"• {esc(n)} ({esc(h)})" for n, h, _ in mal)
        texto += ("\n\nPara arreglarlos: abre el canal en YouTube, copia el @nombre que sale "
                  "en la dirección y ponlo como handle en config.yaml.")
    print(re.sub(r"<[^>]+>", "", texto))
    comun.enviar_telegram(texto)


def prueba(url: str) -> None:
    cfg = comun.cargar_config()
    m = re.search(r"(?:v=|youtu\.be/|shorts/|live/)([\w-]{11})", url)
    vid = m.group(1) if m else url[-11:]
    url_video = f"https://www.youtube.com/watch?v={vid}"
    titulo, autor = "Vídeo de prueba", "Prueba"
    try:  # título y canal reales del vídeo
        r = requests.get("https://www.youtube.com/oembed",
                         params={"url": url_video, "format": "json"}, timeout=20)
        if r.ok:
            titulo, autor = r.json().get("title", titulo), r.json().get("author_name", autor)
    except requests.RequestException:
        pass
    item = {"video_id": vid, "url": url_video, "titulo": titulo, "canal": autor,
            "clave_canal": "prueba", "publicado": comun.ahora_utc().isoformat()}
    procesar_video(item, cfg, None)
    print("Prueba completada.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--comprobar-canales", action="store_true")
    ap.add_argument("--prueba", metavar="URL")
    args = ap.parse_args()
    if args.comprobar_canales:
        comprobar_canales()
    elif args.prueba:
        prueba(args.prueba)
    else:
        ejecucion_normal()
