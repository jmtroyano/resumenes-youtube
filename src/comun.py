"""Utilidades compartidas: rutas, configuración, estado y envío de mensajes."""
from __future__ import annotations

import html
import json
import os
import re
import smtplib
import time
from datetime import datetime, timezone
from email.mime.text import MIMEText
from pathlib import Path

import requests
import yaml

RAIZ = Path(__file__).resolve().parent.parent
RUTA_CONFIG = RAIZ / "config.yaml"
RUTA_ESTADO = RAIZ / "state" / "estado.json"
DIR_DATOS = RAIZ / "data"
DIR_RESUMENES = DIR_DATOS / "resumenes"
DIR_INFORMES = DIR_DATOS / "informes"
CSV_RESUMENES = DIR_DATOS / "resumenes.csv"
CSV_SENTIMIENTO = DIR_DATOS / "sentimiento_por_tema.csv"


def ahora_utc() -> datetime:
    return datetime.now(timezone.utc)


def cargar_config() -> dict:
    with open(RUTA_CONFIG, encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    cfg.setdefault("modelo", "gemini-2.5-flash")
    cfg.setdefault("idioma_resumen", "español")
    cfg.setdefault("max_videos_por_ejecucion", 4)
    cfg.setdefault("videos_iniciales_por_canal", 1)
    cfg.setdefault("dias_maximos_en_cola", 21)
    cfg.setdefault("max_intentos", 3)
    cfg.setdefault("saltar_shorts", True)
    cfg.setdefault("fps_video", 0.1)
    cfg["canales"] = [c for c in cfg.get("canales", []) if c.get("activo", True)]
    return cfg


def estado_vacio() -> dict:
    return {
        "ids_canales": {},        # handle -> channel_id (caché)
        "canales_vistos": [],     # claves de canal ya inicializados
        "avisos_canal": [],       # canales de los que ya se avisó un fallo
        "procesados": {},         # video_id -> fecha (resumidos u omitidos)
        "cola": [],               # vídeos pendientes de resumir
        "fallidos": {},           # video_id -> motivo
    }


def cargar_estado() -> dict:
    if RUTA_ESTADO.exists():
        with open(RUTA_ESTADO, encoding="utf-8") as f:
            estado = json.load(f)
        base = estado_vacio()
        base.update(estado)
        return base
    return estado_vacio()


def guardar_estado(estado: dict) -> None:
    RUTA_ESTADO.parent.mkdir(parents=True, exist_ok=True)
    tmp = RUTA_ESTADO.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(estado, f, ensure_ascii=False, indent=1)
    tmp.replace(RUTA_ESTADO)


def clave_canal(canal: dict) -> str:
    return canal.get("channel_id") or canal.get("handle") or canal["nombre"]


def esc(texto) -> str:
    """Escapa texto para el modo HTML de Telegram."""
    return html.escape(str(texto or ""), quote=False)


# ------------------------------------------------------------------ Telegram
def _partir(texto: str, limite: int = 3900) -> list[str]:
    """Parte un mensaje largo por párrafos para no romper etiquetas HTML."""
    trozos, actual = [], ""
    for parrafo in texto.split("\n\n"):
        while len(parrafo) > limite:  # párrafo gigante: se corta por líneas
            corte = parrafo.rfind("\n", 0, limite)
            corte = corte if corte > 0 else limite
            trozos.append(parrafo[:corte])
            parrafo = parrafo[corte:].lstrip("\n")
        if len(actual) + len(parrafo) + 2 > limite:
            trozos.append(actual)
            actual = parrafo
        else:
            actual = f"{actual}\n\n{parrafo}" if actual else parrafo
    if actual:
        trozos.append(actual)
    return trozos


def enviar_telegram(texto_html: str) -> bool:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        print("[telegram] Sin TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID: no se envía.")
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    ok = True
    for trozo in _partir(texto_html):
        datos = {"chat_id": chat_id, "text": trozo, "parse_mode": "HTML",
                 "disable_web_page_preview": "true"}
        r = requests.post(url, data=datos, timeout=30)
        if r.status_code == 429:  # demasiados mensajes seguidos
            espera = r.json().get("parameters", {}).get("retry_after", 5)
            time.sleep(espera + 1)
            r = requests.post(url, data=datos, timeout=30)
        if not r.ok:
            # Si el HTML da problemas, se reenvía como texto plano.
            plano = html.unescape(re.sub(r"<[^>]+>", "", trozo))
            r = requests.post(url, data={"chat_id": chat_id, "text": plano,
                                         "disable_web_page_preview": "true"}, timeout=30)
            if not r.ok:
                print(f"[telegram] Error {r.status_code}: {r.text[:300]}")
                ok = False
        time.sleep(1)
    return ok


# ------------------------------------------------------------------ Email
def enviar_email(asunto: str, texto_html: str) -> bool:
    """Opcional. Solo envía si existen los secrets EMAIL_USUARIO,
    EMAIL_PASSWORD (contraseña de aplicación de Gmail) y EMAIL_DESTINO."""
    usuario = os.environ.get("EMAIL_USUARIO", "").strip()
    clave = os.environ.get("EMAIL_PASSWORD", "").strip()
    destino = os.environ.get("EMAIL_DESTINO", "").strip() or usuario
    if not usuario or not clave:
        return False
    cuerpo = texto_html.replace("\n", "<br>\n")
    msg = MIMEText(f"<html><body style='font-family:sans-serif'>{cuerpo}</body></html>",
                   "html", "utf-8")
    msg["Subject"] = asunto
    msg["From"] = usuario
    msg["To"] = destino
    servidor = os.environ.get("EMAIL_SMTP", "smtp.gmail.com")
    try:
        with smtplib.SMTP_SSL(servidor, 465, timeout=30) as s:
            s.login(usuario, clave)
            s.sendmail(usuario, [destino], msg.as_string())
        return True
    except Exception as e:  # noqa: BLE001
        print(f"[email] Error enviando: {e}")
        return False


def notificar(asunto: str, texto_html: str) -> None:
    enviar_telegram(texto_html)
    enviar_email(asunto, texto_html)
