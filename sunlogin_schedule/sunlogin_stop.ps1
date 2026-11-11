# sunlogin_stop.ps1
# Stop AweSun (Sunlogin) client and guard processes, and stop SunloginService if running.
# Used by Task Scheduler on weekdays at 09:00.

$ErrorActionPreference = 'SilentlyContinue'
$LogDir = 'D:\dev\code\shell\sunlogin_schedule\logs'
if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir -Force | Out-Null }
$LogFile = Join-Path $LogDir ('sunlogin_' + (Get-Date -Format 'yyyyMM') + '.log')

function Write-Log {
    param([string]$Message)
    $line = '[{0}] [STOP] {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Message
    Add-Content -Path $LogFile -Value $line -Encoding UTF8
}

Write-Log '=== Begin stopping Sunlogin/AweSun ==='

# 1. Kill guard first so it does not respawn the client
$guardProcs = Get-Process -Name 'awesun_guard' -ErrorAction SilentlyContinue
foreach ($p in $guardProcs) {
    Write-Log ('Killing guard pid={0}' -f $p.Id)
    Stop-Process -Id $p.Id -Force
}

# 2. Kill AweSun client processes
$clientNames = @('AweSun', 'SunloginClient', 'SunloginDesktop', 'awesun-mcp-server', 'p2ptelemetry')
foreach ($name in $clientNames) {
    $procs = Get-Process -Name $name -ErrorAction SilentlyContinue
    foreach ($p in $procs) {
        Write-Log ('Killing {0} pid={1}' -f $name, $p.Id)
        Stop-Process -Id $p.Id -Force
    }
}

# 3. Stop SunloginService if running
$svc = Get-Service -Name 'SunloginService' -ErrorAction SilentlyContinue
if ($svc -and $svc.Status -eq 'Running') {
    Write-Log 'Stopping SunloginService'
    Stop-Service -Name 'SunloginService' -Force
}

Start-Sleep -Seconds 2

# 4. Verify
$remaining = Get-Process | Where-Object { $_.ProcessName -like '*AweSun*' -or $_.ProcessName -like '*Sunlogin*' -or $_.ProcessName -like '*awesun_guard*' }
if ($remaining) {
    foreach ($p in $remaining) {
        Write-Log ('WARNING still running: {0} pid={1}' -f $p.ProcessName, $p.Id)
    }
} else {
    Write-Log 'All Sunlogin/AweSun processes stopped successfully'
}

Write-Log '=== Stop finished ==='
