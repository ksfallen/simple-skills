# register_tasks_elevated.ps1
# Must run as Administrator. Registers tasks with -RunLevel Highest so they can
# terminate SYSTEM-owned AweSun/awesun_guard processes.

$ErrorActionPreference = 'Stop'

# Verify admin
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host 'ERROR: This script must run as Administrator.' -ForegroundColor Red
    exit 1
}

$ScriptDir = 'D:\dev\code\shell\sunlogin_schedule'
$StopScript  = Join-Path $ScriptDir 'sunlogin_stop.ps1'
$StartScript = Join-Path $ScriptDir 'sunlogin_start.ps1'
$PsExe = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"

$TaskStopName  = 'SunloginStop-Weekday0900'
$TaskStartName = 'SunloginStart-Weekday1800'

function New-Task {
    param([string]$Name, [string]$ScriptPath, [string]$Time, [string]$Description)

    if (Get-ScheduledTask -TaskName $Name -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $Name -Confirm:$false
        Write-Host "Removed existing task: $Name"
    }

    $action = New-ScheduledTaskAction -Execute $PsExe `
        -Argument ('-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "{0}"' -f $ScriptPath) `
        -WorkingDirectory $ScriptDir

    $trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At $Time

    # Interactive + Highest: runs elevated in the user's session, no UAC prompt after registration
    $principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Highest

    $settings = New-ScheduledTaskSettingsSet `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries `
        -StartWhenAvailable `
        -MultipleInstances IgnoreNew `
        -ExecutionTimeLimit (New-TimeSpan -Minutes 10)

    Register-ScheduledTask -TaskName $Name `
        -Action $action `
        -Trigger $trigger `
        -Principal $principal `
        -Settings $settings `
        -Description $Description `
        -Force | Out-Null

    Write-Host "Registered: $Name @ $Time Mon-Fri -> $ScriptPath"
}

New-Task -Name $TaskStopName  -ScriptPath $StopScript  -Time '09:00' -Description 'Weekday 09:00 stop Sunlogin/AweSun remote tool'
New-Task -Name $TaskStartName -ScriptPath $StartScript -Time '18:00' -Description 'Weekday 18:00 start Sunlogin/AweSun remote tool'

Write-Host ''
Write-Host '=== Final tasks ==='
Get-ScheduledTask -TaskName $TaskStopName, $TaskStartName |
    Select-Object TaskName, State, @{n='RunLevel';e={$_.Principal.RunLevel}}, @{n='NextRun';e={(Get-ScheduledTaskInfo -TaskName $_.TaskName).NextRunTime}} |
    Format-Table -AutoSize
