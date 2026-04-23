@echo off
:: Adiciona a pizzaria para iniciar automaticamente com o Windows
:: Execute este arquivo UMA VEZ como administrador

set "PASTA=%~dp0"
set "VBS=%PASTA%iniciar_oculto.vbs"
set "CHAVE=HKCU\Software\Microsoft\Windows\CurrentVersion\Run"
set "NOME=ServidorPizzaria"

:: Adiciona no registro do Windows (inicialização automática)
reg add "%CHAVE%" /v "%NOME%" /t REG_SZ /d "wscript.exe \"%VBS%\"" /f

if %errorlevel% == 0 (
    echo.
    echo  ✅ PRONTO! O servidor da pizzaria vai iniciar automaticamente
    echo     com o Windows, sem janela de prompt.
    echo.
    echo  Para remover do inicio automatico, execute:
    echo  remover_inicializacao.bat
    echo.
) else (
    echo.
    echo  ❌ Erro ao configurar. Tente executar como Administrador.
    echo.
)
pause
