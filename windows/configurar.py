"""Configura la app en Windows tras instalar dependencias:
  1. Acceso directo "Agente YouTube" en el Escritorio.
  2. Conexión con la app de escritorio de Claude (servidor MCP "agente-youtube").

Se ejecuta desde windows\\instalar.bat. Se puede repetir sin problema.
"""
from __future__ import annotations

import glob
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
PYTHON = RAIZ / ".venv" / "Scripts" / "python.exe"
INICIAR = RAIZ / "windows" / "iniciar.bat"
NOMBRE_MCP = "agente-youtube"


def acceso_directo() -> None:
    ps = (
        "$d=[Environment]::GetFolderPath('Desktop');"
        "$w=New-Object -ComObject WScript.Shell;"
        "$s=$w.CreateShortcut((Join-Path $d 'Agente YouTube.lnk'));"
        f"$s.TargetPath='{INICIAR}';"
        f"$s.WorkingDirectory='{RAIZ}';"
        "$s.IconLocation='shell32.dll,13';"
        "$s.Description='Agente de resúmenes de YouTube';"
        "$s.Save();"
        "Write-Output (Join-Path $d 'Agente YouTube.lnk')"
    )
    r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
                       capture_output=True, text=True)
    if r.returncode == 0:
        print(f"[OK] Acceso directo creado: {r.stdout.strip()}")
    else:
        print(f"[!] No se pudo crear el acceso directo: {r.stderr.strip()}")


def rutas_config_claude() -> list[Path]:
    """Posibles ubicaciones de claude_desktop_config.json (instalación normal y de la Store)."""
    candidatas = []
    appdata = os.environ.get("APPDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")
    if appdata:
        candidatas.append(Path(appdata) / "Claude")
    if local:
        for p in glob.glob(os.path.join(local, "Packages", "Claude_*", "LocalCache", "Roaming", "Claude")):
            candidatas.append(Path(p))
        for p in glob.glob(os.path.join(local, "Packages", "*Anthropic*Claude*", "LocalCache", "Roaming", "Claude")):
            candidatas.append(Path(p))
    existentes = [c for c in candidatas if c.is_dir()]
    if not existentes and appdata:
        existentes = [Path(appdata) / "Claude"]  # se crea; Claude la leerá al arrancar
    return [c / "claude_desktop_config.json" for c in dict.fromkeys(existentes)]


def conectar_claude() -> None:
    entrada = {"command": str(PYTHON), "args": [str(RAIZ / "app" / "mcp_claude.py")],
               "env": {"PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}}
    for ruta in rutas_config_claude():
        try:
            datos = {}
            if ruta.exists():
                texto = ruta.read_text(encoding="utf-8").strip()
                datos = json.loads(texto) if texto else {}
                copia = ruta.with_name(f"claude_desktop_config.copia-{time.strftime('%Y%m%d%H%M%S')}.json")
                shutil.copy2(ruta, copia)
            datos.setdefault("mcpServers", {})[NOMBRE_MCP] = entrada
            ruta.parent.mkdir(parents=True, exist_ok=True)
            ruta.write_text(json.dumps(datos, indent=2, ensure_ascii=False), encoding="utf-8")
            print(f"[OK] Claude conectado (servidor '{NOMBRE_MCP}') en: {ruta}")
        except Exception as e:  # noqa: BLE001
            print(f"[!] No se pudo configurar {ruta}: {e}")
    print("    Reinicia la app de Claude (ciérrala del todo y vuelve a abrirla) para activarlo.")


def comprobar_mcp() -> None:
    r = subprocess.run([str(PYTHON), "-c",
                        "import sys; sys.path.insert(0, r'%s'); import app.mcp_claude as m; "
                        "import asyncio; print(len(asyncio.run(m.mcp.list_tools())))" % RAIZ],
                       capture_output=True, text=True, cwd=RAIZ)
    if r.returncode == 0:
        print(f"[OK] Servidor para Claude funciona ({r.stdout.strip()} herramientas)")
    else:
        print(f"[!] El servidor para Claude falla: {r.stderr.strip()[-800:]}")


if __name__ == "__main__":
    print(f"Python: {sys.version.split()[0]}  Carpeta: {RAIZ}")
    acceso_directo()
    comprobar_mcp()
    if "--sin-claude" not in sys.argv:
        conectar_claude()
