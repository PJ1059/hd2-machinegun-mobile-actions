param([switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$previewUrl = 'http://127.0.0.1:5177/'

function Test-Preview {
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri $previewUrl -TimeoutSec 1
        if ($response.Content -notmatch 'MG-43') { throw 'Port 5177 belongs to another application.' }
        return $true
    } catch {
        if ($_.Exception.Message -match 'belongs to another application') { throw }
        return $false
    }
}

if (-not (Test-Preview)) {
    $nodeExecutable = (Get-Command node -ErrorAction Stop).Source
    $logDirectory = Join-Path $projectRoot 'build'
    New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
    Start-Process -FilePath $nodeExecutable -ArgumentList 'server.mjs' -WorkingDirectory $projectRoot `
        -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logDirectory 'preview-server.log') `
        -RedirectStandardError (Join-Path $logDirectory 'preview-server-error.log')
    $ready = $false
    for ($attempt = 0; $attempt -lt 10; $attempt++) {
        if (Test-Preview) { $ready = $true; break }
        Start-Sleep -Milliseconds 150
    }
    if (-not $ready) { throw 'Preview server failed. See build/preview-server-error.log.' }
}
if (-not $NoBrowser) { Start-Process $previewUrl }
Write-Output "MG-43 preview ready: $previewUrl"
