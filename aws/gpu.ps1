<#
Run the quantum dashboard on an NVIDIA GPU in your AWS account.

  .\aws\gpu.ps1 up        # launch a GPU instance (Deep Learning AMI, NVIDIA drivers preinstalled)
  .\aws\gpu.ps1 deploy    # copy the code, install CUDA-Q, start the dashboard on the instance
  .\aws\gpu.ps1 chain     # spin chain on the GPU: exact up to ~31 spins, 100 spins as an MPS -> data/ibm/chain_gpu.json
  .\aws\gpu.ps1 tunnel    # open http://localhost:8766 -> dashboard on the GPU (leave this window open)
  .\aws\gpu.ps1 status    # show instance state, IP and hourly-billing reminder
  .\aws\gpu.ps1 stop      # stop the instance (no GPU charges; disk is kept, small storage cost)
  .\aws\gpu.ps1 down      # terminate the instance and delete the security group

Prerequisites: `aws login` (or `aws sso login`) so the AWS CLI has a session, and a
GPU quota above zero ("Running On-Demand G and VT instances"; `up` checks this).

Security: the instance only accepts SSH from your current public IP. The dashboard
binds to 127.0.0.1 on the instance and is reached only through the SSH tunnel.
#>
param(
  [Parameter(Position = 0)][ValidateSet("up", "deploy", "chain", "tunnel", "status", "stop", "down")][string]$Action = "status",
  [string]$Region = $(aws configure get region),
  [string[]]$InstanceTypes = @("g6.xlarge", "g5.xlarge", "g4dn.xlarge"),  # first one offered in the region wins
  [int]$LocalPort = 8766
)
$ErrorActionPreference = "Stop"
$Name = "quantum-lab"
$KeyPath = Join-Path $HOME ".ssh\$Name.pem"
$Here = Split-Path -Parent $PSScriptRoot   # the quantum/ folder
if (-not $Region) { $Region = "ap-southeast-2" }

function Aws { param([Parameter(ValueFromRemainingArguments)]$a) $out = & aws @a --region $Region --output json; if ($LASTEXITCODE) { throw "aws $($a -join ' ') failed" }; if ($out) { $out | ConvertFrom-Json } }

function Get-Instance {
  $r = Aws ec2 describe-instances --filters "Name=tag:Name,Values=$Name" "Name=instance-state-name,Values=pending,running,stopping,stopped"
  $r.Reservations | ForEach-Object { $_.Instances } | Select-Object -First 1
}

function Ssh-Args($ip) { @("-i", $KeyPath, "-o", "StrictHostKeyChecking=accept-new", "-o", "ServerAliveInterval=30", "ubuntu@$ip") }

# make sure the CLI has a live session before doing anything
& aws sts get-caller-identity --region $Region --output json *> $null
if ($LASTEXITCODE) { throw "AWS CLI session missing or expired. Run 'aws login' (or 'aws sso login') first." }

