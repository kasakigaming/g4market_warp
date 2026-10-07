# SteamDNS

App nhỏ cho Windows: bật/tắt bypass chặn Steam bằng NRPT (Name Resolution Policy Table).
Chỉ các domain của Steam được hỏi qua Google DNS (8.8.8.8 / 8.8.4.4); DNS của Wi-Fi giữ nguyên,
các trang khác vẫn đi DNS router.

- Bật/tắt xong, nếu Steam đang mở app sẽ tự thoát hẳn Steam rồi mở lại.
- Hiện trạng thái kết nối Steam, DNS đang dùng và IP Steam phân giải được.
- Giao diện tối có hiệu ứng mượt, kèm banner G4Market.
- Cần quyền admin (exe tự hỏi UAC khi mở).

Sản phẩm miễn phí cho cộng đồng [g4market.com](https://g4market.com/). Nếu bạn phải trả tiền
mua lại từ bất kỳ ai thì chắc chắn đó là lừa đảo.

## Chạy

Tải `SteamDNS.exe` và mở. Hoặc chạy từ mã nguồn:

```
pip install pillow
pythonw steam_dns.pyw
```

`DnsToggle.ps1` là bản PowerShell cũ (có thêm `-On` / `-Off` để bật/tắt không cần giao diện).

## Build exe

```
pip install pyinstaller pillow
pyinstaller --onefile --windowed --uac-admin --icon steam_dns.ico --name SteamDNS ^
  --add-data "assets/g4market_logo.png;assets" ^
  --exclude-module numpy --exclude-module PIL.ImageQt --exclude-module PyQt5 ^
  --exclude-module PyQt6 --exclude-module PySide6 --exclude-module olefile steam_dns.pyw
```
