Set shell = CreateObject("WScript.Shell")

repo = "C:\Users\Royce Gregoriades\Documents\Projects\Workshop-Memory-HA-App"
scriptPath = repo & "\deploy_server_update.ps1"

updateId = InputBox( _
    "Enter the approved server update ID:", _
    "Deploy Workshop Memory Update" _
)

If Trim(updateId) = "" Then
    WScript.Quit
End If

command = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File " & _
    Chr(34) & scriptPath & Chr(34) & _
    " -UpdateId " & Chr(34) & Trim(updateId) & Chr(34)

exitCode = shell.Run(command, 1, True)

If exitCode = 0 Then
    MsgBox "Server update deployed successfully.", _
        vbInformation, _
        "Workshop Memory"
Else
    MsgBox "Deployment failed. Check the PowerShell error and the Failed folder.", _
        vbCritical, _
        "Workshop Memory"
End If