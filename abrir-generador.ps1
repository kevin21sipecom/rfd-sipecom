param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Opciones)
Push-Location $PSScriptRoot
try {
    $LocalPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
    if (Test-Path -LiteralPath $LocalPython) {
        & $LocalPython -m generador_rfd gui @Opciones
    } elseif (Get-Command py -ErrorAction SilentlyContinue) {
        & py -3 -m generador_rfd gui @Opciones
    } else {
        & python -m generador_rfd gui @Opciones
    }
} finally {
    Pop-Location
}
