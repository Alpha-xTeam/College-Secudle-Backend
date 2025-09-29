import qrcode
import os
from PIL import Image, ImageDraw, ImageFont
from config import Config
from utils.network_utils import get_frontend_url

# Design palette
PRIMARY_COLOR = '#0B3D91'     # deep blue for accents
ACCENT_COLOR = '#3498DB'      # lighter blue for separators
TEXT_COLOR = '#111111'        # primary text color (black-ish)
TEAM_COLOR = '#C0392B'        # team name color (red)
FRAME_COLOR = '#2C3E50'      # frame outline
BACKGROUND_COLOR = '#FFFFFF'  # white background

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
    
    # رسم المثلث الخارجي
    draw.polygon(outer_triangle, fill=fill_color, outline=outline_color)
    
    # رسم المثلث الداخلي
    draw.polygon(inner_triangle, fill="white", outline="white")
    
    # إضافة تأثير ثلاثي الأبعاد
    line_width = 3
    draw.line([
        (center_x - outer_size//3, center_y - outer_size//6),
        (center_x - outer_size//2, center_y + outer_size//3)
    ], fill=outline_color, width=line_width)
    draw.line([
        (center_x + outer_size//3, center_y - outer_size//6),
        (center_x + outer_size//2, center_y + outer_size//3)
    ], fill=outline_color, width=line_width)
    draw.line([
        (center_x - outer_size//2, center_y + outer_size//3),
        (center_x + outer_size//2, center_y + outer_size//3)
    ], fill=outline_color, width=line_width)

def generate_room_qr(room_code, room_id, base_url=None):
    """
    توليد QR Code للقاعة مع تصميم احترافي
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
            base_url = 'https://www.it-college.zone.id'
            print(f"QR Generator: Using hardcoded FRONTEND_URL: {base_url} for room {room_code}")
        else:
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
        qr_img = qr.make_image(fill_color=PRIMARY_COLOR, back_color=BACKGROUND_COLOR)

        # إنشاء صورة أكبر للتصميم النهائي
        final_width = 600
        final_height = 800
        final_img = Image.new('RGB', (final_width, final_height), BACKGROUND_COLOR)

        # تغيير حجم QR Code
        qr_size = 400
        qr_img = qr_img.resize((qr_size, qr_size), Image.Resampling.LANCZOS)

        # وضع QR Code في المنتصف
        qr_x = (final_width - qr_size) // 2
        qr_y = 150
        final_img.paste(qr_img, (qr_x, qr_y))

        # إعداد للرسم
        draw = ImageDraw.Draw(final_img)
        
        # محاولة تحميل خطوط احترافية مع تدرج بدائل
        def load_font(preferred, size):
            try:
                return ImageFont.truetype(preferred, size)
            except Exception:
                return None

        font_title = load_font("DejaVuSans-Bold.ttf", 28) or load_font("arialbd.ttf", 28) or ImageFont.load_default()
        font_subtitle = load_font("DejaVuSans.ttf", 18) or load_font("arial.ttf", 18) or ImageFont.load_default()
        font_medium = load_font("DejaVuSans.ttf", 16) or load_font("arial.ttf", 16) or ImageFont.load_default()
        font_small = load_font("DejaVuSans.ttf", 12) or load_font("arial.ttf", 12) or ImageFont.load_default()

        # إضافة إطار خارجي احترافي مع ظل ناعم
        border_width = 4
        frame_rect = [(border_width, border_width), (final_width - border_width, final_height - border_width)]
        draw.rectangle(frame_rect, outline=FRAME_COLOR, width=border_width)

        # إضافة خط فاصل علوي بارز
        line_y = 130
        line_margin = 50
        draw.line([(line_margin, line_y), (final_width - line_margin, line_y)], 
                 fill=ACCENT_COLOR, width=4)

        # العنوان الرئيسي (أسود)
        title_text = "COLLEGE SCHEDULE SYSTEM"
        title_bbox = draw.textbbox((0, 0), title_text, font=font_title)
        title_width = title_bbox[2] - title_bbox[0]
        title_x = (final_width - title_width) // 2
        draw.text((title_x, 40), title_text, fill=TEXT_COLOR, font=font_title)
        
        # العنوان الفرعي (أسود، أخف)
        subtitle_text = "Smart Room Management"
        subtitle_bbox = draw.textbbox((0, 0), subtitle_text, font=font_medium)
        subtitle_width = subtitle_bbox[2] - subtitle_bbox[0]
        subtitle_x = (final_width - subtitle_width) // 2
        draw.text((subtitle_x, 85), subtitle_text, fill=TEXT_COLOR, font=font_medium)

        # ضع لوجو الفريق واسم الفريق في صف واحد أسفل رمز الـ QR
        logo_path = os.path.join(os.path.dirname(__file__), '..', 'static', 'qrcodes', 'alpha-logo.png')
        print(f"QR Generator: Looking for logo at: {logo_path}")
        logo_size = 80
        logo_y = qr_y + qr_size + 18

        team_text = "Created by Alpha Team - Cybersecurity Department"
        # Use black for all texts except team name, so we'll split team name and rest
        team_name = "Alpha Team"
        prefix_text = "Created by "
        suffix_text = " - Cybersecurity Department"

        # Calculate text metrics for combined layout
        prefix_bbox = draw.textbbox((0, 0), prefix_text, font=font_small)
        name_bbox = draw.textbbox((0, 0), team_name, font=font_small)
        suffix_bbox = draw.textbbox((0, 0), suffix_text, font=font_small)
        prefix_w = prefix_bbox[2] - prefix_bbox[0]
        name_w = name_bbox[2] - name_bbox[0]
        suffix_w = suffix_bbox[2] - suffix_bbox[0]

        spacing = 12
        combined_width = logo_size + spacing + prefix_w + name_w + suffix_w
        start_x = (final_width - combined_width) // 2

        if os.path.exists(logo_path):
            print(f"QR Generator: Logo file exists, trying to load...")
            try:
                logo_img = Image.open(logo_path).convert("RGBA")
                logo_img = logo_img.resize((logo_size, logo_size), Image.Resampling.LANCZOS)
                final_img.paste(logo_img, (start_x, logo_y), logo_img)
                # Write team text next to logo: prefix (black), team name (red), suffix (black)
                text_x = start_x + logo_size + spacing
                text_y = logo_y + (logo_size - (prefix_bbox[3] - prefix_bbox[1])) // 2
                draw.text((text_x, text_y), prefix_text, fill=TEXT_COLOR, font=font_small)
                draw.text((text_x + prefix_w, text_y), team_name, fill=TEAM_COLOR, font=font_small)
                draw.text((text_x + prefix_w + name_w, text_y), suffix_text, fill=TEXT_COLOR, font=font_small)
                print(f"QR Generator: Logo loaded and team name rendered")
            except Exception as e:
                print(f"QR Generator: Error adding team logo: {e}")
                fallback_x = (final_width - (prefix_w + name_w + suffix_w)) // 2
                draw.text((fallback_x, logo_y), prefix_text, fill=TEXT_COLOR, font=font_small)
                draw.text((fallback_x + prefix_w, logo_y), team_name, fill=TEAM_COLOR, font=font_small)
                draw.text((fallback_x + prefix_w + name_w, logo_y), suffix_text, fill=TEXT_COLOR, font=font_small)
        else:
            print(f"QR Generator: Logo file does not exist")
            fallback_x = (final_width - (prefix_w + name_w + suffix_w)) // 2
            draw.text((fallback_x, logo_y), prefix_text, fill=TEXT_COLOR, font=font_small)
            draw.text((fallback_x + prefix_w, logo_y), team_name, fill=TEAM_COLOR, font=font_small)
            draw.text((fallback_x + prefix_w + name_w, logo_y), suffix_text, fill=TEXT_COLOR, font=font_small)

        # إضافة خط فاصل أسفل منطقة الـ QR/logo
        line_y = logo_y + logo_size + 12
        draw.line([(line_margin, line_y), (final_width - line_margin, line_y)],
                 fill=ACCENT_COLOR, width=3)

        # النص الرئيسي للمسح أسفل الخط (أسود)
        scan_text = "Scan the barcode to view schedule"
        scan_bbox = draw.textbbox((0, 0), scan_text, font=font_subtitle)
        scan_width = scan_bbox[2] - scan_bbox[0]
        scan_x = (final_width - scan_width) // 2
        scan_y = line_y + 12
        draw.text((scan_x, scan_y), scan_text, fill=TEXT_COLOR, font=font_subtitle)

        # معلومات القاعة (أسود)
        room_text = f"Room Code: {room_code}"
        room_bbox = draw.textbbox((0, 0), room_text, font=font_medium)
        room_width = room_bbox[2] - room_bbox[0]
        room_x = (final_width - room_width) // 2
        room_y = scan_y + 36
        draw.text((room_x, room_y), room_text, fill=TEXT_COLOR, font=font_medium)

        # النص السفلي (أسود)
        footer_text = "Powered by College Schedule System"
        footer_bbox = draw.textbbox((0, 0), footer_text, font=font_small)
        footer_width = footer_bbox[2] - footer_bbox[0]
        footer_x = (final_width - footer_width) // 2
        footer_y = room_y + 58
        draw.text((footer_x, footer_y), footer_text, fill=TEXT_COLOR, font=font_small)
        
        # إضافة زخارف في الزوايا بلمسة باهتة
        corner_size = 30
        corner_width = 4
        corner_color = ACCENT_COLOR
        draw.line([(15, 15), (15 + corner_size, 15)], fill=corner_color, width=corner_width)
        draw.line([(15, 15), (15, 15 + corner_size)], fill=corner_color, width=corner_width)
        draw.line([(final_width - 15 - corner_size, 15), (final_width - 15, 15)], 
                 fill=corner_color, width=corner_width)
        draw.line([(final_width - 15, 15), (final_width - 15, 15 + corner_size)], 
                 fill=corner_color, width=corner_width)
        draw.line([(15, final_height - 15 - corner_size), (15, final_height - 15)], 
                 fill=corner_color, width=corner_width)
        draw.line([(15, final_height - 15), (15 + corner_size, final_height - 15)], 
                 fill=corner_color, width=corner_width)
        draw.line([(final_width - 15 - corner_size, final_height - 15), 
                  (final_width - 15, final_height - 15)], fill=corner_color, width=corner_width)
        draw.line([(final_width - 15, final_height - 15 - corner_size), 
                  (final_width - 15, final_height - 15)], fill=corner_color, width=corner_width)
        
        # تحديد مسار الحفظ
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