@echo off
rem Arranca la app del Agente YouTube y la abre en el navegador.
chcp 65001 >nul
title Agente YouTube - deja esta ventana abierta
cd /d "%~dp0.."
if not exist ".venv\Scripts\python.exe" (
  echo La app no esta instalada. Ejecuta windows\instalar.bat primero.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m app.servidor %*
if errorlevel 1 pause
