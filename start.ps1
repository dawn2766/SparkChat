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

function Stop-PortProcess([int]$Port) {
    $connections = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue
    $processIds = $connections | Select-Object -ExpandProperty OwningProcess -Unique
    foreach ($processId in $processIds) {
        if ($processId -and $processId -ne $PID) {
            Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
        }
    }
}

function Wait-PortProcess([System.Diagnostics.Process]$Process, [int]$Port, [string]$Name) {
    for ($attempt = 0; $attempt -lt 50; $attempt++) {
        if ($Process.HasExited) {
            throw "$Name 启动失败，进程已退出（退出码 $($Process.ExitCode)）。"
        }
        if (Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue) {
            return
        }
        Start-Sleep -Milliseconds 100
    }
    Stop-Process -Id $Process.Id -Force -ErrorAction SilentlyContinue
    throw "$Name 启动超时：端口 $Port 未开始监听。"
}

Stop-PortProcess $speechPort
Stop-PortProcess $clientPort

$realtimeProcess = Start-Process powershell.exe -PassThru -WorkingDirectory $PSScriptRoot -ArgumentList @(
    "-NoExit", "-Command", "& '$python' -m backend.realtime"
)
Wait-PortProcess $realtimeProcess $speechPort "豆包实时代理"

$webProcess = Start-Process powershell.exe -PassThru -WorkingDirectory $PSScriptRoot -ArgumentList @(
    "-NoExit", "-Command", "& '$python' -m backend.app"
)
Wait-PortProcess $webProcess $clientPort "SparkChat Web 服务"

Write-Host "SparkChat 已启动" -ForegroundColor Green
Write-Host "客户端: http://127.0.0.1:$clientPort" -ForegroundColor Cyan
Write-Host "豆包实时代理: ws://127.0.0.1:$speechPort" -ForegroundColor Cyan