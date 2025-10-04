from flask import Blueprint, request, current_app
from flask_jwt_extended import create_access_token, jwt_required, get_jwt_identity
from models import get_user_by_username, get_user_by_email, check_password, set_password
from utils.helpers import validate_json_data, format_response
from datetime import datetime, timezone

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
        
        temp_used = False
        # First try main password
        if not check_password(user['password_hash'], password):
            # Try temp password if present and not yet used
            tp_hash = user.get('temp_password_hash')
            tp_used_flag = user.get('temp_password_used')
            if tp_hash and not tp_used_flag:
                # If the temp password matches, mark it used (one-time) and allow login
                if check_password(tp_hash, password):
                    # Persist temp_password_used = True to prevent reuse
                    try:
                        current_app.supabase.table('users').update({'temp_password_used': True}).eq('id', user.get('id')).execute()
                    except Exception:
                        # Non-fatal: log and continue
                        current_app.logger.exception('Failed to mark temp_password_used')
                    temp_used = True
                else:
                    return format_response(message='كلمة المرور غير صحيحة', success=False, status_code=401)
            else:
                # No temp hash or already used
                return format_response(message='كلمة المرور غير صحيحة أو مستخدمة مسبقاً', success=False, status_code=401)
        
        # إنشاء JWT token باستخدام username كـ string بسيط
        access_token = create_access_token(identity=user['username'])
        
        # Sanitize user object (do not return password hashes)
        safe_user = {k: v for k, v in user.items() if k not in ('password_hash', 'temp_password_hash', 'temp_password_expires_at')}

        return format_response(
            data={
                'access_token': access_token,
                'user': safe_user,
                'must_change_password': temp_used
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
        current = data['current_password']
        valid_current = False
        # Check main password
        if check_password(user['password_hash'], current):
            valid_current = True
            used_temp = False
        else:
            # Check temp password (no expiry — one-time token semantics handled at login)
            tp_hash = user.get('temp_password_hash')
            if tp_hash and check_password(tp_hash, current):
                valid_current = True
                used_temp = True

        if not valid_current:
            return format_response(
                message='كلمة المرور الحالية غير صحيحة',
                success=False,
                status_code=400
            )
        
        # تحديث كلمة المرور
        new_password_hash = set_password(data['new_password'])
        supabase = current_app.supabase
        # Update password and remove any temp password fields if present
        update_payload = {
            'password_hash': new_password_hash,
            'temp_password_hash': None,
            'temp_password_expires_at': None,
            'temp_password_used': True
        }
        response = supabase.table('users').update(update_payload).eq('username', username).execute()

        err = getattr(response, 'error', None)
        if err:
            raise Exception(err)

        return format_response(
            message='تم تغيير كلمة المرور بنجاح'
        )
        
    except Exception as e:
        return format_response(
            message=f'حدث خطأ: {str(e)}',
            success=False,
            status_code=500
        )