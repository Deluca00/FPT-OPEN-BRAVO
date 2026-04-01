# 📖 HƯỚNG DẪN SỬ DỤNG ỨNG DỤNG BARCODE SCANNER

## FPT University - Openbravo ERP Barcode Scanner Application

**Phiên bản:** 1.0  
**Cập nhật:** 03/02/2026

---

## 📋 MỤC LỤC

1. [Giới thiệu](#1-giới-thiệu)
2. [Yêu cầu hệ thống](#2-yêu-cầu-hệ-thống)
3. [Khởi động ứng dụng](#3-khởi-động-ứng-dụng)
4. [Giao diện chính](#4-giao-diện-chính)
5. [Tab Scanner - Quét mã vạch](#5-tab-scanner---quét-mã-vạch)
6. [Tab Purchase Orders - Đơn đặt hàng](#6-tab-purchase-orders---đơn-đặt-hàng)
7. [Tab Goods Receipts - Phiếu nhập kho](#7-tab-goods-receipts---phiếu-nhập-kho)
8. [Tab Warehouse - Quản lý kho](#8-tab-warehouse---quản-lý-kho)
9. [Tab Invoice Export - Đơn bán hàng](#9-tab-invoice-export---đơn-bán-hàng)
10. [Tab AI Detect - Phát hiện AI](#10-tab-ai-detect---phát-hiện-ai)
11. [Chia sẻ QR Code](#11-chia-sẻ-qr-code)
12. [Truy cập từ xa với Cloudflare](#12-truy-cập-từ-xa-với-cloudflare)
13. [Câu hỏi thường gặp](#13-câu-hỏi-thường-gặp)

---

## 1. Giới thiệu

### 1.1. Mục đích
Ứng dụng **Barcode Scanner** được phát triển để hỗ trợ quản lý kho hàng, xử lý đơn hàng và kiểm tra chất lượng sản phẩm, tích hợp trực tiếp với hệ thống **Openbravo ERP**.

### 1.2. Tính năng chính
- ✅ Quét mã vạch sản phẩm bằng camera hoặc nhập thủ công
- ✅ Quản lý đơn đặt hàng (Purchase Orders)
- ✅ Tạo và quản lý phiếu nhập kho (Goods Receipts)
- ✅ Quản lý kho hàng và chuyển kho (Warehouse Movement)
- ✅ Tạo đơn bán hàng và xuất kho (Sale Orders & Goods Shipments)
- ✅ Phát hiện sản phẩm lỗi và kiểm tra đóng gói bằng AI
- ✅ Truy cập từ xa qua Cloudflare Tunnel

---

## 2. Yêu cầu hệ thống

### 2.1. Phần cứng
- Máy tính hoặc điện thoại có kết nối mạng
- Camera (nếu sử dụng chức năng quét mã vạch)
- Màn hình tối thiểu 320px (responsive)

### 2.2. Phần mềm
- Trình duyệt web hiện đại: Chrome, Firefox, Edge, Safari
- Kết nối đến server Openbravo ERP
- Python 3.8+ (cho việc chạy server)

---

## 3. Khởi động ứng dụng

### 3.1. Khởi động thủ công
1. Mở thư mục `barcode_app`
2. Chạy file `start.bat` (Windows)
3. Truy cập: `http://localhost:5000` hoặc `https://localhost:5443`

### 3.2. Khởi động tự động với Windows
1. Chạy file `add_to_startup.bat` để thêm vào Windows Startup
2. Ứng dụng sẽ tự động chạy khi khởi động máy tính

### 3.3. Truy cập từ thiết bị di động
1. Kết nối cùng mạng WiFi với server
2. Truy cập qua IP máy chủ: `http://192.168.x.x:5000`
3. Hoặc quét mã QR trong phần **Share QR Code**

---

## 4. Giao diện chính

### 4.1. Thanh điều hướng (Navigation Bar)
Ứng dụng có 6 tab chính:

| Icon | Tab | Chức năng |
|------|-----|-----------|
| 📱 | **Scanner** | Quét mã vạch sản phẩm |
| 🛒 | **Purchase Orders** | Quản lý đơn đặt hàng |
| 📦 | **Goods Receipts** | Quản lý phiếu nhập kho |
| 🏢 | **Warehouse** | Quản lý kho và chuyển hàng |
| 🧾 | **Invoice Export** | Đơn bán hàng & xuất kho |
| 🤖 | **AI Detect** | Phát hiện lỗi bằng AI |

### 4.2. Thanh công cụ
- **Nút Home**: Quay về tab Scanner
- **Nút Share**: Chia sẻ QR Code để truy cập ứng dụng

---

## 5. Tab Scanner - Quét mã vạch

### 5.1. Mô tả
Tab chính để quét và tìm kiếm sản phẩm theo mã vạch (barcode). Hiển thị tổng quan các thống kê nhanh.

### 5.2. Thống kê nhanh
Phần đầu tab hiển thị 3 ô thống kê:
- **PO**: Số lượng Purchase Orders đang xử lý
- **GR**: Số lượng Goods Receipts đang xử lý
- **Scanned**: Số lượng sản phẩm đã quét trong phiên

### 5.3. Cách sử dụng

#### 5.3.1. Quét bằng camera
1. Nhấn nút **📷 Camera** màu xanh
2. Cho phép trình duyệt truy cập camera
3. Hướng camera vào mã vạch sản phẩm
4. Hệ thống tự động nhận dạng và tìm kiếm

#### 5.3.2. Nhập thủ công
1. Nhập mã vạch vào ô **"Enter or scan barcode..."**
2. Nhấn **Enter** hoặc click nút **🔍 Search**
3. Kết quả hiển thị bên dưới

### 5.4. Kết quả tìm kiếm
Khi tìm thấy sản phẩm, hệ thống hiển thị:
- Thông tin sản phẩm
- Các Purchase Orders liên quan
- Cho phép chọn PO để xử lý

### 5.5. Chi tiết Purchase Order (PO Details)
Khi chọn một PO, màn hình hiển thị:

| Cột | Mô tả |
|-----|-------|
| **#** | Số thứ tự |
| **Sản phẩm** | Tên sản phẩm |
| **Barcode** | Mã vạch |
| **Đặt** | Số lượng đặt hàng |
| **Đã nhận** | Số lượng đã nhận |
| **Còn** | Số lượng còn lại cần nhận |
| **Nhập** | Ô nhập số lượng nhận lần này |
| **Chọn** | Checkbox chọn sản phẩm |

### 5.6. Các thao tác trên PO Details
- **Đóng**: Đóng panel chi tiết PO
- **In PDF**: Xuất Purchase Order ra file PDF
- **QR Code**: Hiển thị mã QR của PO
- **Tạo Goods Receipt**: Tạo phiếu nhập kho từ các sản phẩm đã chọn

### 5.7. Quy trình tạo Goods Receipt từ Scanner
1. Quét barcode sản phẩm → Chọn Purchase Order
2. Nhập số lượng nhận vào cột **"Nhập"**
3. Tick checkbox ở cột **"Chọn"** cho các sản phẩm cần nhập
4. Chọn **Warehouse** (kho nhập)
5. Click **"Tạo Goods Receipt"**
6. Xác nhận tạo → Hệ thống tự động tạo GR trong Openbravo

---

## 6. Tab Purchase Orders - Đơn đặt hàng

### 6.1. Mô tả
Quản lý toàn bộ đơn đặt hàng từ nhà cung cấp (Purchase Orders) trong hệ thống Openbravo.

### 6.2. Giao diện chính
- **Tiêu đề**: "Purchase Orders" với nút Filter và Refresh
- **Bảng lọc**: Ẩn/hiện khi click nút Filter
- **Danh sách PO**: Hiển thị các PO theo filter

### 6.3. Bộ lọc (Filter Panel)

| Bộ lọc | Mô tả |
|--------|-------|
| **Search** | Tìm theo Document No, Supplier |
| **Status** | Lọc theo trạng thái: All, Completed (CO), Draft (DR), Voided (VO) |
| **Supplier** | Lọc theo nhà cung cấp |
| **From Date** | Ngày bắt đầu |
| **To Date** | Ngày kết thúc |
| **Pending Items Only** | Chỉ hiện PO còn hàng chưa nhận |

### 6.4. Các thao tác
- **Toggle Filter**: Ẩn/hiện bảng lọc
- **Refresh**: Tải lại danh sách PO
- **Clear**: Xóa tất cả bộ lọc
- **Apply Filters**: Áp dụng bộ lọc

### 6.5. Chi tiết từng PO
Click vào một PO trong danh sách để xem:
- Thông tin chi tiết đơn hàng
- Danh sách sản phẩm
- Trạng thái nhận hàng
- Tùy chọn tạo Goods Receipt

---

## 7. Tab Goods Receipts - Phiếu nhập kho

### 7.1. Mô tả
Quản lý các phiếu nhập kho (Goods Receipts) đã được tạo từ Purchase Orders.

### 7.2. Bộ lọc

| Bộ lọc | Mô tả |
|--------|-------|
| **Search** | Tìm theo Doc No, Supplier, PO |
| **Status** | Draft (DR) hoặc Completed (CO) |
| **Supplier** | Lọc theo nhà cung cấp |
| **Warehouse** | Lọc theo kho |
| **From/To Date** | Khoảng thời gian |
| **PO Number** | Số Purchase Order liên quan |
| **Pending Only** | Chỉ hiện GR chưa complete |

### 7.3. Thông tin hiển thị cho mỗi GR
- **Document Number**: Số chứng từ
- **Date**: Ngày tạo
- **Supplier**: Nhà cung cấp
- **Warehouse**: Kho nhập
- **Status**: Trạng thái (Draft/Completed)
- **Related PO**: Purchase Order liên quan

### 7.4. Các thao tác
- **Xem chi tiết**: Click vào GR để xem danh sách sản phẩm
- **In PDF**: Xuất phiếu nhập kho ra PDF
- **Complete**: Hoàn thành phiếu nhập (chuyển từ Draft sang Completed)

---

## 8. Tab Warehouse - Quản lý kho

### 8.1. Mô tả
Quản lý tồn kho theo từng tổ chức, kho, và thực hiện chuyển kho giữa các vị trí.

### 8.2. Cấu trúc phân cấp
```
Organizations (Tổ chức)
└── Warehouses (Kho)
    └── Locators (Vị trí trong kho)
        └── Products (Sản phẩm)
```

### 8.3. Giao diện Organization List
Màn hình mặc định hiển thị danh sách các tổ chức dưới dạng cards:
- Tên tổ chức
- Số lượng kho trong tổ chức
- Click để mở danh sách kho

### 8.4. Giao diện Warehouse Detail
Khi chọn một kho, hiển thị chi tiết:

| Cột | Mô tả |
|-----|-------|
| **Code** | Mã sản phẩm |
| **Product Name** | Tên sản phẩm |
| **Barcode** | Mã vạch |
| **Location** | Vị trí trong kho |
| **Quantity** | Số lượng tồn |
| **UOM** | Đơn vị tính |
| **Actions** | Xem lịch sử chuyển kho |

### 8.5. Bộ lọc trong Warehouse Detail

| Bộ lọc | Mô tả |
|--------|-------|
| **Search** | Tìm theo code, name, barcode |
| **Location** | Lọc theo vị trí |
| **Stock** | In Stock (>0), Low Stock (<10), Out of Stock (=0) |
| **Sort By** | Sắp xếp theo Name, Qty, Code |

### 8.6. Chuyển kho (Transfer Stock)

#### Bước 1: Mở form chuyển kho
- Click nút **"Transfer Stock"** màu tím

#### Bước 2: Điền thông tin
| Trường | Mô tả |
|--------|-------|
| **Source Warehouse** | Kho nguồn |
| **Source Locator** | Vị trí nguồn |
| **Destination Warehouse** | Kho đích |
| **Destination Locator** | Vị trí đích |
| **Product** | Sản phẩm cần chuyển |
| **Quantity** | Số lượng chuyển |
| **Notes** | Ghi chú (tùy chọn) |

#### Bước 3: Xác nhận
- Click **"Create Movement"** để tạo phiếu chuyển kho
- Hệ thống sẽ tạo Goods Movement trong Openbravo

### 8.7. Lịch sử chuyển kho
- Click icon 📜 ở cột Actions để xem lịch sử chuyển kho của sản phẩm
- Hiển thị: Chứng từ, Ngày, Từ kho, Đến kho, Số lượng, Trạng thái

### 8.8. Breadcrumb Navigation
- Sử dụng breadcrumb để điều hướng giữa các cấp
- Click **"Locations"** để quay về danh sách tổ chức

---

## 9. Tab Invoice Export - Đơn bán hàng

### 9.1. Mô tả
Quản lý đơn bán hàng (Sale Orders) và phiếu xuất kho (Goods Shipments) cho quy trình bán hàng.

### 9.2. Bố cục giao diện
Màn hình chia làm 2 cột:
- **Cột trái**: Sale Orders (Đơn bán hàng)
- **Cột phải**: Goods Shipments (Phiếu xuất kho)

### 9.3. Sale Orders

#### 9.3.1. Bộ lọc
| Bộ lọc | Mô tả |
|--------|-------|
| **Status Filter** | All, Completed (CO), Draft (DR) |
| **From Date** | Ngày bắt đầu |
| **To Date** | Ngày kết thúc |

#### 9.3.2. Tạo Sale Order mới
1. Click nút **"Create Sale Order"**
2. Điền thông tin:
   - **Customer**: Chọn khách hàng
   - **Warehouse**: Chọn kho xuất
   - **Products**: Thêm sản phẩm và số lượng
3. Click **"Submit"** để tạo đơn

### 9.4. Goods Shipments

#### 9.4.1. Tạo Goods Shipment từ Sale Order
1. Click vào một Sale Order trong danh sách bên trái
2. Chọn sản phẩm cần xuất
3. Click **"Create Goods Shipment"**
4. Xác nhận để tạo phiếu xuất kho

#### 9.4.2. Bộ lọc
| Bộ lọc | Mô tả |
|--------|-------|
| **Status Filter** | All, Completed (CO), Draft (DR) |
| **From Date** | Ngày bắt đầu |
| **To Date** | Ngày kết thúc |

### 9.5. Xuất dữ liệu

| Nút | Chức năng |
|-----|-----------|
| **Export Excel** | Xuất toàn bộ SO và GS ra file Excel |
| **Export CSV** | Xuất ra file CSV |

### 9.6. In PDF
- Click icon 🖨️ trên từng Sale Order hoặc Goods Shipment
- Hệ thống sẽ tạo file PDF để in

### 9.7. Quy trình làm việc hoàn chỉnh
```
1. Tạo Sale Order → Chọn khách hàng, kho, sản phẩm → Submit
2. Tạo Goods Shipment → Click vào SO → Chọn sản phẩm → Create Goods Shipment
3. In PDF → Click nút 🖨️ để in chứng từ
4. Export → Xuất dữ liệu Excel/CSV để báo cáo
```

---

## 10. Tab AI Detect - Phát hiện AI

### 10.1. Mô tả
Sử dụng trí tuệ nhân tạo (AI) để phát hiện sản phẩm lỗi và kiểm tra đóng gói hàng hóa.

### 10.2. Hai chế độ phát hiện

| Chế độ | Mục đích | Màu |
|--------|----------|-----|
| **Product Defect Detection** | Phát hiện sản phẩm bị lỗi/hư hỏng | 🔴 Đỏ |
| **Box Packaging Verification** | Kiểm tra đóng gói: Hộp + Băng keo + Hóa đơn | 🟢 Xanh |

### 10.3. Product Defect Detection

#### 10.3.1. Cách sử dụng
1. **Chụp ảnh**: Click **"Use Camera"** để mở camera
2. **Tải ảnh**: Click **"Upload Image"** để chọn file ảnh
3. Hệ thống AI sẽ phân tích và hiển thị kết quả

#### 10.3.2. Điền thông tin sản phẩm lỗi
| Trường | Mô tả |
|--------|-------|
| **Product** | Chọn sản phẩm bị lỗi |
| **Defect Type** | Loại lỗi: Dented/Damaged, Missing Parts, Quality Issue, Packaging Damaged |
| **Quantity** | Số lượng sản phẩm lỗi |
| **Warehouse** | Kho chứa sản phẩm |
| **Goods Shipment** | Liên kết với phiếu xuất kho (tùy chọn) |
| **Notes** | Ghi chú thêm |

#### 10.3.3. Lưu kết quả
- Click **"Save Defect & Update Inventory"**
- Hệ thống sẽ:
  - Lưu record phát hiện lỗi
  - Cập nhật số lượng tồn kho
  - Ghi nhận ảnh minh chứng

### 10.4. Box Packaging Verification

#### 10.4.1. Mục đích
Kiểm tra xem gói hàng có đầy đủ 3 thành phần:
- ✅ **Box**: Hộp carton
- ✅ **Tape**: Băng keo dán
- ✅ **Receipt**: Hóa đơn/phiếu giao hàng

#### 10.4.2. Cách sử dụng
1. Click **"Use Camera"** hoặc **"Upload Image"**
2. AI sẽ phân tích và đánh giá từng thành phần
3. Mỗi thành phần hiển thị trạng thái:
   - 🟢 **Detected**: Phát hiện có
   - 🔴 **Not Found**: Không tìm thấy
   - ⚪ **Pending**: Chưa kiểm tra

#### 10.4.3. Kết quả kiểm tra
- **PASS**: Đủ cả 3 thành phần ✅
- **FAIL**: Thiếu một hoặc nhiều thành phần ❌

#### 10.4.4. Liên kết với Goods Shipment
- Chọn Goods Shipment từ dropdown
- Click **"Save Packaging Check"** để lưu kết quả

### 10.5. Bảng lịch sử

#### 10.5.1. Product Detection History
| Cột | Mô tả |
|-----|-------|
| **Date** | Ngày phát hiện |
| **Type** | Loại: Defect/Good |
| **Product** | Tên sản phẩm |
| **Qty** | Số lượng |
| **Status** | Trạng thái xử lý |
| **Actions** | Xem chi tiết, Chỉnh sửa |

#### 10.5.2. Packaging Check History
| Cột | Mô tả |
|-----|-------|
| **Date** | Ngày kiểm tra |
| **Shipment** | Mã phiếu xuất kho |
| **Result** | PASS/FAIL |
| **Status** | Trạng thái |
| **Actions** | Xem chi tiết |

### 10.6. Xuất báo cáo
| Nút | Chức năng |
|-----|-----------|
| **Refresh** | Làm mới dữ liệu |
| **Excel** | Xuất ra file Excel |
| **PDF** | Xuất ra file PDF |

---

## 11. Chia sẻ QR Code

### 11.1. Truy cập
- Click icon **Share** (📤) trên thanh navigation

### 11.2. Hai loại QR Code

| QR Code | Mô tả |
|---------|-------|
| **Barcode App** | Truy cập ứng dụng Barcode Scanner |
| **Openbravo ERP** | Truy cập hệ thống Openbravo ERP |

### 11.3. Sử dụng QR Code
1. Mở app quét QR trên điện thoại
2. Quét mã QR tương ứng
3. Truy cập ngay vào ứng dụng

### 11.4. Lưu ý
- **Mạng LAN**: Chỉ truy cập được khi cùng mạng WiFi
- **Cloudflare**: Truy cập được từ bất kỳ đâu qua internet

---

## 12. Truy cập từ xa với Cloudflare

### 12.1. Mô tả
Cloudflare Tunnel cho phép truy cập ứng dụng từ bất kỳ đâu trên internet, không cần cùng mạng LAN.

### 12.2. Khởi động Cloudflare Tunnels
1. Chạy file `cloudflare_tunnels.py` hoặc `start_cloudflare_tunnels.bat`
2. Hệ thống tự động tạo 2 tunnel:
   - Tunnel cho Barcode App (port 5443)
   - Tunnel cho Openbravo (port 8443)
3. URL được lưu vào `cloudflare_config.json`

### 12.3. Xem URL Cloudflare
- Mở Share QR Code modal
- URL Cloudflare hiển thị dưới mỗi QR Code
- Ví dụ: `https://xxx-xxx-xxx.trycloudflare.com`

### 12.4. Tự động khởi động
- Chạy `add_to_startup.bat` để thêm vào Windows Startup
- Khi khởi động máy, cả app và Cloudflare tunnels sẽ tự chạy

---

## 13. Câu hỏi thường gặp

### Q1: Không quét được barcode bằng camera?
**A:** Kiểm tra:
- Đã cho phép trình duyệt truy cập camera chưa?
- Camera có bị che hoặc thiếu sáng không?
- Thử sử dụng HTTPS thay vì HTTP

### Q2: Không tạo được Goods Receipt?
**A:** Kiểm tra:
- Đã chọn Warehouse chưa?
- Đã tick chọn ít nhất 1 sản phẩm chưa?
- Số lượng nhập có hợp lệ không?

### Q3: Không kết nối được Openbravo?
**A:** Kiểm tra:
- Server Openbravo đang chạy không?
- Thông tin kết nối trong `Openbravo.properties` đúng chưa?
- PostgreSQL database đang hoạt động không?

### Q4: Cloudflare tunnel không hoạt động?
**A:** Kiểm tra:
- Đã cài đặt `cloudflared` chưa?
- Chạy `cloudflare_tunnels.py` có lỗi gì không?
- Kiểm tra file `cloudflare_config.json`

### Q5: AI không phát hiện được?
**A:** Kiểm tra:
- Model AI đã được cài đặt trong thư mục `ModelAI/`?
- Ảnh chụp có đủ sáng và rõ nét không?
- File model `.pt` có bị lỗi không?

### Q6: Làm sao để dừng ứng dụng?
**A:** 
- Đóng cửa sổ terminal đang chạy `app.py`
- Hoặc sử dụng Task Manager để tắt process Python

### Q7: Làm sao xóa khỏi Windows Startup?
**A:** Chạy file `remove_from_startup.bat`

---

## 📞 Hỗ trợ kỹ thuật

**Email:** support@fpt.edu.vn  
**Hotline:** 1900-xxxx  
**Tài liệu online:** https://docs.openbravo.com

---

## 📝 Lịch sử cập nhật

| Phiên bản | Ngày | Thay đổi |
|-----------|------|----------|
| 1.0 | 03/02/2026 | Phiên bản đầu tiên |

---

**© 2026 FPT University. All rights reserved.**
