"""
Test Stream từ 2 Camera Dahua
IP 100 và 101
"""

import cv2
import threading
import time
from datetime import datetime


class DualCameraTester:
    """Test 2 camera RTSP stream"""
    
    def __init__(self):
        self.cameras = {
            'Camera 100': "rtsp://admin:L212A477@172.16.251.100:554/cam/realmonitor?channel=1&subtype=0",
            'Camera 101': "rtsp://admin:L27EEFF1@172.16.251.101:554/cam/realmonitor?channel=1&subtype=0"
        }
        self.threads = {}
        self.results = {}
        
    def test_camera(self, name, rtsp_url, timeout=10):
        """Test một camera"""
        print(f"\n🎥 Testing {name}")
        print(f"   URL: {rtsp_url}")
        print(f"   Đang kết nối...", end='', flush=True)
        
        try:
            cap = cv2.VideoCapture(rtsp_url)
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            
            start = time.time()
            frame_count = 0
            
            while time.time() - start < timeout:
                ret, frame = cap.read()
                
                if ret and frame is not None:
                    frame_count += 1
                    
                    # Add timestamp
                    text = f"{name} - {datetime.now().strftime('%H:%M:%S')} - Frame {frame_count}"
                    cv2.putText(frame, text, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
                    
                    # Display
                    cv2.imshow(name, frame)
                    
                    # Press 'q' to quit
                    if cv2.waitKey(1) & 0xFF == ord('q'):
                        print()
                        print(f"   ⏹️  Dừng (Q pressed)")
                        break
                    
                    if frame_count == 1:
                        print()
                        print(f"   ✅ Kết nối OK! Resolution: {frame.shape[1]}x{frame.shape[0]}")
                else:
                    print('.', end='', flush=True)
            
            elapsed = time.time() - start
            cap.release()
            
            if frame_count > 0:
                fps = frame_count / elapsed
                self.results[name] = f"✅ OK - {frame_count} frames, {fps:.1f} FPS"
            else:
                self.results[name] = "❌ FAIL - Không nhận frame"
            
        except Exception as e:
            print()
            self.results[name] = f"❌ ERROR: {str(e)[:50]}"
            
    def run_all(self, duration=15):
        """Test cả 2 camera cùng lúc"""
        print("\n" + "="*70)
        print("🎬 DUAL CAMERA STREAM TEST")
        print("="*70)
        print(f"Duration: {duration}s")
        print(f"Cameras: {', '.join(self.cameras.keys())}")
        print("="*70)
        
        # Start threads
        for name, url in self.cameras.items():
            thread = threading.Thread(target=self.test_camera, args=(name, url, duration))
            thread.daemon = True
            thread.start()
            self.threads[name] = thread
            time.sleep(1)  # Offset start time
        
        # Wait for all threads
        for thread in self.threads.values():
            thread.join()
        
        # Close windows
        cv2.destroyAllWindows()
        
        # Print results
        print("\n" + "="*70)
        print("📊 KẾT QUẢ:")
        print("="*70)
        for name, result in self.results.items():
            print(f"  {name}: {result}")
        print("="*70)
        
    def run_sequential(self, duration=10):
        """Test từng camera một"""
        print("\n" + "="*70)
        print("🎬 SEQUENTIAL CAMERA TEST")
        print("="*70)
        print(f"Duration per camera: {duration}s")
        print("="*70)
        
        for name, url in self.cameras.items():
            self.test_camera(name, url, duration)
            cv2.destroyAllWindows()
            
        # Print results
        print("\n" + "="*70)
        print("📊 KẾT QUẢ:")
        print("="*70)
        for name, result in self.results.items():
            print(f"  {name}: {result}")
        print("="*70)


if __name__ == '__main__':
    import sys
    
    tester = DualCameraTester()
    
    if len(sys.argv) > 1:
        if sys.argv[1] == '--parallel':
            duration = int(sys.argv[2]) if len(sys.argv) > 2 else 15
            print(f"🔄 Mode: Song song (Parallel) - {duration}s")
            tester.run_all(duration)
        elif sys.argv[1] == '--seq':
            duration = int(sys.argv[2]) if len(sys.argv) > 2 else 10
            print(f"📋 Mode: Tuần tự (Sequential) - {duration}s mỗi camera")
            tester.run_sequential(duration)
        else:
            print(f"Usage:")
            print(f"  python test_dual_camera.py --parallel [duration]")
            print(f"  python test_dual_camera.py --seq [duration]")
            print(f"\nExample:")
            print(f"  python test_dual_camera.py --parallel 20")
            print(f"  python test_dual_camera.py --seq 10")
    else:
        # Default: song song
        print(f"🔄 Mode: Song song (default) - 15s")
        print(f"\nGợi ý:")
        print(f"  Tuần tự: python test_dual_camera.py --seq 10")
        print(f"  Song song: python test_dual_camera.py --parallel 20\n")
        tester.run_all(15)
