#!/usr/bin/env pwsh
# clone 직후 한 줄로 웹을 띄운다 (Windows 네이티브 PowerShell용).
# macOS/Linux/WSL은 quickstart.sh를 쓴다 — 이 스크립트와 로직을 맞춰
# 둔다(가용성 확인 -> 서버 두 개 기동 -> 브라우저 오픈 -> Ctrl+C 시 정리).
# pip install 없이 돈다: token_bench와 정적 웹 서버 모두 Python 내장
# http.server 위에서 돌고, Headroom·RTK·Caveman처럼 별도 설치가 필요한
# 조건은 preflight가 알아서 건너뛰고 설치법을 알려준다(--skip-unavailable).

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

$WebPort = if ($env:WEB_PORT) { $env:WEB_PORT } else { 8765 }
$ApiPort = if ($env:API_PORT) { $env:API_PORT } else { 8787 }

function Find-Python311 {
    foreach ($entry in @(
        @{ Exe = "py"; Args = @("-3.11") },
        @{ Exe = "python3.11"; Args = @() },
        @{ Exe = "python"; Args = @() }
    )) {
        $cmd = Get-Command $entry.Exe -ErrorAction SilentlyContinue
        if (-not $cmd) { continue }
        try {
            $version = & $entry.Exe @($entry.Args) --version 2>&1
        } catch {
            continue
        }
        if ($version -match "3\.11") {
            return $entry
        }
    }
    return $null
}

$Python = Find-Python311
if (-not $Python) {
    Write-Error "Python 3.11을 찾지 못했습니다. https://www.python.org/downloads/ 에서 설치하거나 winget install Python.Python.3.11 을 실행하세요."
    exit 1
}

function Invoke-Py {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Rest)
    & $Python.Exe @($Python.Args) @Rest
}

function Test-PortInUse {
    param([int]$Port)
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $task = $client.ConnectAsync("127.0.0.1", $Port)
        return ($task.Wait(200)) -and $client.Connected
    } catch {
        return $false
    } finally {
        $client.Close()
    }
}

Write-Host "== 조건 가용성 확인 (모델 호출 없음) =="
Invoke-Py -m token_bench preflight --skip-unavailable

# Start-Job은 백그라운드 프로세스 종료를 보장하지 않으므로, PID를 직접 쥐고
# 있다가 종료 시 Stop-Process로 확실히 끊는 Start-Process -PassThru를 쓴다.
$procs = @()

function Start-Backend {
    param([string]$LogPath, [string[]]$ModuleArgs)
    return Start-Process -FilePath $Python.Exe `
        -ArgumentList (@($Python.Args) + $ModuleArgs) `
        -WorkingDirectory $PSScriptRoot `
        -RedirectStandardOutput $LogPath `
        -RedirectStandardError "$LogPath.err" `
        -WindowStyle Hidden -PassThru
}

try {
    if (Test-PortInUse -Port $ApiPort) {
        Write-Host "== 로컬 실험 API는 이미 :$ApiPort 에서 실행 중입니다 =="
    } else {
        Write-Host "== 로컬 실험 API 시작 (127.0.0.1:$ApiPort, 모델 호출 없음) =="
        $procs += Start-Backend -LogPath "$env:TEMP\token-bench-api.log" `
            -ModuleArgs @("-m", "token_bench", "serve", "--port", $ApiPort)
    }

    if (Test-PortInUse -Port $WebPort) {
        Write-Host "== 웹은 이미 :$WebPort 에서 실행 중입니다 =="
    } else {
        Write-Host "== 웹 서버 시작 (127.0.0.1:$WebPort) =="
        $procs += Start-Backend -LogPath "$env:TEMP\token-bench-web.log" `
            -ModuleArgs @("-m", "http.server", $WebPort)
    }

    $url = "http://127.0.0.1:$WebPort/web/#settings"
    Start-Sleep -Seconds 1
    Write-Host ""
    Write-Host "== 준비 완료: $url =="
    Start-Process $url

    Write-Host "이 창을 열어 둔 채로 두면 서버가 유지됩니다. 끝내려면 Ctrl+C."
    while ($true) { Start-Sleep -Seconds 1 }
} finally {
    Write-Host ""
    Write-Host "서버를 정리합니다."
    foreach ($proc in $procs) {
        Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
    }
}
