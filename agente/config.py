"""Lectura y escritura de config.yaml (ajustes generales + lista de canales)."""
from __future__ import annotations

import yaml

from .bloqueo import repo as _bloqueo
from .rutas import RUTA_CONFIG

AJUSTES_POR_DEFECTO = {
    "proveedor_ia": "gemini",
    "modelo": "gemini-3.8-flash",
    "idioma_resumen": "español",
    "max_videos_por_ejecucion": 4,
    "videos_iniciales_por_canal": 1,
    "dias_maximos_en_cola": 21,
    "max_intentos": 3,
    "saltar_shorts": True,
    "fps_video": 0.1,
}

COMENTARIOS_AJUSTES = {
    "proveedor_ia": "Proveedor de IA para resúmenes y análisis (por ahora: gemini)",
    "modelo": "Modelo de Gemini. Si Google lo retira, pon el 'flash' más reciente",
    "idioma_resumen": "Idioma de todos los resúmenes y análisis",
    "max_videos_por_ejecucion": "Vídeos resumidos como máximo en cada ejecución automática",
    "videos_iniciales_por_canal": "Vídeos que se cogen al activar un canal por primera vez",
    "dias_maximos_en_cola": "Días que un vídeo puede esperar en cola antes de descartarse",
    "max_intentos": "Intentos antes de dar un vídeo por imposible",
    "saltar_shorts": "Ignorar los Shorts de YouTube",
    "fps_video": "Fotogramas por segundo que mira Gemini cuando resume desde el vídeo",
}

ORDEN_CAMPOS_CANAL = ["nombre", "handle", "channel_id", "idioma", "region", "tipo",
                      "max_por_revision", "activo"]

CABECERA = """\
# ============================================================
#  CONFIGURACIÓN DEL AGENTE DE RESÚMENES DE YOUTUBE
#  Se puede editar desde la app web (recomendado) o a mano.
#
#  Canales:
#   - activo: true  -> se resume automáticamente cada 3 horas (GitHub)
#   - activo: false -> en pausa: solo se usa bajo demanda desde la app
#   - channel_id    -> ID "UC..." del canal (la app lo rellena sola)
#   - max_por_revision -> límite de vídeos nuevos por revisión
# ============================================================
"""


def cargar() -> dict:
    """Devuelve la configuración completa con TODOS los canales."""
    with _bloqueo, open(RUTA_CONFIG, encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    for k, v in AJUSTES_POR_DEFECTO.items():
        cfg.setdefault(k, v)
    canales = []
    for c in cfg.get("canales") or []:
        if not c or not c.get("nombre"):
            continue
        c.setdefault("activo", True)
        canales.append(c)
    cfg["canales"] = canales
    return cfg


def canales_activos(cfg: dict) -> list[dict]:
    return [c for c in cfg["canales"] if c.get("activo", True)]


def _limpiar_canal(c: dict) -> dict:
    limpio = {k: c[k] for k in ORDEN_CAMPOS_CANAL if c.get(k) not in (None, "")}
    limpio["activo"] = bool(c.get("activo", True))
    for k, v in c.items():  # conserva campos extra que alguien añada a mano
        if k not in limpio and v not in (None, ""):
            limpio[k] = v
    return limpio


def guardar(cfg: dict) -> None:
    with _bloqueo:
        partes = [CABECERA]
        for k in AJUSTES_POR_DEFECTO:
            partes.append(f"# {COMENTARIOS_AJUSTES[k]}")
            partes.append(yaml.safe_dump({k: cfg.get(k, AJUSTES_POR_DEFECTO[k])},
                                         allow_unicode=True, sort_keys=False).strip())
        extras = {k: v for k, v in cfg.items()
                  if k not in AJUSTES_POR_DEFECTO and k != "canales"}
        if extras:
            partes.append(yaml.safe_dump(extras, allow_unicode=True, sort_keys=False).strip())
        canales = [_limpiar_canal(c) for c in cfg.get("canales", [])]
        partes.append("")
        partes.append(yaml.safe_dump({"canales": canales}, allow_unicode=True,
                                     sort_keys=False, width=1000, indent=2).strip())
        texto = "\n".join(partes) + "\n"
        tmp = RUTA_CONFIG.with_suffix(".tmp")
        tmp.write_text(texto, encoding="utf-8")
        tmp.replace(RUTA_CONFIG)
