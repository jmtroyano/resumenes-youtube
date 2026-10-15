"""Sincronización con GitHub mediante git (solo en la app local).

La app guarda sus cambios (canales, transcripts, resúmenes manuales, análisis)
en la copia local del repositorio y los sube; también baja lo que haya hecho
GitHub Actions (resúmenes automáticos, informes).
"""
from __future__ import annotations

import subprocess
import threading
import time

from .bloqueo import repo as _bloqueo
from .rutas import RAIZ

RUTAS_LOCALES = ["config.yaml", "transcripts", "data/resumenes", "data/analisis"]

_estado = {"ultimo_ok": None, "ultimo_error": None, "pendiente": False, "en_curso": False}


def _git(*args: str, timeout: int = 120) -> subprocess.CompletedProcess:
    flags = {"creationflags": 0x08000000} if hasattr(subprocess, "CREATE_NO_WINDOW") else {}
    return subprocess.run(["git", *args], cwd=RAIZ, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout, **flags)


def disponible() -> bool:
    try:
        return _git("rev-parse", "--is-inside-work-tree", timeout=15).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def estado() -> dict:
    info = dict(_estado)
    info["disponible"] = disponible()
    if info["disponible"]:
        r = _git("status", "--porcelain", "--", *RUTAS_LOCALES, timeout=30)
        info["cambios_sin_subir"] = len([l for l in r.stdout.splitlines() if l.strip()])
        r = _git("log", "-1", "--format=%cd · %s", "--date=format:%d/%m %H:%M", timeout=15)
        info["ultimo_commit"] = r.stdout.strip()
    return info


def bajar() -> tuple[bool, str]:
    """git pull (trae lo que haya hecho GitHub Actions)."""
    with _bloqueo:
        r = _git("pull", "--rebase", "--autostash")
        if r.returncode != 0:
            _git("rebase", "--abort")
            _estado["ultimo_error"] = r.stderr.strip()[-500:]
            return False, _estado["ultimo_error"]
        _estado["ultimo_ok"] = time.strftime("%H:%M:%S")
        return True, r.stdout.strip()


def subir(mensaje: str) -> tuple[bool, str]:
    """Guarda los cambios locales en un commit, trae lo remoto y sube."""
    with _bloqueo:
        _estado["en_curso"] = True
        try:
            _git("add", "-A", "--", *RUTAS_LOCALES)
            if _git("diff", "--cached", "--quiet").returncode != 0:
                r = _git("commit", "-m", mensaje)
                if r.returncode != 0:
                    raise RuntimeError(r.stderr.strip() or r.stdout.strip())
            ultimo = ""
            for _ in range(3):
                r = _git("pull", "--rebase", "--autostash", timeout=180)
                if r.returncode != 0:
                    _git("rebase", "--abort")
                    ultimo = r.stderr.strip()
                    time.sleep(3)
                    continue
                r = _git("push", timeout=180)
                if r.returncode == 0:
                    _estado.update(ultimo_ok=time.strftime("%H:%M:%S"), ultimo_error=None,
                                   pendiente=False)
                    return True, "Sincronizado con GitHub"
                ultimo = r.stderr.strip()
                time.sleep(3)
            raise RuntimeError(ultimo or "No se pudo subir a GitHub")
        except Exception as e:  # noqa: BLE001
            _estado.update(ultimo_error=str(e)[-500:], pendiente=True)
            return False, str(e)[-500:]
        finally:
            _estado["en_curso"] = False


def subir_en_segundo_plano(mensaje: str) -> None:
    if not disponible():
        return
    _estado["pendiente"] = True
    threading.Thread(target=subir, args=(mensaje,), daemon=True).start()
