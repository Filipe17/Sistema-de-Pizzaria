' Inicia o servidor da pizzaria (o tunnel é iniciado automaticamente pelo servidor)
Dim objShell
Set objShell = CreateObject("WScript.Shell")

Dim pasta
pasta = Left(WScript.ScriptFullName, InStrRev(WScript.ScriptFullName, "\"))

' Roda pythonw.exe (sem janela) — ele já inicia o tunnel automaticamente
objShell.Run "pythonw.exe """ & pasta & "servidor_pizzaria.py""", 0, False

Set objShell = Nothing
