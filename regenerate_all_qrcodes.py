from app import create_app
from models import db, Room
from utils.qr_generator import generate_room_qr

app = create_app()
with app.app_context():
    rooms = Room.query.all()
    for room in rooms:
        qr_path = generate_room_qr(room.code, room.id)
        if qr_path:
            room.qr_code_path = qr_path
            print(f"تم توليد باركود جديد للقاعة: {room.code} -> {qr_path}")
    db.session.commit()
print("تمت إعادة توليد جميع الباركودات بنجاح.")
