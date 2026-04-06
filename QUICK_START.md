# 🚀 RTSP Camera - Quick Start Guide

## ⚡ 5 Bước Để Khởi Động

### 1️⃣ **Cài Đặt Dependencies**
```bash
cd barcode_app
pip install -r requirements.txt
```

### 2️⃣ **Kiểm Tra Camera Configuration**
Mở `app.py`, đảm bảo camera URLs chính xác:

```python
RTSP_CAMERAS = {
    '100': {
        'name': 'Camera 100 - Box Check',
        'url': 'rtsp://admin:L212A477@172.16.251.100:554/cam/realmonitor?channel=1&subtype=0',
        'type': 'box'
    },
    '101': {
        'name': 'Camera 101 - Defect Detection',
        'url': 'rtsp://admin:L27EEFF1@172.16.251.101:554/cam/realmonitor?channel=1&subtype=0',
        'type': 'defect'
    }
}
```

✅ **Đã Cấu Hình Sẵn!**

### 3️⃣ **Khởi Động App**
```bash
python app.py
```

**Kết Quả:**
```
🚀 Openbravo Barcode Scanner App
📦 Database: openbravo@localhost:5432

📹 INITIALIZING RTSP CAMERAS
✅ Camera 100 - Box Check
✅ Camera 101 - Defect Detection
```

### 4️⃣ **Truy Cập Camera Control Panel**
Mở browser: **http://localhost:5000/static/camera-control.html**

![Camera Panel Interface]
```
┌─────────────────────────────────────────────────┐
│  📹 RTSP Camera Control Panel                    │
│  FPT Warehouse - Real-time Management & AI      │
└─────────────────────────────────────────────────┘
├─ Status: ✅ All cameras online
├─ Cameras: 2
│
├─ Camera 100 - Box Check
│  ├─ [Live Feed Preview]
│  ├─ [▶ Start] [⏹ Stop] [📷 Capture]
│  └─ Status: ✅ Running
│
├─ Camera 101 - Defect Detection
│  ├─ [Live Feed Preview]
│  ├─ [▶ Start] [⏹ Stop] [📷 Capture]
│  └─ Status: ✅ Running
│
└─ 🤖 AI Detection
   ├─ Select Camera: [Camera 101 ▼]
   ├─ Detection Type: [Defect Detection ▼]
   └─ [🔍 Run AI Detection]
```

### 5️⃣ **Test Camera Feed**
Đơn cử nhất - mở terminal:

```bash
# Lấy frame hiện tại từ camera
curl http://localhost:5000/api/camera/101/frame > test.jpg

# Xem ảnh để verify nó hoạt động
start test.jpg  # Windows
# open test.jpg  # macOS
# xdg-open test.jpg  # Linux
```

---

## 🎮 Điều Khiển Camera

### Via Web UI (Dễ Nhất - Khuyến Nghị)
1. Mở: `http://localhost:5000/static/camera-control.html`
2. Bấm nút "▶ Start" để khởi động camera
3. Xem live video feed
4. Bấm "🔍 Run AI Detection" để phân tích ảnh

### Via API (Nâng Cao)

**Lấy Trạng Thái Tất Cả Cameras:**
```bash
curl http://localhost:5000/api/camera/status | jq
```

**Bắt Đầu/Dừng Camera 101:**
```bash
# Start
curl -X POST http://localhost:5000/api/camera/101/start

# Stop
curl -X POST http://localhost:5000/api/camera/101/stop
```

**Lấy Frame Từ Camera:**
```bash
curl http://localhost:5000/api/camera/101/frame \
  --output camera_frame.jpg
```

**Run AI Detection:**
```bash
curl -X POST http://localhost:5000/api/ai-detect \
  -H "Content-Type: application/json" \
  -d '{
    "type": "defect",
    "camera_id": "101"
  }' | jq
```

---

## 📋 Các Endpoints Chính

### Quản Lý Camera
| Command | URL |
|---------|-----|
| List cameras | `GET /api/camera/list` |
| Get status | `GET /api/camera/status` |
| Start camera | `POST /api/camera/{id}/start` |
| Stop camera | `POST /api/camera/{id}/stop` |

