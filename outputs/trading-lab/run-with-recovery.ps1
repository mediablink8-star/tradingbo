# Local recovery helper. It cannot keep a sleeping/offline computer online.
$ErrorActionPreference='Stop'
Set-Location -LiteralPath $PSScriptRoot
$labPython='C:\Users\30699\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
if (-not (Test-Path -LiteralPath $labPython)) {$labPython=(Get-Command python).Source}
try {
    $existing=Invoke-RestMethod -Uri 'http://127.0.0.1:8765/api/live' -TimeoutSec 3
    Write-Host 'Dashboard is already running. Stop that copy before using the recovery helper.'
    exit 0
} catch {}
Write-Host 'Local dashboard recovery is active. Ctrl+C stops recovery and its child process.'
Write-Host 'A restarted process forgets session API keys; reconnect keys in the dashboard.'
$labProcess=$null
try {
    while ($true) {
        $labProcess=Start-Process -FilePath $labPython -ArgumentList 'app.py' -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $PSScriptRoot 'service-output.log') -RedirectStandardError (Join-Path $PSScriptRoot 'service-error.log')
        $labProcess.WaitForExit()
        Write-Host 'Dashboard exited. Waiting 10 seconds before restarting.'
        Start-Sleep -Seconds 10
    }
} finally {
    try { $null=Invoke-RestMethod -Uri 'http://127.0.0.1:8765/api/pump/stop' -Method Post -ContentType 'application/json' -Body '{}' -TimeoutSec 3 } catch {}
    if ($labProcess -and -not $labProcess.HasExited) {Stop-Process -Id $labProcess.Id -ErrorAction SilentlyContinue}
}

