# 📡 Camera API Reference

## Overview

Complete API documentation for RTSP Camera control and AI detection endpoints.

**Base URL:** `http://localhost:5000/api`

---

## 🎥 Camera Management Endpoints

### 1. List All Cameras
```bash
GET /camera/list
```

**Description:** Get list of all configured cameras

**Response (200):**
```json
{
  "success": true,
  "total": 2,
  "cameras": [
    {
      "id": "100",
      "name": "Camera 100 - Box Check",
      "type": "box",
      "url": "rtsp://admin:***@[HIDDEN]"
    },
    {
      "id": "101",
      "name": "Camera 101 - Defect Detection",
      "type": "defect",
      "url": "rtsp://admin:***@[HIDDEN]"
    }
  ]
}
```

**Example:**
```bash
curl http://localhost:5000/api/camera/list
```

---

### 2. Get Camera Status
```bash
GET /camera/status
```

**Description:** Get real-time status of all cameras

**Response (200):**
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

**Fields:**
- `is_running` - Camera stream is active
- `has_frame` - Latest frame successfully captured
- `error` - Error message if any

**Example:**
```bash
curl http://localhost:5000/api/camera/status | jq
```

---

### 3. Start Camera Stream
```bash
POST /camera/{camera_id}/start
```

**Parameters:**
- `camera_id` - Camera ID (100 or 101)

**Response (200):**
```json
{
  "success": true,
  "camera_id": "101",
  "message": "Camera started"
}
```

**Error (404):**
```json
{
  "error": "Camera not found"
}
```

**Example:**
```bash
curl -X POST http://localhost:5000/api/camera/101/start
```

---

### 4. Stop Camera Stream
```bash
POST /camera/{camera_id}/stop
```

**Parameters:**
- `camera_id` - Camera ID (100 or 101)

**Response (200):**
```json
{
  "success": true,
  "camera_id": "101",
  "message": "Camera stopped"
}
```

**Example:**
```bash
curl -X POST http://localhost:5000/api/camera/101/stop
```

---

## 📸 Frame Capture Endpoints

### 5. Get Frame (JPEG)
```bash
GET /camera/{camera_id}/frame
```

**Description:** Get current frame as JPEG image

**Parameters:**
- `camera_id` - Camera ID (100 or 101)

**Response (200):** JPEG Image binary data

**Response (503):** No frame available
```json
{
  "error": "No frame available"
}
```

**Headers:**
- `Content-Type`: `image/jpeg`
- `Content-Length`: Frame size in bytes

**Example:**
```bash
# Save to file
curl http://localhost:5000/api/camera/101/frame --output frame.jpg

# Use in HTML
<img src="http://localhost:5000/api/camera/101/frame" />
```

---

### 6. Video Feed (MJPEG Streaming)
```bash
GET /camera/{camera_id}/video-feed
```

**Description:** Continuous MJPEG video stream (~20 FPS)

**Parameters:**
- `camera_id` - Camera ID (100 or 101)

**Response (200):** MJPEG Stream

**Headers:**
- `Content-Type`: `multipart/x-mixed-replace; boundary=frame`

**Example:**
```html
<!-- HTML5 video tag -->
<img src="http://localhost:5000/api/camera/101/video-feed" 
     width="640" height="480" />

<!-- Or in JavaScript -->
<video id="stream" width="640" height="480">
  <source src="http://localhost:5000/api/camera/101/video-feed" 
          type="video/mp4">
</video>
```

---

### 7. Capture Snapshot (Base64)
```bash
POST /camera/{camera_id}/capture
```

**Description:** Capture current frame as Base64-encoded image

**Parameters:**
- `camera_id` - Camera ID (100 or 101)

**Response (200):**
```json
{
  "success": true,
  "camera_id": "101",
  "image": "data:image/jpeg;base64,/9j/4AAQSkZJRg...",
  "timestamp": "2026-04-06T10:30:45.123456"
}
```

**Response (503):**
```json
{
  "error": "No frame available"
}
```

**Example:**
```bash
curl -X POST http://localhost:5000/api/camera/101/capture | jq '.image'
```

**JavaScript:**
```javascript
async function captureFromCamera(cameraId = '101') {
  const response = await fetch(`/api/camera/${cameraId}/capture`, {
    method: 'POST'
  });
  const data = await response.json();
  
  if (data.success) {
    // Use Base64 image directly
    document.getElementById('preview').src = data.image;
    console.log('Captured at:', data.timestamp);
  }
}
```

---

## 🤖 AI Detection Endpoints

### 8. Run AI Detection
```bash
POST /ai-detect
```

**Description:** Run AI detection on image from camera or upload

**Content-Type:** `application/json`

**Request Body (Camera):**
```json
{
  "type": "defect",
  "camera_id": "101"
}
```

**Request Body (Upload Image):**
```json
{
  "type": "defect",
  "image": "data:image/jpeg;base64,/9j/4AAQSkZJRg..."
}
```

