from flask import Blueprint, request, current_app
from flask_jwt_extended import create_access_token, jwt_required, get_jwt_identity
from models import get_user_by_username, get_user_by_email, check_password, set_password
from utils.helpers import validate_json_data, format_response

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/login', methods=['POST'])
def login():
    """تسجيل الدخول - يقبل البريد الإلكتروني أو اسم المستخدم"""
    try:
        data = request.get_json()
        
        if not data or 'username' not in data or 'password' not in data:
            return format_response(
                message='يرجى إدخال اسم المستخدم وكلمة المرور',
                success=False,
                status_code=400
            )
        
        login_identifier = data['username']  # يمكن أن يكون بريد إلكتروني أو اسم مستخدم
        password = data['password']
        
        # البحث عن المستخدم بالبريد الإلكتروني أو اسم المستخدم
        user = get_user_by_username(login_identifier)
        if not user:
            user = get_user_by_email(login_identifier)

        if not user:
            return format_response(
                message='اسم المستخدم غير موجود',
                success=False,
                status_code=401
            )
        
        if not check_password(user['password_hash'], password):
            return format_response(
                message='كلمة المرور غير صحيحة',
                success=False,
                status_code=401
            )
        
        # إنشاء JWT token باستخدام username كـ string بسيط
        access_token = create_access_token(identity=user['username'])
        
        return format_response(
            data={
                'access_token': access_token,
                'user': user
            },
            message=f"مرحباً {user['full_name']} - تم تسجيل الدخول بنجاح"
        )
        
    except Exception as e:
        print(f"خطأ في تسجيل الدخول: {str(e)}")  # للتشخيص
        return format_response(
            message=f'حدث خطأ في الخادم: {str(e)}',
            success=False,
            status_code=500
        )

@auth_bp.route('/profile', methods=['GET'])
@jwt_required()
def get_profile():
    """الحصول على معلومات المستخدم الحالي"""
    try:
        username = get_jwt_identity()
        user = get_user_by_username(username)
        
        if not user:
            return format_response(
                message='المستخدم غير موجود',
                success=False,
                status_code=404
            )
        
        return format_response(
            data=user,
            message='تم جلب البيانات بنجاح'
        )
        
    except Exception as e:
        return format_response(
            message=f'حدث خطأ: {str(e)}',
            success=False,
            status_code=500
        )

@auth_bp.route('/change-password', methods=['POST'])
@jwt_required()
@validate_json_data(['current_password', 'new_password'])
def change_password(data):
    """تغيير كلمة المرور"""
    try:
        username = get_jwt_identity()
        user = get_user_by_username(username)
        
        if not user:
            return format_response(
                message='المستخدم غير موجود',
                success=False,
                status_code=404
            )
        
        # التحقق من كلمة المرور الحالية
        if not check_password(user['password_hash'], data['current_password']):
            return format_response(
                message='كلمة المرور الحالية غير صحيحة',
                success=False,
                status_code=400
            )
        
        # تحديث كلمة المرور
        new_password_hash = set_password(data['new_password'])
        supabase = current_app.supabase
        response = supabase.table('users').update({'password_hash': new_password_hash}).eq('username', username).execute()

        if response.get('error'):
            raise Exception(response['error'])

        return format_response(
            message='تم تغيير كلمة المرور بنجاح'
        )
        
    except Exception as e:
        return format_response(
            message=f'حدث خطأ: {str(e)}',
            success=False,
            status_code=500
        )