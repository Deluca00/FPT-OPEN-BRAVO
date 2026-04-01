"""
Cloudflare Tunnel Auto-Start Script
Tự động chạy tunnels và cập nhật URL vào config
"""

import subprocess
import threading
import re
import json
import os
import time
import sys

CONFIG_FILE = os.path.join(os.path.dirname(__file__), 'cloudflare_config.json')

# Store tunnel URLs
tunnel_urls = {
    'barcode_app': None,
    'openbravo': None
}

def load_config():
    """Load current config"""
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
    except:
        pass
    return {
        "enabled": False,
        "barcode_app": {"tunnel_url": "", "local_port": 5443},
        "openbravo": {"tunnel_url": "", "local_port": 8080}
    }

def save_config(config):
    """Save config to file"""
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=4, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"Error saving config: {e}")
        return False

def run_tunnel(name, local_url, key, no_tls_verify=False):
    """Run a cloudflare tunnel and capture URL"""
    global tunnel_urls
    
    print(f"\n[{name}] Starting tunnel for {local_url}...")
    
    try:
        cmd = ['cloudflared', 'tunnel', '--url', local_url]
        if no_tls_verify:
            cmd.append('--no-tls-verify')
        
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
        )
        
        url_pattern = re.compile(r'https://[a-zA-Z0-9-]+\.trycloudflare\.com')
        
        for line in process.stdout:
            line = line.strip()
            
            # Find tunnel URL
            match = url_pattern.search(line)
            if match and tunnel_urls[key] is None:
                url = match.group(0)
                tunnel_urls[key] = url
                print(f"\n{'='*60}")
                print(f"[{name}] ✅ TUNNEL URL: {url}")
                print(f"{'='*60}\n")
                
                # Update config
                update_config()
            
            # Print cloudflared output (filtered)
            if 'INF' in line or 'ERR' in line or 'WRN' in line:
                # Simplify output
                if 'Registered tunnel connection' in line:
                    print(f"[{name}] ✓ Tunnel connected")
                elif 'ERR' in line:
                    print(f"[{name}] ⚠ {line}")
        
        process.wait()
        
    except FileNotFoundError:
        print(f"[ERROR] cloudflared not found! Install with: winget install Cloudflare.cloudflared")
    except Exception as e:
        print(f"[{name}] Error: {e}")

def update_config():
    """Update config file with tunnel URLs"""
    config = load_config()
    updated = False
    
    if tunnel_urls['barcode_app']:
        config['barcode_app']['tunnel_url'] = tunnel_urls['barcode_app']
        updated = True
    
    if tunnel_urls['openbravo']:
        config['openbravo']['tunnel_url'] = tunnel_urls['openbravo']
        updated = True
    
    if updated:
        config['enabled'] = True
        if save_config(config):
            print("\n✅ Config đã được cập nhật tự động!")
            print(f"   Barcode App: {tunnel_urls['barcode_app'] or 'Đang chờ...'}")
            print(f"   Openbravo:   {tunnel_urls['openbravo'] or 'Đang chờ...'}")

def main():
    print("="*60)
    print("   🚀 CLOUDFLARE TUNNEL AUTO-START")
    print("="*60)
    print()
    print("Đang khởi động tunnels...")
    print("URLs sẽ tự động được cập nhật vào config.")
    print()
    print("⚠️  ĐẢM BẢO CÁC APP ĐÃ CHẠY:")
    print("   - Barcode App: https://localhost:5443")
    print("   - Openbravo:   http://localhost:8080")
    print()
    print("Nhấn Ctrl+C để dừng tất cả tunnels.")
    print("="*60)
    
    # Start tunnels in threads
    threads = []
    
    # Barcode App tunnel (HTTPS với --no-tls-verify vì dùng self-signed cert)
    t1 = threading.Thread(
        target=run_tunnel,
        args=("Barcode App", "https://localhost:5443", "barcode_app", True),
        daemon=True
    )
    threads.append(t1)
    
    # Openbravo tunnel (HTTP)
    t2 = threading.Thread(
        target=run_tunnel,
        args=("Openbravo", "http://localhost:8080", "openbravo", False),
        daemon=True
    )
    threads.append(t2)
    
    # Start all threads
    for t in threads:
        t.start()
        time.sleep(2)  # Stagger starts
    
    # Wait for URLs to be captured
    print("\nĐang chờ tunnel URLs...")
    timeout = 30
    start_time = time.time()
    
    while (tunnel_urls['barcode_app'] is None or tunnel_urls['openbravo'] is None):
        if time.time() - start_time > timeout:
            print("\n⚠️  Timeout! Một số tunnels có thể chưa kết nối.")
            break
        time.sleep(1)
    
    # Print final summary
    print("\n" + "="*60)
    print("   📋 TUNNEL URLs (đã lưu vào config)")
    print("="*60)
    print(f"\n   🔷 Barcode App:")
    print(f"      {tunnel_urls['barcode_app'] or '❌ Chưa kết nối'}")
    print(f"\n   🔶 Openbravo:")
    if tunnel_urls['openbravo']:
        print(f"      {tunnel_urls['openbravo']}/openbravo")
    else:
        print(f"      ❌ Chưa kết nối")
    print("\n" + "="*60)
    print("\n✅ Tunnels đang chạy. Nhấn Ctrl+C để dừng.")
    print("   Mở app và vào Chia sẻ → Cloudflare để xem QR codes.")
    
    # Keep running
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n\n👋 Đang dừng tunnels...")
        sys.exit(0)

if __name__ == '__main__':
    main()
