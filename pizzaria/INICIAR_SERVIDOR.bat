@echo off
:: Inicia o servidor agora (sem janela de prompt)
:: Para iniciar automaticamente com Windows, execute: instalar_inicializacao.bat

set "PASTA=%~dp0"
start "" "pythonw.exe" "%PASTA%servidor_pizzaria.py"

:: Aguarda 2 segundos e abre o admin no navegador
timeout /t 2 /nobreak >nul
start http://localhost:5000/admin
