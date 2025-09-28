from app import create_app
from utils.qr_generator import generate_room_qr

app = create_app()
with app.app_context():
    supabase = app.supabase
    rooms_res = supabase.table("rooms").select("*").eq("is_active", True).execute()
    for room in rooms_res.data:
        qr_path = generate_room_qr(room["code"], room["id"])
        if qr_path:
            supabase.table("rooms").update({"qr_code_path": qr_path}).eq("id", room["id"]).execute()
            print(f"تم توليد باركود جديد للقاعة: {room['code']} -> {qr_path}")
print("تمت إعادة توليد جميع الباركودات بنجاح.")
