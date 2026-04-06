#!/usr/bin/env python3
"""
Quick API Test Script for Camera Endpoints
Tests all camera functionality without needing a browser
"""

import requests
import json
import sys
import time
from pathlib import Path

# Configuration
API_BASE = "http://localhost:5000/api"
TIMEOUT = 5

# Colors for terminal output
class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    RESET = '\033[0m'
    BOLD = '\033[1m'

def print_header(text):
    print(f"\n{Colors.BOLD}{Colors.BLUE}{'='*60}{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.BLUE}{text}{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.BLUE}{'='*60}{Colors.RESET}\n")

def print_success(text):
    print(f"{Colors.GREEN}✅ {text}{Colors.RESET}")

def print_error(text):
    print(f"{Colors.RED}❌ {text}{Colors.RESET}")

def print_info(text):
    print(f"{Colors.YELLOW}ℹ️ {text}{Colors.RESET}")

def test_connectivity():
    """Test if app is running"""
    print_header("1. Testing App Connectivity")
    try:
        response = requests.get(f"{API_BASE}/camera/list", timeout=TIMEOUT)
        print_success(f"App is running on port 5000")
        return True
    except requests.exceptions.ConnectionError:
        print_error("Cannot connect to app on http://localhost:5000")
        print_info("Make sure app is running: python app.py")
        return False
    except Exception as e:
        print_error(f"Connection error: {e}")
        return False

def test_camera_list():
    """List all cameras"""
    print_header("2. Listing All Cameras")
    try:
        response = requests.get(f"{API_BASE}/camera/list", timeout=TIMEOUT)
        data = response.json()
        
        if data['success']:
            print_success(f"Found {data['total']} cameras")
            for camera in data['cameras']:
                print(f"  • {camera['id']}: {camera['name']}")
                print(f"    Type: {camera['type']}")
            return True
        else:
            print_error("Failed to list cameras")
            return False
    except Exception as e:
        print_error(f"Error: {e}")
        return False

def test_camera_status():
    """Get camera status"""
    print_header("3. Checking Camera Status")
    try:
        response = requests.get(f"{API_BASE}/camera/status", timeout=TIMEOUT)
        data = response.json()
        
        if data['success']:
            for camera_id, status in data['cameras'].items():
                is_running = "✅" if status['is_running'] else "❌"
                has_frame = "✅" if status['has_frame'] else "❌"
                
                print(f"  Camera {camera_id}: {status['name']}")
                print(f"    Running: {is_running}")
                print(f"    Frame: {has_frame}")
                if status['error']:
                    print(f"    Error: {status['error']}")
                print()
            return True
        else:
            print_error("Failed to get camera status")
            return False
    except Exception as e:
        print_error(f"Error: {e}")
        return False

def test_camera_operations(camera_id="101"):
    """Test start, stop, capture operations"""
    print_header(f"4. Testing Camera {camera_id} Operations")
    
    try:
        # Start camera
        print_info(f"Starting camera {camera_id}...")
        response = requests.post(f"{API_BASE}/camera/{camera_id}/start", timeout=TIMEOUT)
        data = response.json()
        if data['success']:
            print_success(f"Camera {camera_id} started")
        time.sleep(1)
        
        # Get frame
        print_info(f"Capturing frame from camera {camera_id}...")
        response = requests.get(f"{API_BASE}/camera/{camera_id}/frame", timeout=TIMEOUT)
        if response.status_code == 200:
            frame_size = len(response.content)
            print_success(f"Frame captured ({frame_size} bytes)")
        else:
            print_error(f"Failed to capture frame (HTTP {response.status_code})")
        
        # Capture snapshot (base64)
        print_info(f"Capturing snapshot from camera {camera_id}...")
        response = requests.post(f"{API_BASE}/camera/{camera_id}/capture", timeout=TIMEOUT)
        data = response.json()
        if data['success']:
            if 'image' in data:
                img_size = len(data['image'])
                print_success(f"Snapshot captured (Base64: {img_size} bytes)")
                print_info(f"Timestamp: {data['timestamp']}")
        else:
            print_error(f"Failed to capture snapshot: {data.get('error')}")
        
        # Stop camera
        print_info(f"Stopping camera {camera_id}...")
        response = requests.post(f"{API_BASE}/camera/{camera_id}/stop", timeout=TIMEOUT)
        data = response.json()
        if data['success']:
            print_success(f"Camera {camera_id} stopped")
        
        return True
    except Exception as e:
        print_error(f"Error: {e}")
        return False

def test_ai_detection(camera_id="101", detection_type="defect"):
    """Test AI detection endpoint"""
    print_header("5. Testing AI Detection")
    
    try:
        print_info(f"Running {detection_type} detection on camera {camera_id}...")
        
        response = requests.post(
            f"{API_BASE}/ai-detect",
            json={
                "type": detection_type,
                "camera_id": camera_id
            },
            timeout=TIMEOUT
        )
        
        data = response.json()
        
        if data['success']:
            print_success(f"AI detection completed")
            print(f"  Detection Type: {data.get('detection_type', 'N/A')}")
            
            if 'results' in data and data['results']:
                print(f"  Results:")
                for result in data['results']:
                    print(f"    • Class: {result.get('class', 'Unknown')}")
                    print(f"      Confidence: {result.get('confidence', 'N/A'):.2%}")
                    print(f"      Label: {result.get('label', 'N/A')}")
            else:
                print_info("No objects detected")
        else:
            print_error(f"AI detection failed: {data.get('error', 'Unknown error')}")
        
        return data['success']
    except Exception as e:
        print_error(f"Error: {e}")
        return False

def main():
    """Run all tests"""
    print(f"\n{Colors.BOLD}{Colors.BLUE}")
    print("╔════════════════════════════════════════════════════════════╗")
    print("║            CAMERA API TEST SUITE                           ║")
    print("║          FPT Warehouse Barcode Scanner App                 ║")
    print("╚════════════════════════════════════════════════════════════╝")
    print(f"{Colors.RESET}")
    
    results = []
    
    # Run tests
    if not test_connectivity():
        print_error("Cannot proceed without app connectivity")
        sys.exit(1)
    
    results.append(("Camera List", test_camera_list()))
    results.append(("Camera Status", test_camera_status()))
    results.append(("Camera Operations", test_camera_operations()))
    results.append(("AI Detection", test_ai_detection()))
    
    # Summary
    print_header("TEST SUMMARY")
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for test_name, result in results:
        status = f"{Colors.GREEN}✅ PASS{Colors.RESET}" if result else f"{Colors.RED}❌ FAIL{Colors.RESET}"
        print(f"  {test_name}: {status}")
    
    print()
    if passed == total:
        print_success(f"All {total} tests passed! 🎉")
        return 0
    else:
        print_error(f"{total - passed}/{total} tests failed")
        return 1

if __name__ == "__main__":
    sys.exit(main())
