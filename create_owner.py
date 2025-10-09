from models import create_user
from models import set_password

def create_owner():
    """إنشاء مستخدم المالك"""
    owner_data = {
        'username': 'owner',
        'email': 'owner@it-college.zone.id',
        'name': 'Owner',
        'role': 'owner',
        'department_id': None,  # المالك لا ينتمي لقسم
        'is_active': True
    }
    
    password = 'owner#2005'
    password_hash = set_password(password)
    owner_data['password_hash'] = password_hash
    
    user = create_user(owner_data)
    if user:
        print("تم إنشاء مستخدم المالك بنجاح")
        print(f"الاسم: {user['username']}")
        print(f"الإيميل: {user['email']}")
        print(f"الرتبة: {user['role']}")
    else:
        print("فشل في إنشاء مستخدم المالك")

if __name__ == "__main__":
    create_owner()