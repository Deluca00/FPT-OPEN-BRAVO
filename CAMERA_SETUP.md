# RTSP Camera Setup Guide

## Cấu Hình Camera (Hiện Tại)

Ứng dụng hiện đã được cấu hình với 2 camera RTSP:

### Camera 100 - Box Check
- **Mục đích**: Kiểm tra hộp, dây keo, hóa đơn đóng gói
- **RTSP URL**: `rtsp://admin:L212A477@172.16.251.100:554/cam/realmonitor?channel=1&subtype=0`
- **Loại**: Box detection

### Camera 101 - Defect Detection  
- **Mục đích**: Phát hiện lỗi sản phẩm
- **RTSP URL**: `rtsp://admin:L27EEFF1@172.16.251.101:554/cam/realmonitor?channel=1&subtype=0`
- **Loại**: Defect detection

---

## API Endpoints

### 1. **Lấy Trạng Thái Camera**
```bash
GET /api/camera/status
```

**Response:**
```json
{
  "success": true,
  "cameras": {
    "100": {
      "name": "Camera 100 - Box Check",
      "type": "box",
      "is_running": true,
      "has_frame": true,
      "error": null
    },
    "101": {
      "name": "Camera 101 - Defect Detection",
      "type": "defect",
      "is_running": true,
      "has_frame": true,
      "error": null
    }
  }
}
```

---

### 2. **Lấy Danh Sách Camera**
```bash
GET /api/camera/list
```

---

### 3. **Bắt Đầu Stream Camera**
```bash
POST /api/camera/{camera_id}/start
```

**Ví dụ:**
```bash
POST /api/camera/100/start
```

---

### 4. **Dừng Stream Camera**
```bash
POST /api/camera/{camera_id}/stop
```

---

### 5. **Lấy Frame Hiện Tại (JPEG)**
```bash
GET /api/camera/{camera_id}/frame
```

**Ví dụ:**
```bash
GET /api/camera/101/frame
```

**Response:** JPEG image file

---

### 6. **Video Feed Streaming (MJPEG)**
```bash
GET /api/camera/{camera_id}/video-feed
```

**Ví dụ:** Nhúng vào HTML:
```html
<img src="/api/camera/100/video-feed" width="640" height="480" />
```

---

### 7. **Chụp Ảnh từ Camera (Base64)**
```bash
POST /api/camera/{camera_id}/capture
```

**Response:**
```json
{
  "success": true,
  "camera_id": "101",
  "image": "data:image/jpeg;base64,/9j/4AAQSkZJRg...",
  "timestamp": "2026-04-06T10:30:45.123456"
}
```

---

### 8. **AI Detection từ Camera**
```bash
POST /api/ai-detect
Content-Type: application/json

{
  "type": "defect",
  "camera_id": "101"
}
```

**Hoặc với ảnh upload:**
```json
{
  "type": "box",
  "image": "data:image/jpeg;base64,/9j/4AAQSkZJRg..."
}
```

**Response:**
```json
{
  "success": true,
  "detection_type": "defect",
  "results": [
    {
      "class": "fd",
      "confidence": 0.95,
      "label": "Defect Detected"
    }
  ]
}
```

---

## Cấu Hình Camera trong App

**Tệp cấu hình:** `app.py`

Để thêm hoặc sửa đổi camera, chỉnh sửa dictionary `RTSP_CAMERAS`:

```python
RTSP_CAMERAS = {
    '100': {
        'name': 'Camera 100 - Box Check',
        'url': 'rtsp://admin:PASSWORD@IP:PORT/stream',
        'type': 'box'  # box, defect, general
    },
    '101': {
        'name': 'Camera 101 - Defect Detection',
        'url': 'rtsp://admin:PASSWORD@IP:PORT/stream',
        'type': 'defect'
    }
}
```

---

## Khởi Động App

```bash
python app.py
```

Khi khởi động, app sẽ tự động:
1. Khởi tạo RTSPCameraManager
2. Kết nối đến các camera RTSP
3. Bắt đầu streaming từ các camera
4. Hiển thị trạng thái kết nối

**Output mẫu:**
```
============================================================
   📹 INITIALIZING RTSP CAMERAS
============================================================
   ✅ Camera 100 - Box Check
   ✅ Camera 101 - Defect Detection
============================================================
```

---

## Troubleshooting

### ❌ Camera not connected

**Kiểm tra:**
1. Kiểm tra URL RTSP chính xác
2. Kiểm tra credentials (username/password)
3. Kiểm tra network connectivity: `ping 172.16.251.100`
4. Kiểm tra firewall: RTSP thường dùng port 554

**Log:**
```bash
❌ Camera 101: Cannot open RTSP stream
```

### ❌ OpenCV not available

**Giải pháp:**
```bash
pip install opencv-python
```

**Hoặc dùng requirements.txt:**
```bash
pip install -r requirements.txt
```

### ⚠️ Frame read failed

**Nguyên nhân:** Connection unstable, network delay

**Giải pháp:**
- Kiểm tra bandwidth network
- Tăng timeout trong capture settings
- Kiểm tra camera trạng thái: `GET /api/camera/status`

---

## Sử Dụng trong Frontend

### Hiển thị Live Video
```html
<!-- Camera 101 - Defect Detection -->
<video id="defect-video" width="640" height="480" style="border: 2px solid #F37021;">
  <source src="/api/camera/101/video-feed" type="video/mp4">
</video>
```

### Chụp Ảnh qua JavaScript
```javascript
async function captureFromCamera(cameraId = '101') {
  const response = await fetch('/api/camera/' + cameraId + '/capture', {
    method: 'POST'
  });
  const data = await response.json();
  return data.image;  // Base64 data
}
```

### AI Detection qua Camera
```javascript
async function detectDefectFromCamera() {
  const response = await fetch('/api/ai-detect', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      type: 'defect',
      camera_id: '101'
    })
  });
  return await response.json();
}
```

---

## Tính Năng Chính

✅ **Real-time RTSP Streaming** - Kết nối và stream từ nhiều camera RTSP  
✅ **Frame Capture** - Chụp ảnh từ camera bất kỳ lúc nào  
✅ **Video Feed Streaming** - MJPEG stream cho frontend  
✅ **Base64 Encoding** - Hỗ trợ ảnh base64 cho AI detection  
✅ **Auto Reconnection** - Tự động khôi phục khi mất kết nối (sắp tới)  
✅ **Multi-Camera Support** - Hỗ trợ nhiều camera cùng lúc  

---

## Ghi Chú

- Camera được khởi động tự động khi app start
- Có thể control camera qua API endpoints
- Mỗi camera chạy trên thread riêng
- Frame rate: ~30 FPS (có thể điều chỉnh)
- JPEG quality: 85 (có thể điều chỉnh)

