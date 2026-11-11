# sunlogin_start.ps1
# Start AweSun (Sunlogin) client if not already running.
# Used by Task Scheduler on weekdays at 18:00.

$ErrorActionPreference = 'SilentlyContinue'
$LogDir = 'D:\dev\code\shell\sunlogin_schedule\logs'
if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir -Force | Out-Null }
$LogFile = Join-Path $LogDir ('sunlogin_' + (Get-Date -Format 'yyyyMM') + '.log')

$AweSunExe = 'D:\Program Files\oray\SunloginClient\AweSun\AweSun.exe'

function Write-Log {
    param([string]$Message)
    $line = '[{0}] [START] {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Message
    Add-Content -Path $LogFile -Value $line -Encoding UTF8
}

Write-Log '=== Begin starting Sunlogin/AweSun ==='

$existing = Get-Process -Name 'AweSun' -ErrorAction SilentlyContinue
if ($existing) {
    Write-Log ('AweSun already running (pid={0}), no action' -f ($existing.Id -join ','))
    Write-Log '=== Start finished ==='
    exit 0
}

if (-not (Test-Path $AweSunExe)) {
    Write-Log ('ERROR: AweSun.exe not found at {0}' -f $AweSunExe)
    Write-Log '=== Start finished ==='
    exit 1
}

# Launch in the interactive user session so the tray icon appears
Write-Log ('Launching {0} --cmd=autorun' -f $AweSunExe)
Start-Process -FilePath $AweSunExe -ArgumentList '--cmd=autorun' -WorkingDirectory (Split-Path $AweSunExe -Parent)

Start-Sleep -Seconds 5

$check = Get-Process -Name 'AweSun' -ErrorAction SilentlyContinue
if ($check) {
    Write-Log ('AweSun started successfully pid={0}' -f ($check.Id -join ','))
} else {
    Write-Log 'WARNING: AweSun process not detected after launch'
}

Write-Log '=== Start finished ==='
