' Inicia cloudflared tunnel em segundo plano e salva log
Dim objShell, objFSO
Set objShell = CreateObject("WScript.Shell")
Set objFSO   = CreateObject("Scripting.FileSystemObject")

Dim pasta
pasta = Left(WScript.ScriptFullName, InStrRev(WScript.ScriptFullName, "\"))

Dim logPath
logPath = pasta & "dados\tunnel.log"

' Limpa log anterior
If objFSO.FileExists(logPath) Then
    objFSO.DeleteFile logPath
End If

' Roda cloudflared redirecionando saída para o log
' Usa cmd /c com START para manter processo vivo sem janela
objShell.Run "cmd /c """ & pasta & "cloudflared.exe"" tunnel --url http://localhost:5000 > """ & logPath & """ 2>&1", 0, False

Set objShell = Nothing
Set objFSO   = Nothing
