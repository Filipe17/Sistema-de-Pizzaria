@echo off
title Gerar ServidorPizzaria.exe
cd /d "%~dp0"

echo.
echo  ==========================================
echo    Gerando ServidorPizzaria.exe...
echo  ==========================================
echo.

pyinstaller --onefile --noconsole --name ServidorPizzaria servidor_pizzaria.py

if exist "dist\ServidorPizzaria.exe" (
    copy /Y "dist\ServidorPizzaria.exe" "ServidorPizzaria.exe"
    echo.
    echo  ServidorPizzaria.exe gerado com sucesso!
) else (
    echo  ERRO ao gerar .exe
)

pause
