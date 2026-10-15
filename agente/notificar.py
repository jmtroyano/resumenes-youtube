"""Envío de mensajes por Telegram y (opcional) email."""
from __future__ import annotations

import html
import re
import smtplib
import time
from email.mime.text import MIMEText

import requests

from . import entorno


def esc(texto) -> str:
    """Escapa texto para el modo HTML de Telegram."""
    return html.escape(str(texto or ""), quote=False)


def partir(texto: str, limite: int = 3900) -> list[str]:
    """Parte un mensaje largo por párrafos para no romper etiquetas HTML."""
    trozos, actual = [], ""
    for parrafo in texto.split("\n\n"):
        while len(parrafo) > limite:
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


def telegram(texto_html: str) -> bool:
    token = entorno.obtener("TELEGRAM_BOT_TOKEN")
    chat_id = entorno.obtener("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("[telegram] Sin TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID: no se envía.")
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    ok = True
    for trozo in partir(texto_html):
        datos = {"chat_id": chat_id, "text": trozo, "parse_mode": "HTML",
                 "disable_web_page_preview": "true"}
        r = requests.post(url, data=datos, timeout=30)
        if r.status_code == 429:
            espera = r.json().get("parameters", {}).get("retry_after", 5)
            time.sleep(espera + 1)
            r = requests.post(url, data=datos, timeout=30)
        if not r.ok:
            plano = html.unescape(re.sub(r"<[^>]+>", "", trozo))
            r = requests.post(url, data={"chat_id": chat_id, "text": plano,
                                         "disable_web_page_preview": "true"}, timeout=30)
            if not r.ok:
                print(f"[telegram] Error {r.status_code}: {r.text[:300]}")
                ok = False
        time.sleep(1)
    return ok


def email(asunto: str, texto_html: str) -> bool:
    usuario = entorno.obtener("EMAIL_USUARIO")
    clave = entorno.obtener("EMAIL_PASSWORD")
    destino = entorno.obtener("EMAIL_DESTINO") or usuario
    if not usuario or not clave:
        return False
    cuerpo = texto_html.replace("\n", "<br>\n")
    msg = MIMEText(f"<html><body style='font-family:sans-serif'>{cuerpo}</body></html>",
                   "html", "utf-8")
    msg["Subject"] = asunto
    msg["From"] = usuario
    msg["To"] = destino
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as s:
            s.login(usuario, clave)
            s.sendmail(usuario, [destino], msg.as_string())
        return True
    except Exception as e:  # noqa: BLE001
        print(f"[email] Error enviando: {e}")
        return False


def notificar(asunto: str, texto_html: str) -> None:
    telegram(texto_html)
    email(asunto, texto_html)


def markdown_a_telegram(md: str) -> str:
    """Conversión sencilla de Markdown a HTML de Telegram."""
    lineas = []
    for linea in md.splitlines():
        l = esc(linea)
        m = re.match(r"^#{1,6}\s+(.*)$", l)
        if m:
            l = f"<b>{m.group(1)}</b>"
        l = re.sub(r"^\s*[-*]\s+", "• ", l)
        l = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", l)
        lineas.append(l)
    return "\n".join(lineas)
