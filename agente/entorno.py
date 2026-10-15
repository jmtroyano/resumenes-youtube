"""Claves y ajustes privados.

En GitHub Actions llegan como variables de entorno (secrets). En tu ordenador
se guardan en el archivo .env de la raíz, que NUNCA se sube a GitHub.
"""
from __future__ import annotations

import os

from .rutas import RUTA_ENV

CLAVES = ["GEMINI_API_KEY", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID",
          "EMAIL_USUARIO", "EMAIL_PASSWORD", "EMAIL_DESTINO"]


def _leer_archivo() -> dict[str, str]:
    datos: dict[str, str] = {}
    if RUTA_ENV.exists():
        for linea in RUTA_ENV.read_text(encoding="utf-8").splitlines():
            linea = linea.strip()
            if not linea or linea.startswith("#") or "=" not in linea:
                continue
            k, v = linea.split("=", 1)
            datos[k.strip()] = v.strip().strip('"').strip("'")
    return datos


def cargar() -> None:
    """Carga .env en os.environ sin pisar variables ya definidas."""
    for k, v in _leer_archivo().items():
        if v and not os.environ.get(k):
            os.environ[k] = v


def obtener(clave: str) -> str:
    return os.environ.get(clave, "").strip() or _leer_archivo().get(clave, "").strip()


def guardar(valores: dict[str, str]) -> None:
    """Guarda (o borra, si el valor es vacío) claves en .env y en el proceso."""
    datos = _leer_archivo()
    for k, v in valores.items():
        if k not in CLAVES:
            continue
        v = (v or "").strip()
        if v:
            datos[k] = v
            os.environ[k] = v
        else:
            datos.pop(k, None)
            os.environ.pop(k, None)
    lineas = ["# Claves privadas de la app. Este archivo no se sube a GitHub."]
    lineas += [f"{k}={v}" for k, v in datos.items()]
    RUTA_ENV.write_text("\n".join(lineas) + "\n", encoding="utf-8")


def resumen_publico() -> dict[str, bool]:
    """Qué claves están configuradas (sin revelar su valor)."""
    return {k: bool(obtener(k)) for k in CLAVES}
