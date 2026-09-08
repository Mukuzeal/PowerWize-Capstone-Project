# PowerWize local dev launcher (Windows)
# Starts PostgreSQL (if not already up), clears stale Flask processes, runs the app.

$ErrorActionPreference = 'Stop'
$root   = $PSScriptRoot
$pgBin  = "$env:USERPROFILE\scoop\apps\postgresql\current\bin"
$pgData = "$env:USERPROFILE\scoop\apps\postgresql\current\data"

# 1. PostgreSQL --------------------------------------------------------------
$ready = (& "$pgBin\pg_isready" -q; $LASTEXITCODE -eq 0)
if ($ready) {
    Write-Host "[pg] already running" -ForegroundColor DarkGray
} else {
    Write-Host "[pg] starting..." -ForegroundColor Cyan
    $log = "$pgData\log\server-$(Get-Date -Format yyyyMMdd-HHmmss).log"
    New-Item -ItemType Directory -Force -Path "$pgData\log" | Out-Null
    & "$pgBin\pg_ctl" -D $pgData -l $log -w start
    if ($LASTEXITCODE -ne 0) { throw "PostgreSQL failed to start - see $log" }
}

# 2. Kill stale app.py processes ------------------------------------------------
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -like '*app.py*' } |
    ForEach-Object {
        Write-Host "[app] killing stale PID $($_.ProcessId)" -ForegroundColor DarkYellow
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }

# 3. Run the app --------------------------------------------------------------
Write-Host "[app] starting on http://127.0.0.1:5000" -ForegroundColor Green
Set-Location "$root\src"
& "$root\.venv\Scripts\python.exe" app.py