### Capture & Streaming
| Command | URL |
|---------|-----|
| Get frame (JPEG) | `GET /api/camera/{id}/frame` |
| Video stream (MJPEG) | `GET /api/camera/{id}/video-feed` |
| Capture snapshot | `POST /api/camera/{id}/capture` |

### AI Detection
| Command | URL |
|---------|-----|
| Run detection | `POST /api/ai-detect` |

---

## 🐛 Troubleshooting

### ❓ "OpenCV not available"
```bash
pip install opencv-python
# hoặc
pip install -r requirements.txt
```

### ❓ "Cannot connect to RTSP stream"
1. **Kiểm tra URL:** Ensure `172.16.251.100` ping được
   ```bash
   ping 172.16.251.100
   ```

2. **Kiểm tra Credentials:** Username/password đúng chứ?
   ```
   rtsp://admin:PASSWORD@IP:554/...
   ```

3. **Kiểm tra Firewall:** Port 554 không bị block
   ```bash
   telnet 172.16.251.100 554
   ```

### ❓ "No frame available"
- Camera đã start chưa? `POST /api/camera/101/start`
- Check status: `GET /api/camera/status`
- Chờ 2-3 giây để stream initialize

### ❓ "AI detection failed"
- Camera đang chạy chứa? 
- Có YOLO model files không?
- Check logs: `GET /api/camera/status`

---

## 📊 Kiểm Tra Hệ Thống

### Health Check Script
```bash
echo "=== Checking App ===" 
curl -s http://localhost:5000/api/camera/list | jq '.total'

echo "=== Checking Cameras ===" 
curl -s http://localhost:5000/api/camera/status | jq '.cameras'

echo "=== Testing Frame Capture ==="
curl -s http://localhost:5000/api/camera/101/frame -o /dev/null && echo "✅ Success" || echo "❌ Failed"
```

---

## 🎯 Common Tasks

### View Live Camera 101
```html
<img src="http://localhost:5000/api/camera/101/video-feed" />
```

### Capture & Save to File
```python
import requests
import base64

# Capture dari camera
response = requests.post('http://localhost:5000/api/camera/101/capture')
data = response.json()
image_base64 = data['image']

# Save to file
with open('captured.jpg', 'wb') as f:
    f.write(base64.b64decode(image_base64.split(',')[1]))
```

### Run AI Detection & Get Results
```python
import requests
import json

response = requests.post(
    'http://localhost:5000/api/ai-detect',
    json={
        'type': 'defect',
        'camera_id': '101'
    }
)

results = response.json()
print(json.dumps(results, indent=2))
```

---

## 🎬 Demo Video

**Step-by-step:** `http://localhost:5000/static/camera-control.html`

1. ✅ Cameras automatically start
2. ✅ Live feed displays in real-time
3. ✅ Click "Run AI Detection" to analyze
4. ✅ Results show in JSON format

---

## 📞 Getting Help

1. **Check Camera Status**
   ```bash
   curl http://localhost:5000/api/camera/status
   ```

2. **Check App Logs**
   - Look at terminal output của app.py

3. **Read Documentation**
   - `CAMERA_SETUP.md` - Detailed technical guide
   - `IMPLEMENTATION.md` - What was added
   - `API.md` (if exists) - Full API reference

---

## ✅ Verification Checklist

- [ ] `pip install -r requirements.txt` completed
- [ ] Camera URLs verified in `app.py`
- [ ] `python app.py` started successfully
- [ ] Both cameras show ✅ status
- [ ] Web UI loads at `http://localhost:5000/static/camera-control.html`
- [ ] Can see live video feeds
- [ ] AI detection runs without errors
- [ ] Frames capture correctly

---

## 🚀 Next Steps

1. **Integration:**
   - Add camera endpoints to your frontend
   - Display live feeds in dashboard
   - Trigger AI detection on demand

2. **Advanced:**
   - Set up recording
   - Add motion detection
   - Create detection alerts
   - Store results in database

3. **Production:**
   - Set up SSL/HTTPS
   - Add authentication
   - Configure logging
   - Setup monitoring

---

**Ready? Start with Step 1 above! 🚀**

