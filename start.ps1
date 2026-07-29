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

$ngrokCommand = Get-Command ngrok -ErrorAction SilentlyContinue
if ($ngrokCommand) {
    $ngrok = $ngrokCommand.Source
} else {
    $ngrok = Get-ChildItem "$env:LOCALAPPDATA\Microsoft\WinGet\Packages" `
        -Filter ngrok.exe -Recurse -ErrorAction SilentlyContinue |
        Select-Object -First 1 -ExpandProperty FullName
}
if (-not $ngrok) {
    throw "未找到 ngrok。请先运行: winget install --id Ngrok.Ngrok --exact"
}

if (-not (Test-Path ".\.env")) {
    throw "未找到 .env 配置文件。"
}

function Get-DotEnvValue([string]$Name, [string]$Default) {
    $match = Get-Content ".\.env" | Where-Object { $_ -match "^\s*$Name\s*=" } | Select-Object -First 1
    if (-not $match) { return $Default }
    return ($match -split "=", 2)[1].Trim()
}

function Set-DotEnvValue([string]$Name, [string]$Value) {
    $lines = Get-Content ".\.env"
    $pattern = "^\s*$Name\s*="
    if ($lines -match $pattern) {
        $lines = $lines | ForEach-Object { if ($_ -match $pattern) { "$Name=$Value" } else { $_ } }
    } else {
        $lines += "$Name=$Value"
    }
    Set-Content ".\.env" -Value $lines -Encoding utf8
}

$speechPort = [int](Get-DotEnvValue "SPEECH_ENGINE_PORT" "3101")
$clientPort = [int](Get-DotEnvValue "CLIENT_PORT" "3002")

$tunnel = $null
try {
    $tunnel = (Invoke-RestMethod "http://127.0.0.1:4040/api/tunnels").tunnels |
        Where-Object { $_.config.addr -match ":$speechPort$" } |
        Select-Object -First 1
} catch {
    $tunnel = $null
}

if (-not $tunnel) {
    Start-Process powershell.exe -WorkingDirectory $PSScriptRoot -ArgumentList @(
        "-NoExit", "-Command", "& '$ngrok' http $speechPort"
    )

    for ($attempt = 0; $attempt -lt 40 -and -not $tunnel; $attempt++) {
        [System.Threading.Thread]::Sleep(250)
        try {
            $tunnel = (Invoke-RestMethod "http://127.0.0.1:4040/api/tunnels").tunnels |
                Where-Object { $_.config.addr -match ":$speechPort$" } |
                Select-Object -First 1
        } catch {
            $tunnel = $null
        }
    }
}

if (-not $tunnel) {
    throw "ngrok 隧道启动失败。"
}

$wsUrl = $tunnel.public_url -replace "^https://", "wss://"
$wsUrl = "$wsUrl/ws"
Set-DotEnvValue "SPEECH_ENGINE_WS_URL" $wsUrl

& $python create_engine.py
if ($LASTEXITCODE -ne 0) {
    throw "Speech Engine 配置同步失败。"
}

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
Write-Host "Speech Engine: $wsUrl" -ForegroundColor Cyan