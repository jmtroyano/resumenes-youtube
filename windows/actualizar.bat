@echo off
rem Descarga la ultima version desde GitHub y reinstala dependencias.
chcp 65001 >nul
cd /d "%~dp0.."
git pull --rebase --autostash
call windows\instalar.bat
