$ErrorActionPreference = 'SilentlyContinue'

Write-Output '=== AweSun/Sunlogin processes ==='
Get-Process | Where-Object { $_.ProcessName -match 'AweSun|Sunlogin|awesun_guard' } |
    Select-Object ProcessName, Id, Path |
    Format-Table -AutoSize | Out-String

Write-Output ''
Write-Output '=== Try killing one to see error ==='
$p = Get-Process -Name 'awesun_guard' -ErrorAction SilentlyContinue | Select-Object -First 1
if ($p) {
    try {
        Stop-Process -Id $p.Id -Force -ErrorAction Stop
        Write-Output "Killed $($p.Id) OK"
    } catch {
        Write-Output "FAILED to kill $($p.Id): $($_.Exception.Message)"
    }
} else {
    Write-Output 'no awesun_guard process'
}

Write-Output ''
Write-Output '=== Current process elevation ==='
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
$isAdmin = $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
Write-Output "User: $($identity.Name)  IsAdmin(elevated): $isAdmin"

Write-Output ''
Write-Output '=== Owner of AweSun process ==='
Get-CimInstance Win32_Process -Filter "Name='AweSun.exe' OR Name='awesun_guard.exe'" |
    ForEach-Object {
        $owner = Invoke-CimMethod -InputObject $_ -MethodName GetOwner
        Write-Output ("pid={0} name={1} owner={2}\{3}" -f $_.ProcessId, $_.Name, $owner.Domain, $owner.User)
    }
