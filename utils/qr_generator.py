import qrcode
import os
from PIL import Image, ImageDraw, ImageFont
from config import Config
from utils.network_utils import get_frontend_url

def draw_penrose_triangle(draw, center_x, center_y, size, fill_color="#FF0000", outline_color="#CC0000"):
    """
    رسم مثلث بنروز (المثلث اللانهائي) احترافي
    """
    # حساب النقاط للمثلث الثلاثي الأبعاد
    outer_size = size
    inner_size = size * 0.6
    
    # المثلث الخارجي الأحمر
    outer_triangle = [
        (center_x, center_y - outer_size//2),                    # النقطة العلوية
        (center_x - outer_size//2, center_y + outer_size//3),    # النقطة السفلية اليسرى
        (center_x + outer_size//2, center_y + outer_size//3),    # النقطة السفلية اليمنى
    ]
    
    # المثلث الداخلي الأبيض
    inner_triangle = [
        (center_x, center_y - inner_size//2),                    # النقطة العلوية
        (center_x - inner_size//2, center_y + inner_size//3),    # النقطة السفلية اليسرى
        (center_x + inner_size//2, center_y + inner_size//3),    # النقطة السفلية اليمنى
    ]
    
    # رسم الظل
    shadow_offset = 2
    shadow_triangle = [(x + shadow_offset, y + shadow_offset) for x, y in outer_triangle]
    draw.polygon(shadow_triangle, fill="#AA0000", outline="#AA0000")
    
    # رسم المثلث الخارجي الأحمر
    draw.polygon(outer_triangle, fill=fill_color, outline=fill_color)
    
    # رسم المثلث الداخلي الأبيض
    draw.polygon(inner_triangle, fill="white", outline="white")
    
    # إضافة تأثير ثلاثي الأبعاد
    # الخطوط الجانبية للمثلث
    line_width = 3
    
    # الخط الأيسر
    draw.line([
        (center_x - outer_size//3, center_y - outer_size//6),
        (center_x - outer_size//2, center_y + outer_size//3)
    ], fill="#AA0000", width=line_width)
    
    # الخط الأيمن
    draw.line([
        (center_x + outer_size//3, center_y - outer_size//6),
        (center_x + outer_size//2, center_y + outer_size//3)
    ], fill="#AA0000", width=line_width)
    
    # الخط السفلي
    draw.line([
        (center_x - outer_size//2, center_y + outer_size//3),
        (center_x + outer_size//2, center_y + outer_size//3)
    ], fill="#AA0000", width=line_width)

def generate_room_qr(room_code, room_id, base_url=None):
    """
    توليد QR Code للقاعة مع تصميم احترافي ومثلث بنروز داخل الباركود
    Args:
        room_code: رمز القاعة
        room_id: معرف القاعة في قاعدة البيانات
        base_url: رابط الأساسي للواجهة الأمامية (اختياري)
    Returns:
        str: مسار ملف QR المحفوظ
    """
    try:
        print(f"QR Generator: Called with base_url={base_url}, room_code={room_code}")
        # إنشاء رابط القاعة باستخدام base_url أو الافتراضي
        if base_url is None:
            # Force the correct URL for now
            base_url = 'https://www.it-college.zone.id'
            print(f"QR Generator: Using hardcoded FRONTEND_URL: {base_url} for room {room_code}")
        else:
            # Override any passed base_url to force correct domain
            print(f"QR Generator: Received base_url: {base_url}, overriding to correct domain")
            base_url = 'https://www.it-college.zone.id'
            print(f"QR Generator: Using overridden FRONTEND_URL: {base_url} for room {room_code}")
        room_url = f"{base_url}/room/{room_code}"
        print(f"QR Generator: Final URL being encoded: {room_url}")  # Debug the actual URL
        # إنشاء QR Code بدقة عالية
        qr = qrcode.QRCode(
            version=5,
            error_correction=qrcode.constants.ERROR_CORRECT_H,
            box_size=12,
            border=1,
        )
        qr.add_data(room_url)
        qr.make(fit=True)
        # إنشاء الصورة الأساسية للـ QR بألوان احترافية
        qr_img = qr.make_image(fill_color="#1a1a1a", back_color="white")
        # إنشاء صورة أكبر للتصميم النهائي
        final_width = 600
        final_height = 800
        final_img = Image.new('RGB', (final_width, final_height), '#FFFFFF')
        # تغيير حجم QR Code
        qr_size = 400
        qr_img = qr_img.resize((qr_size, qr_size), Image.Resampling.LANCZOS)
        # وضع QR Code في المنتصف
        qr_x = (final_width - qr_size) // 2
        qr_y = 150
        final_img.paste(qr_img, (qr_x, qr_y))
        # إعداد للرسم
        draw = ImageDraw.Draw(final_img)
        
        # إضافة الخطوط والنصوص
        try:
            # محاولة تحميل خطوط احترافية
            font_title = ImageFont.truetype("arial.ttf", 32)
            font_subtitle = ImageFont.truetype("arial.ttf", 22)
            font_medium = ImageFont.truetype("arial.ttf", 18)
            font_small = ImageFont.truetype("arial.ttf", 14)
        except:
            # استخدام الخط الافتراضي
            font_title = ImageFont.load_default()
            font_subtitle = ImageFont.load_default()
            font_medium = ImageFont.load_default()
            font_small = ImageFont.load_default()
        
        # إضافة إطار خارجي احترافي
        border_width = 4
        draw.rectangle([
            (border_width, border_width), 
            (final_width - border_width, final_height - border_width)
        ], outline="#2C3E50", width=border_width)
        
        # إضافة خط فاصل علوي
        line_y = 130
        line_margin = 50
        draw.line([(line_margin, line_y), (final_width - line_margin, line_y)], 
                 fill="#3498DB", width=3)
        
        # العنوان الرئيسي
        title_text = "COLLEGE SCHEDULE SYSTEM"
        title_bbox = draw.textbbox((0, 0), title_text, font=font_title)
        title_width = title_bbox[2] - title_bbox[0]
        title_x = (final_width - title_width) // 2
        draw.text((title_x, 40), title_text, fill="#2C3E50", font=font_title)
        
        # العنوان الفرعي
        subtitle_text = "Smart Room Management"
        subtitle_bbox = draw.textbbox((0, 0), subtitle_text, font=font_medium)
        subtitle_width = subtitle_bbox[2] - subtitle_bbox[0]
        subtitle_x = (final_width - subtitle_width) // 2
        draw.text((subtitle_x, 85), subtitle_text, fill="#7F8C8D", font=font_medium)
        
        # ضع لوجو الفريق واسم الفريق في صف واحد أسفل رمز الـ QR
        logo_path = os.path.join(os.path.dirname(__file__), '..', 'static', 'qrcodes', 'alpha-logo.png')
        print(f"QR Generator: Looking for logo at: {logo_path}")
        logo_size = 64
        logo_y = qr_y + qr_size + 10

        team_text = "Created by Alpha Team - Cybersecurity Department"
        team_bbox = draw.textbbox((0, 0), team_text, font=font_small)
        team_width = team_bbox[2] - team_bbox[0]
        team_height = team_bbox[3] - team_bbox[1]

        spacing = 12
        combined_width = logo_size + spacing + team_width
        start_x = (final_width - combined_width) // 2

        if os.path.exists(logo_path):
            print(f"QR Generator: Logo file exists, trying to load...")
            try:
                logo_img = Image.open(logo_path).convert("RGBA")
                logo_img = logo_img.resize((logo_size, logo_size), Image.Resampling.LANCZOS)
                # لصق الشعار عند الموضع المحسوب
                final_img.paste(logo_img, (start_x, logo_y), logo_img)
                # كتابة اسم الفريق بجانب الشعار
                text_x = start_x + logo_size + spacing
                text_y = logo_y + (logo_size - team_height) // 2
                draw.text((text_x, text_y), team_text, fill="#E67E22", font=font_small)
                print(f"QR Generator: Logo loaded successfully")
            except Exception as e:
                print(f"QR Generator: Error adding team logo: {e}")
                # في حال فشل تحميل الشعار، ارسم اسم الفريق بموقع مركزي بدلاً من الشعار
                fallback_x = (final_width - team_width) // 2
                draw.text((fallback_x, logo_y), team_text, fill="#E67E22", font=font_small)
        else:
            print(f"QR Generator: Logo file does not exist")
            # إذا لم يوجد الشعار، ارسم اسم الفريق في منتصف العرض أسفل الـ QR
            fallback_x = (final_width - team_width) // 2
            draw.text((fallback_x, logo_y), team_text, fill="#E67E22", font=font_small)

        # إضافة خط فاصل أسفل منطقة الـ QR/logo
        line_y = logo_y + logo_size + 12
        draw.line([(line_margin, line_y), (final_width - line_margin, line_y)],
                 fill="#3498DB", width=3)

        # النص الرئيسي للمسح أسفل الخط
        scan_text = "Scan the barcode to view schedule"
        scan_bbox = draw.textbbox((0, 0), scan_text, font=font_subtitle)
        scan_width = scan_bbox[2] - scan_bbox[0]
        scan_x = (final_width - scan_width) // 2
        scan_y = line_y + 12
        draw.text((scan_x, scan_y), scan_text, fill="#E74C3C", font=font_subtitle)

        # معلومات القاعة
        room_text = f"Room Code: {room_code}"
        room_bbox = draw.textbbox((0, 0), room_text, font=font_medium)
        room_width = room_bbox[2] - room_bbox[0]
        room_x = (final_width - room_width) // 2
        room_y = scan_y + 36
        draw.text((room_x, room_y), room_text, fill="#34495E", font=font_medium)

        # النص السفلي
        footer_text = "Powered by College Schedule System"
        footer_bbox = draw.textbbox((0, 0), footer_text, font=font_small)
        footer_width = footer_bbox[2] - footer_bbox[0]
        footer_x = (final_width - footer_width) // 2
        footer_y = room_y + 58
        draw.text((footer_x, footer_y), footer_text, fill="#95A5A6", font=font_small)
        
        # إضافة زخارف في الزوايا
        corner_size = 30
        corner_width = 4
        
        # الزاوية العلوية اليسرى
        draw.line([(15, 15), (15 + corner_size, 15)], fill="#3498DB", width=corner_width)
        draw.line([(15, 15), (15, 15 + corner_size)], fill="#3498DB", width=corner_width)
        
        # الزاوية العلوية اليمنى
        draw.line([(final_width - 15 - corner_size, 15), (final_width - 15, 15)], 
                 fill="#3498DB", width=corner_width)
        draw.line([(final_width - 15, 15), (final_width - 15, 15 + corner_size)], 
                 fill="#3498DB", width=corner_width)
        
        # الزاوية السفلية اليسرى
        draw.line([(15, final_height - 15 - corner_size), (15, final_height - 15)], 
                 fill="#3498DB", width=corner_width)
        draw.line([(15, final_height - 15), (15 + corner_size, final_height - 15)], 
                 fill="#3498DB", width=corner_width)
        
        # الزاوية السفلية اليمنى
        draw.line([(final_width - 15 - corner_size, final_height - 15), 
                  (final_width - 15, final_height - 15)], fill="#3498DB", width=corner_width)
        draw.line([(final_width - 15, final_height - 15 - corner_size), 
                  (final_width - 15, final_height - 15)], fill="#3498DB", width=corner_width)
        
        # تحديد مسار الحفظ
        # اجعل المسار دائماً داخل backend/static/qrcodes
        backend_dir = os.path.dirname(os.path.abspath(__file__))
        qr_folder = os.path.join(backend_dir, '..', 'static', 'qrcodes')
        if not os.path.exists(qr_folder):
            os.makedirs(qr_folder)
        filename = f"room_{room_code}_qr.png"
        file_path = os.path.join(qr_folder, filename)
        try:
            final_img.save(file_path, 'PNG', quality=95, optimize=True, dpi=(300, 300))
            print(f"QR Generator: Successfully saved QR code to: {file_path}")
            print(f"QR Generator: QR code contains URL: {room_url}")
        except Exception as save_error:
            print(f"QR Generator: Error saving QR code: {save_error}")
            return None
        return file_path
    
    except Exception as e:
        print(f"Error generating QR code: {str(e)}")
        return None

def delete_room_qr(qr_code_path):
    """
    Delete room QR Code
    Args:
        qr_code_path: QR file path
    Returns:
        bool: True if deleted successfully
    """
    try:
        if qr_code_path and os.path.exists(qr_code_path):
            # محاولة إغلاق الملف إذا كان مفتوحاً
            try:
                with open(qr_code_path, 'rb') as f:
                    pass
            except Exception:
                pass
            import gc
            gc.collect()
            os.remove(qr_code_path)
            return True
        return False
    except Exception as e:
        print(f"Error deleting QR code: {str(e)}")
        return False