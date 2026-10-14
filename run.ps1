param([switch]$DebugMode)
$ErrorActionPreference = 'Stop'
if ($DebugMode) { $env:FLASK_DEBUG = '1' }
$venvPython = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
$localPython = Join-Path $PSScriptRoot '.runtime/python/python.exe'
$entrypoint = Join-Path $PSScriptRoot 'app.py'
if (Test-Path -LiteralPath $venvPython) {
    $taskPython = $venvPython
} elseif (Test-Path -LiteralPath $localPython) {
    $taskPython = $localPython
} else {
    $taskPython = 'py'
}
Push-Location -LiteralPath $PSScriptRoot
try {
    & $taskPython -m flask --app criticard db-upgrade
    if ($LASTEXITCODE -ne 0) { throw 'Falha nas migrações. O servidor não foi iniciado.' }
    & $taskPython $entrypoint
} finally { Pop-Location }
exit $LASTEXITCODE
