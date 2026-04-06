"""
Flask Barcode Scanner App for Openbravo
- Quét barcode để tìm Purchase Order
- Tạo/Update Goods Receipt từ Purchase Order
"""

from flask import Flask, render_template, request, jsonify, redirect, url_for, flash, send_from_directory, send_file, make_response
from flask_cors import CORS
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime
import uuid
import os
import base64
import io
import json
from urllib.parse import quote
import threading
import time
import socket
import re

# Barcode scanning libraries
BARCODE_SCANNER_AVAILABLE = False
SCANNER_TYPE = None
CV2_AVAILABLE = False

# Try to import cv2 and numpy first
try:
    import cv2
    import numpy as np
    CV2_AVAILABLE = True
    print("✓ OpenCV (cv2) loaded successfully.")
except ImportError as e:
    print(f"⚠ OpenCV not available: {e}")

# Try zxing-cpp first (more reliable on Windows)
try:
    import zxingcpp
    from PIL import Image
    BARCODE_SCANNER_AVAILABLE = True
    SCANNER_TYPE = 'zxing'
    print("✓ zxing-cpp loaded successfully. Server-side barcode scanning enabled.")
except ImportError:
    pass

# Fallback to pyzbar if zxing not available
if not BARCODE_SCANNER_AVAILABLE:
    try:
        from pyzbar.pyzbar import decode as pyzbar_decode
        from PIL import Image
        BARCODE_SCANNER_AVAILABLE = True
        SCANNER_TYPE = 'pyzbar'
        print("✓ pyzbar loaded successfully. Server-side barcode scanning enabled.")
    except Exception as e:
        print(f"⚠ Barcode scanner not available: {e}")
        print("  Server-side barcode scanning disabled. Using JavaScript scanner only.")


def preprocess_image_for_barcode(img_array):
    """
    Tiền xử lý ảnh để quét barcode chuẩn hơn
    Sử dụng CLAHE và tăng contrast
    """
    if not CV2_AVAILABLE:
        return img_array
    
    # Convert to grayscale if needed
    if len(img_array.shape) == 3:
        gray = cv2.cvtColor(img_array, cv2.COLOR_BGR2GRAY)
    else:
        gray = img_array
    
    # CLAHE (Contrast Limited Adaptive Histogram Equalization)
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(gray)
    
    # Tăng sáng và contrast nhẹ
    enhanced = cv2.convertScaleAbs(enhanced, alpha=1.2, beta=15)
    
    return enhanced

app = Flask(__name__, static_folder='static')
app.secret_key = 'openbravo-barcode-secret-key'
CORS(app)

# Database configuration - đọc từ Openbravo.properties hoặc dùng default
DB_CONFIG = {
    'host': os.getenv('DB_HOST', 'localhost'),
    'port': os.getenv('DB_PORT', '5432'),
    'database': os.getenv('DB_NAME', 'openbravo'),
    'user': os.getenv('DB_USER', 'postgres'),
    'password': os.getenv('DB_PASSWORD', 'postgres')
}


def get_db_connection():
    """Tạo kết nối đến PostgreSQL database"""
    try:
        conn = psycopg2.connect(
            host=DB_CONFIG['host'],
            port=DB_CONFIG['port'],
            database=DB_CONFIG['database'],
            user=DB_CONFIG['user'],
            password=DB_CONFIG['password'],
            cursor_factory=RealDictCursor
        )
        return conn
    except Exception as e:
        print(f"Database connection error: {e}")
        return None


def generate_uuid():
    """Generate UUID32 format cho Openbravo"""
    return uuid.uuid4().hex.upper()


# ==================== RTSP CAMERA CONFIG ====================

# RTSP Camera configuration
RTSP_CAMERAS = {
    '100': {
        'name': 'Camera 100 - Box Check',
        'url': 'rtsp://admin:L212A477@172.16.251.100:554/cam/realmonitor?channel=1&subtype=0',
        'type': 'box'  # box, defect, general
    },
    '101': {
        'name': 'Camera 101 - Defect Detection',
        'url': 'rtsp://admin:L27EEFF1@172.16.251.101:554/cam/realmonitor?channel=1&subtype=0',
        'type': 'defect'  # box, defect, general
    }
}


class RTSPCameraManager:
    """Quản lý kết nối RTSP cameras"""
    
    def __init__(self):
        self.cameras = {}
        self.threads = {}
        self.frames = {}
        self.last_error = {}
        self.is_running = {}
        
        if not CV2_AVAILABLE:
            print("⚠ OpenCV not available - RTSP camera support disabled")
            return
        
        # Khởi tạo các camera
        for camera_id, config in RTSP_CAMERAS.items():
            self.cameras[camera_id] = config
            self.frames[camera_id] = None
            self.last_error[camera_id] = None
            self.is_running[camera_id] = False
    
    def start_camera(self, camera_id):
        """Bắt đầu stream từ camera"""
        if camera_id not in self.cameras:
            return False
        
        if self.is_running.get(camera_id):
            return True
        
        def capture_frames():
            try:
                cap = cv2.VideoCapture(self.cameras[camera_id]['url'])
                cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # Giảm buffer delay
                
                if not cap.isOpened():
                    self.last_error[camera_id] = "Cannot open RTSP stream"
                    print(f"❌ Camera {camera_id}: {self.last_error[camera_id]}")
                    return
                
                print(f"✓ Camera {camera_id} connected successfully")
                self.is_running[camera_id] = True
                
                while self.is_running[camera_id]:
                    ret, frame = cap.read()
                    if ret:
                        self.frames[camera_id] = frame
                        self.last_error[camera_id] = None
                    else:
                        self.last_error[camera_id] = "Frame read failed"
                    
                    time.sleep(0.03)  # ~30 FPS
                
                cap.release()
                print(f"⚠ Camera {camera_id} stream stopped")
                
            except Exception as e:
                self.last_error[camera_id] = str(e)
                print(f"❌ Camera {camera_id} error: {e}")
                self.is_running[camera_id] = False
        
        # Tạo thread cho stream
        thread = threading.Thread(target=capture_frames, daemon=True)
        thread.start()
        self.threads[camera_id] = thread
        return True
    
    def stop_camera(self, camera_id):
        """Dừng stream từ camera"""
        if camera_id in self.cameras:
            self.is_running[camera_id] = False
            if camera_id in self.threads:
                self.threads[camera_id].join(timeout=2)
    
    def get_frame(self, camera_id):
        """Lấy frame hiện tại từ camera"""
        if camera_id not in self.cameras:
            return None
        return self.frames.get(camera_id)
    
    def get_frame_jpg(self, camera_id):
        """Lấy frame dưới dạng JPEG bytes"""
        frame = self.get_frame(camera_id)
        if frame is None:
            return None
        
        ret, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
        if ret:
            return buffer.tobytes()
        return None
    
    def get_status(self):
        """Lấy trạng thái tất cả cameras"""
        status = {}
        for camera_id, config in self.cameras.items():
            status[camera_id] = {
                'name': config['name'],
                'type': config['type'],
                'is_running': self.is_running.get(camera_id, False),
                'has_frame': self.frames.get(camera_id) is not None,
                'error': self.last_error.get(camera_id)
            }
        return status


# ==================== INITIALIZE CAMERA MANAGER ====================
camera_manager = RTSPCameraManager() if CV2_AVAILABLE else None

# Tự động bắt đầu camera streams khi app khởi động
def start_all_cameras():
    """Bắt đầu tất cả cameras"""
    if camera_manager is None:
        return
    
    for camera_id in RTSP_CAMERAS.keys():
        camera_manager.start_camera(camera_id)
        time.sleep(0.5)  # Delay giữa các camera


# ==================== CLOUDFLARE CONFIG ====================

CLOUDFLARE_CONFIG_FILE = os.path.join(os.path.dirname(__file__), 'cloudflare_config.json')

def load_cloudflare_config():
    """Load Cloudflare tunnel configuration"""
    try:
        if os.path.exists(CLOUDFLARE_CONFIG_FILE):
            with open(CLOUDFLARE_CONFIG_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        print(f"Error loading Cloudflare config: {e}")
    return {
        "enabled": False,
        "barcode_app": {"tunnel_url": "", "local_port": 5443},
        "openbravo": {"tunnel_url": "", "local_port": 8080}
    }

def save_cloudflare_config(config):
    """Save Cloudflare tunnel configuration"""
    try:
        with open(CLOUDFLARE_CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=4, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"Error saving Cloudflare config: {e}")
        return False


# ==================== API ENDPOINTS ====================

# ==================== CAMERA ENDPOINTS ====================

@app.route('/api/camera/status')
def get_camera_status():
    """Lấy trạng thái tất cả cameras"""
    if camera_manager is None:
        return jsonify({'error': 'OpenCV not available'}), 400
    
    return jsonify({
        'success': True,
        'cameras': camera_manager.get_status()
    })


@app.route('/api/camera/<camera_id>/start', methods=['POST'])
def start_camera(camera_id):
    """Bắt đầu stream từ camera cụ thể"""
    if camera_manager is None:
        return jsonify({'error': 'OpenCV not available'}), 400
    
    if camera_id not in RTSP_CAMERAS:
        return jsonify({'error': 'Camera not found'}), 404
    
    result = camera_manager.start_camera(camera_id)
    return jsonify({
        'success': result,
        'camera_id': camera_id,
        'message': 'Camera started' if result else 'Camera already running'
    })


@app.route('/api/camera/<camera_id>/stop', methods=['POST'])
def stop_camera(camera_id):
    """Dừng stream từ camera cụ thể"""
    if camera_manager is None:
        return jsonify({'error': 'OpenCV not available'}), 400
    
    if camera_id not in RTSP_CAMERAS:
        return jsonify({'error': 'Camera not found'}), 404
    
    camera_manager.stop_camera(camera_id)
    return jsonify({
        'success': True,
        'camera_id': camera_id,
        'message': 'Camera stopped'
    })


@app.route('/api/camera/<camera_id>/frame')
def get_camera_frame(camera_id):
    """Lấy frame hiện tại từ camera dưới dạng JPEG"""
    if camera_manager is None:
        return jsonify({'error': 'OpenCV not available'}), 400
    
    if camera_id not in RTSP_CAMERAS:
        return jsonify({'error': 'Camera not found'}), 404
    
    frame_data = camera_manager.get_frame_jpg(camera_id)
    if frame_data is None:
        return jsonify({'error': 'No frame available'}), 503
    
    return send_file(
        io.BytesIO(frame_data),
        mimetype='image/jpeg'
    )


@app.route('/api/camera/<camera_id>/video-feed')
def get_camera_video_feed(camera_id):
    """Streaming video feed từ camera (MJPEG)"""
    if camera_manager is None:
        return jsonify({'error': 'OpenCV not available'}), 400
    
    if camera_id not in RTSP_CAMERAS:
        return jsonify({'error': 'Camera not found'}), 404
    
    def generate_frames():
        while True:
            frame_data = camera_manager.get_frame_jpg(camera_id)
            if frame_data:
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n'
                       b'Content-Length: ' + str(len(frame_data)).encode() + b'\r\n\r\n'
                       + frame_data + b'\r\n')
            time.sleep(0.05)  # ~20 FPS
    
    from flask import Response
    return Response(
        generate_frames(),
        mimetype='multipart/x-mixed-replace; boundary=frame'
    )


@app.route('/api/camera/<camera_id>/capture', methods=['POST'])
def capture_camera_snapshot(camera_id):
    """Chụp ảnh từ camera và lưu base64 để dùng cho AI detection"""
    if camera_manager is None:
        return jsonify({'error': 'OpenCV not available'}), 400
    
    if camera_id not in RTSP_CAMERAS:
        return jsonify({'error': 'Camera not found'}), 404
    
    frame_data = camera_manager.get_frame_jpg(camera_id)
    if frame_data is None:
        return jsonify({'error': 'No frame available'}), 503
    
    # Chuyển thành base64 để client có thể dùng ngay
    base64_data = base64.b64encode(frame_data).decode('utf-8')
    
    return jsonify({
        'success': True,
        'camera_id': camera_id,
        'image': f'data:image/jpeg;base64,{base64_data}',
        'timestamp': datetime.now().isoformat()
    })


@app.route('/api/camera/list')
def list_cameras():
    """Lấy danh sách tất cả cameras đã cấu hình"""
    cameras = []
    for camera_id, config in RTSP_CAMERAS.items():
        cameras.append({
            'id': camera_id,
            'name': config['name'],
            'type': config['type'],
            'url': config['url'].split('@')[0] + '@[HIDDEN]' if '@' in config['url'] else config['url']  # Ẩn credentials
        })
    
    return jsonify({
        'success': True,
        'total': len(cameras),
        'cameras': cameras
    })


@app.after_request
def add_no_cache_headers(response):
    """Disable cache cho tất cả responses (including static files)"""
    # Áp dụng cho tất cả responses
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response


@app.route('/')
def index():
    """Trang chủ với barcode scanner"""
    from flask import make_response
    response = make_response(render_template('index.html'))
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response


@app.route('/camera-control')
def camera_control():
    """Trang camera control panel - không cache"""
    static_path = os.path.join(os.path.dirname(__file__), 'static', 'camera-control.html')
    
    if not os.path.exists(static_path):
        return jsonify({'error': 'Camera control page not found'}), 404
    
    with open(static_path, 'r', encoding='utf-8') as f:
        html_content = f.read()
    
    response = make_response(html_content)
    response.headers['Content-Type'] = 'text/html; charset=utf-8'
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response


