# bootstrap_elevate.ps1
# Launch register_tasks_elevated.ps1 in an elevated (Administrator) PowerShell.
# Triggers a UAC prompt. Waits for the elevated process to finish and shows its output.

$target = 'D:\dev\code\shell\sunlogin_schedule\register_tasks_elevated.ps1'
$logFile = 'D:\dev\code\shell\sunlogin_schedule\logs\register_output.txt'

$logDir = Split-Path $logFile -Parent
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir -Force | Out-Null }
if (Test-Path $logFile) { Remove-Item $logFile -Force }

Write-Host "Launching elevated PowerShell (UAC prompt will appear)..."
$argList = @(
    '-NoProfile',
    '-ExecutionPolicy', 'Bypass',
    '-Command',
    "& { & '$target' *>&1 | Tee-Object -FilePath '$logFile' }"
)

$proc = Start-Process -FilePath 'powershell.exe' -ArgumentList $argList -Verb RunAs -PassThru -Wait
Write-Host "Elevated process exited with code: $($proc.ExitCode)"

Write-Host ''
Write-Host '=== Elevated run output ==='
if (Test-Path $logFile) {
    Get-Content $logFile
} else {
    Write-Host '(no output file produced)'
}