**Parameters:**
- `type` - Detection type: `"defect"`, `"box"`, or `"accessory"`
- `camera_id` - (Optional) Camera ID to capture from
- `image` - (Optional) Base64-encoded image data

**Response (200):**
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

**Response (400):**
```json
{
  "success": false,
  "error": "No image provided and no camera specified"
}
```

**Response (503):**
```json
{
  "success": false,
  "error": "Cannot capture from camera 101"
}
```

**Example - From Camera:**
```bash
curl -X POST http://localhost:5000/api/ai-detect \
  -H "Content-Type: application/json" \
  -d '{
    "type": "defect",
    "camera_id": "101"
  }' | jq
```

**Example - From Image File:**
```bash
# First, get Base64 encoded image
IMAGE_B64=$(base64 < image.jpg | tr -d '\n')

curl -X POST http://localhost:5000/api/ai-detect \
  -H "Content-Type: application/json" \
  -d "{
    \"type\": \"defect\",
    \"image\": \"data:image/jpeg;base64,${IMAGE_B64}\"
  }" | jq
```

**JavaScript:**
```javascript
async function detectDefectsFromCamera() {
  const response = await fetch('/api/ai-detect', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      type: 'defect',
      camera_id: '101'
    })
  });
  
  const result = await response.json();
  
  if (result.success) {
    console.log('Detection results:', result.results);
    
    for (const detection of result.results) {
      console.log(`Found: ${detection.label} (${detection.confidence.toFixed(2)}%)`);
    }
  } else {
    console.error('Detection failed:', result.error);
  }
}
```

---

## 📊 Response Status Codes

| Code | Meaning |
|------|---------|
| 200 | Success |
| 400 | Bad request (missing required params) |
| 404 | Camera not found |
| 500 | Server error |
| 503 | Service unavailable (e.g., no frame ready) |

---

## 🔄 Detection Types

### defect
Detects product defects using YOLO Model_can
- **Classes:** `com` (complete), `fd` (defect)
- **Usage:** Product quality control

### box
Detects packaging materials (box, tape, receipt)
- **Classes:** Multiple box-related items
- **Usage:** Packaging verification

### accessory
Detects accessories in packaging
- **Classes:** Various accessories
- **Usage:** Shipment verification

---

## 📱 Integration Examples

### Real-time Dashboard
```html
<div class="camera-display">
  <img id="camera-feed" 
       src="/api/camera/101/video-feed" 
       width="640" height="480" />
</div>

<div class="controls">
  <button onclick="detectDefects()">🔍 Detect Defects</button>
  <button onclick="captureSnapshot()">📷 Capture</button>
</div>

<script>
async function detectDefects() {
  const response = await fetch('/api/ai-detect', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      type: 'defect',
      camera_id: '101'
    })
  });
  
  const result = await response.json();
  displayResults(result);
}

function captureSnapshot() {
  const img = document.getElementById('camera-feed');
  img.src = '/api/camera/101/frame?t=' + Date.now();
}
</script>
```

### Python Integration
```python
import requests
import json

# Get camera status
status = requests.get('http://localhost:5000/api/camera/status').json()
print(json.dumps(status, indent=2))

# Start camera
requests.post('http://localhost:5000/api/camera/101/start')

# Capture frame
frame_resp = requests.get('http://localhost:5000/api/camera/101/frame')
with open('frame.jpg', 'wb') as f:
    f.write(frame_resp.content)

# Run detection
detect_resp = requests.post(
    'http://localhost:5000/api/ai-detect',
    json={'type': 'defect', 'camera_id': '101'}
)
results = detect_resp.json()
print(json.dumps(results, indent=2))
```

---

## ⚡ Performance Tips

1. **Polling:** Don't poll `/camera/status` more than every 5 seconds
2. **Frame Size:** JPEG quality set to 85 for balance
3. **FPS:** Defaults to 30 FPS for camera, 20 FPS for stream
4. **Buffering:** Single frame buffer - always gets latest frame
5. **Threading:** Each camera runs on separate thread (non-blocking)

---

## 🐛 Troubleshooting

### No frame available
- Start camera first: `POST /camera/{id}/start`
- Check status: `GET /camera/status`
- Wait 2-3 seconds for stream to initialize

### AI detection timeout
- Ensure camera is running and has frames
- Check network connectivity
- May take 5-10 seconds for first detection

### 404 Camera not found
- Use correct camera ID: "100" or "101"
- Check with: `GET /camera/list`

### Connection refused
- Ensure app is running: `python app.py`
- Check if port 5000 is available
- Try: `http://localhost:5000` first

---

## 📚 See Also

- [QUICK_START.md](QUICK_START.md) - Quick start guide
- [CAMERA_SETUP.md](CAMERA_SETUP.md) - Detailed setup
- [test_camera_api.py](test_camera_api.py) - Automated tests

---

**API Version:** 1.0  
**Last Updated:** April 6, 2026

