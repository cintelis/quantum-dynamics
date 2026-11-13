<#
Copy the dashboard to the VM:   .\deploy\push.ps1  [-Target user@host] [-Key ~\.ssh\key] [-Dest ~/quantum] [-WithEnv] [-Up]
Target and Key default to QUANTUM_VM and QUANTUM_VM_KEY in deploy\.env (kept out of git).
Then on the VM: cd ~/quantum/deploy && docker compose up -d --build   (see README.md)
The VM's .env (tunnel token) is left alone, unless -WithEnv copies this PC's deploy\.env over (first deploy).
#>
param([string]$Target, [string]$Key, [string]$Dest = "~/quantum", [switch]$WithEnv, [switch]$Up)   # -Up: rebuild and restart on the VM too
$ErrorActionPreference = "Stop"
$envFile = Join-Path $PSScriptRoot ".env"
$cfg = @{}
if (Test-Path $envFile) { Get-Content $envFile | Where-Object { $_ -match '^\s*(QUANTUM_VM\w*)=(.*)$' } | ForEach-Object { $cfg[$Matches[1]] = $Matches[2].Trim() } }
if (-not $Target) { $Target = $cfg["QUANTUM_VM"] }
if (-not $Key) { $Key = $cfg["QUANTUM_VM_KEY"] -replace '^~', $HOME }
if (-not $Target -or -not $Key) { throw "Set -Target and -Key, or QUANTUM_VM and QUANTUM_VM_KEY in deploy\.env" }
$Here = Split-Path -Parent $PSScriptRoot
$tgz = Join-Path $env:TEMP "quantum-push.tgz"
& tar -czf $tgz -C $Here --exclude=__pycache__ --exclude=output --exclude=aws --exclude=.git --exclude=deploy/.env --exclude="deploy/access_*" --exclude=deploy/PRIVATE-NOTES.md .
if ($LASTEXITCODE) { throw "tar failed" }
& ssh -i $Key $Target "mkdir -p $Dest"
& scp -i $Key $tgz "${Target}:$Dest/../quantum-push.tgz"
if ($LASTEXITCODE) { throw "scp failed" }
& ssh -i $Key $Target "tar -xzf $Dest/../quantum-push.tgz -C $Dest && rm $Dest/../quantum-push.tgz && sed -i 's/\r$//' $Dest/*.sh"
Remove-Item $tgz
if ($WithEnv) {
  & scp -i $Key (Join-Path $PSScriptRoot ".env") "${Target}:$Dest/deploy/.env"
  if ($LASTEXITCODE) { throw "copying .env failed" }
  & ssh -i $Key $Target "chmod 600 $Dest/deploy/.env"
}
if ($Up) {
  # docker writes progress to stderr, which Windows PowerShell 5.1 treats as an error: merge it on the VM side
  & ssh -i $Key $Target "cd $Dest/deploy && docker compose up -d --build --quiet-build 2>&1 && docker compose ps 2>&1"
  if ($LASTEXITCODE) { throw "rebuild on the VM failed" }
  Write-Host "Updated and restarted on ${Target}."
} else {
  Write-Host "Copied to ${Target}:$Dest. Next, on the VM: cd $Dest/deploy && docker compose up -d --build   (or rerun with -Up)"
}
