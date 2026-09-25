# 把 api.erucmoney.com 用 Cloudflare Tunnel 接到本機 Node.js :3001，並裝成 Windows 服務（階段 3）
#
# 前提：erucmoney.com 的 DNS 已經在 Cloudflare（網域在 Cloudflare 買的就是）。
# 需要系統管理員 PowerShell（cloudflared service install 要寫服務）。
#
#   powershell -ExecutionPolicy Bypass -File Deploy\install_tunnel.ps1
#
# 步驟（互動的部分會開瀏覽器，請自己按）：
#   1. winget 安裝 cloudflared
#   2. cloudflared tunnel login        → 瀏覽器選 erucmoney.com 授權，產生 ~/.cloudflared/cert.pem
#   3. cloudflared tunnel create money → 產生 <id>.json 憑證
#   4. 寫 ~/.cloudflared/config.yml（ingress 只有 3001）
#   5. cloudflared tunnel route dns money api.erucmoney.com   → 自動加 CNAME
#   6. cloudflared service install     → 開機常駐；日誌在事件檢視器
# 重跑是安全的：已存在的隧道與 DNS 會沿用。
#
# 移除：cloudflared service uninstall；cloudflared tunnel delete money

$ErrorActionPreference = 'Stop'
$TunnelName = 'money'
$Hostname   = 'api.erucmoney.com'
$Here       = Split-Path -Parent $MyInvocation.MyCommand.Path
$CfDir      = Join-Path $env:USERPROFILE '.cloudflared'

if (-not (Get-Command cloudflared -ErrorAction SilentlyContinue)) {
    Write-Host '[1/6] 安裝 cloudflared（winget）'
    winget install --id Cloudflare.cloudflared -e --accept-source-agreements --accept-package-agreements
    $env:Path = [System.Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [System.Environment]::GetEnvironmentVariable('Path', 'User')
}
Write-Host ("cloudflared " + (cloudflared --version))

if (-not (Test-Path (Join-Path $CfDir 'cert.pem'))) {
    Write-Host '[2/6] 登入 Cloudflare（會開瀏覽器，選 erucmoney.com）'
    cloudflared tunnel login
}

$list = cloudflared tunnel list --output json | ConvertFrom-Json
$t = $list | Where-Object { $_.name -eq $TunnelName }
if (-not $t) {
    Write-Host "[3/6] 建立隧道 $TunnelName"
    cloudflared tunnel create $TunnelName | Out-Null
    $list = cloudflared tunnel list --output json | ConvertFrom-Json
    $t = $list | Where-Object { $_.name -eq $TunnelName }
}
$TunnelId = $t.id
$Cred = Join-Path $CfDir "$TunnelId.json"
if (-not (Test-Path $Cred)) { throw "找不到憑證 $Cred（隧道可能是在別台機器建的，先 cloudflared tunnel delete $TunnelName 再重跑）" }
Write-Host "隧道 $TunnelName = $TunnelId"

Write-Host '[4/6] 寫 config.yml'
$cfg = [IO.File]::ReadAllText((Join-Path $Here 'cloudflared-config.yml'))
$cfg = $cfg.Replace('<TUNNEL_ID>', $TunnelId).Replace('<CREDENTIALS_FILE>', $Cred.Replace('\', '/'))
[IO.File]::WriteAllText((Join-Path $CfDir 'config.yml'), $cfg, (New-Object System.Text.UTF8Encoding $false))

Write-Host "[5/6] DNS：$Hostname → 隧道"
cloudflared tunnel route dns $TunnelName $Hostname 2>&1 | ForEach-Object { Write-Host "  $_" }

Write-Host '[6/6] 裝成 Windows 服務'
$svc = Get-Service cloudflared -ErrorAction SilentlyContinue
if ($svc) { Write-Host '  服務已存在，重新啟動'; Restart-Service cloudflared }
else { cloudflared service install; Start-Service cloudflared }
Start-Sleep -Seconds 5
Write-Host ("服務狀態：" + (Get-Service cloudflared).Status)
Write-Host "測試：curl https://$Hostname/health   （Node :3001 要先啟動）"
