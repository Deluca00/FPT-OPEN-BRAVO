' FPT Warehouse Scanner - Auto Start Script
' Chạy ẩn không hiện cửa sổ CMD
' Khởi động cả Barcode App và Cloudflare Tunnels

Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = "C:\openbravo_installation\openbravo-release-24Q2\barcode_app"

' 1. Chạy Barcode App (ẩn)
WshShell.Run "cmd /c python app.py", 0, False

' Đợi 5 giây để app khởi động hoàn toàn
WScript.Sleep 5000

' 2. Chạy Cloudflare Tunnels script (ẩn) - tự động lấy URL và cập nhật config
WshShell.Run "cmd /c python cloudflare_tunnels.py", 0, False
