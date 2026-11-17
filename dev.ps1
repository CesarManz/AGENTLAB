$ErrorActionPreference = "Stop"

$root = $PSScriptRoot
$pythonExe = Join-Path $root ".venv\Scripts\python.exe"
$frontendDir = Join-Path $root "frontend"

if (-not (Test-Path $pythonExe)) {
    Write-Error "No se encontró el entorno virtual en .venv\Scripts\python.exe"
    exit 1
}

Write-Host "Iniciando AGENT LAB (Backend + Frontend)..." -ForegroundColor Cyan

$backend = Start-Process -FilePath $pythonExe `
    -ArgumentList "-m", "uvicorn", "backend.api.main:app", "--reload", "--port", "8000" `
    -WorkingDirectory $root `
    -NoNewWindow -PassThru

$frontend = Start-Process -FilePath "npm.cmd" `
    -ArgumentList "run", "dev" `
    -WorkingDirectory $frontendDir `
    -NoNewWindow -PassThru

Write-Host "Backend  -> http://127.0.0.1:8000" -ForegroundColor Green
Write-Host "Frontend -> http://localhost:5173" -ForegroundColor Green
Write-Host "Presiona Ctrl + C para detener ambos servidores.`n" -ForegroundColor DarkGray

try {
    Wait-Process -Id $backend.Id, $frontend.Id
} finally {
    if (-not $backend.HasExited) { Stop-Process -Id $backend.Id -Force -ErrorAction SilentlyContinue }
    if (-not $frontend.HasExited) { Stop-Process -Id $frontend.Id -Force -ErrorAction SilentlyContinue }
    Write-Host "`nServidores detenidos." -ForegroundColor Yellow
}
