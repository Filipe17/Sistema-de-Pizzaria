@echo off
title Instalar Dependencias
cd /d "%~dp0"

echo.
echo  Instalando dependencias Python...
echo.
pip install pystray pillow pyinstaller
echo.
echo  Pronto! Execute INICIAR_SERVIDOR.bat
pause
