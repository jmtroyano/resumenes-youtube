"""App web local: API REST + interfaz.

Arranque:  python -m app.servidor   (desde la raíz del repositorio)
Abre:      http://localhost:8000

La interfaz (app/web) solo habla con esta API, así que se puede sustituir por
una app móvil o de escritorio sin tocar la lógica (que está en agente/).
"""
from __future__ import annotations

import contextlib
import os
import sys
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agente import (__version__, almacen, analisis, canales, config, entorno,  # noqa: E402
                    ia as modulo_ia, procesar, sync, transcripts, youtube)
from agente.notificar import esc, markdown_a_telegram, telegram  # noqa: E402

DIR_WEB = Path(__file__).resolve().parent / "web"


class ErrorUsuario(Exception):
    def __init__(self, mensaje: str, codigo: int = 400):
        super().__init__(mensaje)
        self.codigo = codigo


def endpoint(funcion):
    """Ejecuta la función en un hilo y convierte errores en JSON legible."""
    async def envoltura(request: Request):
        try:
            datos = {}
            if request.method in ("POST", "PATCH", "PUT"):
                cuerpo = await request.body()
                datos = (await request.json()) if cuerpo else {}
            resultado = await run_in_threadpool(funcion, request, datos)
            return JSONResponse(resultado)
        except ErrorUsuario as e:
            return JSONResponse({"error": str(e)}, status_code=e.codigo)
        except (canales.ErrorCanal, youtube.ErrorYouTube, transcripts.ErrorTranscript,
                modulo_ia.ErrorConfiguracion, modulo_ia.CupoAgotado, ValueError) as e:
            return JSONResponse({"error": str(e)}, status_code=400)
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            return JSONResponse({"error": f"{type(e).__name__}: {e}"}, status_code=500)
    return envoltura


def _info_video_local(vid: str) -> dict:
    reg = almacen.cargar_resumen(vid)
    t_existe = transcripts.existe(vid)
    info = {"tiene_transcript": t_existe, "tiene_resumen": bool(reg)}
    if reg:
        r = reg["resumen"]
        info.update(sentimiento=r["sentimiento_general"], puntuacion=r["puntuacion_sentimiento"],
                    fuente_resumen=reg.get("fuente", "video"))
    return info


# ------------------------------------------------------------------ estado / ajustes
@endpoint
def api_estado(request, datos):
    cfg = config.cargar()
    return {"version": __version__, "claves": entorno.resumen_publico(),
            "modelo": cfg["modelo"], "idioma_resumen": cfg["idioma_resumen"],
            "canales": len(cfg["canales"]), "activos": len(config.canales_activos(cfg)),
            "git": sync.estado()}


@endpoint
def api_guardar_claves(request, datos):
    entorno.guardar({k: v for k, v in datos.items() if k in entorno.CLAVES})
    return {"ok": True, "claves": entorno.resumen_publico()}


@endpoint
def api_guardar_ajustes(request, datos):
    cfg = config.cargar()
    for k in ("modelo", "idioma_resumen", "max_videos_por_ejecucion"):
        if datos.get(k) not in (None, ""):
            cfg[k] = int(datos[k]) if k == "max_videos_por_ejecucion" else str(datos[k]).strip()
    config.guardar(cfg)
    sync.subir_en_segundo_plano("App: ajustes actualizados")
    return {"ok": True}


@endpoint
def api_probar_ia(request, datos):
    cfg = config.cargar()
    texto = modulo_ia.crear(cfg).generar("Responde solo con la palabra: funciona", 0)
    return {"ok": True, "respuesta": texto[:100]}


@endpoint
def api_sync_bajar(request, datos):
    ok, msg = sync.bajar()
    if not ok:
        raise ErrorUsuario(f"No se pudo bajar de GitHub: {msg}")
    return {"ok": True, "mensaje": msg, "git": sync.estado()}


@endpoint
def api_sync_subir(request, datos):
    ok, msg = sync.subir("App: sincronización manual")
    if not ok:
        raise ErrorUsuario(f"No se pudo subir a GitHub: {msg}")
    return {"ok": True, "mensaje": msg, "git": sync.estado()}


# ------------------------------------------------------------------ canales
@endpoint
def api_canales(request, datos):
    return {"canales": canales.listar()}


