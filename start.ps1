$ErrorActionPreference = "Stop"

Set-Location $PSScriptRoot

$pythonCandidates = @(
    ".\.venv\Scripts\python.exe",
    "$env:CONDA_PREFIX\python.exe",
    "C:\Users\14704\miniconda3\envs\greenapp\python.exe"
)
$python = $pythonCandidates |
    Where-Object { $_ -and (Test-Path $_) } |
    Select-Object -First 1
if (-not $python) {
    $python = (Get-Command python -ErrorAction Stop).Source
}
$python = (Resolve-Path $python).Path

if (-not (Test-Path ".\.env")) {
    throw "未找到 .env 配置文件。"
}

function Get-DotEnvValue([string]$Name, [string]$Default) {
    $match = Get-Content ".\.env" | Where-Object { $_ -match "^\s*$Name\s*=" } | Select-Object -First 1
    if (-not $match) { return $Default }
    return ($match -split "=", 2)[1].Trim()
}

$speechPort = [int](Get-DotEnvValue "SPEECH_ENGINE_PORT" "3101")
$clientPort = [int](Get-DotEnvValue "CLIENT_PORT" "3002")

if (-not (Get-NetTCPConnection -State Listen -LocalPort $speechPort -ErrorAction SilentlyContinue)) {
    Start-Process powershell.exe -WorkingDirectory $PSScriptRoot -ArgumentList @(
        "-NoExit", "-Command", "& '$python' server.py"
    )
}

if (-not (Get-NetTCPConnection -State Listen -LocalPort $clientPort -ErrorAction SilentlyContinue)) {
    Start-Process powershell.exe -WorkingDirectory $PSScriptRoot -ArgumentList @(
        "-NoExit", "-Command", "& '$python' token_server.py"
    )
}

Write-Host "SparkChat 已启动" -ForegroundColor Green
Write-Host "客户端: http://127.0.0.1:$clientPort" -ForegroundColor Cyan
Write-Host "豆包实时代理: ws://127.0.0.1:$speechPort" -ForegroundColor Cyan