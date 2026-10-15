"""Resúmenes automáticos (los ejecuta GitHub Actions cada 3 horas).

Solo procesa los canales con `activo: true`. Si un vídeo ya tiene resumen (por
ejemplo, hecho a mano desde la app) se salta; si tiene transcript descargado,
se resume desde el texto (más rápido y barato); si no, viendo el vídeo.
"""
from __future__ import annotations

import argparse
import re
from datetime import timedelta

from . import almacen, config, entorno, ia as modulo_ia, procesar, youtube
from .canales import clave as clave_canal
from .notificar import esc, notificar, telegram


def resolver_id(canal: dict, estado: dict) -> str | None:
    if canal.get("channel_id"):
        return canal["channel_id"]
    handle = (canal.get("handle") or "").strip()
    if not handle:
        return None
    if handle in estado["ids_canales"]:
        return estado["ids_canales"][handle]
    try:
        cid = youtube.info_canal(handle)["channel_id"]
    except youtube.ErrorYouTube as e:
        print(f"  [canal] {e}")
        return None
    estado["ids_canales"][handle] = cid
    return cid


def actualizar_cola(cfg: dict, estado: dict) -> list[str]:
    """Añade a la cola los vídeos nuevos de los canales activos."""
    hoy = almacen.ahora_utc().isoformat()
    activos = config.canales_activos(cfg)
    claves_activas = {clave_canal(c) for c in activos}
    # Equivalencias por si una clave antigua era el handle o el nombre del canal
    alias = {}
    for c in cfg["canales"]:
        for k in (c.get("channel_id"), c.get("handle"), c.get("nombre")):
            if k:
                alias[k] = clave_canal(c)

    # Canales en pausa: se vacía su parte de la cola y se "olvidan", para que al
    # reactivarlos solo se coja su último vídeo y no todo lo atrasado.
    vivos = []
    for v in estado["cola"]:
        v["clave_canal"] = alias.get(v["clave_canal"], v["clave_canal"])
        if v["clave_canal"] in claves_activas:
            vivos.append(v)
        else:
            estado["procesados"][v["video_id"]] = hoy
    estado["cola"] = vivos
    estado["canales_vistos"] = sorted({alias.get(c, c) for c in estado["canales_vistos"]}
                                      & claves_activas)

    en_cola = {v["video_id"] for v in estado["cola"]}
    no_encontrados = []
    for canal in activos:
        clave = clave_canal(canal)
        cid = resolver_id(canal, estado)
        if not cid:
            no_encontrados.append(canal["nombre"])
            continue
        try:
            videos = youtube.leer_feed(cid)
        except Exception as e:  # noqa: BLE001
            print(f"  [feed] {canal['nombre']}: {e}")
            continue
        if cfg["saltar_shorts"]:
            videos = [v for v in videos if not v["es_short"]]
        nuevos = [v for v in videos
                  if v["video_id"] not in estado["procesados"]
                  and v["video_id"] not in en_cola
                  and v["video_id"] not in estado["fallidos"]]
        primera_vez = clave not in estado["canales_vistos"]
        limite = cfg["videos_iniciales_por_canal"] if primera_vez else canal.get("max_por_revision", 15)
        aceptados, omitidos = nuevos[:limite], nuevos[limite:]
        for v in aceptados:
            estado["cola"].append({**{k: v[k] for k in ("video_id", "titulo", "url", "publicado")},
                                   "canal": canal["nombre"], "clave_canal": clave,
                                   "intentos": 0, "en_cola_desde": hoy})
            en_cola.add(v["video_id"])
        for v in omitidos:
            estado["procesados"][v["video_id"]] = hoy
        if primera_vez:
            estado["canales_vistos"].append(clave)
        if aceptados:
            print(f"  + {canal['nombre']}: {len(aceptados)} vídeo(s) nuevo(s)")

    limite_cola = almacen.ahora_utc() - timedelta(days=cfg["dias_maximos_en_cola"])
    vivos = []
    for v in estado["cola"]:
        if almacen.parse_fecha(v["en_cola_desde"]) < limite_cola:
            estado["procesados"][v["video_id"]] = hoy
        else:
            vivos.append(v)
    estado["cola"] = vivos
    limite_reg = (almacen.ahora_utc() - timedelta(days=120)).isoformat()
    estado["procesados"] = {k: f for k, f in estado["procesados"].items() if f >= limite_reg}
    return no_encontrados


def elegir_lote(cola: list[dict], n: int) -> list[dict]:
    """Reparte el cupo entre canales por turnos, empezando por lo más reciente."""
    por_canal: dict[str, list[dict]] = {}
    for v in sorted(cola, key=lambda x: x.get("publicado", ""), reverse=True):
        por_canal.setdefault(v["clave_canal"], []).append(v)
    lote = []
    while len(lote) < n and any(por_canal.values()):
        for lista in por_canal.values():
            if lista and len(lote) < n:
                lote.append(lista.pop(0))
    return lote


def _quitar(estado: dict, video_id: str) -> None:
    estado["cola"] = [v for v in estado["cola"] if v["video_id"] != video_id]