@endpoint
def api_anadir_canal(request, datos):
    entrada = (datos.get("entrada") or "").strip()
    if not entrada:
        raise ErrorUsuario("Escribe el @nombre, la URL o el ID del canal")
    canal = canales.anadir(entrada, datos.get("idioma", ""), datos.get("region", ""),
                           datos.get("tipo", ""), bool(datos.get("activo")), datos.get("nombre", ""))
    sync.subir_en_segundo_plano(f"App: canal añadido ({canal['nombre']})")
    return {"canal": canal}


@endpoint
def api_editar_canal(request, datos):
    canal = canales.actualizar(request.path_params["clave"], **datos)
    estado = "activado" if canal.get("activo") else "en pausa"
    sync.subir_en_segundo_plano(f"App: canal {canal['nombre']} {estado}")
    return {"canal": canal}


@endpoint
def api_borrar_canal(request, datos):
    canal = canales.eliminar(request.path_params["clave"])
    sync.subir_en_segundo_plano(f"App: canal eliminado ({canal['nombre']})")
    return {"ok": True}


# ------------------------------------------------------------------ vídeos
def _videos_de_canal(canal: dict, mas: bool) -> tuple[list[dict], str | None]:
    try:
        cid = canal.get("channel_id") or youtube.info_canal(canal.get("handle") or canal["nombre"])["channel_id"]
        idioma = canal.get("idioma") or ""
        lista = (youtube.mas_videos(cid, 50, idioma) if mas
                 else youtube.listar_videos(cid, 15, idioma))
    except Exception as e:  # noqa: BLE001
        return [], f"{canal['nombre']}: {e}"
    for v in lista:
        v["canal"] = canal["nombre"]
        v["clave_canal"] = canales.clave(canal)
        v["idioma_canal"] = canal.get("idioma", "")
    return lista, None


@endpoint
def api_videos(request, datos):
    claves = [c for c in request.query_params.get("canales", "").split(",") if c]
    mas = request.query_params.get("mas") == "1"
    shorts = request.query_params.get("shorts") == "1"
    cfg = config.cargar()
    elegidos = [c for c in cfg["canales"] if canales.clave(c) in claves] if claves else []
    if not elegidos:
        raise ErrorUsuario("Elige al menos un canal")
    videos, errores = [], []
    with ThreadPoolExecutor(max_workers=8) as ex:
        for lista, error in ex.map(lambda c: _videos_de_canal(c, mas), elegidos):
            videos += lista
            if error:
                errores.append(error)
    if not shorts:
        videos = [v for v in videos if not v.get("es_short")]
    for v in videos:
        v.update(_info_video_local(v["video_id"]))
        v["miniatura"] = youtube.miniatura(v["video_id"])
    videos.sort(key=lambda v: v.get("publicado", ""), reverse=True)
    return {"videos": videos, "errores": errores}


@endpoint
def api_info_video(request, datos):
    vid = youtube.extraer_id_video(datos.get("url", ""))
    if not vid:
        raise ErrorUsuario("No reconozco esa URL de YouTube")
    info = youtube.info_video(vid)
    info.update(_info_video_local(vid), miniatura=youtube.miniatura(vid), publicado="")
    return {"video": info}


# ------------------------------------------------------------------ transcripts
@endpoint
def api_descargar_transcripts(request, datos):
    vids = datos.get("video_ids") or []
    metas = datos.get("metas") or {}
    if not vids:
        raise ErrorUsuario("No has elegido ningún vídeo")
    cfg = config.cargar()
    idioma_por_canal = {c["nombre"]: c.get("idioma") for c in cfg["canales"]}
    resultados = []
    for vid in vids:
        meta = metas.get(vid) or {}
        try:
            t = transcripts.descargar(vid, [idioma_por_canal.get(meta.get("canal"), "")], meta,
                                      forzar=bool(datos.get("forzar")))
            resultados.append({"video_id": vid, "ok": True, "palabras": t.get("palabras"),
                               "idioma": t.get("idioma"), "automatico": t.get("es_automatico")})
        except transcripts.ErrorTranscript as e:
            resultados.append({"video_id": vid, "ok": False, "error": str(e)})
    if any(r["ok"] for r in resultados):
        sync.subir_en_segundo_plano(f"App: {sum(r['ok'] for r in resultados)} transcript(s)")
    return {"resultados": resultados}


