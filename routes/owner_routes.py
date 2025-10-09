from flask import Blueprint, request, current_app
from flask_jwt_extended import jwt_required, get_jwt_identity
from models import (
    get_user_by_username,
    create_user as create_user_model,
    get_all_departments,
    get_all_users,
    update_user,
    delete_user,
    check_password,
)
from utils.helpers import (
    validate_json_data,
    format_response,
    owner_required,
    user_management_required,
    get_user_department_filter,
)
from datetime import datetime

owner_bp = Blueprint("owner", __name__)


@owner_bp.route("/dashboard", methods=["GET"])
@owner_required
def owner_dashboard():
    """لوحة تحكم المالك - إحصائيات عامة"""
    try:
        supabase = current_app.supabase
        
        # إحصائيات المستخدمين
        users_res = supabase.table("users").select("*").execute()
        total_users = len(users_res.data) if users_res.data else 0
        
        # إحصائيات الأقسام
        departments_res = supabase.table("departments").select("*").execute()
        total_departments = len(departments_res.data) if departments_res.data else 0
        
        # إحصائيات القاعات
        rooms_res = supabase.table("rooms").select("*").eq("is_active", True).execute()
        total_rooms = len(rooms_res.data) if rooms_res.data else 0
        
        # إحصائيات الجداول
        schedules_res = supabase.table("schedules").select("*").eq("is_active", True).execute()
        total_schedules = len(schedules_res.data) if schedules_res.data else 0
        
        # إحصائيات الطلاب
        students_res = supabase.table("students").select("*").execute()
        total_students = len(students_res.data) if students_res.data else 0
        
        stats = {
            'total_users': total_users,
            'total_departments': total_departments,
            'total_rooms': total_rooms,
            'total_schedules': total_schedules,
            'total_students': total_students,
        }
        
        return format_response(data=stats, message="تم جلب إحصائيات لوحة التحكم")
        
    except Exception as e:
        return format_response(
            message=f"حدث خطأ: {str(e)}", success=False, status_code=500
        )


@owner_bp.route("/users", methods=["GET"])
@owner_required
def get_all_users():
    """الحصول على جميع المستخدمين"""
    try:
        print("Owner get_all_users called")
        supabase = current_app.supabase
        
        users_res = supabase.table("users").select("*").execute()
        print(f"Users query result: {len(users_res.data) if users_res.data else 0} users")
        
        # إضافة أسماء الأقسام
        departments_res = supabase.table("departments").select("id, name").execute()
        departments_dict = {dept["id"]: dept["name"] for dept in departments_res.data}
        
        for user in users_res.data:
            # Ensure frontend expects `full_name` consistently
            if not user.get('full_name') and user.get('name'):
                user['full_name'] = user.get('name')
            
            if user.get("department_id"):
                user["department_name"] = departments_dict.get(user["department_id"], "Unknown")
            else:
                user["department_name"] = "No Department"
        
        result = format_response(data=users_res.data, message="تم جلب جميع المستخدمين")
        print(f"Returning users data: {len(users_res.data) if users_res.data else 0} users")
        return result
        
    except Exception as e:
        print(f"Error in get_all_users: {str(e)}")
        return format_response(
            message=f"حدث خطأ: {str(e)}", success=False, status_code=500
        )


@owner_bp.route("/users", methods=["POST"])
@owner_required
def create_user():
    """إنشاء مستخدم جديد"""
    try:
        supabase = current_app.supabase
        data = request.get_json()
        
        if not data:
            return format_response(
                message="لم يتم توفير بيانات", success=False, status_code=400
            )
        
        required_fields = ["username", "email", "name", "role", "password"]
        for field in required_fields:
            if field not in data or not data[field]:
                return format_response(
                    message=f"الحقل المطلوب مفقود: {field}",
                    success=False,
                    status_code=400,
                )
        
        # التحقق من عدم وجود المستخدم
        existing_user = supabase.table("users").select("*").eq("username", data["username"]).execute()
        if existing_user.data:
            return format_response(
                message="اسم المستخدم موجود بالفعل", success=False, status_code=400
            )
        
        existing_email = supabase.table("users").select("*").eq("email", data["email"]).execute()
        if existing_email.data:
            return format_response(
                message="الإيميل موجود بالفعل", success=False, status_code=400
            )
        
        # إنشاء المستخدم
        user_data = {
            'username': data['username'],
            'email': data['email'],
            'name': data['name'],
            'role': data['role'],
            'department_id': data.get('department_id'),
            'is_active': data.get('is_active', True),
            'created_at': datetime.utcnow().isoformat(),
        }
        
        # تشفير كلمة المرور
        from models import set_password
        user_data['password_hash'] = set_password(data['password'])
        
        user_res = supabase.table("users").insert(user_data).execute()
        
        if user_res.data:
            return format_response(data=user_res.data[0], message="تم إنشاء المستخدم بنجاح")
        else:
            return format_response(
                message="فشل في إنشاء المستخدم", success=False, status_code=500
            )
        
    except Exception as e:
        return format_response(
            message=f"حدث خطأ: {str(e)}", success=False, status_code=500
        )


