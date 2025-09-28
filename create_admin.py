
import sys
import os
from datetime import datetime

# إضافة المسار الجذر للمشروع إلى مسار بايثون للسماح بالاستيراد
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from backend.app import create_app
from backend.models import db, User

def add_admin_user():
    """إنشاء مستخدم عميد أول في قاعدة البيانات"""
    app = create_app()
    with app.app_context():
        print("Creating database tables if they don't exist...")
        db.create_all()
        
        # التحقق مما إذا كان المستخدم المسؤول موجودًا بالفعل
        if User.query.filter_by(username='admin').first():
            print("Admin user already exists.")
            return

        print("Creating admin user...")
        try:
            admin_user = User(
                username='admin',
                email='moqtadali473@gmail.com',
                full_name='Admin User',
                role='dean',
                is_active=True,
                created_at=datetime.utcnow()
            )
            admin_user.set_password('admin123')
            
            db.session.add(admin_user)
            db.session.commit()
            
            print("===================================================")
            print("✅ Admin user 'admin' created successfully!")
            print("===================================================")
        except Exception as e:
            print(f"❌ Error creating admin user: {e}")
            db.session.rollback()

if __name__ == '__main__':
    add_admin_user()
