@echo off
:: Remove a pizzaria do inicio automatico do Windows

reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v "ServidorPizzaria" /f

if %errorlevel% == 0 (
    echo.
    echo  ✅ Removido do inicio automatico.
    echo.
) else (
    echo.
    echo  Nao estava configurado para iniciar automaticamente.
    echo.
)
pause
