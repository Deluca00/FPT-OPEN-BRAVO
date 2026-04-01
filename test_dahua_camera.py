"""
Test Dahua Camera RTSP Connection
Công cụ để test và debug camera IP Dahua
"""

import cv2
import threading
import time
from datetime import datetime
import sys


class DahuaRTSPTester:
    """Test Dahua Camera RTSP Connection"""
    
    def __init__(self, rtsp_url, username='admin', password='admin'):
        """
        RTSP URL format:
        - rtsp://username:password@camera_ip:554/cam/realmonitor?channel=1&subtype=0
        - rtsp://ip:554/stream1
        - rtsp://ip:8554/cam/realmonitor?channel=1
        """
        self.rtsp_url = rtsp_url
        self.username = username
        self.password = password
        self.cap = None
        self.is_connected = False
        self.frame_count = 0
        
    def test_connection(self, timeout=10):
        """Test kết nối RTSP"""
        print(f"🔗 Đang test RTSP: {self.rtsp_url}")
        print(f"   Timeout: {timeout}s")
        print("   Đang kết nối", end='', flush=True)
        
        try:
            self.cap = cv2.VideoCapture(self.rtsp_url)
            self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # Giảm delay
            # cv2.CAP_PROP_RECONNECT không tồn tại trong OpenCV cũ
            # Thay vào đó dùng timeout
            try:
                self.cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, timeout * 1000)
                self.cap.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, 5000)
            except:
                pass
            
            # Thử đọc frame với retry và progress indicator
            ret = False
            frame = None
            start_time = time.time()
            
            while time.time() - start_time < timeout:
                ret, frame = self.cap.read()
                if ret and frame is not None:
                    print()  # New line
                    break
                print('.', end='', flush=True)
                time.sleep(0.5)
            
            
            if ret and frame is not None:
                self.is_connected = True
                print(f"✅ Kết nối thành công!")
                print(f"   Frame size: {frame.shape}")
                print(f"   FPS: {self.cap.get(cv2.CAP_PROP_FPS):.2f}")
                print(f"   Frame Width: {frame.shape[1]}, Height: {frame.shape[0]}")
                return True
            else:
                elapsed = time.time() - start_time
                print()
                if elapsed >= timeout:
                    print(f"⏱️  TIMEOUT ({elapsed:.1f}s) - Camera không phản hồi")
                    print("   💡 Thử:")
                    print("      - Kiểm tra IP/port: ping 172.16.251.100")
                    print("      - Thử port khác (8554)")
                    print("      - Kiểm tra username/password")
                else:
                    print(f"❌ Không thể đọc frame từ stream")
                return False
                
        except Exception as e:
            print()
            print(f"❌ Lỗi kết nối: {e}")
            return False
        finally:
            if self.cap:
                self.cap.release()
    
    def stream_frames(self, duration=10, save_frame=False, display=True):
        """Stream frames trong thời gian nhất định"""
        print(f"\n📹 Streaming trong {duration}s...")
        
        try:
            self.cap = cv2.VideoCapture(self.rtsp_url)
            self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            # Thêm timeouts cho RTSP
            try:
                self.cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 10000)
                self.cap.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, 5000)
            except:
                pass  # OpenCV cũ không support timeout properties
            
            start_time = time.time()
            fps_start = time.time()
            fps_count = 0
            
            while time.time() - start_time < duration:
                ret, frame = self.cap.read()
                
                if ret and frame is not None:
                    self.frame_count += 1
                    fps_count += 1
                    
                    # Calculate FPS
                    elapsed = time.time() - fps_start
                    if elapsed > 1.0:
                        fps = fps_count / elapsed
                        fps_start = time.time()
                        fps_count = 0
                    else:
                        fps = 0
                    
                    # Add timestamp và info
                    cv2.putText(frame, datetime.now().strftime('%Y-%m-%d %H:%M:%S'), 
                              (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
                    cv2.putText(frame, f'Frame: {self.frame_count} | FPS: {fps:.1f}', 
                              (10, 70), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
                    cv2.putText(frame, f'Resolution: {frame.shape[1]}x{frame.shape[0]}', 
                              (10, 110), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
                    
                    # Display nếu có GUI
                    if display:
                        cv2.imshow('Dahua RTSP Stream (Nhấn Q để thoát)', frame)
                    
                    # Save first frame
                    if save_frame and self.frame_count == 1:
                        cv2.imwrite('dahua_test_frame.jpg', frame)
                        print(f"   💾 Frame đã lưu: dahua_test_frame.jpg")
                    
                    # Press 'q' để thoát
                    if display and cv2.waitKey(1) & 0xFF == ord('q'):
                        print("   ⏹️  Dừng stream (người dùng nhấn Q)")
                        break
                else:
                    print(f"⚠️  Lỗi đọc frame")
                    time.sleep(0.5)
                    
            elapsed = time.time() - start_time
            print(f"✅ Stream dừng sau {elapsed:.1f}s")
            print(f"   Tổng frames: {self.frame_count}")
            if self.frame_count > 0:
                print(f"   Trung bình FPS: {self.frame_count / elapsed:.2f}")
            return self.frame_count > 0
            
        except Exception as e:
            print(f"❌ Lỗi streaming: {e}")
            import traceback
            traceback.print_exc()
            return False
        finally:
            if self.cap:
                self.cap.release()
            if cv2.getWindowProperty('Dahua RTSP Stream (Nhấn Q để thoát)', cv2.WND_PROP_VISIBLE) >= 0:
                cv2.destroyAllWindows()
    def test_multiple_urls(self, urls_list, timeout=5):
        """Test nhiều RTSP URLs"""
        print("\n🔍 Test nhiều URLs:")
        print("=" * 60)
        
        for url in urls_list:
            print(f"\n📍 Testing: {url}")
            print("-" * 60)
            
            try:
                cap = cv2.VideoCapture(url)
                cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                try:
                    cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, timeout * 1000)
                    cap.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, 2000)
                except:
                    pass
                
                start = time.time()
                connected = False
                
                while time.time() - start < timeout:
                    ret, frame = cap.read()
                    if ret and frame is not None:
                        connected = True
                        print(f"   ✅ THÀNH CÔNG - {frame.shape[0]}x{frame.shape[1]}")
                        break
                    time.sleep(0.2)
                
                if not connected:
                    print(f"   ❌ THẤT BẠI - Timeout")
                
                cap.release()
                
            except Exception as e:
                print(f"   ❌ LỖI: {str(e)[:100]}")


def print_help():
    """Hướng dẫn sử dụng"""
    help_text = """
╔════════════════════════════════════════════════════════════╗
║         DAHUA CAMERA RTSP TEST TOOL                        ║
╚════════════════════════════════════════════════════════════╝

📌 CÁCH SỬ DỤNG:

1️⃣  TEST KẾT NỐI ĐƠN GIẢN:
   python test_dahua_camera.py <RTSP_URL>
   
   Ví dụ:
   python test_dahua_camera.py "rtsp://admin:admin@172.16.251.100:554/cam/realmonitor?channel=1&subtype=0"

2️⃣  TEST VỚI STREAM:
   python test_dahua_camera.py <RTSP_URL> --stream --duration 15
   
   Tuỳ chọn:
   --duration N    : Stream trong N giây (mặc định 10)
   --save-frame    : Lưu frame đầu tiên

3️⃣  TEST NHIỀU URLs:
   python test_dahua_camera.py --test-multiple

4️⃣  DEBUG NETWORK:
   python test_dahua_camera.py --debug <IP_CAMERA>

═════════════════════════════════════════════════════════════

🔗 RTSP URLs PHỔ BIẾN DAHUA:

✓ Với authentication:
  rtsp://admin:password@172.16.251.100:554/cam/realmonitor?channel=1&subtype=0

✓ Không authentication:
  rtsp://172.16.251.100:554/stream1

✓ Port 8554:
  rtsp://admin:password@172.16.251.100:8554/cam/realmonitor?channel=1

✓ Preview stream:
  rtsp://admin:password@172.16.251.100:554/cam/realmonitor?channel=1&subtype=1

═════════════════════════════════════════════════════════════

🎯 THÔNG TIN CAMERA MẶC ĐỊNH:
   IP:       172.16.251.100
   Port:     554 (hoặc 8554)
   Username: admin
   Password: admin

═════════════════════════════════════════════════════════════

💡 TROUBLESHOOTING:

❌ "module 'cv2' has no attribute 'CAP_PROP_RECONNECT'"
   → Đã fix! Update file latest version

❌ "Failed to open stream"
   → Kiểm tra ping: ping 172.16.251.100
   → Kiểm tra port: telnet 172.16.251.100 554
   → Kiểm tra username/password
   → Check URL format: rtsp://user:pass@ip:port/path

❌ "Cannot read frame" / "Timeout"
   → Camera không cho phép stream RTSP
   → Firewall chặn port 554
   → Thử port 8554 hoặc khác
   → Kiểm tra RTSP enable trong camera settings

❌ "Connection refused"
   → Camera không phản hồi
   → Port sai
   → RTSP service chưa start
   → Thử reboot camera

═════════════════════════════════════════════════════════════

🔧 CÁCH DEBUG:

1. Nếu ping OK nhưng RTSP lỗi:
   python test_dahua_camera.py --test-multiple
   
   Caching sẽ test các URL format phổ biến

2. Check cổng mở:
   Windows: netstat -an | findstr :554
   Linux:   netstat -tuln | grep 554

3. Thử FFmpeg (nếu cài):
   ffplay -rtsp_transport tcp rtsp://admin:admin@172.16.251.100:554/cam/realmonitor?channel=1

═════════════════════════════════════════════════════════════
"""
    print(help_text)


# ============ MAIN ============

if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='Dahua Camera RTSP Tester', add_help=False)
    parser.add_argument('url', nargs='?', help='RTSP URL')
    parser.add_argument('--stream', action='store_true', help='Stream frames')
    parser.add_argument('--duration', type=int, default=10, help='Duration in seconds (default: 10)')
    parser.add_argument('--save-frame', action='store_true', help='Save first frame')
    parser.add_argument('--test-multiple', action='store_true', help='Test multiple URLs')
    parser.add_argument('--timeout', type=int, default=10, help='Connection timeout in seconds (default: 10)')
    parser.add_argument('-h', '--help', action='store_true', help='Show help')
    
    args = parser.parse_args()
    
    if args.help:
        print_help()
        sys.exit(0)
    
    if args.test_multiple:
        # Test các URLs phổ biến
        urls = [
            "rtsp://admin:admin@172.16.251.100:554/cam/realmonitor?channel=1&subtype=0",
            "rtsp://admin:admin@172.16.251.100:554/stream1",
            "rtsp://172.16.251.100:554/cam/realmonitor?channel=1&subtype=0",
            "rtsp://admin:admin@172.16.251.100:8554/cam/realmonitor?channel=1",
            "rtsp://127.0.0.1:554/cam/realmonitor?channel=1",
        ]
        
        tester = DahuaRTSPTester("")
        tester.test_multiple_urls(urls)
        
    elif args.url:
        tester = DahuaRTSPTester(args.url)
        
        # Test kết nối
        if tester.test_connection():
            if args.stream:
                tester.stream_frames(
                    duration=args.duration, 
                    save_frame=args.save_frame
                )
        else:
            print("\n💡 Lưu ý: Đảm bảo URL chính xác!")
            print_help()
    else:
        # Interactive mode
        print("\n🎥 DAHUA CAMERA RTSP TESTER")
        print("=" * 60)
        
        # Default URLs to test
        urls = [
            "rtsp://admin:admin@172.16.251.100:554/cam/realmonitor?channel=1&subtype=0",
            "rtsp://172.16.251.100:554/stream1",
        ]
        
        rtsp_url = input("\n📍 Nhập RTSP URL (hoặc Enter để test mặc định): ").strip()
        
        if not rtsp_url:
            rtsp_url = urls[0]
            print(f"   Sử dụng URL mặc định: {rtsp_url}")
        
        tester = DahuaRTSPTester(rtsp_url)
        
        # Test connection
        if tester.test_connection():
            stream_choice = input("\n▶️  Stream frames? (y/n): ").lower()
            if stream_choice == 'y':
                duration = input("   ⏱️  Thời gian (giây)? (mặc định 10): ").strip()
                duration = int(duration) if duration.isdigit() else 10
                
                save_choice = input("   💾 Lưu frame đầu tiên? (y/n): ").lower()
                tester.stream_frames(duration=duration, save_frame=(save_choice == 'y'))
        else:
            print("\n❌ Không thể kết nối. Vui lòng kiểm tra lại URL.")
