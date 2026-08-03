Set shell = CreateObject("WScript.Shell")

repo = "C:\Users\Royce Gregoriades\Documents\Projects\Workshop-Memory-HA-App"
logFile = repo & "\git-update.log"

command = "powershell.exe -NoProfile -ExecutionPolicy Bypass -Command " & _
    Chr(34) & _
    "Set-Location '" & repo & "'; " & _
    "$message = 'Workshop Memory update ' + (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'); " & _
    "git add . *> '" & logFile & "'; " & _
    "git diff --cached --quiet; " & _
    "if ($LASTEXITCODE -eq 0) { " & _
        "Add-Content '" & logFile & "' 'No changes to commit.'; exit 0 " & _
    "}; " & _
    "git commit -m $message *>> '" & logFile & "'; " & _
    "if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }; " & _
    "git push *>> '" & logFile & "'" & _
    Chr(34)

shell.Run command, 0, True