def ejecucion_normal() -> None:
    cfg = config.cargar()
    estado = almacen.cargar_estado()
    por_clave = {clave_canal(c): c for c in cfg["canales"]}
    print(f"Canales activos: {len(config.canales_activos(cfg))} de {len(cfg['canales'])}")
    print("Revisando canales...")
    no_encontrados = actualizar_cola(cfg, estado)
    nuevos_avisos = [c for c in no_encontrados if c not in estado["avisos_canal"]]
    if nuevos_avisos:
        telegram("⚠️ <b>No encuentro estos canales</b> (revisa su handle en la app):\n"
                 + "\n".join(f"• {esc(c)}" for c in nuevos_avisos))
        estado["avisos_canal"].extend(nuevos_avisos)
    almacen.guardar_estado(estado)
    print(f"Vídeos en cola: {len(estado['cola'])}")

    proveedor = modulo_ia.crear(cfg)
    hechos = 0
    for item in elegir_lote(estado["cola"], cfg["max_videos_por_ejecucion"]):
        if almacen.existe_resumen(item["video_id"]):
            print(f"  = Ya resumido desde la app: {item['titulo']}")
            estado["procesados"][item["video_id"]] = almacen.ahora_utc().isoformat()
            _quitar(estado, item["video_id"])
            almacen.guardar_estado(estado)
            continue
        try:
            print(f"  > Resumiendo: [{item['canal']}] {item['titulo']}")
            reg = procesar.resumir(item, cfg, proveedor, por_clave.get(item["clave_canal"]))
            notificar(f"Resumen: {item['titulo']}", procesar.formatear_mensaje(reg))
            estado["procesados"][item["video_id"]] = almacen.ahora_utc().isoformat()
            _quitar(estado, item["video_id"])
            estado["aviso_config"] = None
            hechos += 1
        except modulo_ia.CupoAgotado:
            print("Cupo de la IA agotado por ahora. El resto queda en cola.")
            break
        except modulo_ia.ErrorConfiguracion as e:
            print(f"Error de configuración de la IA (no se gastan intentos): {e}")
            aviso = str(e)[:200]
            if estado.get("aviso_config") != aviso:
                telegram("⚠️ <b>La IA rechaza la configuración</b> (clave o modelo). "
                         "No se ha gastado ningún intento de los vídeos.\n\n"
                         f"<code>{esc(str(e)[:600])}</code>")
                estado["aviso_config"] = aviso
            break
        except Exception as e:  # noqa: BLE001
            item["intentos"] = item.get("intentos", 0) + 1
            print(f"  ! Error ({item['intentos']}/{cfg['max_intentos']}): {e}")
            if item["intentos"] >= cfg["max_intentos"]:
                estado["fallidos"][item["video_id"]] = str(e)[:300]
                _quitar(estado, item["video_id"])
        finally:
            almacen.guardar_estado(estado)
    n = almacen.regenerar_csv()
    print(f"Hecho: {hechos} resumen(es). Quedan {len(estado['cola'])} en cola. CSV: {n} filas.")


def comprobar_canales() -> None:
    cfg = config.cargar()
    estado = almacen.cargar_estado()
    ok, mal = [], []
    for canal in cfg["canales"]:
        (ok if resolver_id(canal, estado) else mal).append(canal)
    almacen.guardar_estado(estado)
    marca = {True: "▶️", False: "⏸"}
    texto = f"✅ <b>Canales encontrados: {len(ok)}</b> (▶️ automático · ⏸ en pausa)\n"
    texto += "\n".join(f"{marca[c.get('activo', True)]} {esc(c['nombre'])}" for c in ok)
    if mal:
        texto += f"\n\n❌ <b>No encontrados: {len(mal)}</b>\n"
        texto += "\n".join(f"• {esc(c['nombre'])} ({esc(c.get('handle', ''))})" for c in mal)
    print(re.sub(r"<[^>]+>", "", texto))
    telegram(texto)


def prueba(url: str) -> None:
    cfg = config.cargar()
    vid = youtube.extraer_id_video(url) or url[-11:]
    info = youtube.info_video(vid)
    item = {"video_id": vid, "url": info["url"], "titulo": info["titulo"] or "Vídeo de prueba",
            "canal": info["canal"] or "Prueba", "publicado": almacen.ahora_utc().isoformat()}
    reg = procesar.resumir(item, cfg, modulo_ia.crear(cfg))
    notificar(f"Resumen: {item['titulo']}", procesar.formatear_mensaje(reg))
    almacen.regenerar_csv()
    print("Prueba completada.")


def main(argv: list[str] | None = None) -> None:
    entorno.cargar()
    ap = argparse.ArgumentParser()
    ap.add_argument("--comprobar-canales", action="store_true")
    ap.add_argument("--prueba", metavar="URL")
    args = ap.parse_args(argv)
    if args.comprobar_canales:
        comprobar_canales()
    elif args.prueba:
        prueba(args.prueba)
    else:
        ejecucion_normal()
