from flask import jsonify
from functools import wraps
from flask_jwt_extended import get_jwt_identity, jwt_required
from models import get_user_by_username

def admin_required(f):
    """ديكوريتر للتحقق من صلاحيات العميد"""
    @wraps(f)
    @jwt_required()
    def decorated_function(*args, **kwargs):
        try:
            # الحصول على اسم المستخدم من JWT
            username = get_jwt_identity()
            
            # البحث عن المستخدم في قاعدة البيانات
            user = get_user_by_username(username)
            role = user.get('role') if user else None
            if not user or role not in ['dean', 'department_head']:
                return format_response(data=None, message='مطلوب صلاحيات العميد', success=False, status_code=403)
            
            return f(*args, **kwargs)
            
        except Exception as e:
            print(f"❌ خطأ في admin_required: {str(e)}")
            import traceback
            traceback.print_exc()
            return format_response(data=None, message='فشل المصادقة', success=False, status_code=500)
            
    return decorated_function

def user_management_required(f):
    """ديكوريتر للتحقق من صلاحيات إدارة المستخدمين (العميد، رئيس القسم، المشرف)"""
    @wraps(f)
    @jwt_required()
    def decorated_function(*args, **kwargs):
        try:
            # الحصول على اسم المستخدم من JWT
            username = get_jwt_identity()
            
            # البحث عن المستخدم في قاعدة البيانات
            user = get_user_by_username(username)
            role = user.get('role') if user else None
            if not user or role not in ['dean', 'department_head', 'supervisor']:
                return format_response(data=None, message='مطلوب صلاحيات إدارة المستخدمين', success=False, status_code=403)
            
            return f(*args, **kwargs)
            
        except Exception as e:
            print(f"❌ خطأ في user_management_required: {str(e)}")
            import traceback
            traceback.print_exc()
            return format_response(data=None, message='فشل المصادقة', success=False, status_code=500)
            
    return decorated_function

def department_access_required(f):
    """ديكوريتر للتحقق من صلاحيات الوصول للقسم"""
    @wraps(f)
    @jwt_required()
    def decorated_function(*args, **kwargs):
        try:
            # الحصول على اسم المستخدم من JWT
            username = get_jwt_identity()
            
            # البحث عن المستخدم في قاعدة البيانات
            user = get_user_by_username(username)
            if not user:
                return format_response(data=None, message='المستخدم غير موجود', success=False, status_code=404)
            
            role = user.get('role')
            if role not in ['dean', 'department_head', 'supervisor']:
                return format_response(data=None, message='تم رفض الوصول', success=False, status_code=403)
            
            return f(user=user, *args, **kwargs)
            
        except Exception as e:
            print(f"❌ خطأ في المصادقة: {str(e)}")
            return format_response(data=None, message='فشل المصادقة', success=False, status_code=500)
            
    return decorated_function

def validate_json_data(required_fields):
    """ديكوريتر للتحقق من البيانات المطلوبة في JSON"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            from flask import request
            
            if not request.is_json:
                return jsonify({'error': 'Request must be JSON'}), 400
            
            data = request.get_json()
            missing_fields = []
            
            for field in required_fields:
                if field not in data or not data[field]:
                    missing_fields.append(field)
            
            if missing_fields:
                return jsonify({
                    'error': 'Missing required fields',
                    'missing_fields': missing_fields
                }), 400
            
            return f(data=data, *args, **kwargs)
        return decorated_function
    return decorator

def format_response(data=None, message=None, success=True, status_code=200):
    """تنسيق الاستجابة القياسية"""
    from flask import jsonify
    response = {
        'success': success,
        'message': message,
        'data': data
    }
    return jsonify(response), status_code

def get_user_department_filter(user):
    """الحصول على فلتر القسم حسب المستخدم"""
    if user['role'] == 'dean':
        return None  # العميد يرى جميع الأقسام
    else:
        return user['department_id']  # رئيس القسم والمشرف يرون قسمهم فقط

def validate_time_format(time_str):
    """التحقق من صيغة الوقت"""
    try:
        from datetime import datetime
        datetime.strptime(time_str, '%H:%M')
        return True
    except ValueError:
        return False

def validate_day_of_week(day):
    """التحقق من صحة يوم الأسبوع"""
    valid_days = ['sunday', 'monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday']
    return day.lower() in valid_days

def validate_study_type(study_type):
    """التحقق من نوع الدراسة"""
    valid_types = ['morning', 'evening']
    return study_type.lower() in valid_types

def validate_academic_stage(stage):
    """التحقق من المرحلة الدراسية"""
    valid_stages = ['first', 'second', 'third', 'fourth']
    return stage.lower() in valid_stages


def get_user_role(username: str):
    """
    Retrieves the role of a user given their username.
    """
    user = get_user_by_username(username)
    return user.get('role') if user else None

def get_current_user():
    """
    Helper function to get the current user from the JWT identity.
    """
    username = get_jwt_identity()
    if not username:
        return None
    return get_user_by_username(username)