@app.route('/api/qr')
def generate_qr_image():
    """Tạo QR code PNG cho URL chỉ định (hoặc mặc định URL truy cập app)."""
    target_url = request.args.get('url')
    size = int(request.args.get('size', 300))
    color = request.args.get('color', '000000').lstrip('#')

    # Nếu không truyền url, tự tạo link HTTP/HTTPS theo host hiện tại
    if not target_url:
        host = request.host.split(':')[0]
        # Ưu tiên HTTPS port 5443, fallback HTTP 5000
        target_url = f"https://{host}:5443"

    # Thử dùng thư viện qrcode nếu có, nếu không sẽ redirect sang Google Charts
    try:
        import qrcode
        from qrcode.image.pil import PilImage
        qr = qrcode.QRCode(
            version=None,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=max(2, size // 40),
            border=2,
        )
        qr.add_data(target_url)
        qr.make(fit=True)
        img = qr.make_image(fill_color=f"#{color}", back_color="white", image_factory=PilImage)
        buf = io.BytesIO()
        img.save(buf, format='PNG')
        buf.seek(0)
        return send_file(buf, mimetype='image/png')
    except Exception:
        # Fallback: dùng Google Charts API (không cần thư viện)
        chart_url = (
            "https://chart.googleapis.com/chart?"
            f"cht=qr&chs={size}x{size}&chl={quote(target_url)}&chco={color}"
        )
        return redirect(chart_url)


@app.route('/api/cloudflare-config', methods=['GET'])
def get_cloudflare_config():
    """Lấy cấu hình Cloudflare tunnel"""
    config = load_cloudflare_config()
    return jsonify({
        'enabled': config.get('enabled', False),
        'barcode_app': {
            'tunnel_url': config.get('barcode_app', {}).get('tunnel_url', ''),
            'local_port': config.get('barcode_app', {}).get('local_port', 5443),
            'description': config.get('barcode_app', {}).get('description', 'Barcode Scanner App')
        },
        'openbravo': {
            'tunnel_url': config.get('openbravo', {}).get('tunnel_url', ''),
            'local_port': config.get('openbravo', {}).get('local_port', 8080),
            'description': config.get('openbravo', {}).get('description', 'Openbravo ERP')
        }
    })


@app.route('/api/cloudflare-config', methods=['POST'])
def update_cloudflare_config():
    """Cập nhật cấu hình Cloudflare tunnel"""
    try:
        data = request.get_json()
        config = load_cloudflare_config()
        
        if 'enabled' in data:
            config['enabled'] = data['enabled']
        
        if 'barcode_app' in data:
            if 'barcode_app' not in config:
                config['barcode_app'] = {}
            if 'tunnel_url' in data['barcode_app']:
                config['barcode_app']['tunnel_url'] = data['barcode_app']['tunnel_url']
        
        if 'openbravo' in data:
            if 'openbravo' not in config:
                config['openbravo'] = {}
            if 'tunnel_url' in data['openbravo']:
                config['openbravo']['tunnel_url'] = data['openbravo']['tunnel_url']
        
        if save_cloudflare_config(config):
            return jsonify({'success': True, 'message': 'Cloudflare config updated'})
        else:
            return jsonify({'error': 'Failed to save config'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/scan-barcode', methods=['POST'])
def scan_barcode_from_image():
    """
    Nhận ảnh từ camera (base64) và decode barcode bằng zxing hoặc pyzbar
    Với preprocessing CLAHE để quét chuẩn hơn
    """
    if not BARCODE_SCANNER_AVAILABLE:
        return jsonify({'error': 'Barcode scanner library not available on server'}), 500
    
    try:
        data = request.get_json()
        if not data or 'image' not in data:
            return jsonify({'error': 'No image data provided'}), 400
        
        # Decode base64 image
        image_data = data['image']
        if ',' in image_data:
            image_data = image_data.split(',')[1]
        
        image_bytes = base64.b64decode(image_data)
        
        # Convert to PIL Image
        image = Image.open(io.BytesIO(image_bytes))
        
        results = []
        
        if SCANNER_TYPE == 'zxing':
            # Use zxing-cpp - try with original and enhanced
            barcodes = zxingcpp.read_barcodes(image)
            
            # If no result, try with preprocessed image
            if not barcodes and CV2_AVAILABLE:
                img_array = np.array(image)
                if len(img_array.shape) == 3:
                    img_array = cv2.cvtColor(img_array, cv2.COLOR_RGB2BGR)
                enhanced = preprocess_image_for_barcode(img_array)
                enhanced_pil = Image.fromarray(enhanced)
                barcodes = zxingcpp.read_barcodes(enhanced_pil)
            
            for barcode in barcodes:
                results.append({
                    'data': barcode.text,
                    'type': str(barcode.format)
                })
        else:
            # Use pyzbar with enhanced preprocessing
            img_array = np.array(image)
            
            # Convert RGB to BGR for OpenCV
            if len(img_array.shape) == 3 and img_array.shape[2] == 3:
                img_array = cv2.cvtColor(img_array, cv2.COLOR_RGB2BGR)
            
            # Method 1: CLAHE preprocessing (best)
            enhanced = preprocess_image_for_barcode(img_array)
            barcodes = pyzbar_decode(enhanced)
            
            # Method 2: Simple grayscale
            if not barcodes:
                if len(img_array.shape) == 3:
                    gray = cv2.cvtColor(img_array, cv2.COLOR_BGR2GRAY)
                else:
                    gray = img_array
                barcodes = pyzbar_decode(gray)
            
            # Method 3: Binary threshold
            if not barcodes:
                _, thresh = cv2.threshold(enhanced, 127, 255, cv2.THRESH_BINARY)
                barcodes = pyzbar_decode(thresh)
            
            # Method 4: Adaptive threshold
            if not barcodes:
                adaptive = cv2.adaptiveThreshold(enhanced, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2)
                barcodes = pyzbar_decode(adaptive)
            
            # Method 5: Inverted
            if not barcodes:
                inverted = cv2.bitwise_not(enhanced)
                barcodes = pyzbar_decode(inverted)
            
            for barcode in barcodes:
                results.append({
                    'data': barcode.data.decode('utf-8'),
                    'type': barcode.type
                })
        
        if results:
            return jsonify({
                'success': True,
                'barcodes': results,
                'count': len(results),
                'scanner': SCANNER_TYPE
            })
        else:
            return jsonify({
                'success': False,
                'error': 'No barcode detected in image',
                'barcodes': [],
                'scanner': SCANNER_TYPE
            })
            
    except Exception as e:
        return jsonify({'error': f'Error processing image: {str(e)}'}), 500


@app.route('/api/product/barcode/<barcode>')
def get_product_by_barcode(barcode):
    """Tìm sản phẩm theo barcode (UPC)"""
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT m_product_id, value, name, upc, description
            FROM m_product
            WHERE upc = %s OR value = %s
            AND isactive = 'Y'
        """, (barcode, barcode))
        product = cur.fetchone()
        
        if product:
            return jsonify({'success': True, 'product': dict(product)})
        return jsonify({'success': False, 'error': 'Product not found'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/purchase-orders')
def get_purchase_orders():
    """Lấy danh sách Purchase Orders với bộ lọc"""
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    try:
        cur = conn.cursor()
        
        # Lấy các filter params
        docstatus = request.args.get('docstatus', '')  # CO, DR, VO, etc.
        bpartner_id = request.args.get('bpartner_id', '')
        date_from = request.args.get('date_from', '')
        date_to = request.args.get('date_to', '')
        search = request.args.get('search', '')  # Tìm theo documentno
        pending_only = request.args.get('pending_only', '0')  # Chỉ PO còn hàng chưa nhận
        limit = request.args.get('limit', '100')
        
        # Build query
        query = """
            SELECT 
                o.c_order_id,
                o.documentno,
                o.dateordered,
                o.description,
                bp.name as bpartner_name,
                bp.c_bpartner_id,
                o.docstatus,
                o.grandtotal,
                w.name as warehouse_name,
                (SELECT COALESCE(SUM(ol.qtyordered - ol.qtydelivered), 0) 
                 FROM c_orderline ol WHERE ol.c_order_id = o.c_order_id AND ol.qtyordered > ol.qtydelivered) as pending_qty
            FROM c_order o
            JOIN c_bpartner bp ON o.c_bpartner_id = bp.c_bpartner_id
            LEFT JOIN m_warehouse w ON o.m_warehouse_id = w.m_warehouse_id
            WHERE o.issotrx = 'N'
            AND o.isactive = 'Y'
        """
        params = []
        
        # Apply filters
        if docstatus:
            query += " AND o.docstatus = %s"
            params.append(docstatus)
        
        if bpartner_id:
            query += " AND o.c_bpartner_id = %s"
            params.append(bpartner_id)
        
        if date_from:
            query += " AND o.dateordered >= %s"
            params.append(date_from)
        
        if date_to:
            query += " AND o.dateordered <= %s"
            params.append(date_to)
        
        if search:
            query += " AND (o.documentno ILIKE %s OR o.description ILIKE %s)"
            params.append(f'%{search}%')
            params.append(f'%{search}%')
        
        if pending_only == '1':
            query += """ AND EXISTS (
                SELECT 1 FROM c_orderline ol 
                WHERE ol.c_order_id = o.c_order_id 
                AND ol.qtyordered > ol.qtydelivered
            )"""
        
        query += " ORDER BY o.dateordered DESC"
        query += f" LIMIT {int(limit)}"
        
        cur.execute(query, params)
        orders = cur.fetchall()
        
        # Lấy danh sách suppliers để filter
        cur.execute("""
            SELECT DISTINCT bp.c_bpartner_id, bp.name
            FROM c_bpartner bp
            JOIN c_order o ON o.c_bpartner_id = bp.c_bpartner_id
            WHERE o.issotrx = 'N' AND bp.isactive = 'Y'
            ORDER BY bp.name
            LIMIT 50
        """)
        suppliers = cur.fetchall()
        
        return jsonify({
            'success': True, 
            'orders': [dict(o) for o in orders],
            'count': len(orders),
            'suppliers': [dict(s) for s in suppliers]
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/purchase-order/<order_id>')
def get_purchase_order_detail(order_id):
    """Lấy chi tiết Purchase Order với các line items"""
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    try:
        cur = conn.cursor()
        
        # Header
        cur.execute("""
            SELECT 
                o.c_order_id,
                o.documentno,
                o.dateordered,
                o.description,
                o.docstatus,
                bp.name as bpartner_name,
                bp.c_bpartner_id,
                o.m_warehouse_id,
                o.ad_org_id,
                o.ad_client_id
            FROM c_order o
            JOIN c_bpartner bp ON o.c_bpartner_id = bp.c_bpartner_id
            WHERE o.c_order_id = %s
        """, (order_id,))
        order = cur.fetchone()
        
        if not order:
            return jsonify({'error': 'Purchase Order not found'}), 404
        
        # Lines
        cur.execute("""
            SELECT 
                ol.c_orderline_id,
                ol.line,
                p.m_product_id,
                p.value as product_code,
                p.name as product_name,
                p.upc as barcode,
                ol.qtyordered,
                ol.qtydelivered,
                (ol.qtyordered - ol.qtydelivered) as qty_pending,
                ol.priceactual,
                ol.c_uom_id,
                uom.name as uom_name
            FROM c_orderline ol
            LEFT JOIN m_product p ON ol.m_product_id = p.m_product_id
            LEFT JOIN c_uom uom ON ol.c_uom_id = uom.c_uom_id
            WHERE ol.c_order_id = %s
            AND ol.isactive = 'Y'
            ORDER BY ol.line
        """, (order_id,))
        lines = cur.fetchall()
        
        return jsonify({
            'success': True,
            'order': dict(order),
            'lines': [dict(l) for l in lines]
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/purchase-order/search-by-product', methods=['POST'])
def search_po_by_product():
    """Tìm Purchase Order có chứa sản phẩm theo barcode"""
    data = request.get_json()
    barcode = data.get('barcode')
    
    if not barcode:
        return jsonify({'error': 'Barcode is required'}), 400
    
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT DISTINCT
                o.c_order_id,
                o.documentno,
                o.dateordered,
                bp.name as bpartner_name,
                p.name as product_name,
                p.value as product_code,
                ol.qtyordered,
                ol.qtydelivered,
                (ol.qtyordered - ol.qtydelivered) as qty_pending
            FROM c_order o
            JOIN c_orderline ol ON o.c_order_id = ol.c_order_id
            JOIN m_product p ON ol.m_product_id = p.m_product_id
            JOIN c_bpartner bp ON o.c_bpartner_id = bp.c_bpartner_id
            WHERE o.issotrx = 'N'
            AND o.docstatus = 'CO'
            AND o.isactive = 'Y'
            AND (p.upc = %s OR p.value = %s)
            AND (ol.qtyordered - ol.qtydelivered) > 0
            ORDER BY o.dateordered DESC
        """, (barcode, barcode))
        
        results = cur.fetchall()
        return jsonify({
            'success': True,
            'barcode': barcode,
            'purchase_orders': [dict(r) for r in results]
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/purchase-order/search-by-documentno', methods=['POST'])
def search_po_by_documentno():
    """Tìm Purchase Order theo Document Number (mã đơn hàng)"""
    data = request.get_json()
    documentno = data.get('documentno', '').strip()
    
    if not documentno:
        return jsonify({'error': 'Document Number is required'}), 400
    
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    try:
        cur = conn.cursor()
        # Tìm chính xác hoặc tìm gần đúng (LIKE)
        cur.execute("""
            SELECT 
                o.c_order_id,
                o.documentno,
                o.dateordered,
                o.description,
                o.docstatus,
                bp.name as bpartner_name,
                bp.c_bpartner_id,
                o.m_warehouse_id,
                o.ad_org_id,
                o.ad_client_id,
                (SELECT COUNT(*) FROM c_orderline ol WHERE ol.c_order_id = o.c_order_id) as total_lines,
                (SELECT COALESCE(SUM(ol.qtyordered - ol.qtydelivered), 0) 
                 FROM c_orderline ol WHERE ol.c_order_id = o.c_order_id) as total_pending
            FROM c_order o
            JOIN c_bpartner bp ON o.c_bpartner_id = bp.c_bpartner_id
            WHERE o.issotrx = 'N'
            AND o.isactive = 'Y'
            AND (o.documentno = %s OR o.documentno ILIKE %s)
            ORDER BY 
                CASE WHEN o.documentno = %s THEN 0 ELSE 1 END,
                o.dateordered DESC
            LIMIT 20
        """, (documentno, f'%{documentno}%', documentno))
        
        orders = cur.fetchall()
        
        if not orders:
            return jsonify({
                'success': False,
                'error': f'Không tìm thấy Purchase Order với mã: {documentno}'
            }), 404
        
        return jsonify({
            'success': True,
            'documentno': documentno,
            'orders': [dict(o) for o in orders]
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/goods-receipt', methods=['POST'])
def create_goods_receipt():
    """
    Tạo Goods Receipt từ Purchase Order
    Body: {
        c_order_id: string,
        lines: [{ c_orderline_id: string, qty_received: number }],
        m_warehouse_id: string (optional - override warehouse)
    }
    """
    data = request.get_json()
    c_order_id = data.get('c_order_id')
    lines = data.get('lines', [])
    override_warehouse_id = data.get('m_warehouse_id')  # Warehouse do user chọn
    
    if not c_order_id or not lines:
        return jsonify({'error': 'c_order_id and lines are required'}), 400
    
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    try:
        cur = conn.cursor()
        
        # Lấy thông tin Purchase Order
        cur.execute("""
            SELECT 
                o.c_order_id, o.ad_client_id, o.ad_org_id, o.c_bpartner_id,
                o.c_bpartner_location_id, o.m_warehouse_id, o.dateordered,
                o.c_doctype_id, o.poreference
            FROM c_order o
            WHERE o.c_order_id = %s
        """, (c_order_id,))
        order = cur.fetchone()
        
        if not order:
            return jsonify({'error': 'Purchase Order not found'}), 404
        
        # Sử dụng warehouse do user chọn, hoặc warehouse từ PO
        warehouse_id = override_warehouse_id or order['m_warehouse_id']
        
        # Lấy Document Type cho Goods Receipt (MM Receipt)
        cur.execute("""
            SELECT c_doctype_id 
            FROM c_doctype 
            WHERE docbasetype = 'MMR' 
            AND isactive = 'Y'
            AND ad_client_id = %s
            LIMIT 1
        """, (order['ad_client_id'],))
        doctype = cur.fetchone()
        
        if not doctype:
            return jsonify({'error': 'No Document Type found for Goods Receipt'}), 400
        
        # Lấy Locator mặc định từ Warehouse - ưu tiên locator có isdefault = 'Y'
        cur.execute("""
            SELECT m_locator_id, value
            FROM m_locator
            WHERE m_warehouse_id = %s
            AND isdefault = 'Y'
            AND isactive = 'Y'
            LIMIT 1
        """, (warehouse_id,))
        locator = cur.fetchone()
        
        if not locator:
            # Fallback: lấy locator đầu tiên của warehouse
            cur.execute("""
                SELECT m_locator_id, value
                FROM m_locator
                WHERE m_warehouse_id = %s
                AND isactive = 'Y'
                ORDER BY value
                LIMIT 1
            """, (warehouse_id,))
            locator = cur.fetchone()
        
        if not locator:
            return jsonify({'error': 'No Locator found in selected Warehouse'}), 400
        
        # Generate IDs và Document Number
        m_inout_id = generate_uuid()
        now = datetime.now()
        
        # Lấy document sequence
        cur.execute("""
            SELECT currentnext FROM ad_sequence
            WHERE name = 'DocumentNo_M_InOut'
            AND ad_client_id = %s
            LIMIT 1
        """, (order['ad_client_id'],))
        seq = cur.fetchone()
        seq_num = str(seq['currentnext']).zfill(5) if seq else '00001'
        doc_no = f"{now.strftime('%Y%m%d')}-{seq_num}"
        
        # Tạo M_INOUT header (sử dụng warehouse do user chọn)
        cur.execute("""
            INSERT INTO m_inout (
                m_inout_id, ad_client_id, ad_org_id, isactive, created, createdby,
                updated, updatedby, issotrx, documentno, docaction, docstatus,
                posted, processing, processed, c_doctype_id, description,
                c_order_id, dateordered, isprinted, movementtype, movementdate,
                dateacct, c_bpartner_id, c_bpartner_location_id, m_warehouse_id,
                poreference, deliveryrule, freightcostrule, deliveryviarule, priorityrule
            ) VALUES (
                %s, %s, %s, 'Y', %s, '0',
                %s, '0', 'N', %s, 'CO', 'DR',
                'N', NULL, 'N', %s, %s,
                %s, %s, 'N', 'V+', %s,
                %s, %s, %s, %s,
                %s, 'A', 'I', 'D', '5'
            )
        """, (
            m_inout_id, order['ad_client_id'], order['ad_org_id'], now, now,
            doc_no, doctype['c_doctype_id'], f"Created from PO via Barcode Scanner",
            c_order_id, order['dateordered'], now,
            now, order['c_bpartner_id'], order['c_bpartner_location_id'], warehouse_id,
            order['poreference']
        ))
        
        # Tạo M_INOUTLINE cho mỗi line
        line_num = 10
        created_lines = []
        
        for line_data in lines:
            c_orderline_id = line_data.get('c_orderline_id')
            qty_received = line_data.get('qty_received', 0)
            
            if qty_received <= 0:
                continue
            
            # Lấy thông tin orderline
            cur.execute("""
                SELECT ol.c_orderline_id, ol.m_product_id, ol.c_uom_id,
                       ol.qtyordered, ol.qtydelivered, ol.description,
                       p.name as product_name
                FROM c_orderline ol
                LEFT JOIN m_product p ON ol.m_product_id = p.m_product_id
                WHERE ol.c_orderline_id = %s
            """, (c_orderline_id,))
            ol = cur.fetchone()
            
            if not ol:
                continue
            
            m_inoutline_id = generate_uuid()
            
            cur.execute("""
                INSERT INTO m_inoutline (
                    m_inoutline_id, ad_client_id, ad_org_id, isactive, created, createdby,
                    updated, updatedby, line, description, m_inout_id, c_orderline_id,
                    m_locator_id, m_product_id, c_uom_id, movementqty, isinvoiced,
                    isdescription, explode
                ) VALUES (
                    %s, %s, %s, 'Y', %s, '0',
                    %s, '0', %s, %s, %s, %s,
                    %s, %s, %s, %s, 'N',
                    'N', 'N'
                )
            """, (
                m_inoutline_id, order['ad_client_id'], order['ad_org_id'], now,
                now, line_num, ol['description'], m_inout_id, c_orderline_id,
                locator['m_locator_id'], ol['m_product_id'], ol['c_uom_id'], qty_received
            ))
            
            created_lines.append({
                'line': line_num,
                'product': ol['product_name'],
                'qty_received': qty_received
            })
            line_num += 10
        
        conn.commit()
        
        return jsonify({
            'success': True,
            'message': 'Goods Receipt created successfully',
            'goods_receipt': {
                'm_inout_id': m_inout_id,
                'documentno': doc_no,
                'lines': created_lines
            }
        })
        
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/goods-receipt/<inout_id>/complete', methods=['POST'])
def complete_goods_receipt(inout_id):
    """Hoàn thành Goods Receipt (đổi trạng thái sang CO) và cập nhật storage"""
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    try:
        cur = conn.cursor()
        now = datetime.now()
        
        # Lấy thông tin GR header
        cur.execute("""
            SELECT io.m_inout_id, io.ad_client_id, io.ad_org_id, io.docstatus, io.movementdate
            FROM m_inout io
            WHERE io.m_inout_id = %s
        """, (inout_id,))
        gr = cur.fetchone()
        
        if not gr:
            return jsonify({'error': 'Goods Receipt not found'}), 404
        
        if gr['docstatus'] == 'CO':
            return jsonify({'error': 'Goods Receipt already completed'}), 400
        
        # Lấy các dòng GR để cập nhật storage
        cur.execute("""
            SELECT iol.m_inoutline_id, iol.m_product_id, iol.m_locator_id, 
                   iol.movementqty, iol.c_orderline_id,
                   COALESCE(iol.m_attributesetinstance_id, p.m_attributesetinstance_id) as m_attributesetinstance_id,
                   p.c_uom_id
            FROM m_inoutline iol
            JOIN m_product p ON iol.m_product_id = p.m_product_id
            WHERE iol.m_inout_id = %s AND iol.isactive = 'Y'
        """, (inout_id,))
        lines = cur.fetchall()
        
        # Tạo M_Transaction và cập nhật storage cho từng dòng
        for line in lines:
            product_id = line['m_product_id']
            locator_id = line['m_locator_id']
            qty = line['movementqty']
            uom_id = line['c_uom_id']
            attr_id = line['m_attributesetinstance_id'] or '0'  # Default '0' if null
            inoutline_id = line['m_inoutline_id']
            
            # 1. Tạo M_Transaction record (bắt buộc cho Openbravo)
            transaction_id = generate_uuid()
            cur.execute("""
                INSERT INTO m_transaction (
                    m_transaction_id, ad_client_id, ad_org_id, isactive,
                    created, createdby, updated, updatedby,
                    movementtype, m_locator_id, m_product_id,
                    movementdate, movementqty, m_inoutline_id,
                    m_attributesetinstance_id, c_uom_id,
                    trxprocessdate, iscostcalculated, isprocessed
                ) VALUES (
                    %s, %s, %s, 'Y',
                    %s, '0', %s, '0',
                    'V+', %s, %s,
                    %s, %s, %s,
                    %s, %s,
                    %s, 'N', 'Y'
                )
            """, (transaction_id, gr['ad_client_id'], gr['ad_org_id'],
                  now, now,
                  locator_id, product_id,
                  gr['movementdate'], qty, inoutline_id,
                  attr_id, uom_id,
                  now))
            
            # 2. Cập nhật m_storage_detail
            cur.execute("""
                SELECT m_storage_detail_id, qtyonhand
                FROM m_storage_detail
                WHERE m_product_id = %s 
                AND m_locator_id = %s
                AND COALESCE(m_attributesetinstance_id, '0') = COALESCE(%s, '0')
                AND isactive = 'Y'
                LIMIT 1
            """, (product_id, locator_id, attr_id))
            storage = cur.fetchone()
            
            if storage:
                # Update existing storage
                cur.execute("""
                    UPDATE m_storage_detail
                    SET qtyonhand = qtyonhand + %s,
                        updated = %s
                    WHERE m_storage_detail_id = %s
                """, (qty, now, storage['m_storage_detail_id']))
            else:
                # Insert new storage record
                storage_id = generate_uuid()
                cur.execute("""
                    INSERT INTO m_storage_detail (
                        m_storage_detail_id, ad_client_id, ad_org_id, isactive,
                        created, createdby, updated, updatedby,
                        m_product_id, m_locator_id, m_attributesetinstance_id,
                        c_uom_id, qtyonhand, qtyorderonhand, qtyreserved
                    ) VALUES (
                        %s, %s, %s, 'Y',
                        %s, '0', %s, '0',
                        %s, %s, %s,
                        %s, %s, 0, 0
                    )
                """, (storage_id, gr['ad_client_id'], gr['ad_org_id'],
                      now, now,
                      product_id, locator_id, attr_id,
                      uom_id, qty))
        
        # Update trạng thái GR
        cur.execute("""
            UPDATE m_inout
            SET docstatus = 'CO',
                docaction = 'CL',
                processed = 'Y',
                updated = %s
            WHERE m_inout_id = %s
        """, (now, inout_id))
        
        # Update qtydelivered trong c_orderline
        cur.execute("""
            UPDATE c_orderline ol
            SET qtydelivered = ol.qtydelivered + iol.movementqty,
                updated = %s
            FROM m_inoutline iol
            WHERE iol.c_orderline_id = ol.c_orderline_id
            AND iol.m_inout_id = %s
        """, (now, inout_id))
        
        conn.commit()
        
        return jsonify({
            'success': True,
            'message': f'Goods Receipt completed. {len(lines)} product(s) added to storage bin.'
        })
        
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/goods-receipt/<inout_id>/generate-invoice', methods=['POST'])
def generate_invoice_from_gr(inout_id):
    """Tạo Purchase Invoice từ Goods Receipt"""
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    try:
        cur = conn.cursor()
        now = datetime.now()
        
        # Lấy thông tin GR header
        cur.execute("""
            SELECT io.m_inout_id, io.ad_client_id, io.ad_org_id, io.c_bpartner_id,
                   io.c_bpartner_location_id, io.c_order_id, io.m_warehouse_id,
                   io.movementdate, io.documentno, io.docstatus,
                   o.c_currency_id, o.m_pricelist_id, o.c_paymentterm_id,
                   o.fin_paymentmethod_id
            FROM m_inout io
            LEFT JOIN c_order o ON io.c_order_id = o.c_order_id
            WHERE io.m_inout_id = %s
        """, (inout_id,))
        gr = cur.fetchone()
        
        if not gr:
            return jsonify({'error': 'Goods Receipt not found'}), 404
        
        if gr['docstatus'] != 'CO':
            return jsonify({'error': 'Goods Receipt must be completed first'}), 400
        
        # Kiểm tra đã có invoice chưa
        cur.execute("""
            SELECT c_invoice_id, documentno 
            FROM c_invoice 
            WHERE c_invoice_id IN (
                SELECT DISTINCT il.c_invoice_id 
                FROM c_invoiceline il 
                WHERE il.m_inoutline_id IN (
                    SELECT m_inoutline_id FROM m_inoutline WHERE m_inout_id = %s
                )
            )
        """, (inout_id,))
        existing = cur.fetchone()
        if existing:
            return jsonify({'error': f'Invoice already exists: {existing["documentno"]}'}), 400
        
        # Lấy Document Type cho Purchase Invoice (AP Invoice)
        cur.execute("""
            SELECT c_doctype_id FROM c_doctype
            WHERE docbasetype = 'API' 
            AND ad_org_id IN (%s, '0')
            AND isactive = 'Y'
            ORDER BY isdefault DESC
            LIMIT 1
        """, (gr['ad_org_id'],))
        doctype = cur.fetchone()
        
        if not doctype:
            return jsonify({'error': 'No Document Type found for Purchase Invoice'}), 400
        
        # Generate Invoice ID và Document Number
        c_invoice_id = generate_uuid()
        
        cur.execute("""
            SELECT currentnext FROM ad_sequence
            WHERE name = 'DocumentNo_C_Invoice'
            AND ad_client_id = %s
            LIMIT 1
        """, (gr['ad_client_id'],))
        seq = cur.fetchone()
        invoice_docno = f"API-{now.strftime('%Y%m%d')}-{seq['currentnext'] if seq else '001'}"
        
        # Update sequence
        if seq:
            cur.execute("""
                UPDATE ad_sequence 
                SET currentnext = currentnext + 1, updated = %s
                WHERE name = 'DocumentNo_C_Invoice' AND ad_client_id = %s
            """, (now, gr['ad_client_id']))
        
        # Lấy các dòng GR để tạo invoice lines
        cur.execute("""
            SELECT iol.m_inoutline_id, iol.m_product_id, iol.movementqty,
                   iol.c_orderline_id, iol.m_attributesetinstance_id,
                   p.c_uom_id, p.name as product_name,
                   COALESCE(ol.priceactual, pp.pricestd, 0) as price,
                   COALESCE(ol.c_tax_id, t.c_tax_id) as c_tax_id
            FROM m_inoutline iol
            JOIN m_product p ON iol.m_product_id = p.m_product_id
            LEFT JOIN c_orderline ol ON iol.c_orderline_id = ol.c_orderline_id
            LEFT JOIN m_productprice pp ON p.m_product_id = pp.m_product_id 
                AND pp.m_pricelist_version_id = (
                    SELECT m_pricelist_version_id FROM m_pricelist_version 
                    WHERE m_pricelist_id = %s AND validfrom <= %s 
                    ORDER BY validfrom DESC LIMIT 1
                )
            LEFT JOIN c_tax t ON t.c_taxcategory_id = p.c_taxcategory_id 
                AND t.sopotype = 'B' AND t.isactive = 'Y'
            WHERE iol.m_inout_id = %s AND iol.isactive = 'Y'
        """, (gr['m_pricelist_id'], now, inout_id))
        lines = cur.fetchall()
        
        if not lines:
            return jsonify({'error': 'No lines found in Goods Receipt'}), 400
        
        # Tính total
        total_lines = sum(float(l['movementqty']) * float(l['price']) for l in lines)
        
        # Tạo C_INVOICE header
        cur.execute("""
            INSERT INTO c_invoice (
                c_invoice_id, ad_client_id, ad_org_id, isactive,
                created, createdby, updated, updatedby,
                issotrx, documentno, docstatus, docaction,
                processing, processed, posted,
                c_doctype_id, c_doctypetarget_id,
                c_order_id, c_bpartner_id, c_bpartner_location_id,
                dateinvoiced, dateacct, c_currency_id,
                c_paymentterm_id, m_pricelist_id,
                isprinted, isdiscountprinted, isselfservice, iscashvat,
                totallines, grandtotal, chargeamt, withholdingamount,
                ispaid, totalpaid, outstandingamt, daystilldue, dueamt,
                prepaymentamt, calculate_promotions,
                createfrom, generateto, copyfrom,
                createfromorders, createfrominouts,
                fin_paymentmethod_id
            ) VALUES (
                %s, %s, %s, 'Y',
                %s, '0', %s, '0',
                'N', %s, 'DR', 'CO',
                'N', 'N', 'N',
                %s, %s,
                %s, %s, %s,
                %s, %s, %s,
                %s, %s,
                'N', 'N', 'N', 'N',
                %s, %s, 0, 0,
                'N', 0, %s, 0, 0,
                0, 'N',
                'N', 'N', 'N',
                'N', 'Y',
                %s
            )
        """, (
            c_invoice_id, gr['ad_client_id'], gr['ad_org_id'],
            now, now,
            invoice_docno,
            doctype['c_doctype_id'], doctype['c_doctype_id'],
            gr['c_order_id'], gr['c_bpartner_id'], gr['c_bpartner_location_id'],
            now, now, gr['c_currency_id'],
            gr['c_paymentterm_id'], gr['m_pricelist_id'],
            total_lines, total_lines,
            total_lines,
            gr['fin_paymentmethod_id']
        ))
        
        # Tạo invoice lines
        line_no = 0
        for line in lines:
            line_no += 10
            c_invoiceline_id = generate_uuid()
            line_amount = float(line['movementqty']) * float(line['price'])
            
            cur.execute("""
                INSERT INTO c_invoiceline (
                    c_invoiceline_id, ad_client_id, ad_org_id, isactive,
                    created, createdby, updated, updatedby,
                    c_invoice_id, c_orderline_id, m_inoutline_id,
                    line, m_product_id, qtyinvoiced,
                    pricelist, priceactual, pricelimit, pricestd,
                    linenetamt, c_uom_id, c_tax_id,
                    m_attributesetinstance_id,
                    isdescription, financial_invoice_line, isdeferred, explode,
                    grosspricelist, grosspricestd
                ) VALUES (
                    %s, %s, %s, 'Y',
                    %s, '0', %s, '0',
                    %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s,
                    %s,
                    'N', 'N', 'N', 'N',
                    %s, %s
                )
            """, (
                c_invoiceline_id, gr['ad_client_id'], gr['ad_org_id'],
                now, now,
                c_invoice_id, line['c_orderline_id'], line['m_inoutline_id'],
                line_no, line['m_product_id'], line['movementqty'],
                line['price'], line['price'], line['price'], line['price'],
                line_amount, line['c_uom_id'], line['c_tax_id'],
                line['m_attributesetinstance_id'],
                line['price'], line['price']
            ))
        
        conn.commit()
        
        return jsonify({
            'success': True,
            'invoice': {
                'c_invoice_id': c_invoice_id,
                'documentno': invoice_docno
            },
            'message': f'Invoice {invoice_docno} created with {len(lines)} line(s).'
        })
        
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/goods-receipt/<inout_id>/complete-and-invoice', methods=['POST'])
def complete_gr_and_generate_invoice(inout_id):
    """Complete GR và tạo Invoice trong một bước"""
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    try:
        cur = conn.cursor()
        now = datetime.now()
        
        # Kiểm tra GR status
        cur.execute("""
            SELECT io.m_inout_id, io.ad_client_id, io.ad_org_id, io.docstatus, 
                   io.movementdate, io.c_bpartner_id, io.c_bpartner_location_id,
                   io.c_order_id, io.m_warehouse_id
            FROM m_inout io
            WHERE io.m_inout_id = %s
        """, (inout_id,))
        gr = cur.fetchone()
        
        if not gr:
            conn.close()
            return jsonify({'error': 'Goods Receipt not found'}), 404
        
        # === BƯỚC 1: Complete GR nếu chưa complete ===
        if gr['docstatus'] != 'CO':
            # Lấy các dòng GR để cập nhật storage
            cur.execute("""
                SELECT iol.m_inoutline_id, iol.m_product_id, iol.m_locator_id, 
                       iol.movementqty, iol.c_orderline_id,
                       COALESCE(iol.m_attributesetinstance_id, p.m_attributesetinstance_id) as m_attributesetinstance_id,
                       p.c_uom_id
                FROM m_inoutline iol
                JOIN m_product p ON iol.m_product_id = p.m_product_id
                WHERE iol.m_inout_id = %s AND iol.isactive = 'Y'
            """, (inout_id,))
            lines = cur.fetchall()
            
            # Tạo M_Transaction và cập nhật storage cho từng dòng
            for line in lines:
                product_id = line['m_product_id']
                locator_id = line['m_locator_id']
                qty = line['movementqty']
                uom_id = line['c_uom_id']
                attr_id = line['m_attributesetinstance_id'] or '0'  # Default '0' if null
                inoutline_id = line['m_inoutline_id']
                
                # Tạo M_Transaction record
                transaction_id = generate_uuid()
                cur.execute("""
                    INSERT INTO m_transaction (
                        m_transaction_id, ad_client_id, ad_org_id, isactive,
                        created, createdby, updated, updatedby,
                        movementtype, m_locator_id, m_product_id,
                        movementdate, movementqty, m_inoutline_id,
                        m_attributesetinstance_id, c_uom_id,
                        trxprocessdate, iscostcalculated, isprocessed
                    ) VALUES (
                        %s, %s, %s, 'Y', %s, '0', %s, '0',
                        'V+', %s, %s, %s, %s, %s, %s, %s, %s, 'N', 'Y'
                    )
                """, (transaction_id, gr['ad_client_id'], gr['ad_org_id'],
                      now, now, locator_id, product_id,
                      gr['movementdate'], qty, inoutline_id, attr_id, uom_id, now))
                
                # Cập nhật m_storage_detail
                cur.execute("""
                    SELECT m_storage_detail_id, qtyonhand
                    FROM m_storage_detail
                    WHERE m_product_id = %s AND m_locator_id = %s
                    AND COALESCE(m_attributesetinstance_id, '0') = COALESCE(%s, '0')
                    AND isactive = 'Y' LIMIT 1
                """, (product_id, locator_id, attr_id))
                storage = cur.fetchone()
                
                if storage:
                    cur.execute("""
                        UPDATE m_storage_detail SET qtyonhand = qtyonhand + %s, updated = %s
                        WHERE m_storage_detail_id = %s
                    """, (qty, now, storage['m_storage_detail_id']))
                else:
                    storage_id = generate_uuid()
                    cur.execute("""
                        INSERT INTO m_storage_detail (
                            m_storage_detail_id, ad_client_id, ad_org_id, isactive,
                            created, createdby, updated, updatedby,
                            m_product_id, m_locator_id, m_attributesetinstance_id,
                            c_uom_id, qtyonhand, qtyorderonhand, qtyreserved
                        ) VALUES (%s, %s, %s, 'Y', %s, '0', %s, '0', %s, %s, %s, %s, %s, 0, 0)
                    """, (storage_id, gr['ad_client_id'], gr['ad_org_id'],
                          now, now, product_id, locator_id, attr_id, uom_id, qty))
            
            # Update trạng thái GR
            cur.execute("""
                UPDATE m_inout SET docstatus = 'CO', docaction = 'CL', processed = 'Y', updated = %s
                WHERE m_inout_id = %s
            """, (now, inout_id))
            
            # Update qtydelivered trong c_orderline
            cur.execute("""
                UPDATE c_orderline ol SET qtydelivered = ol.qtydelivered + iol.movementqty, updated = %s
                FROM m_inoutline iol WHERE iol.c_orderline_id = ol.c_orderline_id AND iol.m_inout_id = %s
            """, (now, inout_id))
        
        # === BƯỚC 2: Generate Invoice ===
        cur.execute("""
            SELECT o.c_currency_id, o.m_pricelist_id, o.c_paymentterm_id, o.fin_paymentmethod_id
            FROM c_order o WHERE o.c_order_id = %s
        """, (gr['c_order_id'],))
        po = cur.fetchone()
        
        if not po:
            conn.commit()
            conn.close()
            return jsonify({'success': True, 'message': 'GR completed but no PO found for invoice'})
        
        cur.execute("""
            SELECT c_doctype_id FROM c_doctype
            WHERE docbasetype = 'API' AND ad_org_id IN (%s, '0') AND isactive = 'Y'
            ORDER BY isdefault DESC LIMIT 1
        """, (gr['ad_org_id'],))
        doctype = cur.fetchone()
        
        if not doctype:
            conn.commit()
            conn.close()
            return jsonify({'success': True, 'message': 'GR completed but no Invoice DocType found'})
        
        c_invoice_id = generate_uuid()
        cur.execute("SELECT currentnext FROM ad_sequence WHERE name = 'DocumentNo_C_Invoice' AND ad_client_id = %s LIMIT 1", (gr['ad_client_id'],))
        seq = cur.fetchone()
        invoice_docno = f"API-{now.strftime('%Y%m%d')}-{seq['currentnext'] if seq else '001'}"
        
        if seq:
            cur.execute("UPDATE ad_sequence SET currentnext = currentnext + 1, updated = %s WHERE name = 'DocumentNo_C_Invoice' AND ad_client_id = %s", (now, gr['ad_client_id']))
        
        cur.execute("""
            SELECT iol.m_inoutline_id, iol.m_product_id, iol.movementqty, iol.c_orderline_id, iol.m_attributesetinstance_id,
                   p.c_uom_id, COALESCE(ol.priceactual, 0) as price, ol.c_tax_id
            FROM m_inoutline iol JOIN m_product p ON iol.m_product_id = p.m_product_id
            LEFT JOIN c_orderline ol ON iol.c_orderline_id = ol.c_orderline_id
            WHERE iol.m_inout_id = %s AND iol.isactive = 'Y'
        """, (inout_id,))
        inv_lines = cur.fetchall()
        
        total_lines = sum(float(l['movementqty']) * float(l['price']) for l in inv_lines)
        
        cur.execute("""
            INSERT INTO c_invoice (
                c_invoice_id, ad_client_id, ad_org_id, isactive, created, createdby, updated, updatedby,
                issotrx, documentno, docstatus, docaction, processing, processed, posted,
                c_doctype_id, c_doctypetarget_id, c_order_id, c_bpartner_id, c_bpartner_location_id,
                dateinvoiced, dateacct, c_currency_id, c_paymentterm_id, m_pricelist_id,
                isprinted, isdiscountprinted, isselfservice, iscashvat,
                totallines, grandtotal, chargeamt, withholdingamount,
                ispaid, totalpaid, outstandingamt, daystilldue, dueamt, prepaymentamt, calculate_promotions,
                createfrom, generateto, copyfrom, createfromorders, createfrominouts, fin_paymentmethod_id
            ) VALUES (
                %s, %s, %s, 'Y', %s, '0', %s, '0', 'N', %s, 'DR', 'CO', 'N', 'N', 'N',
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                'N', 'N', 'N', 'N', %s, %s, 0, 0, 'N', 0, %s, 0, 0, 0, 'N',
                'N', 'N', 'N', 'N', 'Y', %s
            )
        """, (c_invoice_id, gr['ad_client_id'], gr['ad_org_id'], now, now, invoice_docno,
              doctype['c_doctype_id'], doctype['c_doctype_id'], gr['c_order_id'], gr['c_bpartner_id'], gr['c_bpartner_location_id'],
              now, now, po['c_currency_id'], po['c_paymentterm_id'], po['m_pricelist_id'],
              total_lines, total_lines, total_lines, po['fin_paymentmethod_id']))
        
        line_no = 0
        for line in inv_lines:
            line_no += 10
            c_invoiceline_id = generate_uuid()
            line_amount = float(line['movementqty']) * float(line['price'])
            cur.execute("""
                INSERT INTO c_invoiceline (
                    c_invoiceline_id, ad_client_id, ad_org_id, isactive, created, createdby, updated, updatedby,
                    c_invoice_id, c_orderline_id, m_inoutline_id, line, m_product_id, qtyinvoiced,
                    pricelist, priceactual, pricelimit, pricestd, linenetamt, c_uom_id, c_tax_id, m_attributesetinstance_id,
                    isdescription, financial_invoice_line, isdeferred, explode, grosspricelist, grosspricestd
                ) VALUES (%s, %s, %s, 'Y', %s, '0', %s, '0', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    'N', 'N', 'N', 'N', %s, %s)
            """, (c_invoiceline_id, gr['ad_client_id'], gr['ad_org_id'], now, now,
                  c_invoice_id, line['c_orderline_id'], line['m_inoutline_id'], line_no, line['m_product_id'], line['movementqty'],
                  line['price'], line['price'], line['price'], line['price'], line_amount, line['c_uom_id'], line['c_tax_id'], line['m_attributesetinstance_id'],
                  line['price'], line['price']))
        
        conn.commit()
        conn.close()
        
        return jsonify({
            'success': True,
            'invoice': {'c_invoice_id': c_invoice_id, 'documentno': invoice_docno},
            'message': f'GR completed & Invoice {invoice_docno} created.'
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        if conn:
            conn.rollback()
            conn.close()
        return jsonify({'error': str(e)}), 500


@app.route('/api/goods-receipts')
def get_goods_receipts():
    """Get Goods Receipts list with optional filters"""
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    # Get filter parameters
    search = request.args.get('search', '').strip()
    docstatus = request.args.get('docstatus', '').strip()
    bpartner_id = request.args.get('bpartner_id', '').strip()
    warehouse_id = request.args.get('warehouse_id', '').strip()
    date_from = request.args.get('date_from', '').strip()
    date_to = request.args.get('date_to', '').strip()
    po_documentno = request.args.get('po_documentno', '').strip()
    pending_only = request.args.get('pending_only', '').strip().lower() == 'true'
    
    try:
        cur = conn.cursor()
        
        # Build dynamic query with filters
        query = """
            SELECT 
                io.m_inout_id,
                io.documentno,
                io.movementdate,
                io.docstatus,
                bp.name as bpartner_name,
                bp.c_bpartner_id,
                o.documentno as po_documentno,
                w.name as warehouse_name,
                w.m_warehouse_id
            FROM m_inout io
            JOIN c_bpartner bp ON io.c_bpartner_id = bp.c_bpartner_id
            LEFT JOIN c_order o ON io.c_order_id = o.c_order_id
            LEFT JOIN m_warehouse w ON io.m_warehouse_id = w.m_warehouse_id
            WHERE io.issotrx = 'N'
            AND io.isactive = 'Y'
        """
        params = []
        
        # Search filter (document number, supplier name, PO number)
        if search:
            query += """ AND (
                LOWER(io.documentno) LIKE LOWER(%s) 
                OR LOWER(bp.name) LIKE LOWER(%s)
                OR LOWER(COALESCE(o.documentno, '')) LIKE LOWER(%s)
            )"""
            search_pattern = f'%{search}%'
            params.extend([search_pattern, search_pattern, search_pattern])
        
        # Status filter
        if docstatus:
            query += " AND io.docstatus = %s"
            params.append(docstatus)
        
        # Pending only filter (not completed)
        if pending_only:
            query += " AND io.docstatus != 'CO'"
        
        # Supplier filter
        if bpartner_id:
            query += " AND io.c_bpartner_id = %s"
            params.append(bpartner_id)
        
        # Warehouse filter
        if warehouse_id:
            query += " AND io.m_warehouse_id = %s"
            params.append(warehouse_id)
        
        # Date range filter
        if date_from:
            query += " AND io.movementdate >= %s"
            params.append(date_from)
        if date_to:
            query += " AND io.movementdate <= %s"
            params.append(date_to)
        
        # PO document number filter
        if po_documentno:
            query += " AND LOWER(o.documentno) LIKE LOWER(%s)"
            params.append(f'%{po_documentno}%')
        
        query += " ORDER BY io.movementdate DESC LIMIT 200"
        
        cur.execute(query, params)
        receipts = cur.fetchall()
        return jsonify({'success': True, 'receipts': [dict(r) for r in receipts]})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/goods-receipt/<inout_id>/detail')
def get_goods_receipt_detail(inout_id):
    """Lấy chi tiết Goods Receipt bao gồm các dòng sản phẩm"""
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    try:
        cur = conn.cursor()
        
        # Lấy thông tin header
        cur.execute("""
            SELECT 
                io.m_inout_id,
                io.documentno,
                io.movementdate,
                io.docstatus,
                io.description,
                bp.name as bpartner_name,
                o.documentno as po_documentno,
                w.name as warehouse_name
            FROM m_inout io
            JOIN c_bpartner bp ON io.c_bpartner_id = bp.c_bpartner_id
            LEFT JOIN c_order o ON io.c_order_id = o.c_order_id
            LEFT JOIN m_warehouse w ON io.m_warehouse_id = w.m_warehouse_id
            WHERE io.m_inout_id = %s
        """, (inout_id,))
        gr = cur.fetchone()
        
        if not gr:
            return jsonify({'error': 'Goods Receipt not found'}), 404
        
        # Lấy các dòng
        cur.execute("""
            SELECT 
                iol.m_inoutline_id,
                iol.line,
                iol.movementqty,
                p.value as product_code,
                p.name as product_name,
                COALESCE(NULLIF(p.upc, ''), p.value) as barcode,
                COALESCE(ol.priceactual, 0) as priceactual
            FROM m_inoutline iol
            JOIN m_product p ON iol.m_product_id = p.m_product_id
            LEFT JOIN c_orderline ol ON iol.c_orderline_id = ol.c_orderline_id
            WHERE iol.m_inout_id = %s
            AND iol.isactive = 'Y'
            ORDER BY iol.line
        """, (inout_id,))
        lines = cur.fetchall()
        
        return jsonify({
            'success': True,
            'goods_receipt': dict(gr),
            'lines': [dict(l) for l in lines]
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/partner-addresses/<bpartner_id>')
def get_partner_addresses(bpartner_id):
    """Lấy danh sách địa chỉ của Business Partner"""
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT 
                bpl.c_bpartner_location_id,
                bpl.name,
                bpl.isshipto,
                bpl.isbillto,
                l.address1,
                l.address2,
                l.city,
                l.postal,
                c.name as country
            FROM c_bpartner_location bpl
            LEFT JOIN c_location l ON bpl.c_location_id = l.c_location_id
            LEFT JOIN c_country c ON l.c_country_id = c.c_country_id
            WHERE bpl.c_bpartner_id = %s AND bpl.isactive = 'Y'
            ORDER BY bpl.name
        """, (bpartner_id,))
        addresses = cur.fetchall()
        return jsonify({'success': True, 'addresses': [dict(a) for a in addresses]})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/bpartner-defaults/<bpartner_id>')
def get_bpartner_defaults(bpartner_id):
    """Lấy giá trị mặc định của Business Partner (payment terms, price list, address)"""
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    try:
        cur = conn.cursor()
        
        # Get business partner with defaults
        cur.execute("""
            SELECT 
                bp.c_bpartner_id,
                bp.name,
                bp.m_pricelist_id,
                bp.c_paymentterm_id,
                bp.fin_paymentmethod_id,
                pl.name as pricelist_name,
                pt.name as paymentterm_name,
                pm.name as paymentmethod_name
            FROM c_bpartner bp
            LEFT JOIN m_pricelist pl ON bp.m_pricelist_id = pl.m_pricelist_id
            LEFT JOIN c_paymentterm pt ON bp.c_paymentterm_id = pt.c_paymentterm_id
            LEFT JOIN fin_paymentmethod pm ON bp.fin_paymentmethod_id = pm.fin_paymentmethod_id
            WHERE bp.c_bpartner_id = %s
        """, (bpartner_id,))
        bpartner = cur.fetchone()
        
        if not bpartner:
            return jsonify({'error': 'Business Partner not found'}), 404
        
        # Get default ship-to address
        cur.execute("""
            SELECT c_bpartner_location_id, name
            FROM c_bpartner_location
            WHERE c_bpartner_id = %s AND isactive = 'Y'
            ORDER BY isshipto DESC, isbillto DESC
            LIMIT 1
        """, (bpartner_id,))
        default_address = cur.fetchone()
        
        return jsonify({
            'success': True,
            'defaults': {
                'm_pricelist_id': bpartner['m_pricelist_id'],
                'c_paymentterm_id': bpartner['c_paymentterm_id'],
                'fin_paymentmethod_id': bpartner['fin_paymentmethod_id'],
                'c_bpartner_location_id': default_address['c_bpartner_location_id'] if default_address else None,
                'pricelist_name': bpartner['pricelist_name'],
                'paymentterm_name': bpartner['paymentterm_name'],
                'paymentmethod_name': bpartner['paymentmethod_name'],
                'address_name': default_address['name'] if default_address else None
            }
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/price-lists')
def get_price_lists():
    """Lấy danh sách Price Lists"""
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT 
                pl.m_pricelist_id,
                pl.name,
                pl.description,
                c.iso_code as currency
            FROM m_pricelist pl
            LEFT JOIN c_currency c ON pl.c_currency_id = c.c_currency_id
            WHERE pl.isactive = 'Y' AND pl.issopricelist = 'Y'
            ORDER BY pl.name
        """)
        pricelists = cur.fetchall()
        return jsonify({'success': True, 'pricelists': [dict(p) for p in pricelists]})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/payment-methods')
def get_payment_methods():
    """Lấy danh sách Payment Methods"""
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT 
                fin_paymentmethod_id,
                name,
                description
            FROM fin_paymentmethod
            WHERE isactive = 'Y'
            ORDER BY name
        """)
        methods = cur.fetchall()
        return jsonify({'success': True, 'methods': [dict(m) for m in methods]})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/payment-terms')
def get_payment_terms():
    """Lấy danh sách Payment Terms"""
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT 
                c_paymentterm_id,
                name,
                description,
                netdays
            FROM c_paymentterm
            WHERE isactive = 'Y'
            ORDER BY name
        """)
        terms = cur.fetchall()
        return jsonify({'success': True, 'terms': [dict(t) for t in terms]})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/projects')
def get_projects():
    """Lấy danh sách Projects"""
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    try:
        cur = conn.cursor()
        org_id = request.args.get('org_id', '')
        
        query = """
            SELECT 
                c_project_id,
                value,
                name,
                description
            FROM c_project
            WHERE isactive = 'Y'
        """
        params = []
        
        if org_id:
            query += " AND (ad_org_id = %s OR ad_org_id = 0)"
            params.append(org_id)
        
        query += " ORDER BY name"
        
        cur.execute(query, params)
        projects = cur.fetchall()
        return jsonify({'success': True, 'projects': [dict(p) for p in projects]})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/organizations')
def get_organizations():
    """Lấy danh sách Organizations"""
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT 
                org.ad_org_id,
                org.value,
                org.name,
                org.description
            FROM ad_org org
            WHERE org.isactive = 'Y'
            AND org.issummary = 'N'
            ORDER BY org.name
        """)
        organizations = cur.fetchall()
        return jsonify({'success': True, 'organizations': [dict(o) for o in organizations]})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/customers')
def get_customers():
    """Lấy danh sách khách hàng (Business Partners - Customer)"""
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    try:
        cur = conn.cursor()
        org_id = request.args.get('org_id', '')
        
        query = """
            SELECT 
                bp.c_bpartner_id,
                bp.value,
                bp.name,
                bp.name2 as commercial_name,
                bp.taxid,
                bp.iscustomer,
                bp.isvendor,
                bp.ad_org_id,
                org.name as organization
            FROM c_bpartner bp
            LEFT JOIN ad_org org ON bp.ad_org_id = org.ad_org_id
            WHERE bp.isactive = 'Y' 
            AND bp.iscustomer = 'Y'
        """
        
        params = []
        if org_id:
            # Get all parent organizations in the hierarchy
            query += """ 
                AND bp.ad_org_id IN (
                    WITH RECURSIVE org_tree AS (
                        SELECT ad_org_id, ad_org_id as root_org
                        FROM ad_org
                        WHERE ad_org_id = %s
                        UNION ALL
                        SELECT tn.parent_id, ot.root_org
                        FROM org_tree ot
                        JOIN ad_treenode tn ON tn.node_id = ot.ad_org_id
                        JOIN ad_tree t ON t.ad_tree_id = tn.ad_tree_id AND t.treetype = 'OO'
                        WHERE tn.parent_id IS NOT NULL AND tn.parent_id != '0'
                    )
                    SELECT ad_org_id FROM org_tree
                )
            """
            params.append(org_id)
        
        query += " ORDER BY bp.name"
        
        cur.execute(query, params)
        customers = cur.fetchall()
        return jsonify({'success': True, 'customers': [dict(c) for c in customers]})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/warehouses')
def get_warehouses():
    """Lấy danh sách kho hàng"""
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT 
                w.m_warehouse_id,
                w.value,
                w.name,
                w.description,
                (SELECT COUNT(*) FROM m_locator l WHERE l.m_warehouse_id = w.m_warehouse_id AND l.isactive = 'Y') as locator_count
            FROM m_warehouse w
            WHERE w.isactive = 'Y'
            ORDER BY w.name
        """)
        warehouses = cur.fetchall()
        return jsonify({'success': True, 'warehouses': [dict(w) for w in warehouses]})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/warehouse/<warehouse_id>')
def get_warehouse_detail(warehouse_id):
    """Lấy chi tiết kho và các locator"""
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    try:
        cur = conn.cursor()
        # Warehouse info
        cur.execute("""
            SELECT m_warehouse_id, value, name, description
            FROM m_warehouse WHERE m_warehouse_id = %s
        """, (warehouse_id,))
        warehouse = cur.fetchone()
        
        if not warehouse:
            return jsonify({'error': 'Warehouse not found'}), 404
        
        # Locators
        cur.execute("""
            SELECT m_locator_id, value, x, y, z, isdefault
            FROM m_locator 
            WHERE m_warehouse_id = %s AND isactive = 'Y'
            ORDER BY value
        """, (warehouse_id,))
        locators = cur.fetchall()
        
        return jsonify({
            'success': True,
            'warehouse': dict(warehouse),
            'locators': [dict(l) for l in locators]
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/warehouse/<warehouse_id>/locators')
def get_warehouse_locators(warehouse_id):
    """Lấy danh sách locators của một warehouse"""
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT m_locator_id, value, x, y, z, isdefault
            FROM m_locator 
            WHERE m_warehouse_id = %s AND isactive = 'Y'
            ORDER BY value
        """, (warehouse_id,))
        locators = cur.fetchall()
        
        return jsonify({
            'success': True,
            'locators': [dict(l) for l in locators]
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/organizations-with-warehouses')
def get_organizations_with_warehouses():
    """Lấy danh sách địa điểm (organizations) với warehouses của chúng"""
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    try:
        cur = conn.cursor()
        # Lấy organizations có warehouse
        cur.execute("""
            SELECT 
                o.ad_org_id,
                o.value as org_code,
                o.name as org_name,
                o.description as org_description
            FROM ad_org o
            WHERE o.isactive = 'Y'
            AND EXISTS (SELECT 1 FROM m_warehouse w WHERE w.ad_org_id = o.ad_org_id AND w.isactive = 'Y')
            ORDER BY o.name
        """)
        orgs = cur.fetchall()
        
        result = []
        for org in orgs:
            # Lấy warehouses của org này
            cur.execute("""
                SELECT 
                    w.m_warehouse_id,
                    w.value as warehouse_code,
                    w.name as warehouse_name,
                    w.description,
                    (SELECT COUNT(*) FROM m_locator l WHERE l.m_warehouse_id = w.m_warehouse_id AND l.isactive = 'Y') as locator_count,
                    (SELECT COUNT(DISTINCT sd.m_product_id) FROM m_storage_detail sd 
                     JOIN m_locator l ON sd.m_locator_id = l.m_locator_id 
                     WHERE l.m_warehouse_id = w.m_warehouse_id AND sd.qtyonhand > 0) as product_count,
                    (SELECT COALESCE(SUM(sd.qtyonhand), 0) FROM m_storage_detail sd 
                     JOIN m_locator l ON sd.m_locator_id = l.m_locator_id 
                     WHERE l.m_warehouse_id = w.m_warehouse_id) as total_qty
                FROM m_warehouse w
                WHERE w.ad_org_id = %s AND w.isactive = 'Y'
                ORDER BY w.name
            """, (org['ad_org_id'],))
            warehouses = cur.fetchall()
            
            result.append({
                'ad_org_id': org['ad_org_id'],
                'org_code': org['org_code'],
                'org_name': org['org_name'],
                'org_description': org['org_description'],
                'warehouses': [dict(w) for w in warehouses]
            })
        
        return jsonify({'success': True, 'organizations': result})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/warehouse/<warehouse_id>/products')
def get_warehouse_products(warehouse_id):
    """Lấy danh sách sản phẩm có trong kho với số lượng và vị trí"""
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT 
                p.m_product_id,
                p.value as product_code,
                p.name as product_name,
                COALESCE(NULLIF(p.upc, ''), p.value) as barcode,
                l.m_locator_id,
                l.value as locator_code,
                sd.qtyonhand,
                uom.name as uom_name
            FROM m_storage_detail sd
            JOIN m_product p ON sd.m_product_id = p.m_product_id
            JOIN m_locator l ON sd.m_locator_id = l.m_locator_id
            LEFT JOIN c_uom uom ON p.c_uom_id = uom.c_uom_id
            WHERE l.m_warehouse_id = %s 
            AND sd.qtyonhand > 0
            AND sd.isactive = 'Y'
            ORDER BY l.value, p.name
        """, (warehouse_id,))
        products = cur.fetchall()
        
        # Lấy thông tin warehouse
        cur.execute("""
            SELECT w.name as warehouse_name, o.name as org_name
            FROM m_warehouse w
            LEFT JOIN ad_org o ON w.ad_org_id = o.ad_org_id
            WHERE w.m_warehouse_id = %s
        """, (warehouse_id,))
        warehouse_info = cur.fetchone()
        
        return jsonify({
            'success': True,
            'warehouse_name': warehouse_info['warehouse_name'] if warehouse_info else '',
            'org_name': warehouse_info['org_name'] if warehouse_info else '',
            'products': [dict(p) for p in products],
            'total_products': len(products)
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/locator/<locator_id>/products')
def get_locator_products(locator_id):
    """Lấy danh sách sản phẩm trong một locator cụ thể với lịch sử chuyển kho"""
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    try:
        cur = conn.cursor()
        
        # Lấy thông tin locator
        cur.execute("""
            SELECT l.value as locator_code, l.m_warehouse_id, w.name as warehouse_name
            FROM m_locator l
            JOIN m_warehouse w ON l.m_warehouse_id = w.m_warehouse_id
            WHERE l.m_locator_id = %s
        """, (locator_id,))
        locator_info = cur.fetchone()
        
        if not locator_info:
            return jsonify({'error': 'Locator not found'}), 404
        
        # Lấy sản phẩm trong locator
        cur.execute("""
            SELECT 
                p.m_product_id,
                p.value as product_code,
                p.name as product_name,
                COALESCE(NULLIF(p.upc, ''), p.value) as barcode,
                sd.qtyonhand,
                uom.name as uom_name
            FROM m_storage_detail sd
            JOIN m_product p ON sd.m_product_id = p.m_product_id
            LEFT JOIN c_uom uom ON p.c_uom_id = uom.c_uom_id
            WHERE sd.m_locator_id = %s 
            AND sd.qtyonhand > 0
            AND sd.isactive = 'Y'
            ORDER BY p.name
        """, (locator_id,))
        products = cur.fetchall()
        
        return jsonify({
            'success': True,
            'locator_code': locator_info['locator_code'],
            'warehouse_name': locator_info['warehouse_name'],
            'products': [dict(p) for p in products],
            'total_products': len(products)
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/product/<product_id>/movement-history')
def get_product_movement_history(product_id):
    """Lấy lịch sử chuyển kho của sản phẩm"""
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    try:
        cur = conn.cursor()
        locator_id = request.args.get('locator_id', '')
        print(f"DEBUG: Getting movement history for product {product_id}")
        
        query = """
            SELECT 
                m.documentno,
                m.movementdate,
                m.processed,
                ml.movementqty,
                lf.value as from_locator,
                wf.name as from_warehouse,
                lt.value as to_locator,
                wt.name as to_warehouse
            FROM m_movementline ml
            JOIN m_movement m ON ml.m_movement_id = m.m_movement_id
            LEFT JOIN m_locator lf ON ml.m_locator_id = lf.m_locator_id
            LEFT JOIN m_warehouse wf ON lf.m_warehouse_id = wf.m_warehouse_id
            LEFT JOIN m_locator lt ON ml.m_locatorto_id = lt.m_locator_id
            LEFT JOIN m_warehouse wt ON lt.m_warehouse_id = wt.m_warehouse_id
            WHERE ml.m_product_id = %s
            AND m.isactive = 'Y'
        """
        params = [product_id]
        
        if locator_id:
            query += " AND (ml.m_locator_id = %s OR ml.m_locatorto_id = %s)"
            params.extend([locator_id, locator_id])
        
        query += " ORDER BY m.movementdate DESC LIMIT 50"
        
        cur.execute(query, params)
        history = cur.fetchall()
        
        return jsonify({
            'success': True,
            'history': [{
                'documentno': h['documentno'],
                'movementdate': str(h['movementdate']),
                'docstatus': 'CO' if h['processed'] == 'Y' else 'DR',
                'movementqty': float(h['movementqty']) if h['movementqty'] else 0,
                'from_warehouse': h['from_warehouse'],
                'from_locator': h['from_locator'],
                'to_warehouse': h['to_warehouse'],
                'to_locator': h['to_locator']
            } for h in history]
        })
    except Exception as e:
        import traceback
        print(f"ERROR in movement-history: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/products')
def get_products():
    """Lấy danh sách sản phẩm"""
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    try:
        cur = conn.cursor()
        limit = request.args.get('limit', 100, type=int)
        search = request.args.get('search', '')
        
        if search:
            cur.execute("""
                SELECT 
                    p.m_product_id, p.value, p.name, p.upc, p.description,
                    pc.name as category_name,
                    p.producttype, p.issold, p.ispurchased
                FROM m_product p
                LEFT JOIN m_product_category pc ON p.m_product_category_id = pc.m_product_category_id
                WHERE p.isactive = 'Y'
                AND (UPPER(p.name) LIKE UPPER(%s) OR UPPER(p.value) LIKE UPPER(%s) OR p.upc = %s)
                ORDER BY p.name
                LIMIT %s
            """, (f'%{search}%', f'%{search}%', search, limit))
        else:
            cur.execute("""
                SELECT 
                    p.m_product_id, p.value, p.name, p.upc, p.description,
                    pc.name as category_name,
                    p.producttype, p.issold, p.ispurchased
                FROM m_product p
                LEFT JOIN m_product_category pc ON p.m_product_category_id = pc.m_product_category_id
                WHERE p.isactive = 'Y'
                ORDER BY p.name
                LIMIT %s
            """, (limit,))
        
        products = cur.fetchall()
        return jsonify({'success': True, 'products': [dict(p) for p in products], 'count': len(products)})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/product/<product_id>')
def get_product_detail(product_id):
    """Lấy chi tiết sản phẩm"""
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT 
                p.m_product_id, p.value, p.name, p.upc, p.description,
                pc.name as category_name,
                p.producttype, p.issold, p.ispurchased, p.isstocked,
                uom.name as uom_name
            FROM m_product p
            LEFT JOIN m_product_category pc ON p.m_product_category_id = pc.m_product_category_id
            LEFT JOIN c_uom uom ON p.c_uom_id = uom.c_uom_id
            WHERE p.m_product_id = %s
        """, (product_id,))
        product = cur.fetchone()
        
        if not product:
            return jsonify({'error': 'Product not found'}), 404
        
        # Get prices
        cur.execute("""
            SELECT pp.pricelist, pp.pricestd, pp.pricelimit, pl.name as pricelist_name
            FROM m_productprice pp
            JOIN m_pricelist_version plv ON pp.m_pricelist_version_id = plv.m_pricelist_version_id
            JOIN m_pricelist pl ON plv.m_pricelist_id = pl.m_pricelist_id
            WHERE pp.m_product_id = %s AND pp.isactive = 'Y'
            ORDER BY pl.name
        """, (product_id,))
        prices = cur.fetchall()
        
        # Get stock
        cur.execute("""
            SELECT 
                w.name as warehouse_name,
                l.value as locator,
                COALESCE(sd.qtyonhand, 0) as qty_onhand,
                COALESCE(sd.qtyreserved, 0) as qty_reserved
            FROM m_storage_detail sd
            JOIN m_locator l ON sd.m_locator_id = l.m_locator_id
            JOIN m_warehouse w ON l.m_warehouse_id = w.m_warehouse_id
            WHERE sd.m_product_id = %s
            ORDER BY w.name, l.value
        """, (product_id,))
        stock = cur.fetchall()
        
        return jsonify({
            'success': True,
            'product': dict(product),
            'prices': [dict(p) for p in prices],
            'stock': [dict(s) for s in stock]
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/suppliers')
def get_suppliers():
    """Lấy danh sách nhà cung cấp"""
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT 
                bp.c_bpartner_id, bp.value, bp.name, bp.name2,
                bp.taxid, bp.url,
                bpg.name as group_name,
                (SELECT COUNT(*) FROM c_order o WHERE o.c_bpartner_id = bp.c_bpartner_id AND o.issotrx = 'N') as po_count
            FROM c_bpartner bp
            LEFT JOIN c_bp_group bpg ON bp.c_bp_group_id = bpg.c_bp_group_id
            WHERE bp.isactive = 'Y' AND bp.isvendor = 'Y'
            ORDER BY bp.name
            LIMIT 100
        """)
        suppliers = cur.fetchall()
        return jsonify({'success': True, 'suppliers': [dict(s) for s in suppliers], 'count': len(suppliers)})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/supplier/<bpartner_id>')
def get_supplier_detail(bpartner_id):
    """Lấy chi tiết nhà cung cấp"""
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    try:
        cur = conn.cursor()
        # Supplier info
        cur.execute("""
            SELECT 
                bp.c_bpartner_id, bp.value, bp.name, bp.name2,
                bp.taxid, bp.url, bp.description,
                bpg.name as group_name
            FROM c_bpartner bp
            LEFT JOIN c_bp_group bpg ON bp.c_bp_group_id = bpg.c_bp_group_id
            WHERE bp.c_bpartner_id = %s
        """, (bpartner_id,))
        supplier = cur.fetchone()
        
        if not supplier:
            return jsonify({'error': 'Supplier not found'}), 404
        
        # Locations/Addresses
        cur.execute("""
            SELECT bpl.c_bpartner_location_id, bpl.name, bpl.phone, bpl.fax,
                   l.address1, l.address2, l.city, l.postal
            FROM c_bpartner_location bpl
            LEFT JOIN c_location l ON bpl.c_location_id = l.c_location_id
            WHERE bpl.c_bpartner_id = %s AND bpl.isactive = 'Y'
        """, (bpartner_id,))
        locations = cur.fetchall()
        
        # Recent POs
        cur.execute("""
            SELECT o.c_order_id, o.documentno, o.dateordered, o.docstatus, o.grandtotal
            FROM c_order o
            WHERE o.c_bpartner_id = %s AND o.issotrx = 'N' AND o.isactive = 'Y'
            ORDER BY o.dateordered DESC
            LIMIT 10
        """, (bpartner_id,))
        orders = cur.fetchall()
        
        return jsonify({
            'success': True,
            'supplier': dict(supplier),
            'locations': [dict(l) for l in locations],
            'recent_orders': [dict(o) for o in orders]
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/stock')
def get_stock_levels():
    """Lấy tồn kho"""
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    try:
        cur = conn.cursor()
        warehouse_id = request.args.get('warehouse_id', '')
        
        query = """
            SELECT 
                p.m_product_id, p.value as product_code, p.name as product_name, p.upc,
                w.name as warehouse_name,
                l.value as locator,
                COALESCE(sd.qtyonhand, 0) as qty_onhand,
                COALESCE(sd.qtyreserved, 0) as qty_reserved,
                COALESCE(sd.qtyonhand, 0) - COALESCE(sd.qtyreserved, 0) as qty_available
            FROM m_storage_detail sd
            JOIN m_product p ON sd.m_product_id = p.m_product_id
            JOIN m_locator l ON sd.m_locator_id = l.m_locator_id
            JOIN m_warehouse w ON l.m_warehouse_id = w.m_warehouse_id
            WHERE sd.qtyonhand <> 0
        """
        params = []
        
        if warehouse_id:
            query += " AND w.m_warehouse_id = %s"
            params.append(warehouse_id)
        
        query += " ORDER BY p.name, w.name LIMIT 200"
        
        cur.execute(query, params)
        stock = cur.fetchall()
        
        return jsonify({'success': True, 'stock': [dict(s) for s in stock], 'count': len(stock)})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/product-categories')
def get_product_categories():
    """Lấy danh mục sản phẩm"""
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT 
                pc.m_product_category_id, pc.value, pc.name, pc.description,
                (SELECT COUNT(*) FROM m_product p WHERE p.m_product_category_id = pc.m_product_category_id) as product_count
            FROM m_product_category pc
            WHERE pc.isactive = 'Y'
            ORDER BY pc.name
        """)
        categories = cur.fetchall()
        return jsonify({'success': True, 'categories': [dict(c) for c in categories]})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/movements/by-date')
def get_movements_by_date():
    """Get Goods Movements grouped by date with product summary"""
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    try:
        cur = conn.cursor()
        
        # Get movements grouped by date with line count and product info
        query = """
            SELECT 
                DATE(m.movementdate) as movement_date,
                COUNT(DISTINCT m.m_movement_id) as movement_count,
                SUM(ml.movementqty) as total_qty,
                COUNT(DISTINCT ml.m_product_id) as product_count
            FROM m_movement m
            JOIN m_movementline ml ON m.m_movement_id = ml.m_movement_id
            WHERE m.isactive = 'Y' AND ml.isactive = 'Y'
            GROUP BY DATE(m.movementdate)
            ORDER BY DATE(m.movementdate) DESC
            LIMIT 60
        """
        
        cur.execute(query)
        dates = cur.fetchall()
        
        # Format dates properly
        result = []
        for d in dates:
            result.append({
                'movement_date': str(d['movement_date']),  # Ensure YYYY-MM-DD format
                'movement_count': d['movement_count'],
                'total_qty': float(d['total_qty'] or 0),
                'product_count': d['product_count']
            })
        
        return jsonify({
            'success': True, 
            'dates': result
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/movements/by-date/<date>')
def get_movements_by_specific_date(date):
    """Get all product movements for a specific date"""
    # Validate date format
    import re
    if not re.match(r'^\d{4}-\d{2}-\d{2}$', date):
        return jsonify({'error': f'Invalid date format: {date}. Expected YYYY-MM-DD'}), 400
    
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    try:
        cur = conn.cursor()
        
        # Get all movement lines for the date with full details
        query = """
            SELECT 
                m.m_movement_id,
                m.documentno,
                m.docstatus,
                m.movementdate,
                ml.m_movementline_id,
                ml.movementqty,
                p.value as product_code,
                p.name as product_name,
                COALESCE(NULLIF(p.upc, ''), p.value) as barcode,
                lf.value as from_locator,
                wf.name as from_warehouse,
                lt.value as to_locator,
                wt.name as to_warehouse,
                uom.name as uom_name
            FROM m_movement m
            JOIN m_movementline ml ON m.m_movement_id = ml.m_movement_id
            JOIN m_product p ON ml.m_product_id = p.m_product_id
            LEFT JOIN m_locator lf ON ml.m_locator_id = lf.m_locator_id
            LEFT JOIN m_warehouse wf ON lf.m_warehouse_id = wf.m_warehouse_id
            LEFT JOIN m_locator lt ON ml.m_locatorto_id = lt.m_locator_id
            LEFT JOIN m_warehouse wt ON lt.m_warehouse_id = wt.m_warehouse_id
            LEFT JOIN c_uom uom ON p.c_uom_id = uom.c_uom_id
            WHERE DATE(m.movementdate) = %s
            AND m.isactive = 'Y' AND ml.isactive = 'Y'
            ORDER BY m.documentno, ml.line
        """
        
        cur.execute(query, (date,))
        lines = cur.fetchall()
        
        # Group by movement document
        movements = {}
        for line in lines:
            mv_id = line['m_movement_id']
            if mv_id not in movements:
                movements[mv_id] = {
                    'm_movement_id': mv_id,
                    'documentno': line['documentno'],
                    'docstatus': line['docstatus'],
                    'movementdate': str(line['movementdate']),
                    'lines': []
                }
            movements[mv_id]['lines'].append({
                'product_code': line['product_code'],
                'product_name': line['product_name'],
                'barcode': line['barcode'],
                'movementqty': float(line['movementqty']) if line['movementqty'] else 0,
                'from_warehouse': line['from_warehouse'],
                'from_locator': line['from_locator'],
                'to_warehouse': line['to_warehouse'],
                'to_locator': line['to_locator'],
                'uom_name': line['uom_name']
            })
        
        return jsonify({
            'success': True,
            'date': date,
            'movements': list(movements.values()),
            'total_products': len(lines)
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/movements')
def get_stock_movements():
    """Get Goods Movements list with optional filters"""
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    # Get filter parameters
    search = request.args.get('search', '').strip()
    docstatus = request.args.get('docstatus', '').strip()
    from_warehouse = request.args.get('from_warehouse', '').strip()
    to_warehouse = request.args.get('to_warehouse', '').strip()
    
    try:
        cur = conn.cursor()
        
        query = """
            SELECT DISTINCT
                m.m_movement_id, 
                m.documentno, 
                m.movementdate, 
                m.docstatus,
                m.description,
                org.name as org_name,
                (SELECT w.name FROM m_warehouse w JOIN m_locator l ON w.m_warehouse_id = l.m_warehouse_id 
                 WHERE l.m_locator_id = (SELECT ml.m_locator_id FROM m_movementline ml WHERE ml.m_movement_id = m.m_movement_id LIMIT 1)) as from_warehouse,
                (SELECT w.name FROM m_warehouse w JOIN m_locator l ON w.m_warehouse_id = l.m_warehouse_id 
                 WHERE l.m_locator_id = (SELECT ml.m_locatorto_id FROM m_movementline ml WHERE ml.m_movement_id = m.m_movement_id LIMIT 1)) as to_warehouse
            FROM m_movement m
            LEFT JOIN ad_org org ON m.ad_org_id = org.ad_org_id
            WHERE m.isactive = 'Y'
        """
        params = []
        
        if search:
            query += " AND LOWER(m.documentno) LIKE LOWER(%s)"
            params.append(f'%{search}%')
        
        if docstatus:
            query += " AND m.docstatus = %s"
            params.append(docstatus)
        
        query += " ORDER BY m.movementdate DESC LIMIT 100"
        
        cur.execute(query, params)
        movements = cur.fetchall()
        
        return jsonify({'success': True, 'movements': [dict(m) for m in movements]})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/movement/<movement_id>/detail')
def get_movement_detail(movement_id):
    """Get Goods Movement detail with lines"""
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    try:
        cur = conn.cursor()
        
        # Get header
        cur.execute("""
            SELECT 
                m.m_movement_id, 
                m.documentno, 
                m.movementdate, 
                m.docstatus,
                m.description,
                org.name as org_name
            FROM m_movement m
            LEFT JOIN ad_org org ON m.ad_org_id = org.ad_org_id
            WHERE m.m_movement_id = %s
        """, (movement_id,))
        movement = cur.fetchone()
        
        if not movement:
            return jsonify({'error': 'Movement not found'}), 404
        
        # Get lines
        cur.execute("""
            SELECT 
                ml.m_movementline_id,
                ml.line,
                ml.movementqty,
                p.value as product_code,
                p.name as product_name,
                COALESCE(NULLIF(p.upc, ''), p.value) as barcode,
                lf.value as from_locator,
                wf.name as from_warehouse,
                lt.value as to_locator,
                wt.name as to_warehouse
            FROM m_movementline ml
            JOIN m_product p ON ml.m_product_id = p.m_product_id
            LEFT JOIN m_locator lf ON ml.m_locator_id = lf.m_locator_id
            LEFT JOIN m_warehouse wf ON lf.m_warehouse_id = wf.m_warehouse_id
            LEFT JOIN m_locator lt ON ml.m_locatorto_id = lt.m_locator_id
            LEFT JOIN m_warehouse wt ON lt.m_warehouse_id = wt.m_warehouse_id
            WHERE ml.m_movement_id = %s
            AND ml.isactive = 'Y'
            ORDER BY ml.line
        """, (movement_id,))
        lines = cur.fetchall()
        
        return jsonify({
            'success': True,
            'movement': dict(movement),
            'lines': [dict(l) for l in lines]
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/movement', methods=['POST'])
def create_movement():
    """Create a new Goods Movement (transfer between warehouses)"""
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    try:
        data = request.json
        from_locator_id = data.get('from_locator_id')
        to_locator_id = data.get('to_locator_id')
        lines = data.get('lines', [])  # [{product_id, qty}]
        description = data.get('description', '')
        gr_id = data.get('gr_id')  # Optional: if created from GR
        
        if not from_locator_id or not to_locator_id:
            return jsonify({'error': 'Source and destination locators required'}), 400
        
        if not lines:
            return jsonify({'error': 'At least one product line required'}), 400
        
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        # Get org and client from locator
        cur.execute("""
            SELECT l.ad_org_id, l.ad_client_id, w.name as warehouse_name
            FROM m_locator l
            JOIN m_warehouse w ON l.m_warehouse_id = w.m_warehouse_id
            WHERE l.m_locator_id = %s
        """, (from_locator_id,))
        from_loc = cur.fetchone()
        
        if not from_loc:
            return jsonify({'error': 'Source locator not found'}), 404
        
        # Generate document number
        today = datetime.now()
        prefix = f"MV-{today.strftime('%Y%m%d')}-"
        cur.execute("""
            SELECT COALESCE(MAX(CAST(SUBSTRING(documentno FROM %s) AS INTEGER)), 0) + 1 as next_num
            FROM m_movement WHERE documentno LIKE %s
        """, (len(prefix) + 1, prefix + '%'))
        next_num = cur.fetchone()['next_num']
        documentno = f"{prefix}{next_num:05d}"
        
        movement_id = str(uuid.uuid4()).replace('-', '').upper()[:32]
        
        # Create movement header - using actual table columns
        cur.execute("""
            INSERT INTO m_movement (
                m_movement_id, ad_client_id, ad_org_id, isactive, created, createdby,
                updated, updatedby, documentno, movementdate, processed, description, name
            ) VALUES (
                %s, %s, %s, 'Y', NOW(), '0', NOW(), '0', %s, %s, 'N', %s, %s
            )
        """, (movement_id, from_loc['ad_client_id'], from_loc['ad_org_id'], 
              documentno, today.date(), description, documentno))
        
        # Create movement lines
        line_no = 10
        for item in lines:
            # Get UOM from product
            cur.execute("""
                SELECT c_uom_id FROM m_product WHERE m_product_id = %s
            """, (item['product_id'],))
            product = cur.fetchone()
            if not product:
                raise Exception(f"Product {item['product_id']} not found")
            
            line_id = str(uuid.uuid4()).replace('-', '').upper()[:32]
            cur.execute("""
                INSERT INTO m_movementline (
                    m_movementline_id, ad_client_id, ad_org_id, isactive, created, createdby,
                    updated, updatedby, m_movement_id, m_locator_id, m_locatorto_id,
                    m_product_id, movementqty, line, c_uom_id
                ) VALUES (
                    %s, %s, %s, 'Y', NOW(), '0', NOW(), '0', %s, %s, %s, %s, %s, %s, %s
                )
            """, (line_id, from_loc['ad_client_id'], from_loc['ad_org_id'],
                  movement_id, from_locator_id, to_locator_id, 
                  item['product_id'], item['qty'], line_no, product['c_uom_id']))
            line_no += 10
        
        print(f"DEBUG: Movement {documentno} created in Draft status")
        
        conn.commit()
        
        return jsonify({
            'success': True,
            'movement_id': movement_id,
            'documentno': documentno,
            'message': f'Movement {documentno} created successfully (Draft - requires completion)'
        })
    except Exception as e:
        conn.rollback()
        import traceback
        print(f"ERROR in create_movement: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/movement/<movement_id>/complete', methods=['POST'])
def complete_movement(movement_id):
    """Complete a Goods Movement - create transactions and update stock"""
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        # Check if movement exists and is not completed
        cur.execute("""
            SELECT m.documentno, m.movementdate, m.ad_client_id, m.ad_org_id
            FROM m_movement m
            WHERE m.m_movement_id = %s AND m.processed = 'N'
        """, (movement_id,))
        
        movement = cur.fetchone()
        if not movement:
            return jsonify({'error': 'Movement not found or already completed'}), 404
        
        # Get all movement lines
        cur.execute("""
            SELECT m_movementline_id, m_product_id, movementqty, m_locator_id, m_locatorto_id, c_uom_id
            FROM m_movementline 
            WHERE m_movement_id = %s
        """, (movement_id,))
        movement_lines = cur.fetchall()
        
        print(f"DEBUG: Completing movement {movement['documentno']}, processing {len(movement_lines)} lines")
        
        for line in movement_lines:
            print(f"DEBUG: Processing line for product {line['m_product_id']}, qty={line['movementqty']}")
            
            # Transaction OUT from source locator (negative quantity)
            trx_out_id = str(uuid.uuid4()).replace('-', '').upper()[:32]
            cur.execute("""
                INSERT INTO m_transaction (
                    m_transaction_id, ad_client_id, ad_org_id, isactive, created, createdby,
                    updated, updatedby, m_locator_id, m_product_id, movementtype, movementqty,
                    movementdate, m_movementline_id, c_uom_id
                ) VALUES (
                    %s, %s, %s, 'Y', NOW(), '0', NOW(), '0', %s, %s, 'M-', %s, %s, %s, %s
                )
            """, (trx_out_id, movement['ad_client_id'], movement['ad_org_id'],
                  line['m_locator_id'], line['m_product_id'], -abs(line['movementqty']),
                  movement['movementdate'], line['m_movementline_id'], line['c_uom_id']))
            print(f"DEBUG: Transaction OUT created")
            
            # Update storage detail for source locator (decrease stock)
            cur.execute("""
                UPDATE m_storage_detail 
                SET qtyonhand = qtyonhand - %s, updated = NOW()
                WHERE m_locator_id = %s AND m_product_id = %s
            """, (abs(line['movementqty']), line['m_locator_id'], line['m_product_id']))
            print(f"DEBUG: Source storage updated")
            
            # Transaction IN to destination locator (positive quantity)
            trx_in_id = str(uuid.uuid4()).replace('-', '').upper()[:32]
            cur.execute("""
                INSERT INTO m_transaction (
                    m_transaction_id, ad_client_id, ad_org_id, isactive, created, createdby,
                    updated, updatedby, m_locator_id, m_product_id, movementtype, movementqty,
                    movementdate, m_movementline_id, c_uom_id
                ) VALUES (
                    %s, %s, %s, 'Y', NOW(), '0', NOW(), '0', %s, %s, 'M+', %s, %s, %s, %s
                )
            """, (trx_in_id, movement['ad_client_id'], movement['ad_org_id'],
                  line['m_locatorto_id'], line['m_product_id'], abs(line['movementqty']),
                  movement['movementdate'], line['m_movementline_id'], line['c_uom_id']))
            print(f"DEBUG: Transaction IN created")
            
            # Update or insert storage detail for destination locator (increase stock)
            cur.execute("""
                SELECT m_storage_detail_id FROM m_storage_detail 
                WHERE m_locator_id = %s AND m_product_id = %s
            """, (line['m_locatorto_id'], line['m_product_id']))
            existing = cur.fetchone()
            
            if existing:
                # Update existing record
                cur.execute("""
                    UPDATE m_storage_detail 
                    SET qtyonhand = qtyonhand + %s, updated = NOW()
                    WHERE m_locator_id = %s AND m_product_id = %s
                """, (abs(line['movementqty']), line['m_locatorto_id'], line['m_product_id']))
                print(f"DEBUG: Destination storage updated (existing)")
            else:
                # Insert new record
                storage_id = str(uuid.uuid4()).replace('-', '').upper()[:32]
                cur.execute("""
                    INSERT INTO m_storage_detail (
                        m_storage_detail_id, ad_client_id, ad_org_id, isactive,
                        created, createdby, updated, updatedby,
                        m_locator_id, m_product_id, qtyonhand
                    ) VALUES (
                        %s, %s, %s, 'Y', NOW(), '0', NOW(), '0', %s, %s, %s
                    )
                """, (storage_id, movement['ad_client_id'], movement['ad_org_id'],
                      line['m_locatorto_id'], line['m_product_id'], abs(line['movementqty'])))
                print(f"DEBUG: Destination storage created (new)")
        
        # Mark movement as processed
        cur.execute("""
            UPDATE m_movement 
            SET processed = 'Y', updated = NOW()
            WHERE m_movement_id = %s
        """, (movement_id,))
        
        print(f"DEBUG: Movement {movement['documentno']} marked as processed")
        
        conn.commit()
        
        return jsonify({
            'success': True,
            'message': f'Movement {movement["documentno"]} completed successfully'
        })
    except Exception as e:
        conn.rollback()
        import traceback
        print(f"ERROR in complete_movement: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/movement/from-gr/<gr_id>', methods=['POST'])
def create_movement_from_gr(gr_id):
    """Auto-create Movement from Goods Receipt - transfer to destination warehouse"""
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    try:
        data = request.json or {}
        to_locator_id = data.get('to_locator_id')
        
        cur = conn.cursor()
        
        # Get GR info
        cur.execute("""
            SELECT io.m_inout_id, io.documentno, io.ad_client_id, io.ad_org_id,
                   io.m_warehouse_id, io.docstatus
            FROM m_inout io
            WHERE io.m_inout_id = %s
        """, (gr_id,))
        gr = cur.fetchone()
        
        if not gr:
            return jsonify({'error': 'Goods Receipt not found'}), 404
        
        # Get default source locator from GR warehouse (RN111 or default)
        cur.execute("""
            SELECT l.m_locator_id, l.value, w.name as warehouse_name
            FROM m_locator l
            JOIN m_warehouse w ON l.m_warehouse_id = w.m_warehouse_id
            WHERE l.m_warehouse_id = %s AND l.isactive = 'Y'
            ORDER BY l.isdefault DESC
            LIMIT 1
        """, (gr['m_warehouse_id'],))
        from_loc = cur.fetchone()
        
        if not from_loc:
            return jsonify({'error': 'No source locator found in GR warehouse'}), 404
        
        if not to_locator_id:
            # If no destination, just return the GR products for transfer later
            cur.execute("""
                SELECT 
                    iol.m_product_id, iol.movementqty,
                    p.value as product_code, p.name as product_name
                FROM m_inoutline iol
                JOIN m_product p ON iol.m_product_id = p.m_product_id
                WHERE iol.m_inout_id = %s AND iol.isactive = 'Y'
            """, (gr_id,))
            products = cur.fetchall()
            
            return jsonify({
                'success': True,
                'gr_documentno': gr['documentno'],
                'from_locator': dict(from_loc),
                'products': [dict(p) for p in products],
                'message': 'Ready to create movement. Please select destination warehouse.'
            })
        
        # Create movement with destination
        cur.execute("""
            SELECT 
                iol.m_product_id, iol.movementqty
            FROM m_inoutline iol
            WHERE iol.m_inout_id = %s AND iol.isactive = 'Y'
        """, (gr_id,))
        lines_data = cur.fetchall()
        
        # Generate document number
        today = datetime.now()
        prefix = f"MV-{today.strftime('%Y%m%d')}-"
        cur.execute("""
            SELECT COALESCE(MAX(CAST(SUBSTRING(documentno FROM %s) AS INTEGER)), 0) + 1
            FROM m_movement WHERE documentno LIKE %s
        """, (len(prefix) + 1, prefix + '%'))
        next_num = cur.fetchone()[0]
        documentno = f"{prefix}{next_num:05d}"
        
        movement_id = str(uuid.uuid4()).replace('-', '').upper()[:32]
        
        # Create movement header
        cur.execute("""
            INSERT INTO m_movement (
                m_movement_id, ad_client_id, ad_org_id, isactive, created, createdby,
                updated, updatedby, documentno, movementdate, docstatus, docaction,
                processing, processed, description
            ) VALUES (
                %s, %s, %s, 'Y', NOW(), '0', NOW(), '0', %s, %s, 'DR', 'CO',
                'N', 'N', %s
            )
        """, (movement_id, gr['ad_client_id'], gr['ad_org_id'], 
              documentno, today.date(), f"Transfer from GR {gr['documentno']}"))
        
        # Create movement lines
        line_no = 10
        for item in lines_data:
            line_id = str(uuid.uuid4()).replace('-', '').upper()[:32]
            cur.execute("""
                INSERT INTO m_movementline (
                    m_movementline_id, ad_client_id, ad_org_id, isactive, created, createdby,
                    updated, updatedby, m_movement_id, m_locator_id, m_locatorto_id,
                    m_product_id, movementqty, line
                ) VALUES (
                    %s, %s, %s, 'Y', NOW(), '0', NOW(), '0', %s, %s, %s, %s, %s, %s
                )
            """, (line_id, gr['ad_client_id'], gr['ad_org_id'],
                  movement_id, from_loc['m_locator_id'], to_locator_id, 
                  item['m_product_id'], item['movementqty'], line_no))
            line_no += 10
        
        conn.commit()
        
        return jsonify({
            'success': True,
            'movement_id': movement_id,
            'documentno': documentno,
            'message': f'Movement {documentno} created from GR {gr["documentno"]}'
        })
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/movements/list')
def get_movements_list():
    """Get all movements with status for management UI"""
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        status_filter = request.args.get('status', '')  # 'DR' or 'CO'
        
        query = """
            SELECT 
                m.m_movement_id,
                m.documentno,
                m.movementdate,
                m.processed,
                m.description,
                COUNT(ml.m_movementline_id) as line_count,
                SUM(ml.movementqty) as total_qty
            FROM m_movement m
            LEFT JOIN m_movementline ml ON m.m_movement_id = ml.m_movement_id
            WHERE m.isactive = 'Y'
        """
        
        params = []
        if status_filter == 'DR':
            query += " AND m.processed = 'N'"
        elif status_filter == 'CO':
            query += " AND m.processed = 'Y'"
        
        query += """
            GROUP BY m.m_movement_id, m.documentno, m.movementdate, m.processed, m.description
            ORDER BY m.movementdate DESC, m.created DESC
            LIMIT 100
        """
        
        cur.execute(query, params)
        movements = cur.fetchall()
        
        return jsonify({
            'success': True,
            'movements': [dict(m) for m in movements]
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/movements/cleanup-empty', methods=['POST'])
def cleanup_empty_movements():
    """Deactivate all movements without lines"""
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        # Find empty movements
        cur.execute("""
            SELECT m.m_movement_id, m.documentno
            FROM m_movement m
            LEFT JOIN m_movementline ml ON m.m_movement_id = ml.m_movement_id
            WHERE ml.m_movementline_id IS NULL AND m.isactive = 'Y'
        """)
        
        empty_movements = cur.fetchall()
        
        if not empty_movements:
            return jsonify({'success': True, 'message': 'No empty movements found', 'count': 0})
        
        # Deactivate them
        for mv in empty_movements:
            cur.execute("""
                UPDATE m_movement 
                SET isactive = 'N', updated = NOW()
                WHERE m_movement_id = %s
            """, (mv['m_movement_id'],))
        
        conn.commit()
        
        return jsonify({
            'success': True,
            'message': f'Deactivated {len(empty_movements)} empty movements',
            'count': len(empty_movements)
        })
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/inventories')
def get_inventories():
    """Lấy danh sách phiếu kiểm kê"""
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT 
                i.m_inventory_id, i.documentno, i.movementdate, i.docstatus,
                i.description, w.name as warehouse_name
            FROM m_inventory i
            LEFT JOIN m_warehouse w ON i.m_warehouse_id = w.m_warehouse_id
            WHERE i.isactive = 'Y'
            ORDER BY i.movementdate DESC
            LIMIT 50
        """)
        inventories = cur.fetchall()
        return jsonify({'success': True, 'inventories': [dict(i) for i in inventories]})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/dashboard')
def get_dashboard_stats():
    """Lấy thống kê tổng quan cho dashboard"""
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    try:
        cur = conn.cursor()
        stats = {}
        
        # PO count
        cur.execute("SELECT COUNT(*) as count FROM c_order WHERE issotrx = 'N' AND docstatus = 'CO' AND isactive = 'Y'")
        stats['po_completed'] = cur.fetchone()['count']
        
        cur.execute("SELECT COUNT(*) as count FROM c_order WHERE issotrx = 'N' AND docstatus = 'DR' AND isactive = 'Y'")
        stats['po_draft'] = cur.fetchone()['count']
        
        # GR count
        cur.execute("SELECT COUNT(*) as count FROM m_inout WHERE issotrx = 'N' AND docstatus = 'CO' AND isactive = 'Y'")
        stats['gr_completed'] = cur.fetchone()['count']
        
        cur.execute("SELECT COUNT(*) as count FROM m_inout WHERE issotrx = 'N' AND docstatus = 'DR' AND isactive = 'Y'")
        stats['gr_draft'] = cur.fetchone()['count']
        
        # Product count
        cur.execute("SELECT COUNT(*) as count FROM m_product WHERE isactive = 'Y'")
        stats['products'] = cur.fetchone()['count']
        
        # Supplier count
        cur.execute("SELECT COUNT(*) as count FROM c_bpartner WHERE isvendor = 'Y' AND isactive = 'Y'")
        stats['suppliers'] = cur.fetchone()['count']
        
        # Warehouse count
        cur.execute("SELECT COUNT(*) as count FROM m_warehouse WHERE isactive = 'Y'")
        stats['warehouses'] = cur.fetchone()['count']
        
        # Pending PO lines
        cur.execute("""
            SELECT COUNT(*) as count FROM c_orderline ol
            JOIN c_order o ON ol.c_order_id = o.c_order_id
            WHERE o.issotrx = 'N' AND o.docstatus = 'CO' AND (ol.qtyordered - ol.qtydelivered) > 0
        """)
        stats['pending_lines'] = cur.fetchone()['count']
        
        return jsonify({'success': True, 'stats': stats})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


# ==================== DATABASE TABLES API ====================

@app.route('/api/tables')
def get_all_tables():
    """Lấy danh sách tất cả các bảng trong database"""
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT table_name, 
                   (SELECT count(*) FROM information_schema.columns c 
                    WHERE c.table_name = t.table_name) as column_count
            FROM information_schema.tables t
            WHERE table_schema = 'public'
            AND table_type = 'BASE TABLE'
            ORDER BY table_name
        """)
        tables = cur.fetchall()
        return jsonify({'success': True, 'tables': [dict(t) for t in tables], 'count': len(tables)})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/table/<table_name>')
def get_table_structure(table_name):
    """Lấy cấu trúc của một bảng cụ thể"""
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    try:
        cur = conn.cursor()
        # Lấy columns
        cur.execute("""
            SELECT column_name, data_type, is_nullable, column_default,
                   character_maximum_length
            FROM information_schema.columns
            WHERE table_name = %s
            ORDER BY ordinal_position
        """, (table_name.lower(),))
        columns = cur.fetchall()
        
        # Lấy 10 rows mẫu
        try:
            cur.execute(f"SELECT * FROM {table_name} LIMIT 10")
            sample_data = cur.fetchall()
        except:
            sample_data = []
        
        return jsonify({
            'success': True,
            'table_name': table_name,
            'columns': [dict(c) for c in columns],
            'sample_data': [dict(r) for r in sample_data]
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/tables/related')
def get_related_tables():
    """Lấy danh sách các bảng liên quan đến Purchase Order và Goods Receipt"""
    related = {
        'purchase_order': {
            'description': 'Bảng liên quan đến Purchase Order (Đơn đặt hàng mua)',
            'tables': [
                {'name': 'c_order', 'desc': 'Header đơn hàng (ISSOTRX=N là Purchase)'},
                {'name': 'c_orderline', 'desc': 'Chi tiết dòng đơn hàng'},
                {'name': 'c_orderlinetax', 'desc': 'Thuế theo dòng'},
                {'name': 'c_ordertax', 'desc': 'Tổng thuế đơn hàng'},
                {'name': 'c_order_discount', 'desc': 'Chiết khấu đơn hàng'},
            ]
        },
        'goods_receipt': {
            'description': 'Bảng liên quan đến Goods Receipt (Phiếu nhập kho)',
            'tables': [
                {'name': 'm_inout', 'desc': 'Header phiếu nhập/xuất kho'},
                {'name': 'm_inoutline', 'desc': 'Chi tiết dòng phiếu'},
                {'name': 'm_matchpo', 'desc': 'Khớp với PO'},
            ]
        },
        'product': {
            'description': 'Bảng liên quan đến Sản phẩm',
            'tables': [
                {'name': 'm_product', 'desc': 'Master sản phẩm (chứa UPC barcode)'},
                {'name': 'm_product_category', 'desc': 'Danh mục sản phẩm'},
                {'name': 'm_productprice', 'desc': 'Giá sản phẩm'},
                {'name': 'm_product_po', 'desc': 'Thông tin mua hàng sản phẩm'},
            ]
        },
        'inventory': {
            'description': 'Bảng liên quan đến Kho',
            'tables': [
                {'name': 'm_warehouse', 'desc': 'Kho hàng'},
                {'name': 'm_locator', 'desc': 'Vị trí trong kho'},
                {'name': 'm_storage_detail', 'desc': 'Chi tiết tồn kho'},
                {'name': 'm_inventory', 'desc': 'Kiểm kê'},
                {'name': 'm_movement', 'desc': 'Chuyển kho'},
            ]
        },
        'business_partner': {
            'description': 'Bảng liên quan đến Đối tác (Nhà cung cấp/Khách hàng)',
            'tables': [
                {'name': 'c_bpartner', 'desc': 'Master đối tác'},
                {'name': 'c_bpartner_location', 'desc': 'Địa chỉ đối tác'},
                {'name': 'c_bp_group', 'desc': 'Nhóm đối tác'},
            ]
        },
        'invoice': {
            'description': 'Bảng liên quan đến Hóa đơn',
            'tables': [
                {'name': 'c_invoice', 'desc': 'Header hóa đơn'},
                {'name': 'c_invoiceline', 'desc': 'Chi tiết dòng hóa đơn'},
                {'name': 'c_invoicetax', 'desc': 'Thuế hóa đơn'},
            ]
        },
        'payment': {
            'description': 'Bảng liên quan đến Thanh toán',
            'tables': [
                {'name': 'fin_payment', 'desc': 'Thanh toán'},
                {'name': 'fin_payment_detail', 'desc': 'Chi tiết thanh toán'},
                {'name': 'fin_payment_schedule', 'desc': 'Lịch thanh toán'},
                {'name': 'fin_financial_account', 'desc': 'Tài khoản tài chính'},
            ]
        }
    }
    return jsonify({'success': True, 'related_tables': related})


# ==================== PAYMENT API ENDPOINTS ====================

@app.route('/api/financial-accounts')
def get_financial_accounts():
    """Lấy danh sách tài khoản tài chính (Bank/Cash accounts)"""
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT 
                fa.fin_financial_account_id,
                fa.name,
                fa.description,
                fa.currentbalance,
                fa.initialbalance,
                c.iso_code as currency,
                CASE 
                    WHEN fa.type = 'B' THEN 'Bank'
                    WHEN fa.type = 'C' THEN 'Cash'
                    ELSE 'Other'
                END as account_type,
                fa.isactive,
                org.name as organization
            FROM fin_financial_account fa
            LEFT JOIN c_currency c ON fa.c_currency_id = c.c_currency_id
            LEFT JOIN ad_org org ON fa.ad_org_id = org.ad_org_id
            WHERE fa.isactive = 'Y'
            ORDER BY fa.name
        """)
        accounts = cur.fetchall()
        return jsonify({'success': True, 'accounts': [dict(a) for a in accounts], 'count': len(accounts)})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/financial-account/<account_id>')
def get_financial_account_detail(account_id):
    """Lấy chi tiết tài khoản tài chính"""
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    try:
        cur = conn.cursor()
        # Account info
        cur.execute("""
            SELECT 
                fa.fin_financial_account_id,
                fa.name,
                fa.description,
                fa.currentbalance,
                fa.initialbalance,
                fa.creditlimit,
                c.iso_code as currency,
                c.c_currency_id,
                CASE 
                    WHEN fa.type = 'B' THEN 'Bank'
                    WHEN fa.type = 'C' THEN 'Cash'
                    ELSE 'Other'
                END as account_type,
                fa.type as type_code,
                fa.bankcode,
                fa.swiftcode,
                fa.iban,
                fa.isactive,
                org.name as organization,
                fa.ad_org_id,
                fa.ad_client_id
            FROM fin_financial_account fa
            LEFT JOIN c_currency c ON fa.c_currency_id = c.c_currency_id
            LEFT JOIN ad_org org ON fa.ad_org_id = org.ad_org_id
            WHERE fa.fin_financial_account_id = %s
        """, (account_id,))
        account = cur.fetchone()
        
        if not account:
            return jsonify({'error': 'Financial account not found'}), 404
        
        # Recent transactions
        cur.execute("""
            SELECT 
                t.fin_finacc_transaction_id,
                t.trxtype,
                t.paymentdate,
                t.depositamt,
                t.paymentamt,
                t.description,
                p.documentno as payment_documentno
            FROM fin_finacc_transaction t
            LEFT JOIN fin_payment p ON t.fin_payment_id = p.fin_payment_id
            WHERE t.fin_financial_account_id = %s
            ORDER BY t.paymentdate DESC
            LIMIT 20
        """, (account_id,))
        transactions = cur.fetchall()
        
        return jsonify({
            'success': True,
            'account': dict(account),
            'transactions': [dict(t) for t in transactions]
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/payments')
def get_payments():
    """Lấy danh sách thanh toán"""
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    try:
        cur = conn.cursor()
        payment_type = request.args.get('type', '')  # 'in' hoặc 'out'
        status = request.args.get('status', '')  # 'DR', 'CO', etc.
        limit = request.args.get('limit', 100, type=int)
        
        query = """
            SELECT 
                p.fin_payment_id,
                p.documentno,
                p.paymentdate,
                p.amount,
                p.status,
                p.description,
                CASE WHEN p.isreceipt = 'Y' THEN 'Payment In' ELSE 'Payment Out' END as payment_type,
                p.isreceipt,
                bp.name as bpartner_name,
                fa.name as account_name,
                c.iso_code as currency,
                pm.name as payment_method
            FROM fin_payment p
            LEFT JOIN c_bpartner bp ON p.c_bpartner_id = bp.c_bpartner_id
            LEFT JOIN fin_financial_account fa ON p.fin_financial_account_id = fa.fin_financial_account_id
            LEFT JOIN c_currency c ON p.c_currency_id = c.c_currency_id
            LEFT JOIN fin_paymentmethod pm ON p.fin_paymentmethod_id = pm.fin_paymentmethod_id
            WHERE p.isactive = 'Y'
        """
        params = []
        
        if payment_type == 'in':
            query += " AND p.isreceipt = 'Y'"
        elif payment_type == 'out':
            query += " AND p.isreceipt = 'N'"
        
        if status:
            query += " AND p.status = %s"
            params.append(status)
        
        query += " ORDER BY p.paymentdate DESC LIMIT %s"
        params.append(limit)
        
        cur.execute(query, params)
        payments = cur.fetchall()
        return jsonify({'success': True, 'payments': [dict(p) for p in payments], 'count': len(payments)})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/payment/<payment_id>')
def get_payment_detail(payment_id):
    """Lấy chi tiết thanh toán"""
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    try:
        cur = conn.cursor()
        
        # Payment header
        cur.execute("""
            SELECT 
                p.fin_payment_id,
                p.documentno,
                p.paymentdate,
                p.amount,
                p.usedcredit,
                p.generatedcredit,
                p.status,
                p.description,
                CASE WHEN p.isreceipt = 'Y' THEN 'Payment In' ELSE 'Payment Out' END as payment_type,
                p.isreceipt,
                bp.name as bpartner_name,
                bp.c_bpartner_id,
                fa.name as account_name,
                fa.fin_financial_account_id,
                c.iso_code as currency,
                c.c_currency_id,
                pm.name as payment_method,
                p.fin_paymentmethod_id,
                org.name as organization,
                p.ad_org_id,
                p.ad_client_id,
                p.referenceno
            FROM fin_payment p
            LEFT JOIN c_bpartner bp ON p.c_bpartner_id = bp.c_bpartner_id
            LEFT JOIN fin_financial_account fa ON p.fin_financial_account_id = fa.fin_financial_account_id
            LEFT JOIN c_currency c ON p.c_currency_id = c.c_currency_id
            LEFT JOIN fin_paymentmethod pm ON p.fin_paymentmethod_id = pm.fin_paymentmethod_id
            LEFT JOIN ad_org org ON p.ad_org_id = org.ad_org_id
            WHERE p.fin_payment_id = %s
        """, (payment_id,))
        payment = cur.fetchone()
        
        if not payment:
            return jsonify({'error': 'Payment not found'}), 404
        
        # Payment details (links to invoices/orders)
        cur.execute("""
            SELECT 
                pd.fin_payment_detail_id,
                pd.amount,
                pd.writeoffamt,
                pd.isrefund,
                ps.fin_payment_schedule_id,
                i.documentno as invoice_no,
                i.c_invoice_id,
                o.documentno as order_no,
                o.c_order_id,
                ps.expecteddate,
                ps.invoicedamt,
                ps.outstandingamt,
                ps.paidamt
            FROM fin_payment_detail pd
            LEFT JOIN fin_payment_schedule ps ON pd.fin_payment_schedule_order = ps.fin_payment_schedule_id
                                               OR pd.fin_payment_schedule_invoice = ps.fin_payment_schedule_id
            LEFT JOIN c_invoice i ON ps.c_invoice_id = i.c_invoice_id
            LEFT JOIN c_order o ON ps.c_order_id = o.c_order_id
            WHERE pd.fin_payment_id = %s
            ORDER BY pd.created
        """, (payment_id,))
        details = cur.fetchall()
        
        return jsonify({
            'success': True,
            'payment': dict(payment),
            'details': [dict(d) for d in details]
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/payment-schedules')
def get_payment_schedules():
    """Lấy danh sách lịch thanh toán (các khoản nợ/phải thu)"""
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    try:
        cur = conn.cursor()
        pending_only = request.args.get('pending', 'true').lower() == 'true'
        bpartner_id = request.args.get('bpartner_id', '')
        schedule_type = request.args.get('type', '')  # 'receivable' hoặc 'payable'
        
        query = """
            SELECT 
                ps.fin_payment_schedule_id,
                ps.expecteddate,
                ps.duedate,
                ps.invoicedamt,
                ps.outstandingamt,
                ps.paidamt,
                CASE WHEN i.issotrx = 'Y' THEN 'Receivable' ELSE 'Payable' END as schedule_type,
                i.documentno as invoice_no,
                i.c_invoice_id,
                i.dateinvoiced,
                o.documentno as order_no,
                o.c_order_id,
                bp.name as bpartner_name,
                bp.c_bpartner_id,
                c.iso_code as currency
            FROM fin_payment_schedule ps
            LEFT JOIN c_invoice i ON ps.c_invoice_id = i.c_invoice_id
            LEFT JOIN c_order o ON ps.c_order_id = o.c_order_id
            LEFT JOIN c_bpartner bp ON COALESCE(i.c_bpartner_id, o.c_bpartner_id) = bp.c_bpartner_id
            LEFT JOIN c_currency c ON COALESCE(i.c_currency_id, o.c_currency_id) = c.c_currency_id
            WHERE ps.isactive = 'Y'
        """
        params = []
        
        if pending_only:
            query += " AND ps.outstandingamt > 0"
        
        if bpartner_id:
            query += " AND bp.c_bpartner_id = %s"
            params.append(bpartner_id)
        
        if schedule_type == 'receivable':
            query += " AND i.issotrx = 'Y'"
        elif schedule_type == 'payable':
            query += " AND i.issotrx = 'N'"
        
        query += " ORDER BY ps.duedate ASC LIMIT 100"
        
        cur.execute(query, params)
        schedules = cur.fetchall()
        return jsonify({'success': True, 'schedules': [dict(s) for s in schedules], 'count': len(schedules)})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/payment-schedule/<schedule_id>')
def get_payment_schedule_detail(schedule_id):
    """Lấy chi tiết lịch thanh toán"""
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT 
                ps.fin_payment_schedule_id,
                ps.expecteddate,
                ps.duedate,
                ps.invoicedamt,
                ps.outstandingamt,
                ps.paidamt,
                CASE WHEN i.issotrx = 'Y' THEN 'Receivable' ELSE 'Payable' END as schedule_type,
                i.documentno as invoice_no,
                i.c_invoice_id,
                i.dateinvoiced,
                i.grandtotal as invoice_total,
                o.documentno as order_no,
                o.c_order_id,
                bp.name as bpartner_name,
                bp.c_bpartner_id,
                c.iso_code as currency,
                c.c_currency_id
            FROM fin_payment_schedule ps
            LEFT JOIN c_invoice i ON ps.c_invoice_id = i.c_invoice_id
            LEFT JOIN c_order o ON ps.c_order_id = o.c_order_id
            LEFT JOIN c_bpartner bp ON COALESCE(i.c_bpartner_id, o.c_bpartner_id) = bp.c_bpartner_id
            LEFT JOIN c_currency c ON COALESCE(i.c_currency_id, o.c_currency_id) = c.c_currency_id
            WHERE ps.fin_payment_schedule_id = %s
        """, (schedule_id,))
        schedule = cur.fetchone()
        
        if not schedule:
            return jsonify({'error': 'Payment schedule not found'}), 404
        
        # Lấy các payment đã thanh toán cho schedule này
        cur.execute("""
            SELECT 
                p.fin_payment_id,
                p.documentno,
                p.paymentdate,
                pd.amount,
                p.status,
                pm.name as payment_method
            FROM fin_payment_detail pd
            JOIN fin_payment p ON pd.fin_payment_id = p.fin_payment_id
            LEFT JOIN fin_paymentmethod pm ON p.fin_paymentmethod_id = pm.fin_paymentmethod_id
            WHERE pd.fin_payment_schedule_invoice = %s
               OR pd.fin_payment_schedule_order = %s
            ORDER BY p.paymentdate DESC
        """, (schedule_id, schedule_id))
        payments = cur.fetchall()
        
        return jsonify({
            'success': True,
            'schedule': dict(schedule),
            'payments': [dict(p) for p in payments]
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/invoices')
def get_invoices():
    """Lấy danh sách hóa đơn"""
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    try:
        cur = conn.cursor()
        invoice_type = request.args.get('type', '')  # 'sales', 'purchase'
        status = request.args.get('status', '')
        pending_payment = request.args.get('pending_payment', 'false').lower() == 'true'
        limit = request.args.get('limit', 100, type=int)
        
        query = """
            SELECT 
                i.c_invoice_id,
                i.documentno,
                i.dateinvoiced,
                i.grandtotal,
                i.docstatus,
                i.ispaid,
                CASE WHEN i.issotrx = 'Y' THEN 'Sales' ELSE 'Purchase' END as invoice_type,
                i.issotrx,
                bp.name as bpartner_name,
                c.iso_code as currency,
                COALESCE(
                    (SELECT SUM(ps.outstandingamt) FROM fin_payment_schedule ps WHERE ps.c_invoice_id = i.c_invoice_id),
                    0
                ) as outstanding_amount
            FROM c_invoice i
            LEFT JOIN c_bpartner bp ON i.c_bpartner_id = bp.c_bpartner_id
            LEFT JOIN c_currency c ON i.c_currency_id = c.c_currency_id
            WHERE i.isactive = 'Y'
        """
        params = []
        
        if invoice_type == 'sales':
            query += " AND i.issotrx = 'Y'"
        elif invoice_type == 'purchase':
            query += " AND i.issotrx = 'N'"
        
        if status:
            query += " AND i.docstatus = %s"
            params.append(status)
        
        if pending_payment:
            query += " AND i.ispaid = 'N' AND i.docstatus = 'CO'"
        
        query += " ORDER BY i.dateinvoiced DESC LIMIT %s"
        params.append(limit)
        
        cur.execute(query, params)
        invoices = cur.fetchall()
        return jsonify({'success': True, 'invoices': [dict(i) for i in invoices], 'count': len(invoices)})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/invoice/<invoice_id>')
def get_invoice_detail(invoice_id):
    """Lấy chi tiết hóa đơn"""
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    try:
        cur = conn.cursor()
        
        # Invoice header
        cur.execute("""
            SELECT 
                i.c_invoice_id,
                i.documentno,
                i.dateinvoiced,
                i.dateacct,
                i.grandtotal,
                i.totallines,
                i.docstatus,
                i.ispaid,
                i.description,
                CASE WHEN i.issotrx = 'Y' THEN 'Sales' ELSE 'Purchase' END as invoice_type,
                i.issotrx,
                bp.name as bpartner_name,
                bp.c_bpartner_id,
                c.iso_code as currency,
                c.c_currency_id,
                org.name as organization,
                i.ad_org_id,
                i.ad_client_id,
                pt.name as payment_term,
                o.documentno as order_no
            FROM c_invoice i
            LEFT JOIN c_bpartner bp ON i.c_bpartner_id = bp.c_bpartner_id
            LEFT JOIN c_currency c ON i.c_currency_id = c.c_currency_id
            LEFT JOIN ad_org org ON i.ad_org_id = org.ad_org_id
            LEFT JOIN c_paymentterm pt ON i.c_paymentterm_id = pt.c_paymentterm_id
            LEFT JOIN c_order o ON i.c_order_id = o.c_order_id
            WHERE i.c_invoice_id = %s
        """, (invoice_id,))
        invoice = cur.fetchone()
        
        if not invoice:
            return jsonify({'error': 'Invoice not found'}), 404
        
        # Invoice lines
        cur.execute("""
            SELECT 
                il.c_invoiceline_id,
                il.line,
                il.qtyinvoiced,
                il.pricelist,
                il.priceactual,
                il.linenetamt,
                p.value as product_code,
                p.name as product_name,
                uom.name as uom_name
            FROM c_invoiceline il
            LEFT JOIN m_product p ON il.m_product_id = p.m_product_id
            LEFT JOIN c_uom uom ON il.c_uom_id = uom.c_uom_id
            WHERE il.c_invoice_id = %s
            ORDER BY il.line
        """, (invoice_id,))
        lines = cur.fetchall()
        
        # Payment schedules for this invoice
        cur.execute("""
            SELECT 
                ps.fin_payment_schedule_id,
                ps.expecteddate,
                ps.duedate,
                ps.invoicedamt,
                ps.outstandingamt,
                ps.paidamt
            FROM fin_payment_schedule ps
            WHERE ps.c_invoice_id = %s
            ORDER BY ps.duedate
        """, (invoice_id,))
        schedules = cur.fetchall()
        
        return jsonify({
            'success': True,
            'invoice': dict(invoice),
            'lines': [dict(l) for l in lines],
            'payment_schedules': [dict(s) for s in schedules]
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/payment', methods=['POST'])
def create_payment():
    """
    Tạo thanh toán mới
    Body: {
        fin_financial_account_id: string,
        c_bpartner_id: string,
        fin_paymentmethod_id: string,
        amount: number,
        paymentdate: string (YYYY-MM-DD),
        isreceipt: boolean (true = payment in, false = payment out),
        description: string (optional),
        referenceno: string (optional),
        schedules: [{ fin_payment_schedule_id: string, amount: number }] (optional)
    }
    """
    data = request.get_json()
    
    required_fields = ['fin_financial_account_id', 'c_bpartner_id', 'fin_paymentmethod_id', 'amount', 'isreceipt']
    for field in required_fields:
        if field not in data:
            return jsonify({'error': f'{field} is required'}), 400
    
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    try:
        cur = conn.cursor()
        now = datetime.now()
        
        # Lấy thông tin financial account
        cur.execute("""
            SELECT fa.fin_financial_account_id, fa.ad_client_id, fa.ad_org_id, 
                   fa.c_currency_id, c.iso_code as currency
            FROM fin_financial_account fa
            LEFT JOIN c_currency c ON fa.c_currency_id = c.c_currency_id
            WHERE fa.fin_financial_account_id = %s
        """, (data['fin_financial_account_id'],))
        account = cur.fetchone()
        
        if not account:
            return jsonify({'error': 'Financial account not found'}), 404
        
        # Generate IDs
        fin_payment_id = generate_uuid()
        payment_date = data.get('paymentdate', now.strftime('%Y-%m-%d'))
        isreceipt = 'Y' if data['isreceipt'] else 'N'
        
        # Get document sequence
        cur.execute("""
            SELECT currentnext FROM ad_sequence
            WHERE name = 'DocumentNo_FIN_Payment'
            AND ad_client_id = %s
            LIMIT 1
        """, (account['ad_client_id'],))
        seq = cur.fetchone()
        prefix = 'RCPT' if isreceipt == 'Y' else 'PAY'
        doc_no = f"{prefix}-{now.strftime('%Y%m%d')}-{seq['currentnext'] if seq else '001'}"
        
        # Create payment header
        cur.execute("""
            INSERT INTO fin_payment (
                fin_payment_id, ad_client_id, ad_org_id, isactive, created, createdby,
                updated, updatedby, documentno, paymentdate, isreceipt, status,
                fin_financial_account_id, c_bpartner_id, fin_paymentmethod_id,
                c_currency_id, amount, usedcredit, generatedcredit,
                description, referenceno, posted, processed
            ) VALUES (
                %s, %s, %s, 'Y', %s, '0',
                %s, '0', %s, %s, %s, 'RPAP',
                %s, %s, %s,
                %s, %s, 0, 0,
                %s, %s, 'N', 'N'
            )
        """, (
            fin_payment_id, account['ad_client_id'], account['ad_org_id'], now,
            now, doc_no, payment_date, isreceipt,
            data['fin_financial_account_id'], data['c_bpartner_id'], data['fin_paymentmethod_id'],
            account['c_currency_id'], data['amount'],
            data.get('description', ''), data.get('referenceno', '')
        ))
        
        # Create payment details if schedules provided
        created_details = []
        schedules = data.get('schedules', [])
        
        for schedule_data in schedules:
            schedule_id = schedule_data.get('fin_payment_schedule_id')
            schedule_amount = schedule_data.get('amount', 0)
            
            if not schedule_id or schedule_amount <= 0:
                continue
            
            detail_id = generate_uuid()
            
            # Determine if it's invoice or order schedule
            cur.execute("""
                SELECT c_invoice_id, c_order_id FROM fin_payment_schedule
                WHERE fin_payment_schedule_id = %s
            """, (schedule_id,))
            sched = cur.fetchone()
            
            if sched:
                invoice_schedule = schedule_id if sched.get('c_invoice_id') else None
                order_schedule = schedule_id if sched.get('c_order_id') else None
                
                cur.execute("""
                    INSERT INTO fin_payment_detail (
                        fin_payment_detail_id, ad_client_id, ad_org_id, isactive, created, createdby,
                        updated, updatedby, fin_payment_id, amount, writeoffamt, isrefund,
                        fin_payment_schedule_invoice, fin_payment_schedule_order, isprepayment
                    ) VALUES (
                        %s, %s, %s, 'Y', %s, '0',
                        %s, '0', %s, %s, 0, 'N',
                        %s, %s, 'N'
                    )
                """, (
                    detail_id, account['ad_client_id'], account['ad_org_id'], now,
                    now, fin_payment_id, schedule_amount,
                    invoice_schedule, order_schedule
                ))
                
                created_details.append({
                    'detail_id': detail_id,
                    'schedule_id': schedule_id,
                    'amount': schedule_amount
                })
        
        conn.commit()
        
        return jsonify({
            'success': True,
            'message': 'Payment created successfully',
            'payment': {
                'fin_payment_id': fin_payment_id,
                'documentno': doc_no,
                'amount': data['amount'],
                'currency': account['currency'],
                'status': 'RPAP',
                'details': created_details
            }
        })
        
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/payment/<payment_id>/process', methods=['POST'])
def process_payment(payment_id):
    """
    Xử lý thanh toán (chuyển sang trạng thái hoàn thành)
    Cập nhật outstanding amounts trong payment schedules
    """
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    try:
        cur = conn.cursor()
        now = datetime.now()
        
        # Get payment info
        cur.execute("""
            SELECT fin_payment_id, status, amount, isreceipt,
                   fin_financial_account_id, c_bpartner_id
            FROM fin_payment WHERE fin_payment_id = %s
        """, (payment_id,))
        payment = cur.fetchone()
        
        if not payment:
            return jsonify({'error': 'Payment not found'}), 404
        
        if payment['status'] in ['PWNC', 'RPPC']:
            return jsonify({'error': 'Payment already processed'}), 400
        
        # Update payment status
        new_status = 'PWNC' if payment['isreceipt'] == 'N' else 'RPPC'
        cur.execute("""
            UPDATE fin_payment
            SET status = %s, processed = 'Y', updated = %s
            WHERE fin_payment_id = %s
        """, (new_status, now, payment_id))
        
        # Update payment schedule outstanding amounts
        cur.execute("""
            UPDATE fin_payment_schedule ps
            SET outstandingamt = ps.outstandingamt - pd.amount,
                paidamt = ps.paidamt + pd.amount,
                updated = %s
            FROM fin_payment_detail pd
            WHERE (pd.fin_payment_schedule_invoice = ps.fin_payment_schedule_id
                   OR pd.fin_payment_schedule_order = ps.fin_payment_schedule_id)
            AND pd.fin_payment_id = %s
        """, (now, payment_id))
        
        # Update financial account balance
        if payment['isreceipt'] == 'Y':
            # Payment in - increase balance
            cur.execute("""
                UPDATE fin_financial_account
                SET currentbalance = currentbalance + %s, updated = %s
                WHERE fin_financial_account_id = %s
            """, (payment['amount'], now, payment['fin_financial_account_id']))
        else:
            # Payment out - decrease balance
            cur.execute("""
                UPDATE fin_financial_account
                SET currentbalance = currentbalance - %s, updated = %s
                WHERE fin_financial_account_id = %s
            """, (payment['amount'], now, payment['fin_financial_account_id']))
        
        # Create transaction record
        trans_id = generate_uuid()
        trx_type = 'BPD' if payment['isreceipt'] == 'Y' else 'BPW'
        deposit_amt = payment['amount'] if payment['isreceipt'] == 'Y' else 0
        payment_amt = payment['amount'] if payment['isreceipt'] == 'N' else 0
        
        cur.execute("""
            INSERT INTO fin_finacc_transaction (
                fin_finacc_transaction_id, ad_client_id, ad_org_id, isactive,
                created, createdby, updated, updatedby,
                fin_financial_account_id, fin_payment_id, trxtype,
                paymentdate, depositamt, paymentamt, c_bpartner_id,
                status, processed, posted
            )
            SELECT %s, p.ad_client_id, p.ad_org_id, 'Y',
                   %s, '0', %s, '0',
                   p.fin_financial_account_id, p.fin_payment_id, %s,
                   p.paymentdate, %s, %s, p.c_bpartner_id,
                   'RDNC', 'Y', 'N'
            FROM fin_payment p
            WHERE p.fin_payment_id = %s
        """, (trans_id, now, now, trx_type, deposit_amt, payment_amt, payment_id))
        
        conn.commit()
        
        return jsonify({
            'success': True,
            'message': 'Payment processed successfully',
            'new_status': new_status,
            'transaction_id': trans_id
        })
        
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/payment/<payment_id>/void', methods=['POST'])
def void_payment(payment_id):
    """Hủy thanh toán"""
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    try:
        cur = conn.cursor()
        now = datetime.now()
        
        # Get payment info
        cur.execute("""
            SELECT fin_payment_id, status, amount, isreceipt, fin_financial_account_id
            FROM fin_payment WHERE fin_payment_id = %s
        """, (payment_id,))
        payment = cur.fetchone()
        
        if not payment:
            return jsonify({'error': 'Payment not found'}), 404
        
        # Reverse payment schedule updates if processed
        if payment['status'] in ['PWNC', 'RPPC']:
            cur.execute("""
                UPDATE fin_payment_schedule ps
                SET outstandingamt = ps.outstandingamt + pd.amount,
                    paidamt = ps.paidamt - pd.amount,
                    updated = %s
                FROM fin_payment_detail pd
                WHERE (pd.fin_payment_schedule_invoice = ps.fin_payment_schedule_id
                       OR pd.fin_payment_schedule_order = ps.fin_payment_schedule_id)
                AND pd.fin_payment_id = %s
            """, (now, payment_id))
            
            # Reverse financial account balance
            if payment['isreceipt'] == 'Y':
                cur.execute("""
                    UPDATE fin_financial_account
                    SET currentbalance = currentbalance - %s, updated = %s
                    WHERE fin_financial_account_id = %s
                """, (payment['amount'], now, payment['fin_financial_account_id']))
            else:
                cur.execute("""
                    UPDATE fin_financial_account
                    SET currentbalance = currentbalance + %s, updated = %s
                    WHERE fin_financial_account_id = %s
                """, (payment['amount'], now, payment['fin_financial_account_id']))
        
        # Update payment status to void
        cur.execute("""
            UPDATE fin_payment
            SET status = 'RPVOID', processed = 'N', updated = %s
            WHERE fin_payment_id = %s
        """, (now, payment_id))
        
        conn.commit()
        
        return jsonify({
            'success': True,
            'message': 'Payment voided successfully'
        })
        
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/bpartner/<bpartner_id>/credit')
def get_bpartner_credit(bpartner_id):
    """Lấy thông tin công nợ của đối tác"""
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    try:
        cur = conn.cursor()
        
        # BPartner info
        cur.execute("""
            SELECT bp.c_bpartner_id, bp.name, bp.value,
                   bp.so_creditlimit, bp.so_creditused, bp.totalopenbalance,
                   bp.iscustomer, bp.isvendor
            FROM c_bpartner bp
            WHERE bp.c_bpartner_id = %s
        """, (bpartner_id,))
        bpartner = cur.fetchone()
        
        if not bpartner:
            return jsonify({'error': 'Business Partner not found'}), 404
        
        # Receivables (customer owes us)
        cur.execute("""
            SELECT COALESCE(SUM(ps.outstandingamt), 0) as total_receivable
            FROM fin_payment_schedule ps
            JOIN c_invoice i ON ps.c_invoice_id = i.c_invoice_id
            WHERE i.c_bpartner_id = %s AND i.issotrx = 'Y' AND ps.outstandingamt > 0
        """, (bpartner_id,))
        receivable = cur.fetchone()
        
        # Payables (we owe them)
        cur.execute("""
            SELECT COALESCE(SUM(ps.outstandingamt), 0) as total_payable
            FROM fin_payment_schedule ps
            JOIN c_invoice i ON ps.c_invoice_id = i.c_invoice_id
            WHERE i.c_bpartner_id = %s AND i.issotrx = 'N' AND ps.outstandingamt > 0
        """, (bpartner_id,))
        payable = cur.fetchone()
        
        # Pending invoices
        cur.execute("""
            SELECT i.c_invoice_id, i.documentno, i.dateinvoiced, i.grandtotal,
                   CASE WHEN i.issotrx = 'Y' THEN 'Sales' ELSE 'Purchase' END as invoice_type,
                   COALESCE(ps.outstandingamt, i.grandtotal) as outstanding
            FROM c_invoice i
            LEFT JOIN fin_payment_schedule ps ON i.c_invoice_id = ps.c_invoice_id
            WHERE i.c_bpartner_id = %s AND i.ispaid = 'N' AND i.docstatus = 'CO'
            ORDER BY i.dateinvoiced DESC
            LIMIT 20
        """, (bpartner_id,))
        pending_invoices = cur.fetchall()
        
        return jsonify({
            'success': True,
            'bpartner': dict(bpartner),
            'total_receivable': float(receivable['total_receivable']) if receivable else 0,
            'total_payable': float(payable['total_payable']) if payable else 0,
            'net_balance': float(receivable['total_receivable'] or 0) - float(payable['total_payable'] or 0),
            'pending_invoices': [dict(i) for i in pending_invoices]
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/currencies')
def get_currencies():
    """Lấy danh sách tiền tệ"""
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT c_currency_id, iso_code, description, cursymbol, stdprecision
            FROM c_currency
            WHERE isactive = 'Y'
            ORDER BY iso_code
        """)
        currencies = cur.fetchall()
        return jsonify({'success': True, 'currencies': [dict(c) for c in currencies]})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/dashboard/financial')
def get_financial_dashboard():
    """Lấy thống kê tài chính cho dashboard"""
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    try:
        cur = conn.cursor()
        stats = {}
        
        # Total cash/bank balance
        cur.execute("""
            SELECT COALESCE(SUM(currentbalance), 0) as total_balance
            FROM fin_financial_account WHERE isactive = 'Y'
        """)
        stats['total_balance'] = float(cur.fetchone()['total_balance'])
        
        # Total receivables
        cur.execute("""
            SELECT COALESCE(SUM(ps.outstandingamt), 0) as total
            FROM fin_payment_schedule ps
            JOIN c_invoice i ON ps.c_invoice_id = i.c_invoice_id
            WHERE i.issotrx = 'Y' AND ps.outstandingamt > 0
        """)
        stats['total_receivables'] = float(cur.fetchone()['total'])
        
        # Total payables
        cur.execute("""
            SELECT COALESCE(SUM(ps.outstandingamt), 0) as total
            FROM fin_payment_schedule ps
            JOIN c_invoice i ON ps.c_invoice_id = i.c_invoice_id
            WHERE i.issotrx = 'N' AND ps.outstandingamt > 0
        """)
        stats['total_payables'] = float(cur.fetchone()['total'])
        
        # Overdue receivables
        cur.execute("""
            SELECT COALESCE(SUM(ps.outstandingamt), 0) as total
            FROM fin_payment_schedule ps
            JOIN c_invoice i ON ps.c_invoice_id = i.c_invoice_id
            WHERE i.issotrx = 'Y' AND ps.outstandingamt > 0 AND ps.duedate < CURRENT_DATE
        """)
        stats['overdue_receivables'] = float(cur.fetchone()['total'])
        
        # Overdue payables
        cur.execute("""
            SELECT COALESCE(SUM(ps.outstandingamt), 0) as total
            FROM fin_payment_schedule ps
            JOIN c_invoice i ON ps.c_invoice_id = i.c_invoice_id
            WHERE i.issotrx = 'N' AND ps.outstandingamt > 0 AND ps.duedate < CURRENT_DATE
        """)
        stats['overdue_payables'] = float(cur.fetchone()['total'])
        
        # Recent payments
        cur.execute("""
            SELECT p.fin_payment_id, p.documentno, p.paymentdate, p.amount, p.status,
                   CASE WHEN p.isreceipt = 'Y' THEN 'In' ELSE 'Out' END as type,
                   bp.name as bpartner_name
            FROM fin_payment p
            LEFT JOIN c_bpartner bp ON p.c_bpartner_id = bp.c_bpartner_id
            WHERE p.isactive = 'Y'
            ORDER BY p.created DESC
            LIMIT 10
        """)
        stats['recent_payments'] = [dict(p) for p in cur.fetchall()]
        
        # Payments by status
        cur.execute("""
            SELECT status, COUNT(*) as count, COALESCE(SUM(amount), 0) as total
            FROM fin_payment
            WHERE isactive = 'Y'
            GROUP BY status
        """)
        stats['payments_by_status'] = [dict(p) for p in cur.fetchall()]
        
        return jsonify({'success': True, 'stats': stats})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/search', methods=['POST'])
def universal_search():
    """
    Tìm kiếm đa năng - tự động xác định loại barcode:
    - Document Number (PO, GR)
    - Product barcode (UPC)
    - Product code (Value)
    """
    data = request.get_json()
    barcode = data.get('barcode', '').strip()
    
    if not barcode:
        return jsonify({'error': 'Barcode is required'}), 400
    
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    results = {
        'barcode': barcode,
        'found_type': None,
        'purchase_orders': [],
        'goods_receipts': [],
        'products': [],
        'order_lines': []
    }
    
    try:
        cur = conn.cursor()
        
        # 1. Tìm Purchase Order theo Document Number
        cur.execute("""
            SELECT o.c_order_id, o.documentno, o.dateordered, o.docstatus,
                   bp.name as bpartner_name, o.grandtotal
            FROM c_order o
            JOIN c_bpartner bp ON o.c_bpartner_id = bp.c_bpartner_id
            WHERE o.issotrx = 'N'
            AND (UPPER(o.documentno) LIKE UPPER(%s) OR o.documentno = %s)
            AND o.isactive = 'Y'
            ORDER BY o.dateordered DESC
        """, (f'%{barcode}%', barcode))
        pos = cur.fetchall()
        if pos:
            results['purchase_orders'] = [dict(p) for p in pos]
            results['found_type'] = 'purchase_order'
        
        # 2. Tìm Goods Receipt theo Document Number
        cur.execute("""
            SELECT io.m_inout_id, io.documentno, io.movementdate, io.docstatus,
                   bp.name as bpartner_name, o.documentno as po_documentno
            FROM m_inout io
            JOIN c_bpartner bp ON io.c_bpartner_id = bp.c_bpartner_id
            LEFT JOIN c_order o ON io.c_order_id = o.c_order_id
            WHERE io.issotrx = 'N'
            AND (UPPER(io.documentno) LIKE UPPER(%s) OR io.documentno = %s)
            AND io.isactive = 'Y'
            ORDER BY io.movementdate DESC
        """, (f'%{barcode}%', barcode))
        grs = cur.fetchall()
        if grs:
            results['goods_receipts'] = [dict(g) for g in grs]
            if not results['found_type']:
                results['found_type'] = 'goods_receipt'
        
        # 3. Tìm Product theo UPC hoặc Value
        cur.execute("""
            SELECT m_product_id, value, name, upc, description
            FROM m_product
            WHERE (upc = %s OR UPPER(value) = UPPER(%s) OR UPPER(value) LIKE UPPER(%s))
            AND isactive = 'Y'
        """, (barcode, barcode, f'%{barcode}%'))
        products = cur.fetchall()
        if products:
            results['products'] = [dict(p) for p in products]
            if not results['found_type']:
                results['found_type'] = 'product'
            
            # 4. Tìm PO lines chứa product này (đang chờ nhận)
            for prod in products:
                cur.execute("""
                    SELECT o.c_order_id, o.documentno, o.dateordered,
                           bp.name as bpartner_name,
                           ol.c_orderline_id, ol.qtyordered, ol.qtydelivered,
                           (ol.qtyordered - ol.qtydelivered) as qty_pending
                    FROM c_order o
                    JOIN c_orderline ol ON o.c_order_id = ol.c_order_id
                    JOIN c_bpartner bp ON o.c_bpartner_id = bp.c_bpartner_id
                    WHERE ol.m_product_id = %s
                    AND o.issotrx = 'N'
                    AND o.docstatus = 'CO'
                    AND (ol.qtyordered - ol.qtydelivered) > 0
                    ORDER BY o.dateordered DESC
                """, (prod['m_product_id'],))
                lines = cur.fetchall()
                results['order_lines'].extend([dict(l) for l in lines])
        
        return jsonify({'success': True, **results})
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


# ==================== PURCHASE ORDER PDF PRINT API ====================

# FPT Brand Colors
FPT_ORANGE = '#F37021'
FPT_ORANGE_DARK = '#D65A0A'
FPT_BLUE = '#003399'
FPT_GRAY = '#666666'
FPT_LIGHT_GRAY = '#F5F5F5'


def generate_purchase_order_pdf(order_data, lines_data, qr_data=None):
    """
    Tạo PDF cho Purchase Order theo chuẩn FPT Warehouse
    """
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm, cm
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image, HRFlowable
    from reportlab.lib.enums import TA_CENTER, TA_RIGHT, TA_LEFT
    from reportlab.graphics.shapes import Drawing, Rect, String
    from reportlab.graphics import renderPDF
    
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, 
                           rightMargin=15*mm, leftMargin=15*mm,
                           topMargin=15*mm, bottomMargin=15*mm)
    
    elements = []
    styles = getSampleStyleSheet()
    
    # FPT Custom styles
    fpt_title_style = ParagraphStyle(
        'FPTTitle',
        parent=styles['Heading1'],
        fontSize=20,
        alignment=TA_CENTER,
        spaceAfter=3*mm,
        textColor=colors.HexColor(FPT_ORANGE),
        fontName='Helvetica-Bold'
    )
    
    fpt_subtitle_style = ParagraphStyle(
        'FPTSubtitle',
        parent=styles['Normal'],
        fontSize=10,
        alignment=TA_CENTER,
        textColor=colors.HexColor(FPT_GRAY)
    )
    
    fpt_header_style = ParagraphStyle(
        'FPTHeader',
        parent=styles['Normal'],
        fontSize=11,
        textColor=colors.HexColor(FPT_ORANGE_DARK),
        fontName='Helvetica-Bold',
        spaceAfter=2*mm
    )
    
    fpt_normal_style = ParagraphStyle(
        'FPTNormal',
        parent=styles['Normal'],
        fontSize=9,
        textColor=colors.HexColor('#333333')
    )
    
    # Tạo QR Code từ document ID
    qr_image = None
    if qr_data:
        try:
            import qrcode
            qr = qrcode.QRCode(
                version=1,
                error_correction=qrcode.constants.ERROR_CORRECT_M,
                box_size=5,
                border=1,
            )
            qr.add_data(qr_data)
            qr.make(fit=True)
            qr_img = qr.make_image(fill_color=FPT_ORANGE_DARK, back_color="white")
            
            qr_buffer = io.BytesIO()
            qr_img.save(qr_buffer, format='PNG')
            qr_buffer.seek(0)
            qr_image = Image(qr_buffer, width=32*mm, height=32*mm)
        except Exception as e:
            print(f"QR Code generation error: {e}")
    
    # ==================== HEADER SECTION ====================
    # FPT Logo/Brand header
    brand_text = """
    <font size="22" color="#F37021"><b>FPT</b></font>
    <font size="14" color="#003399"><b> WAREHOUSE</b></font>
    """
    brand_para = Paragraph(brand_text, ParagraphStyle('Brand', alignment=TA_LEFT))
    
    doc_title = Paragraph(
        '<font size="16" color="#F37021"><b>PURCHASE ORDER</b></font>',
        ParagraphStyle('DocTitle', alignment=TA_CENTER, leading=16)
    )
    
    # Header table with brand, title, QR
    if qr_image:
        header_table = Table(
            [[brand_para, doc_title, qr_image]], 
            colWidths=[55*mm, 70*mm, 40*mm]
        )
    else:
        header_table = Table(
            [[brand_para, doc_title, '']], 
            colWidths=[55*mm, 90*mm, 20*mm]
        )
    
    header_table.setStyle(TableStyle([
        ('ALIGN', (0, 0), (0, 0), 'LEFT'),
        ('ALIGN', (1, 0), (1, 0), 'CENTER'),
        ('ALIGN', (2, 0), (2, 0), 'RIGHT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    elements.append(header_table)
    
    # Orange line separator
    elements.append(Spacer(1, 3*mm))
    elements.append(HRFlowable(width="100%", thickness=2, color=colors.HexColor(FPT_ORANGE), spaceAfter=5*mm))
    
    # ==================== DOCUMENT INFO SECTION ====================
    # Two columns: left for doc info, right for supplier info
    left_info = [
        ['<b>Document No:</b>', order_data.get('documentno', 'N/A')],
        ['<b>Order Date:</b>', str(order_data.get('dateordered', 'N/A'))[:10]],
        ['<b>Warehouse:</b>', order_data.get('warehouse_name', 'N/A')],
        ['<b>Status:</b>', '<font color="#27ae60">Completed</font>' if order_data.get('docstatus') == 'CO' else '<font color="#e74c3c">Draft</font>'],
    ]
    
    right_info = [
        ['<b>Supplier:</b>', order_data.get('bpartner_name', 'N/A')],
        ['<b>Address:</b>', order_data.get('bpartner_address', '-')],
        ['<b>Phone:</b>', order_data.get('bpartner_phone', '-')],
        ['<b>Supplier Code:</b>', order_data.get('bpartner_id', '-')[:8] if order_data.get('bpartner_id') else '-'],
    ]
    
    # Convert to Paragraphs
    left_data = [[Paragraph(row[0], fpt_normal_style), Paragraph(str(row[1]), fpt_normal_style)] for row in left_info]
    right_data = [[Paragraph(row[0], fpt_normal_style), Paragraph(str(row[1]), fpt_normal_style)] for row in right_info]
    
    left_table = Table(left_data, colWidths=[35*mm, 50*mm])
    left_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('TOPPADDING', (0, 0), (-1, -1), 1*mm),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 1*mm),
    ]))
    
    right_table = Table(right_data, colWidths=[35*mm, 50*mm])
    right_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('TOPPADDING', (0, 0), (-1, -1), 1*mm),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 1*mm),
    ]))
    
    info_wrapper = Table([[left_table, right_table]], colWidths=[90*mm, 90*mm])
    info_wrapper.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#FFF8F5')),
        ('BOX', (0, 0), (-1, -1), 1, colors.HexColor(FPT_ORANGE)),
        ('TOPPADDING', (0, 0), (-1, -1), 3*mm),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3*mm),
        ('LEFTPADDING', (0, 0), (-1, -1), 3*mm),
        ('RIGHTPADDING', (0, 0), (-1, -1), 3*mm),
    ]))
    elements.append(info_wrapper)
    
    elements.append(Spacer(1, 6*mm))
    
    # ==================== PRODUCT TABLE ====================
    elements.append(Paragraph('<b>ORDER DETAILS</b>', fpt_header_style))
    
    # Table header
    table_header = ['No.', 'Code', 'Product Name', 'UOM', 'Ordered', 'Delivered', 'Pending', 'Unit Price', 'Amount']
    table_data = [table_header]
    
    total_amount = 0
    total_qty = 0
    total_pending = 0
    
    for idx, line in enumerate(lines_data, 1):
        qty_ordered = float(line.get('qtyordered', 0))
        qty_delivered = float(line.get('qtydelivered', 0))
        qty_pending = qty_ordered - qty_delivered
        price = float(line.get('priceactual', 0))
        amount = qty_ordered * price
        total_amount += amount
        total_qty += qty_ordered
        total_pending += qty_pending
        
        table_data.append([
            str(idx),
            str(line.get('product_code', ''))[:12],
            str(line.get('product_name', ''))[:28],
            str(line.get('uom_name', ''))[:6],
            f"{qty_ordered:,.0f}",
            f"{qty_delivered:,.0f}",
            f"{qty_pending:,.0f}",
            f"{price:,.0f}",
            f"{amount:,.0f}"
        ])
    
    # Summary rows
    table_data.append(['', '', '', '', '', '', '', '', ''])
    table_data.append(['', '', Paragraph('<b>TOTAL QUANTITY:</b>', fpt_normal_style), '', f"{total_qty:,.0f}", '', f"{total_pending:,.0f}", '', ''])
    table_data.append(['', '', Paragraph('<b>TOTAL AMOUNT:</b>', fpt_normal_style), '', '', '', '', '', f"{total_amount:,.0f}"])
    
    product_table = Table(table_data, colWidths=[8*mm, 18*mm, 42*mm, 12*mm, 16*mm, 16*mm, 16*mm, 20*mm, 25*mm])
    product_table.setStyle(TableStyle([
        # Header style - FPT Orange
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor(FPT_ORANGE)),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 8),
        ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
        
        # Data style
        ('FONTNAME', (0, 1), (-1, -4), 'Helvetica'),
        ('FONTSIZE', (0, 1), (-1, -1), 8),
        ('ALIGN', (0, 1), (0, -1), 'CENTER'),  # STT
        ('ALIGN', (4, 1), (-1, -1), 'RIGHT'),  # Numbers right aligned
        
        # Alternating row colors
        ('ROWBACKGROUNDS', (0, 1), (-1, -4), [colors.white, colors.HexColor('#FFF8F5')]),
        
        # Summary rows
        ('BACKGROUND', (0, -2), (-1, -1), colors.HexColor('#FFF0E6')),
        ('FONTNAME', (0, -2), (-1, -1), 'Helvetica-Bold'),
        ('TEXTCOLOR', (0, -2), (-1, -1), colors.HexColor(FPT_ORANGE_DARK)),
        
        # Grid
        ('GRID', (0, 0), (-1, -4), 0.5, colors.HexColor('#E0E0E0')),
        ('BOX', (0, 0), (-1, -1), 1.5, colors.HexColor(FPT_ORANGE)),
        ('LINEABOVE', (0, -2), (-1, -2), 1, colors.HexColor(FPT_ORANGE)),
        
        # Padding
        ('TOPPADDING', (0, 0), (-1, -1), 2*mm),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2*mm),
        ('LEFTPADDING', (0, 0), (-1, -1), 1.5*mm),
        ('RIGHTPADDING', (0, 0), (-1, -1), 1.5*mm),
    ]))
    elements.append(product_table)
    
    # Description if any
    if order_data.get('description'):
        elements.append(Spacer(1, 4*mm))
        elements.append(Paragraph(f'<b>Notes:</b> {order_data.get("description", "")}', fpt_normal_style))
    
    elements.append(Spacer(1, 10*mm))
    
    # ==================== SIGNATURE SECTION ====================
    sig_header = [
        Paragraph('<b>Created By</b>', ParagraphStyle('SigHead', alignment=TA_CENTER, fontSize=9)),
        Paragraph('<b>Warehouse</b>', ParagraphStyle('SigHead', alignment=TA_CENTER, fontSize=9)),
        Paragraph('<b>Accountant</b>', ParagraphStyle('SigHead', alignment=TA_CENTER, fontSize=9)),
        Paragraph('<b>Approved By</b>', ParagraphStyle('SigHead', alignment=TA_CENTER, fontSize=9)),
    ]
    
    sig_lines = ['', '', '', '']
    sig_space = ['_____________', '_____________', '_____________', '_____________']
    
    sig_table = Table([sig_header, sig_lines, sig_lines, sig_space], colWidths=[43*mm, 43*mm, 43*mm, 43*mm])
    sig_table.setStyle(TableStyle([
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('TOPPADDING', (0, 1), (-1, 1), 18*mm),
        ('FONTSIZE', (0, -1), (-1, -1), 9),
    ]))
    elements.append(sig_table)
    
    # ==================== FOOTER ====================
    elements.append(Spacer(1, 8*mm))
    elements.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor('#E0E0E0'), spaceAfter=2*mm))
    
    footer_left = f'<font size="7" color="#888888">Printed: {datetime.now().strftime("%Y-%m-%d %H:%M")}</font>'
    footer_right = f'<font size="7" color="#888888">FPT Warehouse System | Document ID: {qr_data[:8] if qr_data else "N/A"}...</font>'
    
    footer_table = Table([
        [Paragraph(footer_left, fpt_normal_style), Paragraph(footer_right, ParagraphStyle('FR', alignment=TA_RIGHT, fontSize=7))]
    ], colWidths=[90*mm, 90*mm])
    footer_table.setStyle(TableStyle([
        ('ALIGN', (0, 0), (0, 0), 'LEFT'),
        ('ALIGN', (1, 0), (1, 0), 'RIGHT'),
    ]))
    elements.append(footer_table)
    
    # Build PDF
    doc.build(elements)
    buffer.seek(0)
    return buffer


@app.route('/api/purchase-order/<order_id>/print')
def print_purchase_order_pdf(order_id):
    """
    Tạo và trả về file PDF của Purchase Order
    Query params:
    - download: nếu = 1 thì download file, không thì hiển thị trong browser
    """
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    try:
        cur = conn.cursor()
        
        # Lấy thông tin header PO
        cur.execute("""
            SELECT 
                o.c_order_id,
                o.documentno,
                o.dateordered,
                o.description,
                o.docstatus,
                o.grandtotal,
                bp.name as bpartner_name,
                bp.c_bpartner_id,
                o.m_warehouse_id,
                w.name as warehouse_name,
                o.ad_org_id,
                org.name as org_name,
                o.ad_client_id
            FROM c_order o
            JOIN c_bpartner bp ON o.c_bpartner_id = bp.c_bpartner_id
            LEFT JOIN m_warehouse w ON o.m_warehouse_id = w.m_warehouse_id
            LEFT JOIN ad_org org ON o.ad_org_id = org.ad_org_id
            WHERE o.c_order_id = %s
        """, (order_id,))
        order = cur.fetchone()
        
        if not order:
            return jsonify({'error': 'Purchase Order not found'}), 404
        
        # Lấy các dòng sản phẩm
        cur.execute("""
            SELECT 
                ol.c_orderline_id,
                ol.line,
                p.m_product_id,
                p.value as product_code,
                p.name as product_name,
                p.upc as barcode,
                ol.qtyordered,
                ol.qtydelivered,
                (ol.qtyordered - ol.qtydelivered) as qty_pending,
                ol.priceactual,
                ol.linenetamt,
                ol.c_uom_id,
                uom.name as uom_name
            FROM c_orderline ol
            LEFT JOIN m_product p ON ol.m_product_id = p.m_product_id
            LEFT JOIN c_uom uom ON ol.c_uom_id = uom.c_uom_id
            WHERE ol.c_order_id = %s
            AND ol.isactive = 'Y'
            ORDER BY ol.line
        """, (order_id,))
        lines = cur.fetchall()
        
        # Tạo QR code data từ document number (số giao dịch hiển thị cho người dùng)
        qr_data = order['documentno']
        
        # Generate PDF
        pdf_buffer = generate_purchase_order_pdf(
            dict(order),
            [dict(l) for l in lines],
            qr_data
        )
        
        # Filename
        filename = f"PO_{order['documentno']}_{datetime.now().strftime('%Y%m%d')}.pdf"
        
        # Check if download or display
        download = request.args.get('download', '0') == '1'
        
        if download:
            return send_file(
                pdf_buffer,
                mimetype='application/pdf',
                as_attachment=True,
                download_name=filename
            )
        else:
            return send_file(
                pdf_buffer,
                mimetype='application/pdf',
                as_attachment=False,
                download_name=filename
            )
    
    except ImportError as e:
        return jsonify({
            'error': f'PDF library not installed. Please run: pip install reportlab qrcode pillow',
            'details': str(e)
        }), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/purchase-order/<order_id>/qrcode')
def get_purchase_order_qrcode(order_id):
    """
    Tạo QR Code image từ Purchase Order - luôn hiển thị documentno
    Query params:
    - size: kích thước QR (default 200)
    - data_type: 'id'/'documentno' (cả 2 đều dùng documentno), 'url' (link đến chi tiết PO)
    """
    try:
        import qrcode
        from PIL import Image as PILImage
        
        size = int(request.args.get('size', 200))
        data_type = request.args.get('data_type', 'documentno')
        
        # Luôn lấy documentno từ database để hiển thị số giao dịch dễ đọc
        qr_content = order_id  # fallback nếu không query được
        
        conn = get_db_connection()
        if conn:
            try:
                cur = conn.cursor()
                cur.execute("SELECT documentno FROM c_order WHERE c_order_id = %s", (order_id,))
                result = cur.fetchone()
                if result:
                    if data_type == 'url':
                        host = request.host
                        qr_content = f"https://{host}/purchase-order/{order_id}"
                    else:
                        # Mặc định dùng documentno cho cả 'id' và 'documentno'
                        qr_content = result['documentno']
            finally:
                conn.close()
        
        # Tạo QR code
        qr = qrcode.QRCode(
            version=None,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=max(2, size // 40),
            border=2,
        )
        qr.add_data(qr_content)
        qr.make(fit=True)
        
        img = qr.make_image(fill_color="black", back_color="white")
        
        # Resize to exact size
        img = img.resize((size, size), PILImage.Resampling.LANCZOS)
        
        buffer = io.BytesIO()
        img.save(buffer, format='PNG')
        buffer.seek(0)
        
        return send_file(buffer, mimetype='image/png')
    
    except ImportError:
        return jsonify({'error': 'qrcode library not installed. Run: pip install qrcode pillow'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/goods-receipt/<inout_id>/qrcode')
def goods_receipt_qrcode(inout_id):
    """
    Generate QR Code for Goods Receipt - sử dụng documentno
    """
    try:
        import qrcode
        from io import BytesIO
        
        size = int(request.args.get('size', 150))
        
        # Lấy documentno từ database
        qr_content = inout_id  # fallback
        conn = get_db_connection()
        if conn:
            try:
                cur = conn.cursor()
                cur.execute("SELECT documentno FROM m_inout WHERE m_inout_id = %s", (inout_id,))
                result = cur.fetchone()
                if result:
                    qr_content = result['documentno']
            finally:
                conn.close()
        
        # Generate QR Code with documentno
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=10,
            border=2,
        )
        qr.add_data(qr_content)
        qr.make(fit=True)
        
        # Create image with FPT green color
        img = qr.make_image(fill_color='#27ae60', back_color='white')
        
        # Resize to requested size
        img = img.resize((size, size))
        
        # Save to buffer
        buffer = BytesIO()
        img.save(buffer, format='PNG')
        buffer.seek(0)
        
        return send_file(buffer, mimetype='image/png')
    
    except ImportError:
        return jsonify({'error': 'qrcode library not installed. Run: pip install qrcode pillow'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/goods-receipt/<inout_id>/print')
def print_goods_receipt_pdf(inout_id):
    """
    Generate PDF for Goods Receipt - FPT Warehouse standard
    """
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import mm, cm
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image, HRFlowable
        from reportlab.lib.enums import TA_CENTER, TA_RIGHT, TA_LEFT
        
        cur = conn.cursor()
        
        # Lấy thông tin header GR
        cur.execute("""
            SELECT 
                io.m_inout_id,
                io.documentno,
                io.movementdate,
                io.description,
                io.docstatus,
                bp.name as bpartner_name,
                o.documentno as po_documentno,
                o.c_order_id,
                w.name as warehouse_name,
                org.name as org_name
            FROM m_inout io
            JOIN c_bpartner bp ON io.c_bpartner_id = bp.c_bpartner_id
            LEFT JOIN c_order o ON io.c_order_id = o.c_order_id
            LEFT JOIN m_warehouse w ON io.m_warehouse_id = w.m_warehouse_id
            LEFT JOIN ad_org org ON io.ad_org_id = org.ad_org_id
            WHERE io.m_inout_id = %s
        """, (inout_id,))
        gr = cur.fetchone()
        
        if not gr:
            return jsonify({'error': 'Goods Receipt not found'}), 404
        
        # Lấy các dòng
        cur.execute("""
            SELECT 
                iol.m_inoutline_id,
                iol.line,
                iol.movementqty,
                p.value as product_code,
                p.name as product_name,
                p.upc as barcode,
                uom.name as uom_name,
                COALESCE(ol.priceactual, 0) as priceactual
            FROM m_inoutline iol
            JOIN m_product p ON iol.m_product_id = p.m_product_id
            LEFT JOIN c_orderline ol ON iol.c_orderline_id = ol.c_orderline_id
            LEFT JOIN c_uom uom ON iol.c_uom_id = uom.c_uom_id
            WHERE iol.m_inout_id = %s
            AND iol.isactive = 'Y'
            ORDER BY iol.line
        """, (inout_id,))
        lines = cur.fetchall()
        
        gr_dict = dict(gr)
        
        # Create PDF with FPT branding
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4,
                               rightMargin=15*mm, leftMargin=15*mm,
                               topMargin=15*mm, bottomMargin=15*mm)
        
        elements = []
        styles = getSampleStyleSheet()
        
        # FPT Styles
        fpt_normal_style = ParagraphStyle(
            'FPTNormal',
            parent=styles['Normal'],
            fontSize=9,
            textColor=colors.HexColor('#333333')
        )
        
        fpt_header_style = ParagraphStyle(
            'FPTHeader',
            parent=styles['Normal'],
            fontSize=11,
            textColor=colors.HexColor('#27ae60'),
            fontName='Helvetica-Bold',
            spaceAfter=2*mm
        )
        
        # QR Code - sử dụng documentno thay vì UUID để người dùng dễ nhận biết
        qr_image = None
        try:
            import qrcode
            qr = qrcode.QRCode(version=1, error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=5, border=1)
            qr.add_data(gr_dict.get('documentno', inout_id))
            qr.make(fit=True)
            qr_img = qr.make_image(fill_color="#27ae60", back_color="white")
            qr_buffer = io.BytesIO()
            qr_img.save(qr_buffer, format='PNG')
            qr_buffer.seek(0)
            qr_image = Image(qr_buffer, width=32*mm, height=32*mm)
        except:
            pass
        
        # ==================== HEADER ====================
        brand_text = """
        <font size="22" color="#F37021"><b>FPT</b></font>
        <font size="14" color="#003399"><b> WAREHOUSE</b></font>
        """
        brand_para = Paragraph(brand_text, ParagraphStyle('Brand', alignment=TA_LEFT))
        
        doc_title = Paragraph(
            '<font size="16" color="#27ae60"><b>GOODS RECEIPT</b></font>',
            ParagraphStyle('DocTitle', alignment=TA_CENTER, leading=16)
        )
        
        if qr_image:
            header_table = Table([[brand_para, doc_title, qr_image]], colWidths=[55*mm, 70*mm, 40*mm])
        else:
            header_table = Table([[brand_para, doc_title, '']], colWidths=[55*mm, 90*mm, 20*mm])
        
        header_table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (0, 0), 'LEFT'),
            ('ALIGN', (1, 0), (1, 0), 'CENTER'),
            ('ALIGN', (2, 0), (2, 0), 'RIGHT'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ]))
        elements.append(header_table)
        
        elements.append(Spacer(1, 3*mm))
        elements.append(HRFlowable(width="100%", thickness=2, color=colors.HexColor('#27ae60'), spaceAfter=5*mm))
        
        # ==================== INFO SECTION ====================
        left_info = [
            ['<b>Receipt No:</b>', gr_dict.get('documentno', 'N/A')],
            ['<b>Receipt Date:</b>', str(gr_dict.get('movementdate', 'N/A'))[:10]],
            ['<b>From PO:</b>', gr_dict.get('po_documentno', '-')],
            ['<b>Status:</b>', '<font color="#27ae60">Completed</font>' if gr_dict.get('docstatus') == 'CO' else '<font color="#e74c3c">Draft</font>'],
        ]
        
        right_info = [
            ['<b>Supplier:</b>', gr_dict.get('bpartner_name', 'N/A')],
            ['<b>Warehouse:</b>', gr_dict.get('warehouse_name', '-')],
            ['<b>Organization:</b>', gr_dict.get('org_name', '-')],
            ['<b>Notes:</b>', gr_dict.get('description', '-') or '-'],
        ]
        
        left_data = [[Paragraph(row[0], fpt_normal_style), Paragraph(str(row[1]), fpt_normal_style)] for row in left_info]
        right_data = [[Paragraph(row[0], fpt_normal_style), Paragraph(str(row[1]), fpt_normal_style)] for row in right_info]
        
        left_table = Table(left_data, colWidths=[35*mm, 50*mm])
        left_table.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP'), ('TOPPADDING', (0, 0), (-1, -1), 1*mm), ('BOTTOMPADDING', (0, 0), (-1, -1), 1*mm)]))
        
        right_table = Table(right_data, colWidths=[35*mm, 50*mm])
        right_table.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP'), ('TOPPADDING', (0, 0), (-1, -1), 1*mm), ('BOTTOMPADDING', (0, 0), (-1, -1), 1*mm)]))
        
        info_wrapper = Table([[left_table, right_table]], colWidths=[90*mm, 90*mm])
        info_wrapper.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#F0FFF0')),
            ('BOX', (0, 0), (-1, -1), 1, colors.HexColor('#27ae60')),
            ('TOPPADDING', (0, 0), (-1, -1), 3*mm),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3*mm),
            ('LEFTPADDING', (0, 0), (-1, -1), 3*mm),
            ('RIGHTPADDING', (0, 0), (-1, -1), 3*mm),
        ]))
        elements.append(info_wrapper)
        
        elements.append(Spacer(1, 6*mm))
        
        # ==================== PRODUCT TABLE ====================
        elements.append(Paragraph('<b>RECEIPT DETAILS</b>', fpt_header_style))
        
        table_header = ['No.', 'Code', 'Product Name', 'Barcode', 'UOM', 'Qty', 'Unit Price', 'Amount']
        table_data = [table_header]
        
        total_amount = 0
        total_qty = 0
        for idx, line in enumerate([dict(l) for l in lines], 1):
            qty = float(line.get('movementqty', 0))
            price = float(line.get('priceactual', 0))
            amount = qty * price
            total_amount += amount
            total_qty += qty
            
            table_data.append([
                str(idx),
                str(line.get('product_code', ''))[:12],
                str(line.get('product_name', ''))[:28],
                str(line.get('barcode', ''))[:12] or '-',
                str(line.get('uom_name', ''))[:6],
                f"{qty:,.0f}",
                f"{price:,.0f}",
                f"{amount:,.0f}"
            ])
        
        table_data.append(['', '', '', '', '', '', '', ''])
        table_data.append(['', '', Paragraph('<b>TOTAL QUANTITY:</b>', fpt_normal_style), '', '', f"{total_qty:,.0f}", '', ''])
        table_data.append(['', '', Paragraph('<b>TOTAL AMOUNT:</b>', fpt_normal_style), '', '', '', '', f"{total_amount:,.0f}"])
        
        product_table = Table(table_data, colWidths=[8*mm, 18*mm, 42*mm, 22*mm, 12*mm, 18*mm, 20*mm, 25*mm])
        product_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#27ae60')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 8),
            ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
            ('FONTNAME', (0, 1), (-1, -4), 'Helvetica'),
            ('FONTSIZE', (0, 1), (-1, -1), 8),
            ('ALIGN', (0, 1), (0, -1), 'CENTER'),
            ('ALIGN', (5, 1), (-1, -1), 'RIGHT'),
            ('ROWBACKGROUNDS', (0, 1), (-1, -4), [colors.white, colors.HexColor('#F0FFF0')]),
            ('BACKGROUND', (0, -2), (-1, -1), colors.HexColor('#E8F5E9')),
            ('FONTNAME', (0, -2), (-1, -1), 'Helvetica-Bold'),
            ('TEXTCOLOR', (0, -2), (-1, -1), colors.HexColor('#2E7D32')),
            ('GRID', (0, 0), (-1, -4), 0.5, colors.HexColor('#C8E6C9')),
            ('BOX', (0, 0), (-1, -1), 1.5, colors.HexColor('#27ae60')),
            ('LINEABOVE', (0, -2), (-1, -2), 1, colors.HexColor('#27ae60')),
            ('TOPPADDING', (0, 0), (-1, -1), 2*mm),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 2*mm),
        ]))
        elements.append(product_table)
        
        elements.append(Spacer(1, 10*mm))
        
        # ==================== SIGNATURES ====================
        sig_header = [
            Paragraph('<b>Delivery</b>', ParagraphStyle('SigHead', alignment=TA_CENTER, fontSize=9)),
            Paragraph('<b>Warehouse</b>', ParagraphStyle('SigHead', alignment=TA_CENTER, fontSize=9)),
            Paragraph('<b>Accountant</b>', ParagraphStyle('SigHead', alignment=TA_CENTER, fontSize=9)),
            Paragraph('<b>Approved By</b>', ParagraphStyle('SigHead', alignment=TA_CENTER, fontSize=9)),
        ]
        
        sig_table = Table([sig_header, ['', '', '', ''], ['', '', '', ''], ['_____________', '_____________', '_____________', '_____________']], colWidths=[43*mm, 43*mm, 43*mm, 43*mm])
        sig_table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('TOPPADDING', (0, 1), (-1, 1), 18*mm),
        ]))
        elements.append(sig_table)
        
        # ==================== FOOTER ====================
        elements.append(Spacer(1, 8*mm))
        elements.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor('#E0E0E0'), spaceAfter=2*mm))
        
        footer_left = f'<font size="7" color="#888888">Printed: {datetime.now().strftime("%Y-%m-%d %H:%M")}</font>'
        footer_right = f'<font size="7" color="#888888">FPT Warehouse System | Document ID: {inout_id[:8]}...</font>'
        
        footer_table = Table([[Paragraph(footer_left, fpt_normal_style), Paragraph(footer_right, ParagraphStyle('FR', alignment=TA_RIGHT, fontSize=7))]], colWidths=[90*mm, 90*mm])
        elements.append(footer_table)
        
        doc.build(elements)
        buffer.seek(0)
        
        filename = f"GR_{gr_dict['documentno']}_{datetime.now().strftime('%Y%m%d')}.pdf"
        download = request.args.get('download', '0') == '1'
        
        return send_file(buffer, mimetype='application/pdf', as_attachment=download, download_name=filename)
    
    except ImportError as e:
        return jsonify({'error': f'PDF library not installed. Run: pip install reportlab qrcode pillow', 'details': str(e)}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/movement/<movement_id>/qrcode')
def movement_qrcode(movement_id):
    """Generate QR Code for Goods Movement - sử dụng documentno"""
    try:
        import qrcode
        from io import BytesIO
        
        size = int(request.args.get('size', 150))
        
        # Lấy documentno từ database
        qr_content = movement_id  # fallback
        conn = get_db_connection()
        if conn:
            try:
                cur = conn.cursor()
                cur.execute("SELECT documentno FROM m_movement WHERE m_movement_id = %s", (movement_id,))
                result = cur.fetchone()
                if result:
                    qr_content = result['documentno']
            finally:
                conn.close()
        
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=10,
            border=2,
        )
        qr.add_data(qr_content)
        qr.make(fit=True)
        
        # Purple color for movements
        img = qr.make_image(fill_color='#9b59b6', back_color='white')
        img = img.resize((size, size))
        
        buffer = BytesIO()
        img.save(buffer, format='PNG')
        buffer.seek(0)
        
        return send_file(buffer, mimetype='image/png')
    
    except ImportError:
        return jsonify({'error': 'qrcode library not installed'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/movement/<movement_id>/print')
def print_movement_pdf(movement_id):
    """Generate PDF for Goods Movement - FPT Warehouse standard"""
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer, Image
        from reportlab.lib.units import mm
        from io import BytesIO
        import qrcode
        
        cur = conn.cursor()
        
        # Get movement header
        cur.execute("""
            SELECT 
                m.m_movement_id, m.documentno, m.movementdate, m.docstatus, m.description,
                org.name as org_name
            FROM m_movement m
            LEFT JOIN ad_org org ON m.ad_org_id = org.ad_org_id
            WHERE m.m_movement_id = %s
        """, (movement_id,))
        movement = cur.fetchone()
        
        if not movement:
            return jsonify({'error': 'Movement not found'}), 404
        
        mv_dict = dict(movement)
        
        # Get movement lines
        cur.execute("""
            SELECT 
                ml.line,
                ml.movementqty,
                p.value as product_code,
                p.name as product_name,
                COALESCE(NULLIF(p.upc, ''), p.value) as barcode,
                u.name as uom_name,
                lf.value as from_locator,
                wf.name as from_warehouse,
                lt.value as to_locator,
                wt.name as to_warehouse
            FROM m_movementline ml
            JOIN m_product p ON ml.m_product_id = p.m_product_id
            LEFT JOIN c_uom u ON p.c_uom_id = u.c_uom_id
            LEFT JOIN m_locator lf ON ml.m_locator_id = lf.m_locator_id
            LEFT JOIN m_warehouse wf ON lf.m_warehouse_id = wf.m_warehouse_id
            LEFT JOIN m_locator lt ON ml.m_locatorto_id = lt.m_locator_id
            LEFT JOIN m_warehouse wt ON lt.m_warehouse_id = wt.m_warehouse_id
            WHERE ml.m_movement_id = %s
            AND ml.isactive = 'Y'
            ORDER BY ml.line
        """, (movement_id,))
        lines = cur.fetchall()
        lines_list = [dict(l) for l in lines]
        
        # Get warehouse names from first line
        from_warehouse = lines_list[0]['from_warehouse'] if lines_list else 'N/A'
        to_warehouse = lines_list[0]['to_warehouse'] if lines_list else 'N/A'
        
        # Create PDF
        buffer = BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4, 
                               leftMargin=15*mm, rightMargin=15*mm,
                               topMargin=15*mm, bottomMargin=15*mm)
        elements = []
        
        # Define FPT styles - Purple theme for movements
        fpt_purple = colors.HexColor('#9b59b6')
        fpt_orange = colors.HexColor('#F37021')
        fpt_blue = colors.HexColor('#003399')
        
        fpt_header_style = ParagraphStyle('FPTHeader', fontSize=11, textColor=fpt_purple, 
                                          spaceAfter=8, spaceBefore=12, fontName='Helvetica-Bold')
        fpt_normal_style = ParagraphStyle('FPTNormal', fontSize=9, leading=12, fontName='Helvetica')
        
        # Generate QR Code - sử dụng documentno thay vì UUID để người dùng dễ nhận biết
        qr = qrcode.QRCode(version=1, box_size=3, border=1)
        qr.add_data(mv_dict.get('documentno', movement_id))
        qr.make(fit=True)
        qr_img = qr.make_image(fill_color='#9b59b6', back_color='white')
        
        qr_buffer = BytesIO()
        qr_img.save(qr_buffer, format='PNG')
        qr_buffer.seek(0)
        qr_image = Image(qr_buffer, width=22*mm, height=22*mm)
        
        # ==================== HEADER ====================
        header_left = Paragraph(
            '<font size="14" color="#F37021"><b>FPT WAREHOUSE</b></font><br/>'
            '<font size="8" color="#666666">Inventory Management System</font>',
            ParagraphStyle('HeaderLeft', leading=14)
        )
        
        doc_title = Paragraph(
            '<font size="16" color="#9b59b6"><b>GOODS MOVEMENT</b></font>',
            ParagraphStyle('DocTitle', alignment=TA_CENTER, leading=16)
        )
        
        header_table = Table([[header_left, doc_title, qr_image]], 
                            colWidths=[55*mm, 85*mm, 30*mm])
        header_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('ALIGN', (0, 0), (0, 0), 'LEFT'),
            ('ALIGN', (1, 0), (1, 0), 'CENTER'),
            ('ALIGN', (2, 0), (2, 0), 'RIGHT'),
        ]))
        elements.append(header_table)
        elements.append(Spacer(1, 8*mm))
        
        # ==================== INFO SECTION ====================
        left_info = [
            ['<b>Document No:</b>', mv_dict.get('documentno', 'N/A')],
            ['<b>Movement Date:</b>', str(mv_dict.get('movementdate', 'N/A'))[:10]],
            ['<b>Status:</b>', '<font color="#9b59b6">Completed</font>' if mv_dict.get('docstatus') == 'CO' else '<font color="#e74c3c">Draft</font>'],
        ]
        
        right_info = [
            ['<b>From Warehouse:</b>', from_warehouse],
            ['<b>To Warehouse:</b>', to_warehouse],
            ['<b>Organization:</b>', mv_dict.get('org_name', '-')],
        ]
        
        left_table_data = [[Paragraph(row[0], fpt_normal_style), 
                           Paragraph(str(row[1]) if row[1] else '-', fpt_normal_style)] for row in left_info]
        right_table_data = [[Paragraph(row[0], fpt_normal_style), 
                            Paragraph(str(row[1]) if row[1] else '-', fpt_normal_style)] for row in right_info]
        
        left_table = Table(left_table_data, colWidths=[35*mm, 45*mm])
        right_table = Table(right_table_data, colWidths=[35*mm, 45*mm])
        
        for t in [left_table, right_table]:
            t.setStyle(TableStyle([
                ('FONTSIZE', (0, 0), (-1, -1), 9),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
                ('TOPPADDING', (0, 0), (-1, -1), 4),
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ]))
        
        info_table = Table([[left_table, right_table]], colWidths=[85*mm, 85*mm])
        elements.append(info_table)
        elements.append(Spacer(1, 6*mm))
        
        # ==================== PRODUCT TABLE ====================
        elements.append(Paragraph('<b>TRANSFER DETAILS</b>', fpt_header_style))
        
        table_header = ['No.', 'Code', 'Product Name', 'Barcode', 'UOM', 'Qty', 'From', 'To']
        table_data = [table_header]
        
        total_qty = 0
        for idx, line in enumerate(lines_list, 1):
            qty = float(line.get('movementqty', 0) or 0)
            total_qty += qty
            
            row = [
                str(idx),
                str(line.get('product_code', '-'))[:12],
                Paragraph(str(line.get('product_name', '-'))[:35], fpt_normal_style),
                str(line.get('barcode', '-'))[:15],
                str(line.get('uom_name', '-'))[:8],
                f"{qty:,.0f}",
                str(line.get('from_locator', '-'))[:10],
                str(line.get('to_locator', '-'))[:10],
            ]
            table_data.append(row)
        
        # Add totals
        table_data.append(['', '', '', '', '', '', '', ''])
        table_data.append(['', '', Paragraph('<b>TOTAL QUANTITY:</b>', fpt_normal_style), '', '', f"{total_qty:,.0f}", '', ''])
        
        product_table = Table(table_data, colWidths=[12*mm, 22*mm, 50*mm, 25*mm, 15*mm, 18*mm, 20*mm, 20*mm])
        product_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), fpt_purple),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 8),
            ('FONTSIZE', (0, 1), (-1, -1), 8),
            ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
            ('ALIGN', (0, 1), (0, -1), 'CENTER'),
            ('ALIGN', (5, 1), (5, -1), 'RIGHT'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('GRID', (0, 0), (-1, -3), 0.5, colors.grey),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ('ROWBACKGROUNDS', (0, 1), (-1, -3), [colors.white, colors.HexColor('#f8f9fa')]),
            ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
            ('LINEABOVE', (0, -1), (-1, -1), 1, fpt_purple),
        ]))
        elements.append(product_table)
        elements.append(Spacer(1, 10*mm))
        
        # Description if any
        if mv_dict.get('description'):
            elements.append(Paragraph(f'<b>Notes:</b> {mv_dict["description"]}', fpt_normal_style))
            elements.append(Spacer(1, 6*mm))
        
        # ==================== SIGNATURES ====================
        sig_header = [
            Paragraph('<b>Prepared By</b>', ParagraphStyle('SigHead', alignment=TA_CENTER, fontSize=9)),
            Paragraph('<b>From Warehouse</b>', ParagraphStyle('SigHead', alignment=TA_CENTER, fontSize=9)),
            Paragraph('<b>To Warehouse</b>', ParagraphStyle('SigHead', alignment=TA_CENTER, fontSize=9)),
            Paragraph('<b>Approved By</b>', ParagraphStyle('SigHead', alignment=TA_CENTER, fontSize=9)),
        ]
        sig_space = [Paragraph('<br/><br/><br/><br/>', fpt_normal_style)] * 4
        sig_line = [Paragraph('_' * 18, ParagraphStyle('SigLine', alignment=TA_CENTER, fontSize=8))] * 4
        
        sig_table = Table([sig_header, sig_space, sig_line], colWidths=[45*mm, 45*mm, 45*mm, 45*mm])
        sig_table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ]))
        elements.append(sig_table)
        elements.append(Spacer(1, 8*mm))
        
        # ==================== FOOTER ====================
        footer_left = f'<font size="7" color="#888888">Printed: {datetime.now().strftime("%Y-%m-%d %H:%M")}</font>'
        footer_right = f'<font size="7" color="#888888">FPT Warehouse System | Document ID: {movement_id[:8]}...</font>'
        
        footer_table = Table([
            [Paragraph(footer_left, fpt_normal_style), Paragraph(footer_right, ParagraphStyle('FooterRight', alignment=TA_RIGHT, fontSize=7))]
        ], colWidths=[90*mm, 90*mm])
        footer_table.setStyle(TableStyle([
            ('LINEABOVE', (0, 0), (-1, 0), 0.5, colors.grey),
            ('TOPPADDING', (0, 0), (-1, 0), 5),
        ]))
        elements.append(footer_table)
        
        # Build PDF
        doc.build(elements)
        buffer.seek(0)
        
        filename = f"MV_{mv_dict['documentno']}_{datetime.now().strftime('%Y%m%d')}.pdf"
        download = request.args.get('download', '0') == '1'
        
        return send_file(buffer, mimetype='application/pdf', as_attachment=download, download_name=filename)
    
    except ImportError as e:
        return jsonify({'error': f'PDF library not installed. Run: pip install reportlab qrcode pillow', 'details': str(e)}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


# ==================== SALE ORDER ENDPOINTS ====================

@app.route('/api/sale-orders')
def get_sale_orders():
    """Lấy danh sách đơn hàng bán (Sale Orders)"""
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    try:
        cur = conn.cursor()
        status = request.args.get('status', '')  # CO, DR, etc
        limit = request.args.get('limit', 100, type=int)
        from_date = request.args.get('from_date', '')
        to_date = request.args.get('to_date', '')
        
        query = """
            SELECT 
                o.c_order_id,
                o.documentno,
                o.dateordered,
                o.docstatus,
                o.grandtotal,
                bp.name as bpartner_name,
                c.iso_code as currency,
                w.name as warehouse_name,
                org.name as organization
            FROM c_order o
            LEFT JOIN c_bpartner bp ON o.c_bpartner_id = bp.c_bpartner_id
            LEFT JOIN c_currency c ON o.c_currency_id = c.c_currency_id
            LEFT JOIN m_warehouse w ON o.m_warehouse_id = w.m_warehouse_id
            LEFT JOIN ad_org org ON o.ad_org_id = org.ad_org_id
            WHERE o.issotrx = 'Y' AND o.isactive = 'Y'
        """
        params = []
        
        if status:
            query += " AND o.docstatus = %s"
            params.append(status)
        
        if from_date:
            query += " AND o.dateordered >= %s"
            params.append(from_date)
        
        if to_date:
            query += " AND o.dateordered <= %s"
            params.append(to_date)
        
        query += " ORDER BY o.dateordered DESC LIMIT %s"
        params.append(limit)
        
        cur.execute(query, params)
        orders = cur.fetchall()
        return jsonify({'success': True, 'orders': [dict(o) for o in orders], 'count': len(orders)})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/sale-order/<order_id>')
def get_sale_order_detail(order_id):
    """Lấy chi tiết Sale Order"""
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    try:
        cur = conn.cursor()
        
        # Order header
        cur.execute("""
            SELECT 
                o.c_order_id,
                o.documentno,
                o.dateordered,
                o.grandtotal,
                o.docstatus,
                o.description,
                bp.name as bpartner_name,
                bp.c_bpartner_id,
                c.iso_code as currency,
                w.name as warehouse_name,
                w.m_warehouse_id,
                org.name as organization,
                o.ad_org_id,
                o.ad_client_id
            FROM c_order o
            LEFT JOIN c_bpartner bp ON o.c_bpartner_id = bp.c_bpartner_id
            LEFT JOIN c_currency c ON o.c_currency_id = c.c_currency_id
            LEFT JOIN m_warehouse w ON o.m_warehouse_id = w.m_warehouse_id
            LEFT JOIN ad_org org ON o.ad_org_id = org.ad_org_id
            WHERE o.c_order_id = %s AND o.issotrx = 'Y'
        """, (order_id,))
        order = cur.fetchone()
        
        if not order:
            return jsonify({'error': 'Sale Order not found'}), 404
        
        # Order lines
        cur.execute("""
            SELECT 
                ol.c_orderline_id,
                ol.line,
                ol.qtyordered,
                ol.qtydelivered,
                ol.pricelist,
                ol.priceactual,
                ol.linenetamt,
                p.value as product_code,
                p.name as product_name,
                p.upc as barcode,
                uom.name as uom_name,
                (ol.qtyordered - COALESCE(ol.qtydelivered, 0)) as qty_pending
            FROM c_orderline ol
            LEFT JOIN m_product p ON ol.m_product_id = p.m_product_id
            LEFT JOIN c_uom uom ON ol.c_uom_id = uom.c_uom_id
            WHERE ol.c_order_id = %s
            ORDER BY ol.line
        """, (order_id,))
        lines = cur.fetchall()
        
        return jsonify({
            'success': True,
            'order': dict(order),
            'lines': [dict(l) for l in lines]
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/sale-order', methods=['POST'])
def create_sale_order():
    """Tạo Sale Order mới"""
    data = request.get_json()
    
    try:
        required = ['ad_org_id', 'c_bpartner_id', 'm_warehouse_id', 'lines']
        for field in required:
            if field not in data:
                return jsonify({'error': f'{field} is required'}), 400
        
        if not data['lines']:
            return jsonify({'error': 'At least one line is required'}), 400
    except Exception as e:
        print(f"Error validating request data: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    try:
        cur = conn.cursor()
        now = datetime.now()
        
        # Use provided organization ID
        org_id = data['ad_org_id']
        
        # Lấy thông tin Business Partner
        cur.execute("""
            SELECT bp.c_bpartner_id, bp.ad_client_id,
                   bpl.c_bpartner_location_id
            FROM c_bpartner bp
            LEFT JOIN c_bpartner_location bpl ON bp.c_bpartner_id = bpl.c_bpartner_id 
                AND bpl.isactive = 'Y'
            WHERE bp.c_bpartner_id = %s
            LIMIT 1
        """, (data['c_bpartner_id'],))
        bpartner = cur.fetchone()
        
        if not bpartner:
            return jsonify({'error': 'Business Partner not found'}), 404
        
        # Lấy Document Type cho Sales Order - search in org hierarchy
        cur.execute("""
            SELECT c_doctype_id 
            FROM c_doctype 
            WHERE docbasetype = 'SOO' AND isactive = 'Y' AND ad_client_id = %s
            AND ad_org_id IN (
                WITH RECURSIVE org_tree AS (
                    SELECT ad_org_id, ad_org_id as root_org
                    FROM ad_org
                    WHERE ad_org_id = %s
                    UNION ALL
                    SELECT tn.parent_id, ot.root_org
                    FROM org_tree ot
                    JOIN ad_treenode tn ON tn.node_id = ot.ad_org_id
                    JOIN ad_tree t ON t.ad_tree_id = tn.ad_tree_id AND t.treetype = 'OO'
                    WHERE tn.parent_id IS NOT NULL AND tn.parent_id != '0'
                )
                SELECT ad_org_id FROM org_tree
                UNION SELECT '0'
            )
            ORDER BY 
                CASE 
                    WHEN ad_org_id = %s THEN 1
                    WHEN ad_org_id = '0' THEN 3
                    ELSE 2
                END
            LIMIT 1
        """, (bpartner['ad_client_id'], org_id, org_id))
        doctype = cur.fetchone()
        
        if not doctype:
            return jsonify({'error': 'No Document Type found for Sales Order'}), 400
        
        # Get Price List from request or default
        pricelist_id = data.get('m_pricelist_id')
        if pricelist_id:
            cur.execute("""
                SELECT pl.m_pricelist_id, pl.c_currency_id
                FROM m_pricelist pl 
                WHERE pl.m_pricelist_id = %s AND pl.isactive = 'Y'
            """, (pricelist_id,))
            pricelist = cur.fetchone()
        else:
            cur.execute("""
                SELECT pl.m_pricelist_id, pl.c_currency_id
                FROM m_pricelist pl 
                WHERE issopricelist = 'Y' AND isactive = 'Y' AND ad_client_id = %s
                LIMIT 1
            """, (bpartner['ad_client_id'],))
            pricelist = cur.fetchone()
        
        # Generate IDs
        c_order_id = generate_uuid()
        
        # Generate Document Number
        cur.execute("""
            SELECT currentnext FROM ad_sequence
            WHERE name = 'DocumentNo_C_Order' AND ad_client_id = %s
        """, (bpartner['ad_client_id'],))
        seq = cur.fetchone()
        seq_num = str(seq['currentnext']).zfill(5) if seq else '00001'
        documentno = f"{now.strftime('%Y%m%d')}-{seq_num}"
        
        # Update sequence
        if seq:
            cur.execute("""
                UPDATE ad_sequence SET currentnext = currentnext + 1
                WHERE name = 'DocumentNo_C_Order' AND ad_client_id = %s
            """, (bpartner['ad_client_id'],))
        
        # Get optional fields from request
        partner_location_id = data.get('c_bpartner_location_id') or bpartner['c_bpartner_location_id']
        order_date = data.get('dateordered', now)
        delivery_date = data.get('datepromised')
        payment_method_id = data.get('fin_paymentmethod_id')
        payment_term_id = data.get('c_paymentterm_id')
        invoice_rule = data.get('invoicerule', 'D')  # I=Immediate, D=After Delivery, O=Order Complete
        description = data.get('description', 'Created via Barcode App')
        
        # Get default payment term if not provided
        if not payment_term_id:
            cur.execute("""
                SELECT c_paymentterm_id FROM c_paymentterm 
                WHERE isactive = 'Y' AND ad_client_id = %s
                ORDER BY isdefault DESC LIMIT 1
            """, (bpartner['ad_client_id'],))
            default_pt = cur.fetchone()
            payment_term_id = default_pt['c_paymentterm_id'] if default_pt else None
        
        # Create C_ORDER header with all required NOT NULL fields
        cur.execute("""
            INSERT INTO c_order (
                c_order_id, ad_client_id, ad_org_id, isactive, created, createdby,
                updated, updatedby, issotrx, documentno, docaction, docstatus,
                processed, c_doctype_id, c_doctypetarget_id, c_bpartner_id,
                c_bpartner_location_id, dateordered, dateacct, datepromised, c_currency_id,
                m_warehouse_id, m_pricelist_id, c_paymentterm_id,
                deliveryrule, deliveryviarule, invoicerule, paymentrule, freightcostrule, priorityrule,
                isdelivered, isinvoiced, isprinted, isselected, isdiscountprinted,
                totallines, grandtotal, posted, isselfservice, iscashvat, iscancelled,
                istaxincluded, description, fin_paymentmethod_id
            ) VALUES (
                %s, %s, %s, 'Y', %s, '0',
                %s, '0', 'Y', %s, 'CO', 'DR',
                'N', %s, %s, %s,
                %s, %s, %s, %s, %s,
                %s, %s, %s,
                'A', 'D', %s, 'P', 'I', '5',
                'N', 'N', 'N', 'N', 'Y',
                0, 0, 'N', 'N', 'N', 'N',
                'N', %s, %s
            )
        """, (
            c_order_id, bpartner['ad_client_id'], org_id, now, now,
            documentno, doctype['c_doctype_id'], doctype['c_doctype_id'], data['c_bpartner_id'],
            partner_location_id, order_date, now, delivery_date, pricelist['c_currency_id'] if pricelist else None,
            data['m_warehouse_id'], pricelist['m_pricelist_id'] if pricelist else None, payment_term_id,
            invoice_rule,
            description, payment_method_id
        ))
        
        # Create order lines
        line_num = 10
        total_lines = 0
        
        for line_data in data['lines']:
            c_orderline_id = generate_uuid()
            
            # Get product info
            cur.execute("""
                SELECT m_product_id, c_uom_id
                FROM m_product
                WHERE m_product_id = %s
            """, (line_data['m_product_id'],))
            product = cur.fetchone()
            
            if not product:
                continue
            
            qty = line_data.get('qtyordered', 0)
            price = line_data.get('priceactual', 0)
            linenetamt = qty * price
            
            # c_orderline has 30 NOT NULL columns
            # Get tax from product's tax category, or use a default one
            cur.execute("""
                SELECT COALESCE(
                    (SELECT t.c_tax_id 
                     FROM m_product p 
                     JOIN c_tax t ON p.c_taxcategory_id = t.c_taxcategory_id 
                     WHERE p.m_product_id = %s AND t.isactive = 'Y' AND t.issummary = 'N'
                     LIMIT 1),
                    (SELECT c_tax_id FROM c_tax WHERE ad_client_id = %s AND isactive = 'Y' AND issummary = 'N' ORDER BY name LIMIT 1)
                ) as c_tax_id
            """, (line_data['m_product_id'], bpartner['ad_client_id']))
            tax_result = cur.fetchone()
            tax_id = tax_result['c_tax_id'] if tax_result else None
            
            if not tax_id:
                return jsonify({'error': f'No tax found for product {line_data["m_product_id"]}'}), 400
            
            cur.execute("""
                INSERT INTO c_orderline (
                    c_orderline_id, ad_client_id, ad_org_id, isactive, created, createdby,
                    updated, updatedby, c_order_id, line, 
                    dateordered, m_warehouse_id,
                    m_product_id, c_uom_id,
                    directship, qtyordered, qtyreserved, qtydelivered, qtyinvoiced, 
                    c_currency_id, pricelist, priceactual, pricelimit, linenetamt, freightamt,
                    isdescription, pricestd, grosspricestd, explode, print_description, relate_orderline,
                    c_tax_id
                ) VALUES (
                    %s, %s, %s, 'Y', %s, '0',
                    %s, '0', %s, %s,
                    %s, %s,
                    %s, %s,
                    'N', %s, 0, 0, 0,
                    %s, %s, %s, %s, %s, 0,
                    'N', %s, %s, 'N', 'N', 'N',
                    %s
                )
            """, (
                c_orderline_id, bpartner['ad_client_id'], org_id, now,
                now, c_order_id, line_num,
                order_date, data['m_warehouse_id'],
                line_data['m_product_id'], product['c_uom_id'],
                qty,
                pricelist['c_currency_id'] if pricelist else None, price, price, price, linenetamt,
                price, price,
                tax_id
            ))
            
            line_num += 10
            total_lines += linenetamt
        
        # Update order total
        cur.execute("""
            UPDATE c_order 
            SET totallines = %s, grandtotal = %s
            WHERE c_order_id = %s
        """, (total_lines, total_lines, c_order_id))
        
        conn.commit()
        
        return jsonify({
            'success': True,
            'message': 'Sale Order created successfully',
            'c_order_id': c_order_id,
            'documentno': documentno
        })
        
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


# ==================== GOODS SHIPMENT ENDPOINTS ====================

@app.route('/api/goods-shipment', methods=['POST'])
def create_goods_shipment():
    """Tạo Goods Shipment từ Sale Order"""
    data = request.get_json()
    
    required = ['c_order_id', 'lines']
    for field in required:
        if field not in data:
            return jsonify({'error': f'{field} is required'}), 400
    
    if not data['lines']:
        return jsonify({'error': 'At least one line is required'}), 400
    
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    try:
        cur = conn.cursor()
        now = datetime.now()
        c_order_id = data['c_order_id']
        lines = data['lines']
        
        # Get Sale Order info
        cur.execute("""
            SELECT 
                o.c_order_id, o.ad_client_id, o.ad_org_id, o.c_bpartner_id,
                o.c_bpartner_location_id, o.m_warehouse_id, o.dateordered,
                o.c_doctype_id
            FROM c_order o
            WHERE o.c_order_id = %s AND o.issotrx = 'Y'
        """, (c_order_id,))
        order = cur.fetchone()
        
        if not order:
            return jsonify({'error': 'Sale Order not found'}), 404
        
        # Get warehouse - use from data or from order
        warehouse_id = data.get('m_warehouse_id', order['m_warehouse_id'])
        
        # Get Document Type for Goods Shipment (MM Shipment)
        cur.execute("""
            SELECT c_doctype_id 
            FROM c_doctype 
            WHERE docbasetype = 'MMS' AND isactive = 'Y' AND ad_client_id = %s
            LIMIT 1
        """, (order['ad_client_id'],))
        doctype = cur.fetchone()
        
        if not doctype:
            return jsonify({'error': 'No Document Type found for Goods Shipment'}), 400
        
        # Get default Locator from Warehouse
        cur.execute("""
            SELECT m_locator_id, value
            FROM m_locator
            WHERE m_warehouse_id = %s AND isdefault = 'Y' AND isactive = 'Y'
            LIMIT 1
        """, (warehouse_id,))
        locator = cur.fetchone()
        
        if not locator:
            cur.execute("""
                SELECT m_locator_id, value
                FROM m_locator
                WHERE m_warehouse_id = %s AND isactive = 'Y'
                ORDER BY value LIMIT 1
            """, (warehouse_id,))
            locator = cur.fetchone()
        
        if not locator:
            return jsonify({'error': 'No Locator found in Warehouse'}), 400
        
        # Generate IDs and Document Number
        m_inout_id = generate_uuid()
        
        cur.execute("""
            SELECT currentnext FROM ad_sequence
            WHERE name = 'DocumentNo_M_InOut' AND ad_client_id = %s
        """, (order['ad_client_id'],))
        seq = cur.fetchone()
        seq_num = str(seq['currentnext']).zfill(5) if seq else '00001'
        documentno = f"{now.strftime('%Y%m%d')}-{seq_num}"
        
        if seq:
            cur.execute("""
                UPDATE ad_sequence SET currentnext = currentnext + 1
                WHERE name = 'DocumentNo_M_InOut' AND ad_client_id = %s
            """, (order['ad_client_id'],))
        
        # Create M_INOUT header for Goods Shipment
        cur.execute("""
            INSERT INTO m_inout (
                m_inout_id, ad_client_id, ad_org_id, isactive, created, createdby,
                updated, updatedby, issotrx, documentno, docaction, docstatus,
                posted, processing, processed, c_doctype_id, description,
                c_order_id, dateordered, isprinted, movementtype, movementdate,
                dateacct, c_bpartner_id, c_bpartner_location_id, m_warehouse_id,
                deliveryrule, freightcostrule, deliveryviarule, priorityrule
            ) VALUES (
                %s, %s, %s, 'Y', %s, '0',
                %s, '0', 'Y', %s, 'CO', 'DR',
                'N', NULL, 'N', %s, %s,
                %s, %s, 'N', 'C-', %s,
                %s, %s, %s, %s,
                'A', 'I', 'D', '5'
            )
        """, (
            m_inout_id, order['ad_client_id'], order['ad_org_id'], now, now,
            documentno, doctype['c_doctype_id'], 'Created from Sale Order via Barcode App',
            c_order_id, order['dateordered'], now,
            now, order['c_bpartner_id'], order['c_bpartner_location_id'], warehouse_id
        ))
        
        # Create M_INOUTLINE for each line
        line_num = 10
        created_lines = []
        
        for line_data in lines:
            c_orderline_id = line_data.get('c_orderline_id')
            qty_delivered = line_data.get('qty_delivered', 0)
            
            if qty_delivered <= 0:
                continue
            
            # Get order line info
            cur.execute("""
                SELECT ol.m_product_id, ol.c_uom_id, ol.qtyordered, ol.qtydelivered
                FROM c_orderline ol
                WHERE ol.c_orderline_id = %s
            """, (c_orderline_id,))
            orderline = cur.fetchone()
            
            if not orderline:
                continue
            
            m_inoutline_id = generate_uuid()
            
            cur.execute("""
                INSERT INTO m_inoutline (
                    m_inoutline_id, ad_client_id, ad_org_id, isactive, created, createdby,
                    updated, updatedby, m_inout_id, c_orderline_id, line,
                    m_product_id, m_locator_id, c_uom_id, movementqty, isinvoiced
                ) VALUES (
                    %s, %s, %s, 'Y', %s, '0',
                    %s, '0', %s, %s, %s,
                    %s, %s, %s, %s, 'N'
                )
            """, (
                m_inoutline_id, order['ad_client_id'], order['ad_org_id'], now,
                now, m_inout_id, c_orderline_id, line_num,
                orderline['m_product_id'], locator['m_locator_id'], orderline['c_uom_id'], qty_delivered
            ))
            
            # Update order line qty delivered
            new_qty_delivered = float(orderline['qtydelivered'] or 0) + qty_delivered
            cur.execute("""
                UPDATE c_orderline 
                SET qtydelivered = %s, updated = %s
                WHERE c_orderline_id = %s
            """, (new_qty_delivered, now, c_orderline_id))
            
            created_lines.append({
                'line': line_num,
                'product_id': orderline['m_product_id'],
                'qty': qty_delivered
            })
            
            line_num += 10
        
        if not created_lines:
            conn.rollback()
            return jsonify({'error': 'No valid lines to create shipment'}), 400
        
        conn.commit()
        
        return jsonify({
            'success': True,
            'message': 'Goods Shipment created successfully',
            'm_inout_id': m_inout_id,
            'documentno': documentno,
            'lines': created_lines
        })
        
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/goods-shipments')
def get_goods_shipments():
    """Lấy danh sách phiếu xuất kho (Goods Shipments)"""
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    try:
        cur = conn.cursor()
        status = request.args.get('status', '')
        limit = request.args.get('limit', 100, type=int)
        from_date = request.args.get('from_date', '')
        to_date = request.args.get('to_date', '')
        
        query = """
            SELECT 
                io.m_inout_id,
                io.documentno,
                io.movementdate,
                io.docstatus,
                bp.name as bpartner_name,
                w.name as warehouse_name,
                org.name as organization,
                o.documentno as order_documentno
            FROM m_inout io
            LEFT JOIN c_bpartner bp ON io.c_bpartner_id = bp.c_bpartner_id
            LEFT JOIN m_warehouse w ON io.m_warehouse_id = w.m_warehouse_id
            LEFT JOIN ad_org org ON io.ad_org_id = org.ad_org_id
            LEFT JOIN c_order o ON io.c_order_id = o.c_order_id
            WHERE io.issotrx = 'Y' AND io.isactive = 'Y'
        """
        params = []
        
        if status:
            query += " AND io.docstatus = %s"
            params.append(status)
        
        if from_date:
            query += " AND io.movementdate >= %s"
            params.append(from_date)
        
        if to_date:
            query += " AND io.movementdate <= %s"
            params.append(to_date)
        
        query += " ORDER BY io.movementdate DESC LIMIT %s"
        params.append(limit)
        
        cur.execute(query, params)
        shipments = cur.fetchall()
        return jsonify({'success': True, 'shipments': [dict(s) for s in shipments], 'count': len(shipments)})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/goods-shipment/<shipment_id>')
def get_goods_shipment_detail(shipment_id):
    """Lấy chi tiết Goods Shipment"""
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    try:
        cur = conn.cursor()
        
        # Shipment header
        cur.execute("""
            SELECT 
                io.m_inout_id,
                io.documentno,
                io.movementdate,
                io.docstatus,
                io.description,
                bp.name as bpartner_name,
                bp.c_bpartner_id,
                w.name as warehouse_name,
                w.m_warehouse_id,
                org.name as organization,
                io.ad_org_id,
                io.ad_client_id,
                o.documentno as order_documentno,
                o.c_order_id
            FROM m_inout io
            LEFT JOIN c_bpartner bp ON io.c_bpartner_id = bp.c_bpartner_id
            LEFT JOIN m_warehouse w ON io.m_warehouse_id = w.m_warehouse_id
            LEFT JOIN ad_org org ON io.ad_org_id = org.ad_org_id
            LEFT JOIN c_order o ON io.c_order_id = o.c_order_id
            WHERE io.m_inout_id = %s AND io.issotrx = 'Y'
        """, (shipment_id,))
        shipment = cur.fetchone()
        
        if not shipment:
            return jsonify({'error': 'Goods Shipment not found'}), 404
        
        # Shipment lines
        cur.execute("""
            SELECT 
                iol.m_inoutline_id,
                iol.line,
                iol.movementqty,
                p.value as product_code,
                p.name as product_name,
                p.upc as barcode,
                uom.name as uom_name,
                l.value as locator
            FROM m_inoutline iol
            LEFT JOIN m_product p ON iol.m_product_id = p.m_product_id
            LEFT JOIN c_uom uom ON iol.c_uom_id = uom.c_uom_id
            LEFT JOIN m_locator l ON iol.m_locator_id = l.m_locator_id
            WHERE iol.m_inout_id = %s
            ORDER BY iol.line
        """, (shipment_id,))
        lines = cur.fetchall()
        
        return jsonify({
            'success': True,
            'shipment': dict(shipment),
            'lines': [dict(l) for l in lines]
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


# ==================== SALE ORDER PRINT PDF ====================

@app.route('/api/sale-order/<order_id>/print')
def print_sale_order_pdf(order_id):
    """In PDF cho Sale Order"""
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import mm
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image, HRFlowable
        from reportlab.lib.enums import TA_CENTER, TA_RIGHT, TA_LEFT
        
        cur = conn.cursor()
        
        # Get Sale Order header
        cur.execute("""
            SELECT 
                o.c_order_id, o.documentno, o.dateordered, o.description,
                o.docstatus, o.grandtotal,
                bp.name as customer_name, bp.value as customer_code,
                w.name as warehouse_name,
                c.iso_code as currency,
                org.name as org_name
            FROM c_order o
            LEFT JOIN c_bpartner bp ON o.c_bpartner_id = bp.c_bpartner_id
            LEFT JOIN m_warehouse w ON o.m_warehouse_id = w.m_warehouse_id
            LEFT JOIN c_currency c ON o.c_currency_id = c.c_currency_id
            LEFT JOIN ad_org org ON o.ad_org_id = org.ad_org_id
            WHERE o.c_order_id = %s AND o.issotrx = 'Y'
        """, (order_id,))
        order = cur.fetchone()
        
        if not order:
            return jsonify({'error': 'Sale Order not found'}), 404
        
        # Get order lines
        cur.execute("""
            SELECT 
                ol.line, ol.qtyordered, ol.qtydelivered, ol.priceactual, ol.linenetamt,
                p.value as product_code, p.name as product_name, p.upc as barcode,
                uom.name as uom_name
            FROM c_orderline ol
            LEFT JOIN m_product p ON ol.m_product_id = p.m_product_id
            LEFT JOIN c_uom uom ON ol.c_uom_id = uom.c_uom_id
            WHERE ol.c_order_id = %s
            ORDER BY ol.line
        """, (order_id,))
        lines = cur.fetchall()
        
        order_dict = dict(order)
        
        # Create PDF - FPT Style
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=15*mm, leftMargin=15*mm,
                               topMargin=15*mm, bottomMargin=15*mm)
        elements = []
        styles = getSampleStyleSheet()
        
        # FPT Styles
        fpt_normal_style = ParagraphStyle('FPTNormal', parent=styles['Normal'], fontSize=9,
                                         textColor=colors.HexColor('#333333'))
        fpt_header_style = ParagraphStyle('FPTHeader', parent=styles['Normal'], fontSize=11,
                                         textColor=colors.HexColor('#F37021'), fontName='Helvetica-Bold',
                                         spaceAfter=2*mm)
        
        # QR Code - sử dụng documentno thay vì UUID
        qr_image = None
        try:
            import qrcode
            qr = qrcode.QRCode(version=1, error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=5, border=1)
            qr.add_data(order_dict.get('documentno', order_id))
            qr.make(fit=True)
            qr_img = qr.make_image(fill_color="#F37021", back_color="white")
            qr_buffer = io.BytesIO()
            qr_img.save(qr_buffer, format='PNG')
            qr_buffer.seek(0)
            qr_image = Image(qr_buffer, width=32*mm, height=32*mm)
        except:
            pass
        
        # ==================== HEADER ====================
        brand_text = '<font size="22" color="#F37021"><b>FPT</b></font><font size="14" color="#003399"><b> WAREHOUSE</b></font>'
        brand_para = Paragraph(brand_text, ParagraphStyle('Brand', alignment=TA_LEFT))
        
        doc_title = Paragraph('<font size="16" color="#F37021"><b>SALE ORDER</b></font>',
                             ParagraphStyle('DocTitle', alignment=TA_CENTER, leading=16))
        
        if qr_image:
            header_table = Table([[brand_para, doc_title, qr_image]], colWidths=[55*mm, 70*mm, 40*mm])
        else:
            header_table = Table([[brand_para, doc_title, '']], colWidths=[55*mm, 90*mm, 20*mm])
        
        header_table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (0, 0), 'LEFT'),
            ('ALIGN', (1, 0), (1, 0), 'CENTER'),
            ('ALIGN', (2, 0), (2, 0), 'RIGHT'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ]))
        elements.append(header_table)
        elements.append(Spacer(1, 3*mm))
        elements.append(HRFlowable(width="100%", thickness=2, color=colors.HexColor('#F37021'), spaceAfter=5*mm))
        
        # ==================== INFO SECTION ====================
        left_info = [
            ['<b>Order No:</b>', order_dict.get('documentno', 'N/A')],
            ['<b>Order Date:</b>', str(order_dict.get('dateordered', 'N/A'))[:10]],
            ['<b>Customer Code:</b>', order_dict.get('customer_code', '-')],
            ['<b>Status:</b>', '<font color="#27ae60">Completed</font>' if order_dict.get('docstatus') == 'CO' else '<font color="#e74c3c">Draft</font>'],
        ]
        
        right_info = [
            ['<b>Customer:</b>', order_dict.get('customer_name', 'N/A')],
            ['<b>Warehouse:</b>', order_dict.get('warehouse_name', '-')],
            ['<b>Organization:</b>', order_dict.get('org_name', '-')],
            ['<b>Currency:</b>', order_dict.get('currency', 'VND')],
        ]
        
        left_data = [[Paragraph(row[0], fpt_normal_style), Paragraph(str(row[1]), fpt_normal_style)] for row in left_info]
        right_data = [[Paragraph(row[0], fpt_normal_style), Paragraph(str(row[1]), fpt_normal_style)] for row in right_info]
        
        left_table = Table(left_data, colWidths=[35*mm, 50*mm])
        left_table.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP'), ('TOPPADDING', (0, 0), (-1, -1), 1*mm), ('BOTTOMPADDING', (0, 0), (-1, -1), 1*mm)]))
        
        right_table = Table(right_data, colWidths=[35*mm, 50*mm])
        right_table.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP'), ('TOPPADDING', (0, 0), (-1, -1), 1*mm), ('BOTTOMPADDING', (0, 0), (-1, -1), 1*mm)]))
        
        info_wrapper = Table([[left_table, right_table]], colWidths=[90*mm, 90*mm])
        info_wrapper.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#FFF5F0')),
            ('BOX', (0, 0), (-1, -1), 1, colors.HexColor('#F37021')),
            ('TOPPADDING', (0, 0), (-1, -1), 3*mm),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3*mm),
            ('LEFTPADDING', (0, 0), (-1, -1), 3*mm),
            ('RIGHTPADDING', (0, 0), (-1, -1), 3*mm),
        ]))
        elements.append(info_wrapper)
        elements.append(Spacer(1, 6*mm))
        
        # ==================== PRODUCT TABLE ====================
        elements.append(Paragraph('<b>ORDER DETAILS</b>', fpt_header_style))
        
        table_header = ['No.', 'Code', 'Product Name', 'Barcode', 'Ordered', 'Delivered', 'Unit Price', 'Amount']
        table_data = [table_header]
        
        total_amount = 0
        total_qty = 0
        for idx, line in enumerate([dict(l) for l in lines], 1):
            qty = float(line.get('qtyordered', 0))
            delivered = float(line.get('qtydelivered', 0) or 0)
            price = float(line.get('priceactual', 0))
            amount = float(line.get('linenetamt', 0))
            total_amount += amount
            total_qty += qty
            
            table_data.append([
                str(idx),
                str(line.get('product_code', ''))[:10],
                str(line.get('product_name', ''))[:26],
                str(line.get('barcode', ''))[:10] or '-',
                f"{qty:,.0f}",
                f"{delivered:,.0f}",
                f"{price:,.0f}",
                f"{amount:,.0f}"
            ])
        
        # Total rows
        table_data.append(['', '', '', '', '', '', '', ''])
        table_data.append(['', '', Paragraph('<b>TOTAL QUANTITY:</b>', fpt_normal_style), '', f"{total_qty:,.0f}", '', '', ''])
        table_data.append(['', '', Paragraph(f'<b>GRAND TOTAL ({order_dict.get("currency", "VND")}):</b>', fpt_normal_style), '', '', '', '', f"{total_amount:,.0f}"])
        
        products_table = Table(table_data, colWidths=[12*mm, 20*mm, 45*mm, 20*mm, 18*mm, 18*mm, 22*mm, 25*mm])
        products_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#F37021')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 8),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 3*mm),
            ('TOPPADDING', (0, 0), (-1, 0), 2*mm),
            ('GRID', (0, 0), (-1, -4), 0.5, colors.grey),
            ('ALIGN', (4, 1), (-1, -1), 'RIGHT'),
            ('FONTSIZE', (0, 1), (-1, -1), 8),
            ('TOPPADDING', (0, 1), (-1, -1), 1.5*mm),
            ('BOTTOMPADDING', (0, 1), (-1, -1), 1.5*mm),
            ('BACKGROUND', (0, -3), (-1, -1), colors.HexColor('#FFF5F0')),
            ('SPAN', (2, -3), (3, -3)),
            ('SPAN', (2, -2), (4, -2)),
            ('SPAN', (2, -1), (6, -1)),
            ('FONTNAME', (0, -3), (-1, -1), 'Helvetica-Bold'),
        ]))
        elements.append(products_table)
        elements.append(Spacer(1, 8*mm))
        
        # ==================== NOTES & SIGNATURES ====================
        if order_dict.get('description'):
            elements.append(Paragraph(f'<b>Notes:</b> {order_dict["description"]}', fpt_normal_style))
            elements.append(Spacer(1, 6*mm))
        
        sig_header = [
            Paragraph('<b>Prepared By</b>', ParagraphStyle('SigHead', alignment=TA_CENTER, fontSize=9)),
            Paragraph('<b>Sales Manager</b>', ParagraphStyle('SigHead', alignment=TA_CENTER, fontSize=9)),
            Paragraph('<b>Customer Approval</b>', ParagraphStyle('SigHead', alignment=TA_CENTER, fontSize=9)),
        ]
        sig_space = [Paragraph('<br/><br/><br/>', fpt_normal_style)] * 3
        sig_line = [Paragraph('_' * 22, ParagraphStyle('SigLine', alignment=TA_CENTER, fontSize=8))] * 3
        
        sig_table = Table([sig_header, sig_space, sig_line], colWidths=[60*mm, 60*mm, 60*mm])
        sig_table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ]))
        elements.append(sig_table)
        elements.append(Spacer(1, 6*mm))
        
        # ==================== FOOTER ====================
        footer_left = f'<font size="7" color="#888888">Printed: {datetime.now().strftime("%Y-%m-%d %H:%M")}</font>'
        footer_right = f'<font size="7" color="#888888">FPT Warehouse System | Order ID: {order_id[:8]}...</font>'
        
        footer_table = Table([[Paragraph(footer_left, fpt_normal_style), Paragraph(footer_right, ParagraphStyle('FooterRight', alignment=TA_RIGHT, fontSize=7))]], 
                            colWidths=[90*mm, 90*mm])
        footer_table.setStyle(TableStyle([
            ('LINEABOVE', (0, 0), (-1, 0), 0.5, colors.grey),
            ('TOPPADDING', (0, 0), (-1, 0), 5),
        ]))
        elements.append(footer_table)
        
        doc.build(elements)
        buffer.seek(0)
        
        filename = f"SO_{order_dict['documentno']}_{datetime.now().strftime('%Y%m%d')}.pdf"
        download = request.args.get('download', '0') == '1'
        
        return send_file(buffer, mimetype='application/pdf', as_attachment=download, 
                        download_name=filename)
    
    except ImportError:
        return jsonify({'error': 'PDF library required. Run: pip install reportlab'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/goods-shipment/<shipment_id>/print')
def print_goods_shipment_pdf(shipment_id):
    """In PDF cho Goods Shipment"""
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import mm
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image, HRFlowable
        from reportlab.lib.enums import TA_CENTER, TA_RIGHT, TA_LEFT
        
        cur = conn.cursor()
        
        # Get Goods Shipment header
        cur.execute("""
            SELECT 
                io.m_inout_id, io.documentno, io.movementdate, io.description,
                io.docstatus,
                bp.name as customer_name,
                w.name as warehouse_name,
                o.documentno as order_documentno,
                org.name as org_name
            FROM m_inout io
            LEFT JOIN c_bpartner bp ON io.c_bpartner_id = bp.c_bpartner_id
            LEFT JOIN m_warehouse w ON io.m_warehouse_id = w.m_warehouse_id
            LEFT JOIN c_order o ON io.c_order_id = o.c_order_id
            LEFT JOIN ad_org org ON io.ad_org_id = org.ad_org_id
            WHERE io.m_inout_id = %s AND io.issotrx = 'Y'
        """, (shipment_id,))
        shipment = cur.fetchone()
        
        if not shipment:
            return jsonify({'error': 'Goods Shipment not found'}), 404
        
        # Get shipment lines
        cur.execute("""
            SELECT 
                iol.line, iol.movementqty,
                p.value as product_code, p.name as product_name,
                l.value as locator,
                uom.name as uom_name
            FROM m_inoutline iol
            LEFT JOIN m_product p ON iol.m_product_id = p.m_product_id
            LEFT JOIN m_locator l ON iol.m_locator_id = l.m_locator_id
            LEFT JOIN c_uom uom ON iol.c_uom_id = uom.c_uom_id
            WHERE iol.m_inout_id = %s
            ORDER BY iol.line
        """, (shipment_id,))
        lines = cur.fetchall()
        
        shipment_dict = dict(shipment)
        
        # Create PDF - FPT Style
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=15*mm, leftMargin=15*mm,
                               topMargin=15*mm, bottomMargin=15*mm)
        elements = []
        styles = getSampleStyleSheet()
        
        # FPT Styles
        fpt_normal_style = ParagraphStyle('FPTNormal', parent=styles['Normal'], fontSize=9,
                                         textColor=colors.HexColor('#333333'))
        fpt_header_style = ParagraphStyle('FPTHeader', parent=styles['Normal'], fontSize=11,
                                         textColor=colors.HexColor('#27ae60'), fontName='Helvetica-Bold',
                                         spaceAfter=2*mm)
        
        # QR Code - sử dụng documentno thay vì UUID
        qr_image = None
        try:
            import qrcode
            qr = qrcode.QRCode(version=1, error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=5, border=1)
            qr.add_data(shipment_dict.get('documentno', shipment_id))
            qr.make(fit=True)
            qr_img = qr.make_image(fill_color="#27ae60", back_color="white")
            qr_buffer = io.BytesIO()
            qr_img.save(qr_buffer, format='PNG')
            qr_buffer.seek(0)
            qr_image = Image(qr_buffer, width=32*mm, height=32*mm)
        except:
            pass
        
        # ==================== HEADER ====================
        brand_text = '<font size="22" color="#F37021"><b>FPT</b></font><font size="14" color="#003399"><b> WAREHOUSE</b></font>'
        brand_para = Paragraph(brand_text, ParagraphStyle('Brand', alignment=TA_LEFT))
        
        doc_title = Paragraph('<font size="16" color="#27ae60"><b>GOODS SHIPMENT</b></font>',
                             ParagraphStyle('DocTitle', alignment=TA_CENTER, leading=16))
        
        if qr_image:
            header_table = Table([[brand_para, doc_title, qr_image]], colWidths=[55*mm, 70*mm, 40*mm])
        else:
            header_table = Table([[brand_para, doc_title, '']], colWidths=[55*mm, 90*mm, 20*mm])
        
        header_table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (0, 0), 'LEFT'),
            ('ALIGN', (1, 0), (1, 0), 'CENTER'),
            ('ALIGN', (2, 0), (2, 0), 'RIGHT'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ]))
        elements.append(header_table)
        elements.append(Spacer(1, 3*mm))
        elements.append(HRFlowable(width="100%", thickness=2, color=colors.HexColor('#27ae60'), spaceAfter=5*mm))
        
        # ==================== INFO SECTION ====================
        left_info = [
            ['<b>Shipment No:</b>', shipment_dict.get('documentno', 'N/A')],
            ['<b>Shipment Date:</b>', str(shipment_dict.get('movementdate', 'N/A'))[:10]],
            ['<b>Related SO:</b>', shipment_dict.get('order_documentno', '-') or 'N/A'],
            ['<b>Status:</b>', '<font color="#27ae60">Completed</font>' if shipment_dict.get('docstatus') == 'CO' else '<font color="#e74c3c">Draft</font>'],
        ]
        
        right_info = [
            ['<b>Customer:</b>', shipment_dict.get('customer_name', 'N/A') or 'N/A'],
            ['<b>Warehouse:</b>', shipment_dict.get('warehouse_name', '-') or 'N/A'],
            ['<b>Organization:</b>', shipment_dict.get('org_name', '-') or 'N/A'],
            ['<b>Document Type:</b>', 'Customer Shipment'],
        ]
        
        left_data = [[Paragraph(row[0], fpt_normal_style), Paragraph(str(row[1]), fpt_normal_style)] for row in left_info]
        right_data = [[Paragraph(row[0], fpt_normal_style), Paragraph(str(row[1]), fpt_normal_style)] for row in right_info]
        
        left_table = Table(left_data, colWidths=[35*mm, 50*mm])
        left_table.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP'), ('TOPPADDING', (0, 0), (-1, -1), 1*mm), ('BOTTOMPADDING', (0, 0), (-1, -1), 1*mm)]))
        
        right_table = Table(right_data, colWidths=[35*mm, 50*mm])
        right_table.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP'), ('TOPPADDING', (0, 0), (-1, -1), 1*mm), ('BOTTOMPADDING', (0, 0), (-1, -1), 1*mm)]))
        
        info_wrapper = Table([[left_table, right_table]], colWidths=[90*mm, 90*mm])
        info_wrapper.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#F0FFF0')),
            ('BOX', (0, 0), (-1, -1), 1, colors.HexColor('#27ae60')),
            ('TOPPADDING', (0, 0), (-1, -1), 3*mm),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3*mm),
            ('LEFTPADDING', (0, 0), (-1, -1), 3*mm),
            ('RIGHTPADDING', (0, 0), (-1, -1), 3*mm),
        ]))
        elements.append(info_wrapper)
        elements.append(Spacer(1, 6*mm))
        
        # ==================== PRODUCT TABLE ====================
        elements.append(Paragraph('<b>SHIPMENT DETAILS</b>', fpt_header_style))
        
        table_header = ['No.', 'Code', 'Product Name', 'Locator', 'Quantity', 'Unit']
        table_data = [table_header]
        
        total_qty = 0
        for idx, line in enumerate([dict(l) for l in lines], 1):
            qty = float(line.get('movementqty', 0))
            total_qty += qty
            
            table_data.append([
                str(idx),
                str(line.get('product_code', ''))[:12],
                str(line.get('product_name', ''))[:38],
                str(line.get('locator', ''))[:15] or '-',
                f"{qty:,.2f}",
                str(line.get('uom_name', ''))[:8] or ''
            ])
        
        # Total row
        table_data.append(['', '', '', '', '', ''])
        table_data.append(['', '', Paragraph('<b>TOTAL QUANTITY SHIPPED:</b>', fpt_normal_style), '', f"{total_qty:,.2f}", ''])
        
        products_table = Table(table_data, colWidths=[12*mm, 25*mm, 60*mm, 30*mm, 25*mm, 18*mm])
        products_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#27ae60')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 8),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 3*mm),
            ('TOPPADDING', (0, 0), (-1, 0), 2*mm),
            ('GRID', (0, 0), (-1, -3), 0.5, colors.grey),
            ('ALIGN', (4, 1), (-1, -1), 'RIGHT'),
            ('FONTSIZE', (0, 1), (-1, -1), 8),
            ('TOPPADDING', (0, 1), (-1, -1), 1.5*mm),
            ('BOTTOMPADDING', (0, 1), (-1, -1), 1.5*mm),
            ('BACKGROUND', (0, -2), (-1, -1), colors.HexColor('#F0FFF0')),
            ('SPAN', (2, -2), (3, -2)),
            ('SPAN', (2, -1), (3, -1)),
            ('FONTNAME', (0, -2), (-1, -1), 'Helvetica-Bold'),
        ]))
        elements.append(products_table)
        elements.append(Spacer(1, 8*mm))
        
        # ==================== NOTES & SIGNATURES ====================
        if shipment_dict.get('description'):
            elements.append(Paragraph(f'<b>Notes:</b> {shipment_dict["description"]}', fpt_normal_style))
            elements.append(Spacer(1, 6*mm))
        
        sig_header = [
            Paragraph('<b>Prepared By</b>', ParagraphStyle('SigHead', alignment=TA_CENTER, fontSize=9)),
            Paragraph('<b>Delivered By</b>', ParagraphStyle('SigHead', alignment=TA_CENTER, fontSize=9)),
            Paragraph('<b>Received By</b>', ParagraphStyle('SigHead', alignment=TA_CENTER, fontSize=9)),
        ]
        sig_space = [Paragraph('<br/><br/><br/>', fpt_normal_style)] * 3
        sig_line = [Paragraph('_' * 22, ParagraphStyle('SigLine', alignment=TA_CENTER, fontSize=8))] * 3
        
        sig_table = Table([sig_header, sig_space, sig_line], colWidths=[60*mm, 60*mm, 60*mm])
        sig_table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ]))
        elements.append(sig_table)
        elements.append(Spacer(1, 6*mm))
        
        # ==================== FOOTER ====================
        footer_left = f'<font size="7" color="#888888">Printed: {datetime.now().strftime("%Y-%m-%d %H:%M")}</font>'
        footer_right = f'<font size="7" color="#888888">FPT Warehouse System | Shipment ID: {shipment_id[:8]}...</font>'
        
        footer_table = Table([[Paragraph(footer_left, fpt_normal_style), Paragraph(footer_right, ParagraphStyle('FooterRight', alignment=TA_RIGHT, fontSize=7))]], 
                            colWidths=[90*mm, 90*mm])
        footer_table.setStyle(TableStyle([
            ('LINEABOVE', (0, 0), (-1, 0), 0.5, colors.grey),
            ('TOPPADDING', (0, 0), (-1, 0), 5),
        ]))
        elements.append(footer_table)
        
        doc.build(elements)
        buffer.seek(0)
        
        filename = f"GS_{shipment_dict['documentno']}_{datetime.now().strftime('%Y%m%d')}.pdf"
        download = request.args.get('download', '0') == '1'
        
        return send_file(buffer, mimetype='application/pdf', as_attachment=download, 
                        download_name=filename)
    
    except ImportError:
        return jsonify({'error': 'PDF library required. Run: pip install reportlab'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


# ==================== INVOICE EXPORT ENDPOINT ====================

@app.route('/api/export/invoice-data')
def export_invoice_data():
    """Export invoice data từ Sale Orders và Goods Shipments ra CSV/Excel"""
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    try:
        import pandas as pd
        from io import BytesIO
        
        cur = conn.cursor()
        export_format = request.args.get('format', 'excel')  # 'excel' or 'csv'
        
        # Get Sale Orders with invoice status
        cur.execute("""
            SELECT 
                o.documentno as so_number,
                o.dateordered as so_date,
                bp.name as customer,
                o.grandtotal as so_total,
                o.docstatus as so_status,
                CASE WHEN EXISTS (
                    SELECT 1 FROM c_invoice i WHERE i.c_order_id = o.c_order_id
                ) THEN 'Yes' ELSE 'No' END as has_invoice,
                (SELECT i.documentno FROM c_invoice i WHERE i.c_order_id = o.c_order_id LIMIT 1) as invoice_number
            FROM c_order o
            LEFT JOIN c_bpartner bp ON o.c_bpartner_id = bp.c_bpartner_id
            WHERE o.issotrx = 'Y' AND o.isactive = 'Y'
            ORDER BY o.dateordered DESC
            LIMIT 1000
        """)
        sale_orders = cur.fetchall()
        
        # Get Goods Shipments with invoice status  
        cur.execute("""
            SELECT 
                io.documentno as shipment_number,
                io.movementdate as shipment_date,
                bp.name as customer,
                o.documentno as so_number,
                io.docstatus as shipment_status,
                CASE WHEN EXISTS (
                    SELECT 1 FROM c_invoiceline il
                    JOIN m_inoutline iol ON il.m_inoutline_id = iol.m_inoutline_id
                    WHERE iol.m_inout_id = io.m_inout_id
                ) THEN 'Yes' ELSE 'No' END as has_invoice,
                (SELECT i.documentno FROM c_invoice i WHERE i.c_order_id = io.c_order_id LIMIT 1) as invoice_number
            FROM m_inout io
            LEFT JOIN c_bpartner bp ON io.c_bpartner_id = bp.c_bpartner_id
            LEFT JOIN c_order o ON io.c_order_id = o.c_order_id
            WHERE io.issotrx = 'Y' AND io.isactive = 'Y'
            ORDER BY io.movementdate DESC
            LIMIT 1000
        """)
        shipments = cur.fetchall()
        
        # Convert to DataFrames
        so_df = pd.DataFrame([dict(row) for row in sale_orders])
        gs_df = pd.DataFrame([dict(row) for row in shipments])
        
        # Create Excel file with multiple sheets
        output = BytesIO()
        
        if export_format == 'excel':
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                so_df.to_excel(writer, sheet_name='Sale Orders', index=False)
                gs_df.to_excel(writer, sheet_name='Goods Shipments', index=False)
            
            output.seek(0)
            filename = f'invoice_export_{datetime.now().strftime("%Y%m%d_%H%M%S")}.xlsx'
            return send_file(output, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                           as_attachment=True, download_name=filename)
        else:
            # CSV format - combine both
            combined_df = pd.concat([
                so_df.assign(source='Sale Order'),
                gs_df.assign(source='Goods Shipment')
            ], ignore_index=True)
            
            combined_df.to_csv(output, index=False)
            output.seek(0)
            filename = f'invoice_export_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
            return send_file(output, mimetype='text/csv', as_attachment=True, download_name=filename)
            
    except ImportError:
        return jsonify({'error': 'pandas and openpyxl required. Run: pip install pandas openpyxl'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


# ==================== AI DETECTION ENDPOINTS ====================

# File path for storing detection history
AI_HISTORY_FILE = os.path.join(os.path.dirname(__file__), 'ai_detection_history.json')

def load_ai_history():
    """Load detection history from JSON file"""
    try:
        if os.path.exists(AI_HISTORY_FILE):
            with open(AI_HISTORY_FILE, 'r', encoding='utf-8-sig') as f:
                return json.load(f)
    except Exception as e:
        print(f"Error loading AI history: {e}")
    return []

def save_ai_history():
    """Save detection history to JSON file"""
    try:
        with open(AI_HISTORY_FILE, 'w', encoding='utf-8') as f:
            json.dump(ai_detection_history, f, ensure_ascii=False, indent=2)
        print(f"✅ AI history saved to {AI_HISTORY_FILE} - {len(ai_detection_history)} records")
    except Exception as e:
        print(f"❌ Error saving AI history: {e}")

# Load history from file on startup
ai_detection_history = load_ai_history()

@app.route('/api/ai-detection-history')
def get_ai_detection_history():
    """Get AI detection history"""
    return jsonify({'history': ai_detection_history})


@app.route('/api/ai-detect', methods=['POST'])
def ai_detect():
    """Run AI detection on uploaded image or camera capture
    Supports 3 detection types:
    - defect: Detect product defects
    - box: Detect box, tape, receipt for packaging verification
    - accessory: Detect accessories in box
    
    Request body:
    {
        "type": "defect|box|accessory",
        "image": "base64_image_data or data:image/jpeg;base64,...",
        "camera_id": "100|101" (optional - if provided, uses camera instead of image)
    }
    """
    data = request.get_json()
    detection_type = data.get('type', 'defect')
    image_data = data.get('image', '')
    camera_id = data.get('camera_id', '')
    
    # Nếu có camera_id, ưu tiên lấy ảnh từ camera
    if camera_id and camera_manager:
        frame_data = camera_manager.get_frame_jpg(camera_id)
        if frame_data:
            image_data = base64.b64encode(frame_data).decode('utf-8')
        else:
            return jsonify({'success': False, 'error': f'Cannot capture from camera {camera_id}'}), 400
    
    if not image_data:
        return jsonify({'success': False, 'error': 'No image provided and no camera specified'}), 400
    
    try:
        # Check if YOLO models are available - models are in modelAI folder
        yolo_model_path = os.path.join(os.path.dirname(__file__), 'modelAI')
        defect_model = os.path.join(yolo_model_path, 'Model_can', 'best.pt')  # Use Model_can for defect detection
        box_model = os.path.join(yolo_model_path, 'Model_box', 'best.pt')     # Use Model_box for box/tape/receipt detection
        accessory_model = os.path.join(yolo_model_path, 'Model_can', 'best.pt')  # Use Model_can for accessory detection
        
        # Demo mode - simulated detection results if models not available
        if detection_type == 'defect':
            model_exists = os.path.exists(defect_model)
            
            if model_exists:
                # Real YOLO detection using Model_can
                # Classes: 'com' = complete/good can, 'fd' = defect/dented can
                from ultralytics import YOLO
                import base64
                import cv2
                import numpy as np
                
                # Decode base64 image
                img_bytes = base64.b64decode(image_data.split(',')[1])
                nparr = np.frombuffer(img_bytes, np.uint8)
                img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                
                model = YOLO(defect_model)
                results = model(img)
                
                defects = []
                complete_count = 0
                defect_count = 0
                
                for r in results:
                    for box in r.boxes:
                        label = r.names[int(box.cls)].lower()
                        # Model_can classes: 'com' = bình thường, 'fla' = lỗi móp méo
                        is_defect = label == 'fla' or 'defect' in label or 'dent' in label
                        
                        if is_defect:
                            defect_count += 1
                            defects.append({
                                'label': 'Lon bị móp/méo (FLA)' if label == 'fla' else r.names[int(box.cls)],
                                'confidence': float(box.conf),
                                'x': float(box.xyxy[0][0]),
                                'y': float(box.xyxy[0][1]),
                                'width': float(box.xyxy[0][2] - box.xyxy[0][0]),
                                'height': float(box.xyxy[0][3] - box.xyxy[0][1]),
                                'isDefect': True
                            })
                        else:
                            # 'com' = complete/good can (bình thường)
                            complete_count += 1
                
                return jsonify({
                    'success': True, 
                    'defects': defects, 
                    'complete_count': complete_count,
                    'defect_count': defect_count,
                    'model': 'yolo'
                })
            else:
                # Demo mode - no defects (user will provide real model)
                return jsonify({
                    'success': True, 
                    'defects': [],
                    'model': 'demo',
                    'message': 'Demo mode - Place defect_model.pt in barcode_app/models/ for real detection'
                })
                
        elif detection_type == 'box':
            model_exists = os.path.exists(box_model)
            
            if model_exists:
                # Real YOLO detection for box, tape, receipt
                from ultralytics import YOLO
                import base64
                import cv2
                import numpy as np
                
                img_bytes = base64.b64decode(image_data.split(',')[1])
                nparr = np.frombuffer(img_bytes, np.uint8)
                img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                
                model = YOLO(box_model)
                results = model(img)
                
                detected = {'box': False, 'tape': False, 'receipt': False}
                detections = []
                
                for r in results:
                    for box in r.boxes:
                        label = r.names[int(box.cls)].lower()
                        # Model_box classes: box, tape, receipt (exact match)
                        if label == 'box':
                            detected['box'] = True
                        elif label == 'tape' or label == 'tap':
                            detected['tape'] = True
                        elif label == 'receipt':
                            detected['receipt'] = True
                        
                        detections.append({
                            'label': r.names[int(box.cls)],
                            'confidence': float(box.conf),
                            'x': float(box.xyxy[0][0]),
                            'y': float(box.xyxy[0][1]),
                            'width': float(box.xyxy[0][2] - box.xyxy[0][0]),
                            'height': float(box.xyxy[0][3] - box.xyxy[0][1]),
                            'isDefect': False
                        })
                
                return jsonify({'success': True, 'detected': detected, 'detections': detections, 'model': 'yolo'})
            else:
                # Demo mode - simulate detection
                import random
                detected = {
                    'box': random.random() > 0.3,
                    'tape': random.random() > 0.3,
                    'receipt': random.random() > 0.3
                }
                return jsonify({
                    'success': True, 
                    'detected': detected,
                    'detections': [],
                    'model': 'demo',
                    'message': 'Demo mode - Place box_model.pt in barcode_app/models/ for real detection'
                })
                
        elif detection_type == 'accessory':
            model_exists = os.path.exists(accessory_model)
            
            if model_exists:
                # Real YOLO detection for accessories
                from ultralytics import YOLO
                import base64
                import cv2
                import numpy as np
                
                img_bytes = base64.b64decode(image_data.split(',')[1])
                nparr = np.frombuffer(img_bytes, np.uint8)
                img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                
                model = YOLO(accessory_model)
                results = model(img)
                
                accessories = []
                detections = []
                
                for r in results:
                    for box in r.boxes:
                        label = r.names[int(box.cls)].lower()
                        accessories.append(label)
                        
                        detections.append({
                            'label': r.names[int(box.cls)],
                            'confidence': float(box.conf),
                            'x': float(box.xyxy[0][0]),
                            'y': float(box.xyxy[0][1]),
                            'width': float(box.xyxy[0][2] - box.xyxy[0][0]),
                            'height': float(box.xyxy[0][3] - box.xyxy[0][1]),
                            'isDefect': False
                        })
                
                return jsonify({'success': True, 'accessories': accessories, 'detections': detections, 'model': 'yolo'})
            else:
                # Demo mode - simulate some accessories found
                import random
                all_accessories = ['manual', 'warranty', 'cable', 'adapter', 'remote', 'battery']
                found = random.sample(all_accessories, random.randint(2, 5))
                return jsonify({
                    'success': True, 
                    'accessories': found,
                    'detections': [],
                    'model': 'demo',
                    'message': 'Demo mode - Place accessory_model.pt in barcode_app/models/ for real detection'
                })
        
        return jsonify({'success': False, 'error': 'Unknown detection type'}), 400
        
    except ImportError as e:
        return jsonify({
            'success': False, 
            'error': f'Required packages not installed: {str(e)}. Run: pip install ultralytics opencv-python'
        }), 500
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/ai-detection-save', methods=['POST'])
def save_ai_detection():
    """Save AI detection record"""
    data = request.get_json()
    detection_type = data.get('type', 'defect')
    
    try:
        import uuid
        
        record = {
            'id': str(uuid.uuid4()),
            'created': datetime.now().isoformat(),
            'type': detection_type,
            'status': 'pending'
        }
        
        if detection_type == 'defect':
            # Get product name and shipment info
            conn = get_db_connection()
            if conn:
                cur = conn.cursor()
                cur.execute("SELECT name FROM m_product WHERE m_product_id = %s", (data.get('m_product_id'),))
                prod = cur.fetchone()
                product_name = prod['name'] if prod else 'Unknown'
                product_id = data.get('m_product_id')
                warehouse_id = data.get('m_warehouse_id')
                quantity = data.get('quantity', 1)
                defect_type = data.get('defect_type', 'other')
                notes = data.get('notes', '')
                
                # Get today's date for aggregation
                today = datetime.now().strftime('%Y-%m-%d')
                
                # Check if there's an existing record for same product + same date
                existing_record = None
                for r in ai_detection_history:
                    if (r.get('type') == 'defect' and 
                        r.get('m_product_id') == product_id and
                        r.get('created', '').startswith(today)):
                        existing_record = r
                        break
                
                if existing_record:
                    # Update existing record - add to defect count
                    existing_record['defect_count'] = existing_record.get('defect_count', existing_record.get('quantity', 0)) + quantity
                    existing_record['quantity'] = existing_record['defect_count']  # For compatibility
                    existing_record['updated'] = datetime.now().isoformat()
                    existing_record['notes'] = f"{existing_record.get('notes', '')} | +{quantity} {defect_type}".strip(' |')
                    existing_record['result'] = f"Defect: {existing_record['defect_count']}"
                    existing_record['status'] = 'pending'
                    save_ai_history()
                    conn.close()
                    return jsonify({
                        'success': True, 
                        'record_id': existing_record['id'], 
                        'aggregated': True, 
                        'total_defects': existing_record['defect_count']
                    })
                
                # Create new record
                record['product_name'] = product_name
                record['m_product_id'] = product_id
                record['m_warehouse_id'] = warehouse_id
                record['quantity'] = quantity
                record['defect_count'] = quantity  # Track defect count
                record['good_count'] = data.get('good_count', 0)  # Track good count
                record['defect_type'] = defect_type
                record['defect_details'] = data.get('defect_details', [])  # Store detailed defects list
                record['notes'] = notes
                
                # Get Goods Shipment info if provided (optional)
                if data.get('m_inout_id'):
                    cur.execute("SELECT documentno FROM m_inout WHERE m_inout_id = %s", (data.get('m_inout_id'),))
                    shipment = cur.fetchone()
                    record['shipment_no'] = shipment['documentno'] if shipment else None
                    record['m_inout_id'] = data.get('m_inout_id')
                
                record['result'] = f"Defect: {defect_type} x {quantity}"
                conn.close()
        
        elif detection_type == 'good_product':
            # Save good product detection (no defects found)
            conn = get_db_connection()
            if conn:
                cur = conn.cursor()
                product_id = data.get('m_product_id')
                good_count = data.get('good_count', 0)
                
                # Get product name
                product_name = 'Unknown Product'
                if product_id:
                    cur.execute("SELECT name FROM m_product WHERE m_product_id = %s", (product_id,))
                    prod = cur.fetchone()
                    product_name = prod['name'] if prod else 'Unknown'
                
                # Get today's date for aggregation
                today = datetime.now().strftime('%Y-%m-%d')
                
                # Check if there's an existing good_product record for same product + same date
                existing_record = None
                for r in ai_detection_history:
                    if (r.get('type') == 'good_product' and 
                        r.get('m_product_id') == product_id and
                        r.get('created', '').startswith(today)):
                        existing_record = r
                        break
                
                if existing_record:
                    # Update existing record - add to good count
                    existing_record['good_count'] = existing_record.get('good_count', 0) + good_count
                    existing_record['updated'] = datetime.now().isoformat()
                    existing_record['result'] = f"Good: {existing_record['good_count']} pcs"
                    save_ai_history()
                    conn.close()
                    return jsonify({
                        'success': True, 
                        'record_id': existing_record['id'], 
                        'aggregated': True, 
                        'total_good': existing_record['good_count']
                    })
                
                # Create new record
                record['product_name'] = product_name
                record['m_product_id'] = product_id
                record['m_warehouse_id'] = data.get('m_warehouse_id')
                record['good_count'] = good_count
                record['defect_count'] = 0
                record['quantity'] = 0
                record['notes'] = data.get('notes', f'Good: {good_count}')
                record['result'] = f"Good: {good_count} pcs"
                record['status'] = 'reviewed'  # Auto-approved since no defects
                conn.close()
                
        elif detection_type == 'box':
            # Box packaging check - Goods Shipment is optional
            record['result'] = data.get('result', 'verified')
            record['detected'] = data.get('detected', {})
            record['missing_items'] = data.get('missing_items', [])
            record['notes'] = data.get('notes', '')
            record['status'] = 'pending' if data.get('missing_items') else 'reviewed'
            
            # Get Goods Shipment info if provided (optional)
            if data.get('m_inout_id'):
                conn = get_db_connection()
                if conn:
                    cur = conn.cursor()
                    cur.execute("SELECT documentno FROM m_inout WHERE m_inout_id = %s", (data.get('m_inout_id'),))
                    shipment = cur.fetchone()
                    record['shipment_no'] = shipment['documentno'] if shipment else None
                    record['m_inout_id'] = data.get('m_inout_id')
                    conn.close()
                
        elif detection_type == 'accessory':
            record['notes'] = data.get('notes', '')
            record['result'] = data.get('result', '')
            record['missing'] = data.get('missing', [])
        
        # Save image data for defect records (limited to 500KB to avoid large file)
        if detection_type == 'defect' and data.get('image'):
            image_data = data.get('image', '')
            if len(image_data) < 500000:  # Only save if less than 500KB
                record['image'] = image_data
        
        ai_detection_history.insert(0, record)
        
        # Keep only last 500 records
        if len(ai_detection_history) > 500:
            ai_detection_history.pop()
        
        # Save to file
        save_ai_history()
        
        return jsonify({'success': True, 'record_id': record['id']})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/ai-detection-update/<record_id>', methods=['POST'])
def update_ai_detection(record_id):
    """Update/edit an AI detection record"""
    try:
        data = request.get_json()
        
        # Find the record
        record = None
        for r in ai_detection_history:
            if r['id'] == record_id:
                record = r
                break
        
        if not record:
            return jsonify({'success': False, 'error': 'Record not found'}), 404
        
        # Update fields
        if 'notes' in data:
            record['notes'] = data['notes']
        if 'status' in data:
            record['status'] = data['status']
        if 'result' in data:
            record['result'] = data['result']
        if 'missing_items' in data:
            record['missing_items'] = data['missing_items']
        if 'defect_count' in data:
            record['defect_count'] = data['defect_count']
            record['quantity'] = data['defect_count']
        if 'good_count' in data:
            record['good_count'] = data['good_count']
        if 'defect_type' in data:
            record['defect_type'] = data['defect_type']
        
        record['updated'] = datetime.now().isoformat()
        
        # Save to file
        save_ai_history()
        
        return jsonify({'success': True, 'record': record})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/ai-detection-delete/<record_id>', methods=['DELETE'])
def delete_ai_detection(record_id):
    """Delete an AI detection record"""
    try:
        global ai_detection_history
        
        # Find and remove the record
        original_len = len(ai_detection_history)
        ai_detection_history = [r for r in ai_detection_history if r['id'] != record_id]
        
        if len(ai_detection_history) == original_len:
            return jsonify({'success': False, 'error': 'Record not found'}), 404
        
        # Save to file
        save_ai_history()
        
        return jsonify({'success': True, 'message': 'Record deleted'})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/ai-detection-confirm/<record_id>', methods=['POST'])
def confirm_ai_detection(record_id):
    """Confirm defect detection - only update local record status (no Openbravo integration)"""
    try:
        # Find the record
        record = None
        for r in ai_detection_history:
            if r['id'] == record_id:
                record = r
                break
        
        if not record:
            return jsonify({'success': False, 'error': 'Record not found'}), 404
        
        if record['type'] != 'defect':
            return jsonify({'success': False, 'error': 'Only defect records can be confirmed'}), 400
        
        # Update record status - no database integration needed
        record['status'] = 'reviewed'
        record['reviewed_at'] = datetime.now().isoformat()
        record['inventory_updated'] = False  # Not connected to Openbravo
        save_ai_history()
        
        return jsonify({
            'success': True, 
            'message': 'Record confirmed successfully',
            'record_id': record_id
        })
            
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/ai-detection-approve/<record_id>', methods=['POST'])
def approve_ai_detection(record_id):
    """Approve detection record (for good_product and box types)"""
    try:
        # Find the record
        record = None
        for r in ai_detection_history:
            if r['id'] == record_id:
                record = r
                break
        
        if not record:
            return jsonify({'success': False, 'error': 'Record not found'}), 404
        
        # Get additional notes from request
        data = request.get_json() or {}
        additional_notes = data.get('notes', '')
        
        # Update record status
        record['status'] = 'reviewed'
        record['updated'] = datetime.now().isoformat()
        
        if additional_notes:
            record['notes'] = f"{record.get('notes', '')} | Approved: {additional_notes}".strip(' |')
        
        save_ai_history()
        
        return jsonify({
            'success': True,
            'message': f'{record["type"]} record approved successfully'
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/ai-detection-export')
def export_ai_detection():
    """Export AI detection history to Excel"""
    try:
        import pandas as pd
        from io import BytesIO
        
        if not ai_detection_history:
            return jsonify({'error': 'No detection history to export'}), 404
        
        df = pd.DataFrame(ai_detection_history)
        
        output = BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, sheet_name='AI Detection History', index=False)
        
        output.seek(0)
        filename = f'ai_detection_history_{datetime.now().strftime("%Y%m%d_%H%M%S")}.xlsx'
        
        return send_file(
            output, 
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True, 
            download_name=filename
        )
        
    except ImportError:
        return jsonify({'error': 'pandas and openpyxl required. Run: pip install pandas openpyxl'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/ai-detection-export-pdf')
def export_ai_detection_pdf():
    """Export AI detection history to PDF with FPT branding"""
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import mm, cm
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, HRFlowable
        from reportlab.lib.enums import TA_CENTER, TA_RIGHT, TA_LEFT
        
        if not ai_detection_history:
            return jsonify({'error': 'No history to export'}), 404
        
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=landscape(A4), 
                               rightMargin=15*mm, leftMargin=15*mm,
                               topMargin=15*mm, bottomMargin=15*mm)
        
        elements = []
        styles = getSampleStyleSheet()
        
        # FPT Colors
        FPT_ORANGE = '#F37021'
        FPT_ORANGE_DARK = '#E65100'
        FPT_BLUE = '#003399'
        
        # ==================== HEADER ====================
        brand_text = """
        <font size="22" color="#F37021"><b>FPT</b></font>
        <font size="14" color="#003399"><b> WAREHOUSE</b></font>
        """
        brand_para = Paragraph(brand_text, ParagraphStyle('Brand', alignment=TA_LEFT))
        
        title_style = ParagraphStyle('Title', fontSize=18, alignment=TA_CENTER, 
                                      textColor=colors.HexColor(FPT_ORANGE), fontName='Helvetica-Bold')
        title = Paragraph('AI DETECTION REPORT', title_style)
        
        date_style = ParagraphStyle('Date', fontSize=10, alignment=TA_RIGHT, textColor=colors.gray)
        date_text = Paragraph(f'Export Date: {datetime.now().strftime("%Y-%m-%d %H:%M")}', date_style)
        
        header_table = Table([[brand_para, title, date_text]], colWidths=[80*mm, 100*mm, 80*mm])
        header_table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (0, 0), 'LEFT'),
            ('ALIGN', (1, 0), (1, 0), 'CENTER'),
            ('ALIGN', (2, 0), (2, 0), 'RIGHT'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ]))
        elements.append(header_table)
        
        # Orange line separator
        elements.append(Spacer(1, 3*mm))
        elements.append(HRFlowable(width="100%", thickness=2, color=colors.HexColor(FPT_ORANGE)))
        elements.append(Spacer(1, 5*mm))
        
        # ==================== SUMMARY ====================
        total_records = len(ai_detection_history)
        defect_count = sum(1 for h in ai_detection_history if h.get('type') == 'defect')
        good_count = sum(1 for h in ai_detection_history if h.get('type') == 'good_product')
        box_count = sum(1 for h in ai_detection_history if h.get('type') == 'box')
        reviewed_count = sum(1 for h in ai_detection_history if h.get('status') == 'reviewed')
        pending_count = total_records - reviewed_count
        
        summary_style = ParagraphStyle('Summary', fontSize=10, textColor=colors.HexColor('#333333'))
        summary_data = [
            ['Total Records:', str(total_records), 'Defect Detection:', str(defect_count)],
            ['Approved:', str(reviewed_count), 'Good Product:', str(good_count)],
            ['Pending:', str(pending_count), 'Packaging Check:', str(box_count)],
        ]
        summary_table = Table(summary_data, colWidths=[40*mm, 25*mm, 45*mm, 25*mm])
        summary_table.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
            ('FONTNAME', (2, 0), (2, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('TEXTCOLOR', (0, 0), (0, -1), colors.HexColor(FPT_ORANGE_DARK)),
            ('TEXTCOLOR', (2, 0), (2, -1), colors.HexColor(FPT_ORANGE_DARK)),
            ('ALIGN', (1, 0), (1, -1), 'LEFT'),
            ('ALIGN', (3, 0), (3, -1), 'LEFT'),
        ]))
        elements.append(summary_table)
        elements.append(Spacer(1, 8*mm))
        
        # ==================== DETAIL TABLE ====================
        section_style = ParagraphStyle('Section', fontSize=12, textColor=colors.HexColor(FPT_ORANGE_DARK),
                                        fontName='Helvetica-Bold', spaceAfter=3*mm)
        elements.append(Paragraph('DETECTION HISTORY DETAILS', section_style))
        
        # Table header
        table_data = [['No.', 'Date/Time', 'Type', 'Product/Shipment', 'Result', 'Notes', 'Status']]
        
        for idx, h in enumerate(ai_detection_history[:50], 1):  # Limit 50 records
            type_text = 'Defect' if h.get('type') == 'defect' else 'Good Product' if h.get('type') == 'good_product' else 'Packaging' if h.get('type') == 'box' else h.get('type', '-')
            ref = h.get('product_name') or h.get('shipment_no') or h.get('order_no') or '-'
            result = h.get('result', '-')
            if h.get('missing_items'):
                result += f" (Missing: {', '.join(h.get('missing_items'))})"
            notes = h.get('notes', '-')[:30] + '...' if len(h.get('notes', '')) > 30 else h.get('notes', '-')
            status = 'Approved' if h.get('status') == 'reviewed' else 'Pending'
            created = datetime.fromisoformat(h.get('created', '')).strftime('%Y-%m-%d %H:%M') if h.get('created') else '-'
            
            table_data.append([str(idx), created, type_text, ref[:20], result[:25], notes, status])
        
        detail_table = Table(table_data, colWidths=[12*mm, 35*mm, 30*mm, 45*mm, 50*mm, 55*mm, 28*mm])
        detail_table.setStyle(TableStyle([
            # Header
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor(FPT_ORANGE)),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 9),
            ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
            
            # Body
            ('FONTSIZE', (0, 1), (-1, -1), 8),
            ('ALIGN', (0, 1), (0, -1), 'CENTER'),
            ('ALIGN', (6, 1), (6, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            
            # Alternating row colors
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#FFF5F0')]),
            
            # Grid
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#dddddd')),
            ('BOX', (0, 0), (-1, -1), 1, colors.HexColor(FPT_ORANGE)),
            
            # Padding
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ]))
        elements.append(detail_table)
        
        # ==================== FOOTER ====================
        elements.append(Spacer(1, 10*mm))
        elements.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor('#dddddd')))
        
        footer_style = ParagraphStyle('Footer', fontSize=8, alignment=TA_CENTER, textColor=colors.gray)
        footer_text = f'FPT University © 2024 - Warehouse Management System | Page 1'
        elements.append(Spacer(1, 3*mm))
        elements.append(Paragraph(footer_text, footer_style))
        
        # Build PDF
        doc.build(elements)
        buffer.seek(0)
        
        filename = f'AI_Detection_Report_{datetime.now().strftime("%Y%m%d_%H%M%S")}.pdf'
        
        return send_file(
            buffer,
            mimetype='application/pdf',
            as_attachment=True,
            download_name=filename
        )
        
    except ImportError as e:
        return jsonify({'error': f'reportlab required. Run: pip install reportlab'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ==================== ERROR HANDLERS ====================

@app.errorhandler(404)
def not_found(e):
    return jsonify({'error': 'Not found'}), 404


@app.errorhandler(500)
def server_error(e):
    return jsonify({'error': 'Internal server error'}), 500


def get_local_ip():
    """Lấy địa chỉ IP local"""
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return "127.0.0.1"
import threading

if __name__ == '__main__':
    local_ip = get_local_ip()
    
    print("=" * 60)
    print("   🚀 Openbravo Barcode Scanner App")
    print("=" * 60)
    print(f"   📦 Database: {DB_CONFIG['database']}@{DB_CONFIG['host']}:{DB_CONFIG['port']}")
    print()
    
    # Kiểm tra SSL certificate
    cert_file = os.path.join(os.path.dirname(__file__), 'cert.pem')
    key_file = os.path.join(os.path.dirname(__file__), 'key.pem')
    has_ssl = os.path.exists(cert_file) and os.path.exists(key_file)
    
    # Tự động generate SSL nếu chưa có
    if not has_ssl:
        print("   🔐 Auto-generating SSL certificate...")
        try:
            from OpenSSL import crypto
            
            # Generate key
            k = crypto.PKey()
            k.generate_key(crypto.TYPE_RSA, 2048)
            
            # Generate certificate
            cert = crypto.X509()
            cert.get_subject().C = "VN"
            cert.get_subject().ST = "Da Nang"
            cert.get_subject().L = "Da Nang"
            cert.get_subject().O = "FPT"
            cert.get_subject().OU = "Warehouse"
            cert.get_subject().CN = local_ip
            cert.set_serial_number(1000)
            cert.gmtime_adj_notBefore(0)
            cert.gmtime_adj_notAfter(365*24*60*60)
            cert.set_issuer(cert.get_subject())
            cert.set_pubkey(k)
            cert.sign(k, 'sha256')
            
            # Save files
            with open(cert_file, 'wb') as f:
                f.write(crypto.dump_certificate(crypto.FILETYPE_PEM, cert))
            with open(key_file, 'wb') as f:
                f.write(crypto.dump_privatekey(crypto.FILETYPE_PEM, k))
            
            has_ssl = True
            print("   ✅ SSL certificate generated successfully!")
        except ImportError:
            print("   ⚠️  pyOpenSSL not installed. Run: pip install pyOpenSSL")
            print("   ⚠️  Or manually run: python generate_ssl.py")
        except Exception as e:
            print(f"   ⚠️  Failed to generate SSL: {e}")
    
    print("   🌐 HTTP Server (Port 5000):")
    print(f"      💻 Local: http://localhost:5000")
    # print(f"      📱 Network: http://{local_ip}:5000")
    print()
    
    if has_ssl:
        # print("   🔒 HTTPS Server (Port 5443):")
        # print(f"      💻 Local: https://localhost:5443")
        # print(f"      📱 Network: https://{local_ip}:5443")
        print()
        print("   ⚠️  Lưu ý: Chấp nhận certificate khi trình duyệt cảnh báo")
        print("   📌 HTTPS cần thiết để dùng Camera trên thiết bị di động")
    else:
        print("   ⚠️  HTTPS không khả dụng (thiếu SSL certificate)")
        print("   📌 Để bật HTTPS + Camera, chạy: python generate_ssl.py")
    
    print()
    print("=" * 60)
    
    if has_ssl:
        # Chạy HTTPS server trên thread riêng
        def run_https():
            from werkzeug.serving import make_server
            import ssl
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ctx.load_cert_chain(cert_file, key_file)
            https_server = make_server('0.0.0.0', 5443, app, ssl_context=ctx, threaded=True)
            https_server.serve_forever()
        
        https_thread = threading.Thread(target=run_https, daemon=True)
        https_thread.start()
        print("   ✅ HTTPS server đang chạy trên port 5443")
    
    # Chạy HTTP server (main thread)
    print("   ✅ HTTP server đang chạy trên port 5000")
    print()
    
    # Hiển thị thông tin Cloudflare nếu có
    cf_config = load_cloudflare_config()
    if cf_config.get('enabled'):
        barcode_url = cf_config.get('barcode_app', {}).get('tunnel_url', '')
        openbravo_url = cf_config.get('openbravo', {}).get('tunnel_url', '')
        if barcode_url or openbravo_url:
            print("=" * 60)
            print("   ☁️  CLOUDFLARE TUNNELS (click nút Chia sẻ để xem QR)")
            print("=" * 60)
            if barcode_url:
                print(f"   📱 Barcode App: {barcode_url}")
            if openbravo_url:
                print(f"   📦 Openbravo:   {openbravo_url}/openbravo")
            print("=" * 60)
            print()
    
    # ==================== INITIALIZE CAMERAS ====================
    print()
    print("=" * 60)
    print("   📹 INITIALIZING RTSP CAMERAS")
    print("=" * 60)
    
    if camera_manager is not None:
        # Bắt đầu tất cả cameras
        start_all_cameras()
        
        # Chờ cameras khởi động và nhận frames
        print("   ⏳ Waiting for cameras to connect...", end='', flush=True)
        max_wait = 10  # Max 10 seconds
        for i in range(max_wait):
            time.sleep(0.5)
            camera_status = camera_manager.get_status()
            all_ready = all(
                status['is_running'] and status['has_frame'] 
                for status in camera_status.values()
            )
            if all_ready:
                print(" ✅ All cameras ready!")
                break
            print(".", end='', flush=True)
        else:
            print(" ⏱️ Timeout (showing status anyway)")
        
        print()
        
        # Hiển thị trạng thái cameras
        camera_status = camera_manager.get_status()
        for camera_id, status in camera_status.items():
            status_icon = "✅" if status['is_running'] and status['has_frame'] else "❌"
            print(f"   {status_icon} {status['name']}")
            if status['error']:
                print(f"      ⚠️  Error: {status['error']}")
        print("=" * 60)
        print()
    else:
        print("   ⚠️  OpenCV not available - Camera support disabled")
        print("=" * 60)
        print()
    
    app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)
