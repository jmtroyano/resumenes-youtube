@echo off
rem Arranca la app del Agente YouTube y la abre en el navegador.
rem Si la app pide reiniciarse (boton "Reiniciar app"), sale con codigo 3 y se vuelve a arrancar.
chcp 65001 >nul
title Agente YouTube - deja esta ventana abierta
cd /d "%~dp0.."
if not exist ".venv\Scripts\python.exe" (
  echo La app no esta instalada. Ejecuta windows\instalar.bat primero.
  pause
  exit /b 1
)
set "ARGS=%*"
:arrancar
".venv\Scripts\python.exe" -m app.servidor %ARGS%
if "%errorlevel%"=="3" goto reiniciar
if errorlevel 1 pause
exit /b

:reiniciar
echo.
echo Reiniciando la app...
set "ARGS=--sin-navegador --reinicio"
goto arrancar
