param(
    [string]$TerminalPath = "C:\Program Files\Exness JO MT5 Terminal\terminal64.exe"
)

$ErrorActionPreference = "Stop"
if (-not (Test-Path -LiteralPath $TerminalPath)) {
    throw "MT5 terminal was not found: $TerminalPath"
}
if (-not (Get-Process terminal64 -ErrorAction SilentlyContinue)) {
    Start-Process -FilePath $TerminalPath
}
