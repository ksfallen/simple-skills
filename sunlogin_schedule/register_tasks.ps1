# register_tasks.ps1
# Register two Windows Scheduled Tasks:
#   SunloginStop-Weekday0900  -> Mon-Fri 09:00 -> sunlogin_stop.ps1
#   SunloginStart-Weekday1800 -> Mon-Fri 18:00 -> sunlogin_start.ps1
# Requires: run in elevated PowerShell if you want -RunLevel Highest; otherwise runs Limited.

$ErrorActionPreference = 'Stop'

$ScriptDir = 'D:\dev\code\shell\sunlogin_schedule'
$StopScript  = Join-Path $ScriptDir 'sunlogin_stop.ps1'
$StartScript = Join-Path $ScriptDir 'sunlogin_start.ps1'
$PsExe = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"

$TaskStopName  = 'SunloginStop-Weekday0900'
$TaskStartName = 'SunloginStart-Weekday1800'

# Determine if we can register Highest run level
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
$runLevel = if ($isAdmin) { 'Highest' } else { 'Limited' }
Write-Host "Admin: $isAdmin  RunLevel: $runLevel"

function New-Task {
    param(
        [string]$Name,
        [string]$ScriptPath,
        [string]$Time,   # 'HH:mm'
        [string]$Description
    )

    # Remove existing
    if (Get-ScheduledTask -TaskName $Name -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $Name -Confirm:$false
        Write-Host "Removed existing task: $Name"
    }

    $action = New-ScheduledTaskAction -Execute $PsExe `
        -Argument ('-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "{0}"' -f $ScriptPath) `
        -WorkingDirectory $ScriptDir

    # Weekly trigger Mon-Fri at $Time
    $trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At $Time

    # Run whether or not user is logged on requires password; use interactive-only so GUI shows
    $principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel $runLevel

    $settings = New-ScheduledTaskSettingsSet `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries `
        -StartWhenAvailable `
        -WakeToRun:$false `
        -MultipleInstances IgnoreNew `
        -ExecutionTimeLimit (New-TimeSpan -Minutes 10)

    Register-ScheduledTask -TaskName $Name `
        -Action $action `
        -Trigger $trigger `
        -Principal $principal `
        -Settings $settings `
        -Description $Description `
        -Force | Out-Null

    Write-Host "Registered: $Name -> $ScriptPath @ $Time (Mon-Fri)"
}

New-Task -Name $TaskStopName  -ScriptPath $StopScript  -Time '09:00' -Description 'Weekday 09:00 stop Sunlogin/AweSun remote tool'
New-Task -Name $TaskStartName -ScriptPath $StartScript -Time '18:00' -Description 'Weekday 18:00 start Sunlogin/AweSun remote tool'

Write-Host ''
Write-Host '=== Registered tasks ==='
Get-ScheduledTask -TaskName $TaskStopName, $TaskStartName |
    Select-Object TaskName, State, @{n='NextRun';e={(Get-ScheduledTaskInfo -TaskName $_.TaskName).NextRunTime}} |
    Format-Table -AutoSize
