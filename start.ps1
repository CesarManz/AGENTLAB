$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
$PyExe = Join-Path $Root ".venv\Scripts\python.exe"

Write-Host "Iniciando AGENT LAB (Backend :8000 + Frontend :5173)..." -ForegroundColor Cyan

$backend = Start-Process -FilePath $PyExe `
    -ArgumentList "-m", "uvicorn", "backend.api.main:app", "--reload", "--reload-dir", "backend", "--port", "8000" `
    -WorkingDirectory $Root `
    -NoNewWindow `
    -PassThru

$frontend = Start-Process -FilePath "npm.cmd" `
    -ArgumentList "run", "dev" `
    -WorkingDirectory (Join-Path $Root "frontend") `
    -NoNewWindow `
    -PassThru

try {
    Start-Sleep -Seconds 2
    Start-Process "http://localhost:5173"
    Write-Host "AGENT LAB activo en http://localhost:5173 (Presiona Ctrl+C para detener ambos servicios)" -ForegroundColor Green
    Wait-Process -Id $backend.Id, $frontend.Id
} finally {
    Write-Host "`nDeteniendo servicios de AGENT LAB..." -ForegroundColor Yellow
    if (-not $backend.HasExited) { Stop-Process -Id $backend.Id -Force -ErrorAction SilentlyContinue }
    if (-not $frontend.HasExited) { Stop-Process -Id $frontend.Id -Force -ErrorAction SilentlyContinue }
}