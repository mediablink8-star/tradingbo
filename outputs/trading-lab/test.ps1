$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$runtime = 'C:\Users\30699\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
if (Test-Path -LiteralPath $runtime) { & $runtime -m unittest -v } else { & python -m unittest -v }
