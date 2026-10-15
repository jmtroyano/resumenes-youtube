"""Gestión de la lista de canales (añadir, borrar, pausar/activar)."""
from __future__ import annotations

from . import config, youtube
from .bloqueo import repo as _bloqueo


class ErrorCanal(Exception):
    pass


def clave(canal: dict) -> str:
    """Identificador estable de un canal."""
    return canal.get("channel_id") or canal.get("handle") or canal["nombre"]


def _coincide(canal: dict, ident: str) -> bool:
    ident = (ident or "").strip().lower()
    return ident in {str(canal.get(k, "")).strip().lower()
                     for k in ("channel_id", "handle", "nombre")} | {clave(canal).lower()}


def buscar(cfg: dict, ident: str) -> dict | None:
    for c in cfg["canales"]:
        if _coincide(c, ident):
            return c
    return None


def listar() -> list[dict]:
    cfg = config.cargar()
    return [{**c, "clave": clave(c)} for c in cfg["canales"]]


def anadir(entrada: str, idioma: str = "", region: str = "", tipo: str = "",
           activo: bool = False, nombre: str = "") -> dict:
    info = youtube.info_canal(entrada)
    with _bloqueo:
        return _anadir(info, idioma, region, tipo, activo, nombre)


def _anadir(info, idioma, region, tipo, activo, nombre) -> dict:
    cfg = config.cargar()
    for c in cfg["canales"]:
        if c.get("channel_id") == info["channel_id"] or (
                info["handle"] and (c.get("handle") or "").lower() == info["handle"].lower()):
            raise ErrorCanal(f"El canal ya está en la lista como «{c['nombre']}»")
    canal = {"nombre": nombre.strip() or info["nombre"], "handle": info["handle"],
             "channel_id": info["channel_id"], "idioma": idioma or None,
             "region": region or None, "tipo": tipo or None, "activo": bool(activo)}
    cfg["canales"].append(canal)
    config.guardar(cfg)
    return {**canal, "clave": clave(canal)}


def eliminar(ident: str) -> dict:
    with _bloqueo:
        cfg = config.cargar()
        canal = buscar(cfg, ident)
        if not canal:
            raise ErrorCanal(f"No encuentro el canal {ident}")
        cfg["canales"] = [c for c in cfg["canales"] if c is not canal]
        config.guardar(cfg)
        return canal


def actualizar(ident: str, **campos) -> dict:
    """Cambia campos de un canal (activo, idioma, region, tipo, nombre, max_por_revision)."""
    with _bloqueo:
        permitidos = {"activo", "idioma", "region", "tipo", "nombre", "max_por_revision"}
        cfg = config.cargar()
        canal = buscar(cfg, ident)
        if not canal:
            raise ErrorCanal(f"No encuentro el canal {ident}")
        for k, v in campos.items():
            if k in permitidos and v is not None:
                canal[k] = bool(v) if k == "activo" else v
        config.guardar(cfg)
        return {**canal, "clave": clave(canal)}


def completar_ids() -> list[str]:
    """Rellena el channel_id de los canales que no lo tengan. Devuelve fallos."""
    cfg = config.cargar()
    fallos, cambios = [], False
    for c in cfg["canales"]:
        if c.get("channel_id"):
            continue
        try:
            info = youtube.info_canal(c.get("handle") or c["nombre"])
            c["channel_id"] = info["channel_id"]
            c.setdefault("handle", info["handle"])
            cambios = True
        except youtube.ErrorYouTube:
            fallos.append(c["nombre"])
    if cambios:
        config.guardar(cfg)
    return fallos
