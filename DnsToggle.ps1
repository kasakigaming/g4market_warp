# Steam DNS - bật/tắt bypass chặn Steam bằng NRPT (Name Resolution Policy Table).
# Chỉ các domain của Steam được hỏi qua Google DNS; DNS của Wi-Fi giữ nguyên, các trang khác vẫn đi DNS router.
# Dùng: chạy không tham số để mở giao diện, hoặc -On / -Off để bật/tắt không cần giao diện.
param([switch]$On, [switch]$Off)

$principal = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    $argList = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-WindowStyle', 'Hidden', '-File', "`"$PSCommandPath`"")
    if ($On) { $argList += '-On' }
    if ($Off) { $argList += '-Off' }
    try { Start-Process powershell.exe -Verb RunAs -WindowStyle Hidden -ArgumentList $argList -Wait:($On -or $Off) }
    catch { }  # người dùng bấm No ở UAC
    exit
}

$RuleName  = 'SteamDNS'
$Resolvers = @('8.8.8.8', '8.8.4.4')
$Domains   = @('steampowered.com', 'steamcommunity.com', 'steamstatic.com', 'steamserver.net', 'steamcontent.com',
               'steamusercontent.com', 's.team', 'steam-chat.com', 'steamgames.com', 'valvesoftware.com',
               'steamdeck.com', 'akamaihd.net')
# NRPT: "x.com" khớp đúng tên miền, ".x.com" khớp mọi subdomain -> thêm cả hai.
$Namespaces = $Domains | ForEach-Object { $_; ".$_" }

function Test-Bypass { [bool](Get-DnsClientNrptRule | Where-Object DisplayName -eq $RuleName) }

function Enable-Bypass {
    Disable-Bypass
    Add-DnsClientNrptRule -Namespace $Namespaces -NameServers $Resolvers -DisplayName $RuleName `
        -Comment 'Bypass nhà mạng chặn Steam qua DNS' -ErrorAction Stop
    Clear-DnsClientCache
}

function Disable-Bypass {
    Get-DnsClientNrptRule | Where-Object DisplayName -eq $RuleName |
        ForEach-Object { Remove-DnsClientNrptRule -Name $_.Name -Force }
    Clear-DnsClientCache
}

if ($On)  { Enable-Bypass;  exit }
if ($Off) { Disable-Bypass; exit }

Add-Type -AssemblyName System.Windows.Forms, System.Drawing
[Windows.Forms.Application]::EnableVisualStyles()

$Green = [Drawing.Color]::FromArgb(22, 128, 61)
$Red   = [Drawing.Color]::FromArgb(185, 28, 28)
$Gray  = [Drawing.Color]::FromArgb(110, 110, 110)

function Get-SteamStatus {
    Clear-DnsClientCache
    try {
        $ips = @(Resolve-DnsName api.steampowered.com -QuickTimeout -ErrorAction Stop |
                 Where-Object IPAddress | ForEach-Object IPAddress)
    } catch { return 'Steam: không phân giải được', $Gray }
    if (-not $ips) { return 'Steam: không phân giải được', $Gray }
    if ($ips | Where-Object { $_ -in '127.0.0.1', '::1', '0.0.0.0', '::' }) {
        return 'Steam: BỊ CHẶN (DNS trả về localhost)', $Red
    }
    "Steam: OK ($($ips[0]))", $Green
}

$form = New-Object Windows.Forms.Form -Property @{
    Text = 'Steam DNS'; ClientSize = New-Object Drawing.Size(340, 220)
    FormBorderStyle = 'FixedSingle'; MaximizeBox = $false; StartPosition = 'CenterScreen'
    Font = New-Object Drawing.Font('Segoe UI', 10); BackColor = [Drawing.Color]::White
}

$lblInfo = New-Object Windows.Forms.Label -Property @{
    Location = '20,14'; Size = '300,20'; ForeColor = $Gray; Font = New-Object Drawing.Font('Segoe UI', 9)
    Text = 'Chỉ domain Steam đi qua Google DNS'
}
$lblState = New-Object Windows.Forms.Label -Property @{
    Location = '20,38'; Size = '300,30'; Font = New-Object Drawing.Font('Segoe UI', 13, [Drawing.FontStyle]::Bold)
}
$btn = New-Object Windows.Forms.Button -Property @{
    Location = '20,78'; Size = '300,50'; Font = New-Object Drawing.Font('Segoe UI', 12, [Drawing.FontStyle]::Bold)
    FlatStyle = 'Flat'; ForeColor = [Drawing.Color]::White; Cursor = 'Hand'
}
$btn.FlatAppearance.BorderSize = 0
$lblSteam = New-Object Windows.Forms.Label -Property @{ Location = '20,142'; Size = '235,22' }
$lnkRefresh = New-Object Windows.Forms.LinkLabel -Property @{
    Location = '262,142'; Size = '60,22'; Text = 'Làm mới'; TextAlign = 'TopRight'
}
$lblHint = New-Object Windows.Forms.Label -Property @{
    Location = '20,172'; Size = '300,40'; ForeColor = $Gray; Font = New-Object Drawing.Font('Segoe UI', 8.5)
    Text = 'Đổi xong, nếu Steam đang mở thì thoát hẳn Steam rồi mở lại.'
}
$form.Controls.AddRange(@($lblInfo, $lblState, $btn, $lblSteam, $lnkRefresh, $lblHint))

function Update-View {
    $form.Cursor = 'WaitCursor'
    if (Test-Bypass) {
        $lblState.Text = 'Bypass Steam: ĐANG BẬT'; $lblState.ForeColor = $Green
        $btn.Text = 'TẮT'; $btn.BackColor = $Red
    } else {
        $lblState.Text = 'Bypass Steam: ĐANG TẮT'; $lblState.ForeColor = $Red
        $btn.Text = 'BẬT'; $btn.BackColor = $Green
    }
    $form.Refresh()
    $text, $color = Get-SteamStatus
    $lblSteam.Text = $text; $lblSteam.ForeColor = $color
    $form.Cursor = 'Default'
}

$btn.Add_Click({
    try {
        if (Test-Bypass) { Disable-Bypass } else { Enable-Bypass }
    } catch {
        [Windows.Forms.MessageBox]::Show("Không đổi được:`n$($_.Exception.Message)", 'Steam DNS', 'OK', 'Error') | Out-Null
    }
    Update-View
})
$lnkRefresh.Add_LinkClicked({ Update-View })
$form.Add_Shown({ Update-View })

[Windows.Forms.Application]::Run($form)
