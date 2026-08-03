param(
    [Parameter(Mandatory = $true)]
    [string]$UpdateId
)

$ErrorActionPreference = "Stop"

$repo = "C:\Users\Royce Gregoriades\Documents\Projects\Workshop-Memory-HA-App"
$vault = "C:\Users\Royce Gregoriades\Documents\Obsidian\Workshop Vault"

$inbox = Join-Path $vault "Server Updates\Inbox"
$applied = Join-Path $vault "Server Updates\Applied"
$failed = Join-Path $vault "Server Updates\Failed"

$patchPath = Join-Path $inbox "$UpdateId.json"
$configPath = Join-Path $repo "workshop-memory\config.yaml"

New-Item -ItemType Directory -Force -Path $applied, $failed | Out-Null

if (-not (Test-Path $patchPath)) {
    throw "Patch file not found: $patchPath"
}

$patch = Get-Content $patchPath -Raw -Encoding UTF8 | ConvertFrom-Json

if ($patch.update_id -ne $UpdateId) {
    throw "Patch update ID does not match the filename."
}

if ($patch.status -ne "approved" -or $patch.user_approved -ne $true) {
    throw "The update has not been explicitly approved."
}

$allowedTargets = @(
    "workshop-memory/src/server.py",
    "workshop-memory/config.yaml",
    "workshop-memory/run.sh",
    "workshop-memory/Dockerfile",
    "workshop-memory/requirements.txt"
)

$targetRelative = $patch.target_file.Replace("/", "\")

if ($patch.target_file -notin $allowedTargets) {
    throw "Target file is not permitted: $($patch.target_file)"
}

$targetPath = [System.IO.Path]::GetFullPath(
    (Join-Path $repo $targetRelative)
)

$repoFullPath = [System.IO.Path]::GetFullPath($repo) +
    [System.IO.Path]::DirectorySeparatorChar

if (-not $targetPath.StartsWith(
    $repoFullPath,
    [System.StringComparison]::OrdinalIgnoreCase
)) {
    throw "Resolved target is outside the Git repository."
}

if (-not (Test-Path $targetPath)) {
    throw "Target file does not exist: $targetPath"
}

$originalTarget = Get-Content $targetPath -Raw -Encoding UTF8
$originalConfig = Get-Content $configPath -Raw -Encoding UTF8

$findText = [string]$patch.find_text
$replacementText = [string]$patch.replacement_text

if ([string]::IsNullOrEmpty($findText)) {
    throw "find_text is empty."
}

$occurrenceCount = (
    [regex]::Matches(
        $originalTarget,
        [regex]::Escape($findText)
    )
).Count

if ($occurrenceCount -eq 0) {
    throw "find_text was not found in the target file."
}

if ($occurrenceCount -gt 1) {
    throw "find_text occurs $occurrenceCount times. Exact replacement refused."
}

$deploymentTime = Get-Date -Format "yyyy-MM-ddTHH:mm:ss"
$failedPath = Join-Path $failed "$UpdateId.json"
$appliedPath = Join-Path $applied "$UpdateId.json"

try {
    $updatedTarget = $originalTarget.Replace(
        $findText,
        $replacementText
    )

    Set-Content `
        -Path $targetPath `
        -Value $updatedTarget `
        -Encoding UTF8 `
        -NoNewline

    if ($patch.deployment.validate_python -eq $true) {
        & python -m py_compile `
            (Join-Path $repo "workshop-memory\src\server.py")

        if ($LASTEXITCODE -ne 0) {
            throw "Python validation failed."
        }
    }

    $versionPattern = '(?m)^version:\s*"(\d+)\.(\d+)\.(\d+)"\s*$'
    $versionMatch = [regex]::Match(
        $originalConfig,
        $versionPattern
    )

    if (-not $versionMatch.Success) {
        throw "Could not find a valid quoted version in config.yaml."
    }

    $major = [int]$versionMatch.Groups[1].Value
    $minor = [int]$versionMatch.Groups[2].Value
    $patchVersion = [int]$versionMatch.Groups[3].Value + 1

    $oldVersion = "$major.$minor.$($patchVersion - 1)"
    $newVersion = "$major.$minor.$patchVersion"

    $updatedConfig = [regex]::Replace(
        $originalConfig,
        $versionPattern,
        "version: `"$newVersion`"",
        1
    )

    Set-Content `
        -Path $configPath `
        -Value $updatedConfig `
        -Encoding UTF8 `
        -NoNewline

    Set-Location $repo

    & git add .
    if ($LASTEXITCODE -ne 0) {
        throw "git add failed."
    }

    & git diff --cached --quiet

    if ($LASTEXITCODE -eq 0) {
        throw "No Git changes were detected after applying the patch."
    }

    $commitMessage = "Apply server update $UpdateId ($newVersion)"

    & git commit -m $commitMessage
    if ($LASTEXITCODE -ne 0) {
        throw "git commit failed."
    }

    & git push
    if ($LASTEXITCODE -ne 0) {
        throw "git push failed."
    }

    $patch.status = "applied"
    $patch | Add-Member `
        -NotePropertyName applied_at `
        -NotePropertyValue $deploymentTime `
        -Force

    $patch | Add-Member `
        -NotePropertyName previous_version `
        -NotePropertyValue $oldVersion `
        -Force

    $patch | Add-Member `
        -NotePropertyName new_version `
        -NotePropertyValue $newVersion `
        -Force

    $patch | Add-Member `
        -NotePropertyName git_commit_message `
        -NotePropertyValue $commitMessage `
        -Force

    $patch |
        ConvertTo-Json -Depth 10 |
        Set-Content $patchPath -Encoding UTF8

    Move-Item $patchPath $appliedPath -Force

    Write-Host "Update applied successfully."
    Write-Host "Update ID: $UpdateId"
    Write-Host "Version: $oldVersion -> $newVersion"
    Write-Host "Patch moved to: $appliedPath"
}
catch {
    Set-Content `
        -Path $targetPath `
        -Value $originalTarget `
        -Encoding UTF8 `
        -NoNewline

    Set-Content `
        -Path $configPath `
        -Value $originalConfig `
        -Encoding UTF8 `
        -NoNewline

    $patch.status = "failed"

    $patch | Add-Member `
        -NotePropertyName failed_at `
        -NotePropertyValue $deploymentTime `
        -Force

    $patch | Add-Member `
        -NotePropertyName error `
        -NotePropertyValue $_.Exception.Message `
        -Force

    $patch |
        ConvertTo-Json -Depth 10 |
        Set-Content $patchPath -Encoding UTF8

    Move-Item $patchPath $failedPath -Force

    throw
}