switch ($Action) {
  "up" {
    $existing = Get-Instance
    if ($existing -and $existing.State.Name -eq "stopped") {
      Aws ec2 start-instances --instance-ids $existing.InstanceId | Out-Null
      & aws ec2 wait instance-running --instance-ids $existing.InstanceId --region $Region
      Write-Host "Restarted $($existing.InstanceId) at $((Get-Instance).PublicIpAddress). Run 'deploy' to start the dashboard again."
      break
    }
    if ($existing) { Write-Host "Instance already exists ($($existing.State.Name)). Use 'status', 'deploy' or 'down'."; break }

    # 1. GPU quota (vCPUs for G instances; xlarge = 4 vCPUs)
    try {
      $q = (Aws service-quotas get-service-quota --service-code ec2 --quota-code L-DB2E81BA).Quota.Value
      if ($q -lt 4) { throw "Your GPU quota (Running On-Demand G and VT instances) is $q vCPUs in $Region. Request at least 4 in the Service Quotas console, then retry." }
      Write-Host "GPU quota: $q vCPUs"
    } catch { if ($_.Exception.Message -like "*quota*vCPUs*") { throw } else { Write-Warning "Could not read GPU quota ($($_.Exception.Message)); continuing." } }

    # 2. instance type actually offered here
    $offered = (Aws ec2 describe-instance-type-offerings --location-type region --filters "Name=instance-type,Values=$($InstanceTypes -join ',')").InstanceTypeOfferings.InstanceType
    $type = $InstanceTypes | Where-Object { $offered -contains $_ } | Select-Object -First 1
    if (-not $type) { throw "None of $($InstanceTypes -join ', ') is offered in $Region." }

    # 3. Deep Learning Base AMI (Ubuntu 22.04, NVIDIA driver + CUDA preinstalled)
    $ami = $null
    try { $ami = (Aws ssm get-parameter --name "/aws/service/deeplearning/ami/x86_64/base-oss-nvidia-driver-gpu-ubuntu-22.04/latest/ami-id").Parameter.Value } catch {}
    if (-not $ami) {
      $imgs = (Aws ec2 describe-images --owners amazon --filters "Name=name,Values=Deep Learning Base OSS Nvidia Driver GPU AMI (Ubuntu 22.04)*" "Name=state,Values=available").Images
      $ami = ($imgs | Sort-Object CreationDate -Descending | Select-Object -First 1).ImageId
    }
    if (-not $ami) { throw "Could not find the AWS Deep Learning Base GPU AMI in $Region." }

    # 4. key pair (saved to ~/.ssh, readable only by you)
    if (-not (Test-Path $KeyPath)) {
      New-Item -ItemType Directory -Force (Split-Path $KeyPath) | Out-Null
      $k = Aws ec2 create-key-pair --key-name $Name --key-type ed25519
      Set-Content -Path $KeyPath -Value $k.KeyMaterial -NoNewline -Encoding ascii
      icacls $KeyPath /inheritance:r /grant:r "$($env:USERNAME):(R)" | Out-Null
    }

    # 5. security group: SSH from your IP only
    $vpc = (Aws ec2 describe-vpcs --filters "Name=isDefault,Values=true").Vpcs[0].VpcId
    if (-not $vpc) { throw "No default VPC in $Region." }
    $sg = (Aws ec2 describe-security-groups --filters "Name=group-name,Values=$Name-sg" "Name=vpc-id,Values=$vpc").SecurityGroups | Select-Object -First 1
    if (-not $sg) { $sgId = (Aws ec2 create-security-group --group-name "$Name-sg" --description "quantum-lab SSH from one IP" --vpc-id $vpc).GroupId } else { $sgId = $sg.GroupId }
    $myIp = (Invoke-RestMethod "https://checkip.amazonaws.com").Trim()
    try { Aws ec2 authorize-security-group-ingress --group-id $sgId --protocol tcp --port 22 --cidr "$myIp/32" | Out-Null } catch {}

    # 6. launch
    Write-Host "Launching $type with $ami in $Region (SSH allowed from $myIp only)..."
    $bdm = '[{"DeviceName":"/dev/sda1","Ebs":{"VolumeSize":100,"VolumeType":"gp3","DeleteOnTermination":true}}]'
    $tags = "ResourceType=instance,Tags=[{Key=Name,Value=$Name}]"
    $inst = (Aws ec2 run-instances --image-id $ami --instance-type $type --key-name $Name --security-group-ids $sgId `
             --block-device-mappings $bdm --tag-specifications $tags --count 1).Instances[0]
    & aws ec2 wait instance-running --instance-ids $inst.InstanceId --region $Region
    $ip = (Get-Instance).PublicIpAddress
    Write-Host "Running: $($inst.InstanceId) at $ip. Billing by the hour has started."
    Write-Host "Next: .\aws\gpu.ps1 deploy   (give it ~1 minute to finish booting)"
  }

  "deploy" {
    $i = Get-Instance; if (-not $i -or $i.State.Name -ne "running") { throw "No running instance. Use 'up' first." }
    $ip = $i.PublicIpAddress
    # the whole project (pages, models, data), without caches and rendered images
    $tgz = Join-Path $env:TEMP "quantum-deploy.tgz"
    & tar -czf $tgz -C $Here --exclude=__pycache__ --exclude=output --exclude=aws .
    if ($LASTEXITCODE) { throw "tar failed" }
    & ssh @(Ssh-Args $ip) "mkdir -p ~/quantum"
    & scp -i $KeyPath -o StrictHostKeyChecking=accept-new $tgz "ubuntu@${ip}:~/quantum.tgz"
    if ($LASTEXITCODE) { throw "scp failed" }
    & ssh @(Ssh-Args $ip) "tar -xzf ~/quantum.tgz -C ~/quantum && mkdir -p ~/quantum/output"
    Remove-Item $tgz
    # install CUDA-Q (same script as WSL), confirm the GPU, start the dashboard bound to localhost
    $remote = @'
set -e
cd ~/quantum
sed -i 's/\r$//' *.sh
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader
[ -x ~/cudaq-env/bin/python ] || bash setup_wsl.sh
pkill -f dashboard.py || true
HOST=127.0.0.1 nohup ~/cudaq-env/bin/python -W ignore dashboard.py > dashboard.log 2>&1 &
sleep 8; tail -n 3 dashboard.log
~/cudaq-env/bin/python -W ignore sim.py --model cavity --backend both --steps 101 | tail -n 6
'@
    $remote | & ssh @(Ssh-Args $ip) "bash -s"
    Write-Host "`nDashboard is up on the GPU. Next: .\aws\gpu.ps1 tunnel"
  }

  "chain" {
    $i = Get-Instance; if (-not $i -or $i.State.Name -ne "running") { throw "No running instance. Use 'up' and 'deploy' first." }
    $ip = $i.PublicIpAddress
    & ssh @(Ssh-Args $ip) "cd ~/quantum && ~/cudaq-env/bin/python -W ignore ibm/chain_gpu.py"
    if ($LASTEXITCODE) { throw "GPU spin-chain run failed" }
    & scp -i $KeyPath "ubuntu@${ip}:~/quantum/data/ibm/chain_gpu.json" (Join-Path $Here "data\ibm\chain_gpu.json")
    Write-Host "Copied data/ibm/chain_gpu.json back. Remember: 'stop' or 'down' when finished."
  }

  "tunnel" {
    $i = Get-Instance; if (-not $i -or $i.State.Name -ne "running") { throw "No running instance." }
    Write-Host "Open http://localhost:$LocalPort  (Ctrl+C here closes the tunnel; the instance keeps running)"
    & ssh @(Ssh-Args $i.PublicIpAddress) -N -L "${LocalPort}:127.0.0.1:8765"
  }

  "status" {
    $i = Get-Instance
    if (-not $i) { Write-Host "No $Name instance in $Region."; break }
    Write-Host "$($i.InstanceId)  $($i.InstanceType)  $($i.State.Name)  $($i.PublicIpAddress)  launched $($i.LaunchTime)"
    if ($i.State.Name -eq "running") { Write-Host "Reminder: a running GPU instance bills by the hour. Use 'stop' or 'down' when finished." }
  }

  "stop" {
    $i = Get-Instance; if (-not $i) { Write-Host "Nothing to stop."; break }
    Aws ec2 stop-instances --instance-ids $i.InstanceId | Out-Null
    Write-Host "Stopping $($i.InstanceId). GPU billing stops; the 100 GB disk is kept (small storage charge). Run 'up' to start it again, or 'down' to delete it."
  }

  "down" {
    $i = Get-Instance
    if ($i) {
      Aws ec2 terminate-instances --instance-ids $i.InstanceId | Out-Null
      & aws ec2 wait instance-terminated --instance-ids $i.InstanceId --region $Region
      Write-Host "Terminated $($i.InstanceId)."
    }
    $sg = (Aws ec2 describe-security-groups --filters "Name=group-name,Values=$Name-sg").SecurityGroups | Select-Object -First 1
    if ($sg) { Aws ec2 delete-security-group --group-id $sg.GroupId | Out-Null; Write-Host "Deleted security group $($sg.GroupId)." }
    Write-Host "Key pair '$Name' and $KeyPath are kept for next time."
  }
}
