# Cloudflare Tunnel - Hướng dẫn sử dụng

## Giới thiệu

Cloudflare Tunnel cho phép bạn truy cập Barcode App và Openbravo từ bất kỳ đâu qua Internet, không cần cùng mạng LAN.

## Cài đặt cloudflared

### Windows
```powershell
# Cách 1: Dùng winget
winget install Cloudflare.cloudflared

# Cách 2: Tải từ website
# https://developers.cloudflare.com/cloudflare-one/connections/connect-apps/install-and-setup/installation/
```

### Linux
```bash
# Debian/Ubuntu
curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb -o cloudflared.deb
sudo dpkg -i cloudflared.deb

# Hoặc dùng brew
brew install cloudflared
```

## Cách sử dụng

### Bước 1: Chạy Barcode App
```batch
cd barcode_app
python app.py
```

### Bước 2: Chạy Cloudflare Tunnels

**Cách đơn giản:** Chạy file `start_cloudflare_tunnels.bat`

**Cách thủ công:**

Mở 2 terminal và chạy:

```powershell
# Terminal 1: Tunnel cho Barcode App
cloudflared tunnel --url https://localhost:5443

# Terminal 2: Tunnel cho Openbravo
cloudflared tunnel --url http://localhost:8080
```

### Bước 3: Copy URL Tunnel

Khi chạy cloudflared, bạn sẽ thấy output như:
```
2024-01-01T12:00:00Z INF +----------------------------+
2024-01-01T12:00:00Z INF |  Your quick Tunnel has been created! 
2024-01-01T12:00:00Z INF +----------------------------+
2024-01-01T12:00:00Z INF Your tunnel is available at:
2024-01-01T12:00:00Z INF https://random-words-here.trycloudflare.com
```

Copy URL này.

### Bước 4: Cấu hình trong App

1. Mở Barcode App
2. Click nút **Chia sẻ** trên header
3. Chọn tab **Cloudflare (Internet)**
4. Click **Cấu hình ngay** hoặc **Chỉnh sửa cấu hình**
5. Paste URL tunnel vào:
   - **Barcode App URL**: URL tunnel của Barcode App
   - **Openbravo URL**: URL tunnel của Openbravo
6. Bật checkbox **Bật Cloudflare Tunnel**
7. Click **Lưu cấu hình**

### Bước 5: Chia sẻ QR Code

Giờ bạn có thể:
- Quét QR code **Barcode App** để truy cập app từ điện thoại
- Quét QR code **Openbravo ERP** để truy cập Openbravo từ điện thoại
- Chia sẻ URL cho người khác truy cập từ bất kỳ đâu!

## Lưu ý quan trọng

1. **Free Tunnel** (Quick Tunnel): URL thay đổi mỗi lần chạy cloudflared
2. **Để có URL cố định**: Đăng ký tài khoản Cloudflare và tạo Named Tunnel
3. **Bảo mật**: Tunnel mở ra Internet, cân nhắc thêm authentication
4. **Bandwidth**: Free tier có giới hạn bandwidth, phù hợp cho demo/test

## Cấu hình nâng cao

### File cấu hình: `cloudflare_config.json`

```json
{
    "enabled": true,
    "barcode_app": {
        "tunnel_url": "https://abc123.trycloudflare.com",
        "local_port": 5443,
        "description": "Barcode Scanner App"
    },
    "openbravo": {
        "tunnel_url": "https://xyz789.trycloudflare.com",
        "local_port": 8080,
        "description": "Openbravo ERP"
    }
}
```

### Tạo Named Tunnel (URL cố định)

```powershell
# Đăng nhập Cloudflare
cloudflared login

# Tạo tunnel
cloudflared tunnel create my-barcode-app

# Chạy tunnel
cloudflared tunnel run --url https://localhost:5443 my-barcode-app
```

## Troubleshooting

### Lỗi: "cloudflared not found"
- Cài đặt cloudflared và thêm vào PATH

### Lỗi: SSL Certificate
- Barcode App dùng self-signed cert, cloudflared sẽ accept nó

### Lỗi: Connection refused
- Đảm bảo Barcode App đang chạy trên port 5443
- Đảm bảo Openbravo đang chạy trên port 8080

## Liên hệ hỗ trợ

Nếu gặp vấn đề, liên hệ team IT.