@endpoint
def api_ver_transcript(request, datos):
    t = transcripts.cargar(request.path_params["vid"])
    if not t:
        raise ErrorUsuario("Ese vídeo no tiene transcript descargado", 404)
    segs = t.pop("segmentos", [])
    t["texto"] = transcripts.texto_con_marcas({"segmentos": segs})
    return {"transcript": t}


# ------------------------------------------------------------------ resúmenes
@endpoint
def api_resumir(request, datos):
    vids = datos.get("video_ids") or []
    metas = datos.get("metas") or {}
    if not vids:
        raise ErrorUsuario("No has elegido ningún vídeo")
    cfg = config.cargar()
    proveedor = modulo_ia.crear(cfg)
    por_nombre = {c["nombre"]: c for c in cfg["canales"]}
    resultados = []
    for vid in vids:
        if almacen.existe_resumen(vid) and not datos.get("rehacer"):
            resultados.append({"video_id": vid, "ok": True, "ya_existia": True})
            continue
        base = analisis.info_basica(vid)
        meta = {**base, **{k: v for k, v in (metas.get(vid) or {}).items() if v}}
        item = {"video_id": vid, "url": youtube.url_video(vid), "titulo": meta.get("titulo", ""),
                "canal": meta.get("canal", ""),
                "publicado": meta.get("publicado") or meta.get("fecha_publicacion", "")}
        try:
            reg = procesar.resumir(item, cfg, proveedor, por_nombre.get(item["canal"]),
                                   permitir_video=bool(datos.get("permitir_video")))
            if datos.get("enviar_telegram"):
                telegram(procesar.formatear_mensaje(reg))
            r = reg["resumen"]
            resultados.append({"video_id": vid, "ok": True, "fuente": reg["fuente"],
                               "sentimiento": r["sentimiento_general"],
                               "puntuacion": r["puntuacion_sentimiento"]})
        except (modulo_ia.CupoAgotado, modulo_ia.ErrorConfiguracion):
            raise
        except Exception as e:  # noqa: BLE001
            resultados.append({"video_id": vid, "ok": False, "error": str(e)[:300]})
    if any(r["ok"] and not r.get("ya_existia") for r in resultados):
        sync.subir_en_segundo_plano("App: resúmenes manuales")
    return {"resultados": resultados}


@endpoint
def api_ver_resumen(request, datos):
    reg = almacen.cargar_resumen(request.path_params["vid"])
    if not reg:
        raise ErrorUsuario("Ese vídeo no tiene resumen", 404)
    return {"resumen": reg}


@endpoint
def api_biblioteca(request, datos):
    q = (request.query_params.get("q") or "").lower().strip()
    canal = request.query_params.get("canal") or ""
    dias = int(request.query_params.get("dias") or 0) or None
    items: dict[str, dict] = {}
    for t in transcripts.listar():
        items[t["video_id"]] = {"video_id": t["video_id"], "titulo": t.get("titulo", ""),
                                "canal": t.get("canal", ""), "url": t.get("url", ""),
                                "publicado": t.get("fecha_publicacion", ""),
                                "palabras": t.get("palabras")}
    for reg in almacen.listar_resumenes():
        d = items.setdefault(reg["video_id"], {"video_id": reg["video_id"]})
        d.update(titulo=d.get("titulo") or reg.get("titulo", ""),
                 canal=d.get("canal") or reg.get("canal", ""), url=reg.get("url", ""),
                 publicado=d.get("publicado") or reg.get("fecha_publicacion", ""),
                 temas=reg["resumen"]["temas"])
    salida = []
    desde = (almacen.ahora_utc().timestamp() - dias * 86400) if dias else None
    for d in items.values():
        d.update(_info_video_local(d["video_id"]), miniatura=youtube.miniatura(d["video_id"]))
        if canal and d.get("canal") != canal:
            continue
        if desde:
            f = almacen.parse_fecha(d.get("publicado"))
            if not f or f.timestamp() < desde:
                continue
        if q and q not in " ".join([d.get("titulo", ""), d.get("canal", ""),
                                    " ".join(d.get("temas") or [])]).lower():
            continue
        salida.append(d)
    salida.sort(key=lambda d: d.get("publicado") or "", reverse=True)
    return {"videos": salida}