@owner_bp.route("/users/<int:user_id>", methods=["PUT"])
@owner_required
def update_user_route(user_id):
    """تحديث مستخدم"""
    try:
        supabase = current_app.supabase
        data = request.get_json()
        
        if not data:
            return format_response(
                message="لم يتم توفير بيانات", success=False, status_code=400
            )
        
        # التحقق من وجود المستخدم
        user_res = supabase.table("users").select("*").eq("id", user_id).execute()
        if not user_res.data:
            return format_response(
                message="المستخدم غير موجود", success=False, status_code=404
            )
        
        # تحديث البيانات
        update_data = {}
        allowed_fields = ["name", "email", "role", "department_id", "is_active"]
        
        for field in allowed_fields:
            if field in data:
                update_data[field] = data[field]
        
        if data.get("password"):
            from models import set_password
            update_data['password_hash'] = set_password(data['password'])
        
        if update_data:
            updated_res = supabase.table("users").update(update_data).eq("id", user_id).execute()
            
            if updated_res.data:
                return format_response(data=updated_res.data[0], message="تم تحديث المستخدم بنجاح")
            else:
                return format_response(
                    message="فشل في تحديث المستخدم", success=False, status_code=500
                )
        else:
            return format_response(
                message="لا توجد بيانات للتحديث", success=False, status_code=400
            )
        
    except Exception as e:
        return format_response(
            message=f"حدث خطأ: {str(e)}", success=False, status_code=500
        )


@owner_bp.route("/users/<int:user_id>", methods=["DELETE"])
@owner_required
def delete_user_route(user_id):
    """حذف مستخدم"""
    try:
        supabase = current_app.supabase
        
        # التحقق من وجود المستخدم
        user_res = supabase.table("users").select("*").eq("id", user_id).execute()
        if not user_res.data:
            return format_response(
                message="المستخدم غير موجود", success=False, status_code=404
            )
        
        user = user_res.data[0]
        
        # منع حذف المالك
        if user["role"] == "owner":
            return format_response(
                message="لا يمكن حذف المالك", success=False, status_code=403
            )
        
        # حذف المستخدم
        supabase.table("users").delete().eq("id", user_id).execute()
        
        return format_response(message="تم حذف المستخدم بنجاح")
        
    except Exception as e:
        return format_response(
            message=f"حدث خطأ: {str(e)}", success=False, status_code=500
        )


@owner_bp.route("/departments", methods=["GET"])
@owner_required
def get_all_departments():
    """الحصول على جميع الأقسام"""
    try:
        supabase = current_app.supabase
        
        departments_res = supabase.table("departments").select("*").execute()
        
        return format_response(data=departments_res.data, message="تم جلب جميع الأقسام")
        
    except Exception as e:
        return format_response(
            message=f"حدث خطأ: {str(e)}", success=False, status_code=500
        )


@owner_bp.route("/system/logs", methods=["GET"])
@owner_required
def get_system_logs():
    """الحصول على سجلات النظام (استخدامات الطلاب)"""
    try:
        from models import get_recent_general_student_usages
        
        limit = request.args.get('limit', 100, type=int)
        logs = get_recent_general_student_usages(limit=limit)
        
        return format_response(data=logs, message="تم جلب سجلات النظام")
        
    except Exception as e:
        return format_response(
            message=f"حدث خطأ: {str(e)}", success=False, status_code=500
        )