@echo off
rem Instala o actualiza la app del Agente YouTube en este ordenador.
rem Doble clic para ejecutar. Se puede repetir sin problema.
chcp 65001 >nul
cd /d "%~dp0.."
set "LOG=%~dp0..\instalacion.log"
echo Instalando el Agente YouTube... (puede tardar un par de minutos)
(
  echo === %DATE% %TIME% ===
  if not exist ".venv\Scripts\python.exe" (
    py -3.13 -m venv .venv || python -m venv .venv
  )
  ".venv\Scripts\python.exe" -m pip install --upgrade pip
  ".venv\Scripts\python.exe" -m pip install -r requirements-app.txt
  ".venv\Scripts\python.exe" windows\configurar.py
  echo === FIN ===
) > "%LOG%" 2>&1
type "%LOG%" | findstr /C:"[OK]" /C:"[!]" /C:"ERROR" /C:"FIN"
echo.
echo Instalacion terminada. Detalles en instalacion.log
timeout /t 8
