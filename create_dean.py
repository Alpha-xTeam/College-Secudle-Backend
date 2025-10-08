import sys
import os
import argparse
import secrets
import string
from datetime import datetime

# allow imports from package root
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from backend.app import create_app
from models import create_user as create_user_model


def generate_password(length: int = 14) -> str:
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*()-_"
    return ''.join(secrets.choice(alphabet) for _ in range(length))


def main(username=None, email=None, full_name=None, password=None):
    app = create_app()
    with app.app_context():
        # توليد بيانات افتراضية إذا لم تُقدّم
        suffix = datetime.utcnow().strftime('%Y%m%d%H%M%S')[-8:]
        if not username:
            username = f'dean_auto_{suffix}'
        if not email:
            email = f'{username}@example.com'
        if not full_name:
            full_name = 'عميد جديد'
        if not password:
            password = generate_password()

        user_data = {
            'username': username,
            'email': email,
            'full_name': full_name,
            'password': password,
            'role': 'dean'
        }

        try:
            created = create_user_model(user_data)
            print('تم إنشاء حساب العميد بنجاح:')
            print(f"username: {username}")
            print(f"email: {email}")
            print(f"password: {password}")
            print('ملاحظة: خزننا كلمة المرور ليُستخدمها المسؤول لتسجيل الدخول وتغييرها لاحقاً.')
            return created
        except Exception as e:
            print('حدث خطأ أثناء إنشاء المستخدم:', str(e))
            return None


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='إنشاء حساب عميد جديد في قاعدة البيانات')
    parser.add_argument('--username', help='اسم المستخدم (اختياري)')
    parser.add_argument('--email', help='البريد الإلكتروني (اختياري)')
    parser.add_argument('--full-name', help='الاسم الكامل (اختياري)')
    parser.add_argument('--password', help='كلمة المرور (اختياري)')
    args = parser.parse_args()
    main(args.username, args.email, args.full_name, args.password)
