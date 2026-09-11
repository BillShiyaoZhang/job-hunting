param(
    [Parameter(Position=0)][ValidateSet('serve','demo','validate','plan','collect','build','test')][string]$Command = 'serve',
    [int]$Port = 8765
)
$ErrorActionPreference = 'Stop'
$projectRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$bundledPython = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
if (Test-Path -LiteralPath $bundledPython) { $pythonExecutable = $bundledPython }
elseif (Get-Command python -ErrorAction SilentlyContinue) { $pythonExecutable = (Get-Command python).Source }
elseif (Get-Command python3 -ErrorAction SilentlyContinue) { $pythonExecutable = (Get-Command python3).Source }
else { throw 'Python 3.11+ is required. Install Python or use the Codex bundled runtime.' }
Push-Location -LiteralPath $projectRoot
try {
    if ($Command -eq 'serve') {
        & $pythonExecutable -m jobradar build
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        & $pythonExecutable -m http.server $Port --bind 127.0.0.1 --directory dist
    } elseif ($Command -eq 'test') {
        & $pythonExecutable -m unittest discover -s tests -v
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        & node --test tests/frontend.test.mjs
    } else {
        & $pythonExecutable -m jobradar $Command
    }
    exit $LASTEXITCODE
} finally { Pop-Location }
