"""
Script tạo SSL certificate tự ký cho Flask HTTPS
"""
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
import datetime
import ipaddress
import socket

def get_local_ip():
    """Lấy địa chỉ IP local của máy"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return "127.0.0.1"

def generate_ssl_cert():
    # Generate key
    key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
        backend=default_backend()
    )
    
    local_ip = get_local_ip()
    print(f"Local IP: {local_ip}")
    
    # Generate certificate
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "VN"),
        x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, "HCM"),
        x509.NameAttribute(NameOID.LOCALITY_NAME, "Ho Chi Minh"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Openbravo Barcode Scanner"),
        x509.NameAttribute(NameOID.COMMON_NAME, local_ip),
    ])
    
    # Subject Alternative Names - cho phép truy cập từ nhiều địa chỉ
    san = x509.SubjectAlternativeName([
        x509.DNSName("localhost"),
        x509.DNSName("*.local"),
        x509.IPAddress(ipaddress.IPv4Address("127.0.0.1")),
        x509.IPAddress(ipaddress.IPv4Address(local_ip)),
    ])
    
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.datetime.utcnow())
        .not_valid_after(datetime.datetime.utcnow() + datetime.timedelta(days=365))
        .add_extension(san, critical=False)
        .sign(key, hashes.SHA256(), default_backend())
    )
    
    # Write key
    with open("key.pem", "wb") as f:
        f.write(key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption()
        ))
    
    # Write cert
    with open("cert.pem", "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))
    
    print("✅ SSL Certificate đã được tạo!")
    print(f"   - cert.pem")
    print(f"   - key.pem")
    print(f"\n🌐 Truy cập từ thiết bị khác:")
    print(f"   https://{local_ip}:5000")
    print(f"\n⚠️  Lưu ý: Khi truy cập lần đầu, trình duyệt sẽ cảnh báo về certificate.")
    print(f"   Chọn 'Advanced' > 'Proceed to {local_ip}' để tiếp tục.")

if __name__ == "__main__":
    generate_ssl_cert()
