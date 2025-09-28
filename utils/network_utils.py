import socket
import requests
import subprocess
import platform
import re

def get_local_ip():
    """
    اكتشاف IP الحاسوب المحلي ديناميكياً
    """
    try:
        # محاولة الحصول على IP من الإنترنت
        response = requests.get('https://api.ipify.org', timeout=3)
        if response.status_code == 200:
            return response.text
    except:
        pass
    
    try:
        # محاولة الحصول على IP من موقع آخر
        response = requests.get('https://httpbin.org/ip', timeout=3)
        if response.status_code == 200:
            return response.json()['origin']
    except:
        pass
    
    # إذا فشل الاتصال بالإنترنت، استخدم IP المحلي
    return get_local_network_ip()

def get_local_network_ip():
    """
    الحصول على IP المحلي من الشبكة
    """
    try:
        # إنشاء socket للاتصال بـ Google DNS
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return "127.0.0.1"

def get_all_network_ips():
    """
    الحصول على جميع IPs المتاحة على الحاسوب
    """
    ips = []
    
    try:
        # الحصول على جميع الواجهات الشبكية
        hostname = socket.gethostname()
        local_ip = socket.gethostbyname(hostname)
        ips.append(local_ip)
    except:
        pass
    
    try:
        # محاولة الحصول على IP من الإنترنت
        response = requests.get('https://api.ipify.org', timeout=3)
        if response.status_code == 200:
            public_ip = response.text
            if public_ip not in ips:
                ips.append(public_ip)
    except:
        pass
    
    # إضافة IP المحلي إذا لم يكن موجوداً
    local_ip = get_local_network_ip()
    if local_ip not in ips:
        ips.append(local_ip)
    
    return ips

def get_best_network_ip():
    """
    الحصول على أفضل IP للاستخدام في الشبكة المحلية
    """
    return "192.168.0.102"

def is_port_available(ip, port):
    """
    التحقق من توفر المنفذ على IP معين
    """
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1)
        result = sock.connect_ex((ip, port))
        sock.close()
        return result != 0  # True إذا كان المنفذ متاح
    except:
        return False

def get_server_url(port=5000):
    """
    الحصول على URL السيرفر مع IP ديناميكي
    """
    ip = get_best_network_ip()
    return f"http://{ip}:{port}"

def get_frontend_url(port=3033):
    """
    الحصول على URL واجهة المستخدم (Frontend) بشكل ديناميكي
    يعطي الأولوية لـ localhost إذا كان متاحاً، ثم أول IP متاح على الشبكة
    """
    # تحقق من توفر localhost أولاً
    import socket
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        result = sock.connect_ex(("127.0.0.1", port))
        sock.close()
        if result == 0:
            return f"http://localhost:{port}"
    except:
        pass

    # إذا لم يكن localhost متاحاً، استخدم أول IP متاح من الشبكة
    ips = get_all_network_ips()
    for ip in ips:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            result = sock.connect_ex((ip, port))
            sock.close()
            if result == 0:
                return f"http://{ip}:{port}"
        except:
            continue

    # fallback: إذا لم يوجد أي IP متاح
    return f"http://127.0.0.1:{port}"

def test_network_connectivity():
    """
    اختبار الاتصال الشبكي وإرجاع معلومات مفيدة
    """
    info = {
        'local_ip': get_local_network_ip(),
        'public_ip': None,
        'all_ips': get_all_network_ips(),
        'best_ip': get_best_network_ip(),
        'server_url': get_server_url(),
        'port_available': is_port_available(get_best_network_ip(), 5000)
    }
    
    try:
        response = requests.get('https://api.ipify.org', timeout=3)
        if response.status_code == 200:
            info['public_ip'] = response.text
    except:
        pass
    
    return info 