# ------------------------------------------------------------------ análisis
@endpoint
def api_analizar(request, datos):
    vids = datos.get("video_ids") or []
    if not vids:
        raise ErrorUsuario("Elige al menos un vídeo")
    res = analisis.analizar(vids, datos.get("instruccion", ""), datos.get("titulo", ""),
                            datos.get("modo", "auto"))
    if datos.get("enviar_telegram"):
        telegram(f"🧠 <b>{esc(res['titulo'])}</b>\n\n" + markdown_a_telegram(res["markdown"]))
    sync.subir_en_segundo_plano(f"App: análisis «{res['titulo']}»")
    return {"analisis": res}


@endpoint
def api_listar_analisis(request, datos):
    return {"analisis": almacen.listar_analisis()}


@endpoint
def api_ver_analisis(request, datos):
    a = almacen.cargar_analisis(request.path_params["ident"])
    if not a:
        raise ErrorUsuario("No encuentro ese análisis", 404)
    return {"analisis": a}


@endpoint
def api_instruccion_defecto(request, datos):
    from agente.esquemas import INSTRUCCION_ANALISIS_POR_DEFECTO  # noqa: PLC0415
    return {"instruccion": INSTRUCCION_ANALISIS_POR_DEFECTO}


# ------------------------------------------------------------------ app
async def index(request):
    return FileResponse(DIR_WEB / "index.html")


rutas = [
    Route("/", index),
    Route("/api/estado", api_estado),
    Route("/api/ajustes/claves", api_guardar_claves, methods=["POST"]),
    Route("/api/ajustes", api_guardar_ajustes, methods=["POST"]),
    Route("/api/ajustes/probar-ia", api_probar_ia, methods=["POST"]),
    Route("/api/sync/bajar", api_sync_bajar, methods=["POST"]),
    Route("/api/sync/subir", api_sync_subir, methods=["POST"]),
    Route("/api/canales", api_canales),
    Route("/api/canales", api_anadir_canal, methods=["POST"]),
    Route("/api/canales/{clave:path}", api_editar_canal, methods=["PATCH"]),
    Route("/api/canales/{clave:path}", api_borrar_canal, methods=["DELETE"]),
    Route("/api/videos", api_videos),
    Route("/api/videos/info", api_info_video, methods=["POST"]),
    Route("/api/transcripts", api_descargar_transcripts, methods=["POST"]),
    Route("/api/transcripts/{vid}", api_ver_transcript),
    Route("/api/resumir", api_resumir, methods=["POST"]),
    Route("/api/resumenes/{vid}", api_ver_resumen),
    Route("/api/biblioteca", api_biblioteca),
    Route("/api/analizar", api_analizar, methods=["POST"]),
    Route("/api/analisis", api_listar_analisis),
    Route("/api/analisis/instruccion", api_instruccion_defecto),
    Route("/api/analisis/{ident}", api_ver_analisis),
    Mount("/web", StaticFiles(directory=DIR_WEB), name="web"),
]


@contextlib.asynccontextmanager
async def ciclo_de_vida(app):
    entorno.cargar()
    if await run_in_threadpool(sync.disponible):
        ok, msg = await run_in_threadpool(sync.bajar)
        print(f"[git] {'Actualizado desde GitHub' if ok else 'No se pudo actualizar: ' + msg}")
    yield


app = Starlette(routes=rutas, lifespan=ciclo_de_vida)


def main():
    import socket  # noqa: PLC0415
    import threading  # noqa: PLC0415
    import webbrowser  # noqa: PLC0415

    import uvicorn  # noqa: PLC0415
    host = os.environ.get("APP_HOST", "127.0.0.1")
    puerto = int(os.environ.get("APP_PUERTO", "8000"))
    url = f"http://localhost:{puerto}"
    abrir = "--sin-navegador" not in sys.argv
    with socket.socket() as s:
        if s.connect_ex(("127.0.0.1", puerto)) == 0:  # ya está arrancada
            print(f"La app ya está abierta en {url}")
            if abrir:
                webbrowser.open(url)
            return
    if abrir:
        threading.Timer(2.5, lambda: webbrowser.open(url)).start()
    print("=" * 60)
    print(f"  Agente YouTube funcionando en {url}")
    print("  Deja esta ventana abierta mientras uses la app.")
    print("  Para pararla, cierra esta ventana.")
    print("=" * 60)
    uvicorn.run(app, host=host, port=puerto, log_level="warning")


if __name__ == "__main__":
    main()
