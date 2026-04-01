# 📦 Openbravo Barcode Scanner & Automation App

> **Ứng dụng bổ trợ tự động hóa cho Openbravo ERP** - Quản lý kho, mua hàng, bán hàng và phát hiện lỗi sản phẩm bằng AI.

---

## 📋 Mục lục

- [Giới thiệu](#-giới-thiệu)
- [Tính năng chính](#-tính-năng-chính)
- [Cài đặt và Cấu hình](#-cài-đặt-và-cấu-hình)
- [API Reference](#-api-reference)
- [Cấu trúc Database](#-cấu-trúc-database)
- [Bài tập thực hành cho sinh viên](#-bài-tập-thực-hành-cho-sinh-viên)
- [Troubleshooting](#-troubleshooting)

---

## 🎯 Giới thiệu

**Openbravo Barcode Scanner App** là ứng dụng web Flask tích hợp với **Openbravo ERP**:

- 📥 **Nhập kho (Goods Receipt)** từ Purchase Order
- 📤 **Xuất kho (Goods Shipment)** từ Sales Order
- 🔄 **Chuyển kho (Inventory Movement)**
- 🧾 **Tạo hóa đơn (Invoice)** tự động
- 💳 **Quản lý thanh toán (Payments)**
- 🤖 **Phát hiện lỗi sản phẩm** bằng AI (YOLO)

---

## ⭐ Tính năng chính

| Tính năng | Mô tả |
|-----------|-------|
| 📱 Quét Barcode | Camera scanning với zxing-cpp/pyzbar |
| 📥 Goods Receipt | Nhập kho từ PO, auto-complete |
| 📤 Goods Shipment | Xuất kho từ SO |
| 🔄 Movement | Chuyển kho giữa locators |
| 🧾 Invoice | Tạo invoice tự động |
| 🤖 AI Detection | YOLO defect detection |
| 🖨️ Print PDF | In phiếu các loại |

---

## 🔧 Cài đặt và Cấu hình

```bash
cd barcode_app
pip install -r requirements.txt

# Cấu hình database
$env:DB_HOST = "localhost"
$env:DB_NAME = "openbravo"
$env:DB_USER = "postgres"
$env:DB_PASSWORD = "postgres"

# Chạy
python app.py
```

**Truy cập:** http://localhost:5000 | https://localhost:5443

---

## 📚 API Reference

### Products & Barcode
| Method | Endpoint | Mô tả |
|--------|----------|-------|
| POST | `/api/scan-barcode` | Quét barcode |
| GET | `/api/product/barcode/<barcode>` | Tìm sản phẩm |
| GET | `/api/products` | Danh sách sản phẩm |

### Purchase & Receipt
| Method | Endpoint | Mô tả |
|--------|----------|-------|
| GET | `/api/purchase-orders` | Danh sách PO |
| POST | `/api/goods-receipt` | Tạo GR |
| POST | `/api/goods-receipt/<id>/complete` | Complete GR |

### Movement & Stock
| Method | Endpoint | Mô tả |
|--------|----------|-------|
| GET | `/api/warehouses` | Danh sách kho |
| POST | `/api/movement` | Tạo Movement |
| GET | `/api/stock` | Tồn kho |

---

## 🗄️ Cấu trúc Database

| Bảng | Mô tả |
|------|-------|
| `c_order` | Order (PO/SO) |
| `c_orderline` | Order Lines |
| `m_inout` | Goods Receipt/Shipment |
| `m_movement` | Inventory Movement |
| `m_product` | Products |
| `m_warehouse` | Warehouses |
| `m_storage_detail` | Stock Levels |

**DOCSTATUS:** `DR`=Draft, `CO`=Completed, `VO`=Voided

---

# 📝 BÀI TẬP THỰC HÀNH CHO SINH VIÊN

---

## 📌 PHẦN 1: CƠ BẢN - LÀM QUEN VỚI HỆ THỐNG

---

### **Bài tập 1.1: Cài đặt và khởi chạy ứng dụng**

**Mục tiêu:** Hiểu cách cài đặt và cấu hình ứng dụng Flask tích hợp với Openbravo

**Yêu cầu:**
1. Cài đặt Python virtual environment
2. Cài đặt các thư viện từ requirements.txt
3. Cấu hình kết nối database PostgreSQL
4. Khởi chạy ứng dụng và truy cập giao diện web

**Các bước thực hiện:**
```powershell
# Bước 1: Tạo virtual environment
cd c:\openbravo_installation\openbravo-release-24Q2\barcode_app
python -m venv venv
.\venv\Scripts\Activate.ps1

# Bước 2: Cài đặt dependencies
pip install -r requirements.txt

# Bước 3: Cấu hình database
$env:DB_HOST = "localhost"
$env:DB_PORT = "5432"
$env:DB_NAME = "openbravo"
$env:DB_USER = "postgres"
$env:DB_PASSWORD = "postgres"

# Bước 4: Chạy ứng dụng
python app.py
```

**Câu hỏi kiểm tra:**
1. Ứng dụng chạy trên port nào?
2. Tại sao cần HTTPS để sử dụng camera trên điện thoại?
3. Giải thích vai trò của Flask-CORS trong ứng dụng?

**Checklist hoàn thành:**
- [ ] Ứng dụng chạy thành công trên http://localhost:5000
- [ ] Hiểu được cấu trúc thư mục dự án
- [ ] Biết cách đọc logs khi có lỗi

---

### **Bài tập 1.2: Khám phá Database Openbravo**

**Mục tiêu:** Hiểu cấu trúc database ERP và mối quan hệ giữa các bảng

**Yêu cầu:** Sử dụng pgAdmin hoặc DBeaver thực hiện các query sau:

**Query 1: Liệt kê 5 Purchase Orders gần nhất**
```sql
SELECT c_order_id, documentno, dateordered, docstatus, grandtotal
FROM c_order
WHERE issotrx = 'N'
ORDER BY dateordered DESC
LIMIT 5;
```

**Query 2: Chi tiết một Purchase Order**
```sql
SELECT 
    o.documentno,
    p.value as product_code,
    p.name as product_name,
    ol.qtyordered,
    ol.qtydelivered,
    (ol.qtyordered - ol.qtydelivered) as qty_pending
FROM c_order o
JOIN c_orderline ol ON o.c_order_id = ol.c_order_id
JOIN m_product p ON ol.m_product_id = p.m_product_id
WHERE o.documentno = '<YOUR_PO_NUMBER>'
ORDER BY ol.line;
```

**Query 3: Kiểm tra tồn kho sản phẩm**
```sql
SELECT 
    p.value as product_code,
    p.name as product_name,
    w.name as warehouse,
    l.value as locator,
    sd.qtyonhand
FROM m_storage_detail sd
JOIN m_product p ON sd.m_product_id = p.m_product_id
JOIN m_locator l ON sd.m_locator_id = l.m_locator_id
JOIN m_warehouse w ON l.m_warehouse_id = w.m_warehouse_id
WHERE sd.qtyonhand > 0
LIMIT 20;
```

**Câu hỏi kiểm tra:**
1. Sự khác nhau giữa `issotrx = 'Y'` và `issotrx = 'N'`?
2. Khi nào `qtydelivered` được cập nhật?
3. Mối quan hệ giữa `m_warehouse` và `m_locator` là gì?

**Checklist hoàn thành:**
- [ ] Hiểu cấu trúc Order → OrderLine → Product
- [ ] Hiểu cách Openbravo quản lý tồn kho
- [ ] Biết phân biệt Purchase Order và Sales Order

---

### **Bài tập 1.3: Sử dụng API cơ bản**

**Mục tiêu:** Học cách gọi REST API và xử lý response

**Yêu cầu:** Sử dụng curl, Postman hoặc Python

**Test 1: Lấy danh sách sản phẩm**
```bash
curl http://localhost:5000/api/products?limit=10
```

**Test 2: Tìm sản phẩm theo barcode**
```bash
curl http://localhost:5000/api/product/barcode/1234567890123
```

**Test 3: Lấy danh sách Purchase Orders**
```bash
curl "http://localhost:5000/api/purchase-orders?docstatus=CO&limit=5"
```

**Test 4: Viết Python script**
```python
import requests

# Lấy danh sách warehouses
response = requests.get('http://localhost:5000/api/warehouses')
data = response.json()

if data['success']:
    for wh in data['warehouses']:
        print(f"Warehouse: {wh['name']} - {wh['locator_count']} locators")
else:
    print(f"Error: {data.get('error')}")
```

**Bài tập nâng cao:** Viết script Python để:
- Lấy tất cả PO có trạng thái 'CO'
- Với mỗi PO, lấy sản phẩm còn pending
- Xuất kết quả ra file CSV

**Checklist hoàn thành:**
- [ ] Biết sử dụng curl/Postman để test API
- [ ] Hiểu cấu trúc JSON response
- [ ] Viết được script tự động hóa

---

## 📌 PHẦN 2: TRUNG BÌNH - QUY TRÌNH NGHIỆP VỤ

---

### **Bài tập 2.1: Quy trình nhập kho hoàn chỉnh**

**Mục tiêu:** Thực hiện quy trình nhập hàng từ PO đến cập nhật kho

**Kịch bản:** Công ty nhận được lô hàng từ nhà cung cấp theo Purchase Order

**Bước 1: Tìm Purchase Order**
```python
import requests

response = requests.post(
    'http://localhost:5000/api/purchase-order/search-by-documentno',
    json={'documentno': 'PO-2024-001'}
)
po_data = response.json()
print(f"Found PO: {po_data}")
```

**Bước 2: Xem chi tiết PO**
```python
po_id = po_data['orders'][0]['c_order_id']
response = requests.get(f'http://localhost:5000/api/purchase-order/{po_id}')
detail = response.json()

print(f"PO: {detail['order']['documentno']}")
print(f"Supplier: {detail['order']['bpartner_name']}")
for line in detail['lines']:
    print(f"  - {line['product_name']}: Pending={line['qty_pending']}")
```

**Bước 3: Tạo Goods Receipt**
```python
gr_data = {
    'c_order_id': po_id,
    'lines': []
}

for line in detail['lines']:
    if float(line['qty_pending']) > 0:
        gr_data['lines'].append({
            'c_orderline_id': line['c_orderline_id'],
            'qty_received': float(line['qty_pending'])
        })

response = requests.post('http://localhost:5000/api/goods-receipt', json=gr_data)
gr_result = response.json()
print(f"Created GR: {gr_result}")
```

**Bước 4: Complete Goods Receipt**
```python
gr_id = gr_result['goods_receipt']['m_inout_id']
response = requests.post(f'http://localhost:5000/api/goods-receipt/{gr_id}/complete')
print(f"Complete result: {response.json()}")
```

**Bước 5: Kiểm tra tồn kho**
```sql
SELECT p.name, l.value as locator, sd.qtyonhand
FROM m_storage_detail sd
JOIN m_product p ON sd.m_product_id = p.m_product_id
JOIN m_locator l ON sd.m_locator_id = l.m_locator_id
WHERE p.m_product_id IN (
    SELECT m_product_id FROM m_inoutline WHERE m_inout_id = '<GR_ID>'
);
```

**Câu hỏi kiểm tra:**
1. Điều gì xảy ra với `qtydelivered` sau khi complete GR?
2. Bảng nào được cập nhật khi complete Goods Receipt?
3. M_Transaction được tạo với mục đích gì?

**Checklist hoàn thành:**
- [ ] Thực hiện được toàn bộ quy trình nhập kho
- [ ] Hiểu các bước và dữ liệu thay đổi
- [ ] Viết được script tự động hóa

---

### **Bài tập 2.2: Quy trình chuyển kho**

**Mục tiêu:** Di chuyển hàng hóa giữa các vị trí kho

**Kịch bản:** Chuyển 10 đơn vị sản phẩm từ Warehouse A sang Warehouse B

**Bước 1: Kiểm tra tồn kho nguồn**
```python
source_warehouse_id = 'YOUR_WAREHOUSE_ID'
response = requests.get(f'http://localhost:5000/api/warehouse/{source_warehouse_id}/products')
products = response.json()

for p in products['products']:
    print(f"{p['product_name']} - Qty: {p['qtyonhand']} @ {p['locator_code']}")
```

**Bước 2: Lấy thông tin locators đích**
```python
dest_warehouse_id = 'DEST_WAREHOUSE_ID'
response = requests.get(f'http://localhost:5000/api/warehouse/{dest_warehouse_id}/locators')
print(f"Available locators: {response.json()}")
```

**Bước 3: Tạo Movement**
```python
movement_data = {
    'ad_org_id': 'YOUR_ORG_ID',
    'm_warehouse_id': source_warehouse_id,
    'lines': [
        {
            'm_product_id': 'PRODUCT_ID',
            'm_locator_id': 'SOURCE_LOCATOR_ID',
            'm_locatorto_id': 'DEST_LOCATOR_ID',
            'movementqty': 10
        }
    ]
}

response = requests.post('http://localhost:5000/api/movement', json=movement_data)
print(f"Movement created: {response.json()}")
```

**Bước 4: Complete và kiểm tra**
```python
movement_id = result['movement']['m_movement_id']
response = requests.post(f'http://localhost:5000/api/movement/{movement_id}/complete')
print(f"Complete result: {response.json()}")

# Kiểm tra warehouse nguồn và đích
```

**Bài tập mở rộng:**
1. Viết script chuyển kho hàng loạt từ file Excel
2. Kiểm tra số lượng trước khi chuyển (không cho chuyển quá số tồn)

**Checklist hoàn thành:**
- [ ] Hiểu quy trình chuyển kho
- [ ] Biết cách xử lý nhiều locators
- [ ] Viết được validation logic

---

### **Bài tập 2.3: Sales Order và Xuất kho**

**Mục tiêu:** Thực hiện quy trình bán hàng từ đơn hàng đến giao hàng

**Bước 1: Lấy thông tin khách hàng**
```python
response = requests.get('http://localhost:5000/api/customers')
customers = response.json()
for c in customers['customers'][:5]:
    print(f"{c['name']} - {c['c_bpartner_id']}")
```

**Bước 2: Tạo Sales Order**
```python
so_data = {
    'ad_org_id': 'ORG_ID',
    'c_bpartner_id': 'CUSTOMER_ID',
    'c_bpartner_location_id': 'LOCATION_ID',
    'm_warehouse_id': 'WAREHOUSE_ID',
    'm_pricelist_id': 'PRICELIST_ID',
    'lines': [
        {'m_product_id': 'PRODUCT_ID', 'qty': 5, 'price': 100.00}
    ]
}

response = requests.post('http://localhost:5000/api/sale-order', json=so_data)
print(f"Created SO: {response.json()}")
```

**Bước 3: Tạo Goods Shipment**
```python
shipment_data = {
    'c_order_id': so_result['order']['c_order_id'],
    'lines': [
        {'c_orderline_id': 'ORDERLINE_ID', 'qty_shipped': 5}
    ]
}

response = requests.post('http://localhost:5000/api/goods-shipment', json=shipment_data)
print(f"Created Shipment: {response.json()}")
```

**Checklist hoàn thành:**
- [ ] Hiểu sự khác nhau giữa Purchase và Sales flow
- [ ] Biết cách tạo đơn hàng bán
- [ ] Thực hiện được xuất kho

---

## 📌 PHẦN 3: NÂNG CAO - TÍCH HỢP VÀ TỰ ĐỘNG HÓA

---

### **Bài tập 3.1: Quét Barcode và xử lý tự động**

**Mục tiêu:** Tích hợp camera quét barcode với quy trình nghiệp vụ

**Code JavaScript (client-side):**
```javascript
async function scanBarcode(imageBase64) {
    const response = await fetch('/api/scan-barcode', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ image: imageBase64 })
    });
    
    const result = await response.json();
    
    if (result.success && result.barcodes.length > 0) {
        const barcode = result.barcodes[0].data;
        console.log(`Detected: ${barcode}`);
        
        // Tìm PO chứa sản phẩm
        const poResponse = await fetch('/api/purchase-order/search-by-product', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ barcode: barcode })
        });
        
        const poResult = await poResponse.json();
        displayPurchaseOrders(poResult.purchase_orders);
    }
}
```

**Bài tập:** Tạo trang web với camera, khi quét barcode hiển thị thông tin sản phẩm và cho phép tạo Goods Receipt nhanh.

**Checklist hoàn thành:**
- [ ] Tích hợp được camera với ứng dụng
- [ ] Xử lý được barcode scanning
- [ ] Tạo flow nhập kho tự động

---

### **Bài tập 3.2: AI Detection - Phát hiện lỗi sản phẩm**

**Mục tiêu:** Sử dụng YOLO để phát hiện sản phẩm lỗi

**Bước 1: Chụp và gửi ảnh**
```python
import requests
import base64

with open('product_image.jpg', 'rb') as f:
    image_data = base64.b64encode(f.read()).decode('utf-8')

response = requests.post(
    'http://localhost:5000/api/ai-detect',
    json={
        'type': 'defect',
        'image': f'data:image/jpeg;base64,{image_data}'
    }
)

result = response.json()
print(f"Good: {result.get('complete_count', 0)}")
print(f"Defect: {result.get('defect_count', 0)}")
```

**Bước 2: Lưu kết quả**
```python
save_data = {
    'type': 'defect',
    'product_name': 'Cola Can',
    'm_product_id': 'PRODUCT_ID',
    'm_warehouse_id': 'WAREHOUSE_ID',
    'good_count': result.get('complete_count', 0),
    'defect_count': result.get('defect_count', 0)
}

response = requests.post('http://localhost:5000/api/ai-detection-save', json=save_data)
```

**Bài tập mở rộng:**
1. Tích hợp detection vào quy trình nhập kho
2. Tạo dashboard thống kê tỷ lệ lỗi

**Checklist hoàn thành:**
- [ ] Sử dụng được AI detection API
- [ ] Hiểu cách YOLO model hoạt động
- [ ] Tích hợp AI vào quy trình thực tế

---

### **Bài tập 3.3: Dashboard Monitoring**

**Mục tiêu:** Tạo dashboard theo dõi hoạt động kho

**Thu thập dữ liệu:**
```python
import requests
import pandas as pd

# Dashboard data
response = requests.get('http://localhost:5000/api/dashboard')
dashboard = response.json()

# Movements by date
response = requests.get('http://localhost:5000/api/movements/by-date')
movements = response.json()

df = pd.DataFrame(movements['dates'])
print(df.head())
```

**Tạo cảnh báo tồn kho thấp:**
```python
response = requests.get('http://localhost:5000/api/stock')
stock = response.json()

LOW_STOCK_THRESHOLD = 10
low_stock = [s for s in stock['stock'] if float(s['qty_available']) < LOW_STOCK_THRESHOLD]

if low_stock:
    print("⚠️ LOW STOCK ALERT:")
    for p in low_stock:
        print(f"  - {p['product_name']}: {p['qty_available']} units")
```

**Checklist hoàn thành:**
- [ ] Thu thập và xử lý dữ liệu từ API
- [ ] Tạo được visualizations
- [ ] Xây dựng hệ thống cảnh báo

---

### **Bài tập 3.4: Scheduled Jobs tự động**

**Mục tiêu:** Tạo tác vụ tự động chạy định kỳ

**Script kiểm tra PO pending:**
```python
# check_pending_orders.py
import requests
from datetime import datetime

def check_pending_orders():
    response = requests.get(
        'http://localhost:5000/api/purchase-orders',
        params={'docstatus': 'CO', 'pending_only': '1'}
    )
    orders = response.json()
    
    pending = [o for o in orders.get('orders', []) if float(o.get('pending_qty', 0)) > 0]
    
    if pending:
        print(f"📦 PENDING ORDERS REPORT - {datetime.now()}")
        for po in pending:
            print(f"• {po['documentno']} - {po['bpartner_name']}: {po['pending_qty']} pending")
    
    return pending

if __name__ == '__main__':
    check_pending_orders()
```

**Windows Task Scheduler batch:**
```batch
@echo off
cd /d c:\openbravo_installation\openbravo-release-24Q2\barcode_app
call venv\Scripts\activate.bat
python check_pending_orders.py >> logs\check_orders.log 2>&1
```

**Checklist hoàn thành:**
- [ ] Viết được scheduled scripts
- [ ] Hiểu cách tự động hóa tác vụ
- [ ] Tạo được hệ thống monitoring

---

## 📌 PHẦN 4: DỰ ÁN TỔNG HỢP

---

### **Dự án 4.1: Mobile Warehouse App**
**Thời gian:** 2-3 tuần | **Nhóm:** 2-3 SV

**Yêu cầu:**
- ✅ Đăng nhập với mã nhân viên
- ✅ Quét barcode bằng camera
- ✅ Xử lý Goods Receipt
- ✅ Chuyển kho nhanh
- ✅ Xem tồn kho
- ✅ Báo cáo cuối ca

**Công nghệ:** HTML5, Bootstrap, JavaScript, MediaDevices API

---

### **Dự án 4.2: Hệ thống QC với AI**
**Thời gian:** 3-4 tuần | **Nhóm:** 3-4 SV

**Yêu cầu:**
- ✅ Chụp ảnh sản phẩm
- ✅ Detect lỗi bằng YOLO
- ✅ Phân loại Good/Defect
- ✅ Lưu database
- ✅ Dashboard thống kê
- ✅ Export báo cáo
- ⭐ Train model mới (bonus)

**Công nghệ:** Ultralytics YOLO, OpenCV, Chart.js

---

### **Dự án 4.3: Microservices Architecture**
**Thời gian:** 3-4 tuần | **Nhóm:** 3-4 SV

**Yêu cầu:**
- ✅ Tách services: Product, Order, Inventory, AI
- ✅ API Gateway với JWT auth
- ✅ Message Queue
- ✅ Health checks
- ✅ Docker containerization

**Công nghệ:** Flask/FastAPI, JWT, Redis, Docker

---

## 📋 PHỤ LỤC

### A. Mẫu báo cáo
```markdown
# BÁO CÁO BÀI TẬP

**SV:** [Họ tên] - [MSSV] | **Lớp:** [Mã lớp] | **Ngày:** [DD/MM/YYYY]

## 1. Mục tiêu
## 2. Các bước thực hiện
## 3. Kết quả
## 4. Khó khăn và giải pháp
## 5. Kiến thức học được
```

### B. Thang điểm

| Tiêu chí | Điểm |
|----------|------|
| Cài đặt thành công | 10 |
| Hiểu database | 15 |
| Sử dụng API | 20 |
| Hoàn thành nghiệp vụ | 25 |
| Code clean | 10 |
| Documentation | 10 |
| Error handling | 10 |
| **Tổng** | **100** |

### C. Tài liệu tham khảo
- Flask: https://flask.palletsprojects.com/
- PostgreSQL: https://www.postgresqltutorial.com/
- Openbravo: https://wiki.openbravo.com/
- YOLO: https://docs.ultralytics.com/

---

## ❓ Troubleshooting

| Lỗi | Giải pháp |
|-----|-----------|
| Database connection | Kiểm tra PostgreSQL, chạy `python check_db.py` |
| Camera không hoạt động | Dùng HTTPS port 5443, chấp nhận certificate |
| SSL Certificate | Chạy `python generate_ssl.py` |

---

**Version:** 1.0.0 | **Updated:** 02/2026 | **Compatible:** Openbravo 24Q2