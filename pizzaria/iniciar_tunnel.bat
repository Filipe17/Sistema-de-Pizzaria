@echo off
title Tunnel Delivery - Pizzaria
color 0A

echo ============================================================
echo   TUNNEL DELIVERY - Pizzaria
echo ============================================================
echo.

:: Verifica se cloudflared já está na pasta
if exist "%~dp0cloudflared.exe" goto INICIAR

echo [1/2] Baixando Cloudflare Tunnel (cloudflared)...
echo       Isso acontece só uma vez.
echo.

:: Baixa cloudflared automaticamente
powershell -Command "Invoke-WebRequest -Uri 'https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe' -OutFile '%~dp0cloudflared.exe'"

if not exist "%~dp0cloudflared.exe" (
    echo ERRO: Nao foi possivel baixar o cloudflared.
    echo Baixe manualmente em: https://github.com/cloudflare/cloudflared/releases
    echo Coloque o arquivo cloudflared.exe na pasta da pizzaria.
    pause
    exit
)
echo [1/2] Download concluido!
echo.

:INICIAR
echo [2/2] Iniciando tunnel...
echo.
echo ============================================================
echo   AGUARDE - O link do delivery vai aparecer abaixo
echo   Procure pela linha com: "trycloudflare.com"
echo   Adicione /delivery no final do link para os clientes!
echo   Exemplo: https://xyz.trycloudflare.com/delivery
echo ============================================================
echo.

"%~dp0cloudflared.exe" tunnel --url http://localhost:5000

pause
