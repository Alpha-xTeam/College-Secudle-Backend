from flask import Blueprint, request, current_app
from flask_jwt_extended import jwt_required
from models import (
    get_all_departments,
    get_user_by_username,
    create_user as create_user_model,
    get_room_by_code,
    get_schedules_by_room_id,
    get_all_announcements,
)
from utils.helpers import validate_json_data, format_response, admin_required, user_management_required
from datetime import datetime, timedelta

dean_bp = Blueprint("dean", __name__)


def cleanup_expired_announcements_logic(supabase):
    """دالة مساعدة لتنظيف الإعلانات المنتهية الصلاحية"""
    try:
        now = datetime.now().isoformat()
        
        # البحث عن الإعلانات المنتهية الصلاحية
        expired_anns_res = supabase.table("announcements").select("id, title, expires_at").execute()
        
        # تصفية الإعلانات المنتهية يدوياً
        expired_ids = []
        for ann in expired_anns_res.data:
            if ann.get("expires_at") and ann["expires_at"] < now:
                expired_ids.append(ann["id"])
        
        # حذف الإعلانات المنتهية إذا وجدت
        if expired_ids:
            for ann_id in expired_ids:
                supabase.table("announcements").delete().eq("id", ann_id).execute()
            print(f"تم حذف {len(expired_ids)} إعلان منتهي الصلاحية تلقائياً")
            
    except Exception as e:
        print(f"خطأ في تنظيف الإعلانات المنتهية: {str(e)}")





@dean_bp.route("/schedules/<int:schedule_id>", methods=["GET"])
@admin_required
def get_schedule(schedule_id):
    """جلب معلومات جدول محاضرة معين"""
    try:
        supabase = current_app.supabase
        schedule_res = supabase.table("schedules").select("*, rooms(code)").eq("id", schedule_id).execute() # Select room code
        if not schedule_res.data:
            return format_response(
                message="الجدول غير موجود",
                success=False,
                status_code=404,
            )
        
        schedule_data = schedule_res.data[0]

        # If it's a temporary move, fetch original room details
        if schedule_data.get("is_temporary") and schedule_data.get("original_room_id"):
            original_room_res = supabase.table("rooms").select("code").eq("id", schedule_data["original_room_id"]).execute()
            if original_room_res.data:
                schedule_data["original_room_code"] = original_room_res.data[0]["code"]
            else:
                schedule_data["original_room_code"] = None # Or handle as appropriate if original room not found

        return format_response(
            data=schedule_data,
            message="تم جلب معلومات الجدول بنجاح",
            status_code=200,
        )
    except Exception as e:
        print(f"Error fetching schedule: {str(e)}")
        return format_response(
            message=f"حدث خطأ في الخادم أثناء جلب الجدول: {str(e)}", success=False, status_code=500
        )


@dean_bp.route("/schedules/<int:schedule_id>", methods=["PUT"])
@admin_required
@validate_json_data(["room_id", "booking_date", "start_time", "end_time", "move_reason"])
def update_schedule(schedule_id, data):
    """تحديث جدول محاضرة موجود (لنقل محاضرة متعارضة)"""
    try:
        supabase = current_app.supabase

        # Fetch the current schedule details to store as original
        original_schedule_res = supabase.table("schedules").select("*").eq("id", schedule_id).execute()
        if not original_schedule_res.data:
            return format_response(
                message="الجدول غير موجود",
                success=False,
                status_code=404,
            )
        original_schedule = original_schedule_res.data[0]

        room_id = data["room_id"]
        booking_date_str = data["booking_date"]
        start_time_str = data["start_time"]
        end_time_str = data["end_time"]
        move_reason = data.get("move_reason", None) # New field

        # Convert booking_date to day_of_week
        booking_date = datetime.strptime(booking_date_str, "%Y-%m-%d").date()
        day_of_week = booking_date.strftime("%A").lower() # e.g., "monday"

        # Validate times
        start_time = datetime.strptime(start_time_str, "%H:%M").time()
        end_time = datetime.strptime(end_time_str, "%H:%M").time()
        if start_time >= end_time:
            return format_response(
                message="وقت البدء يجب أن يكون قبل وقت الانتهاء",
                success=False,
                status_code=400,
            )

        # Check if the target room exists and is active
        target_room_res = supabase.table("rooms").select("id").eq("id", room_id).eq("is_active", True).execute()
        if not target_room_res.data:
            return format_response(
                message="القاعة المستهدفة غير موجودة أو غير نشطة",
                success=False,
                status_code=404,
            )

        # Check for conflicts in the NEW location (excluding the schedule being moved)
        conflicting_schedule_res = (
            supabase.table("schedules")
            .select("*")  # Select all fields to return to frontend
            .eq("room_id", room_id)
            .eq("day_of_week", day_of_week)
            .eq("is_active", True)
            .neq("id", schedule_id) # Exclude the current schedule being updated
            .lt("start_time", end_time_str)
            .gt("end_time", start_time_str)
            .execute()
        )

        if conflicting_schedule_res.data:
            # Return conflicting schedule details to frontend for user action
            return format_response(
                message="القاعة الجديدة مشغولة في هذا الوقت المحدد. يرجى تغيير توقيت المحاضرة الأصلية أو مكانها.",
                success=False,
                status_code=409,  # Conflict
                data=conflicting_schedule_res.data[0]  # Return the conflicting schedule
            )

        # Update the schedule
        update_data = {
            "room_id": room_id,
            "day_of_week": day_of_week,
            "start_time": start_time_str,
            "end_time": end_time_str,
            "is_temporary": True,
            "original_room_id": original_schedule["room_id"],
            "original_booking_date": original_schedule["booking_date"], # Assuming booking_date is stored in original_schedule
            "original_start_time": original_schedule["start_time"],
            "original_end_time": original_schedule["end_time"],
            "move_reason": move_reason
        }

        supabase.table("schedules").update(update_data).eq("id", schedule_id).execute()

        return format_response(
            message="تم نقل المحاضرة بنجاح إلى القاعة والوقت الجديدين.",
            status_code=200,
        )

    except Exception as e:
        print(f"Error updating schedule: {str(e)}")
        return format_response(
            message=f"حدث خطأ في الخادم أثناء تحديث الجدول: {str(e)}", success=False, status_code=500
        )


@dean_bp.route("/departments", methods=["GET"])
@user_management_required
def get_departments_route():
    """الحصول على جميع الأقسام"""
    try:
        departments = get_all_departments()
        return format_response(data=departments, message="تم جلب الأقسام بنجاح")
    except Exception as e:
        return format_response(
            message=f"حدث خطأ: {str(e)}", success=False, status_code=500
        )


@dean_bp.route("/announcements", methods=["GET"])
@admin_required
def dean_get_announcements():
    """جلب إعلانات عامة (العميد)"""
    try:
        supabase = current_app.supabase
        
        # تنظيف الإعلانات المنتهية الصلاحية أولاً
        cleanup_expired_announcements_logic(supabase)
        
        anns_res = (
            supabase.table("announcements")
            .select("*")
            .eq("is_global", True)
            .eq("is_active", True)
            .order("created_at", desc=True)
            .execute()
        )
        return format_response(data=anns_res.data, message="تم جلب الإعلانات")
    except Exception as e:
        return format_response(message=str(e), success=False, status_code=500)


@dean_bp.route("/announcements", methods=["POST"])
@admin_required
@validate_json_data(["title", "body"])
def dean_create_announcement(data):
    """إنشاء إعلان عام (العميد)"""
    try:
        supabase = current_app.supabase
        ann_data = {
            "department_id": None,
            "title": data["title"],
            "body": data["body"],
            "is_global": True,
            "is_active": True,
        }
        if data.get("starts_at"):
            ann_data["starts_at"] = data["starts_at"]
        if data.get("expires_at"):
            ann_data["expires_at"] = data["expires_at"]

        ann_res = supabase.table("announcements").insert(ann_data).execute()
        return format_response(
            data=ann_res.data[0], message="تم إنشاء الإعلان", status_code=201
        )
    except Exception as e:
        return format_response(message=str(e), success=False, status_code=500)


@dean_bp.route("/announcements/<int:ann_id>", methods=["PUT"])
@admin_required
def dean_update_announcement(ann_id):
    try:
        supabase = current_app.supabase
        data = request.get_json() or {}
        
        ann_res = supabase.table("announcements").select("*").eq("id", ann_id).eq("is_global", True).execute()
        if not ann_res.data:
            return format_response(message="الإعلان غير موجود", success=False, status_code=404)

        update_data = {}
        if "title" in data:
            update_data["title"] = data["title"]
        if "body" in data:
            update_data["body"] = data["body"]
        if "is_active" in data:
            update_data["is_active"] = bool(data["is_active"])
        if "starts_at" in data:
            update_data["starts_at"] = data["starts_at"]
        if "expires_at" in data:
            update_data["expires_at"] = data["expires_at"]

        if update_data:
            update_res = supabase.table("announcements").update(update_data).eq("id", ann_id).execute()
            return format_response(data=update_res.data[0], message="تم تحديث الإعلان")
        else:
            return format_response(data=ann_res.data[0], message="لم يتم تحديث أي بيانات")

    except Exception as e:
        return format_response(message=str(e), success=False, status_code=500)


@dean_bp.route("/announcements/<int:ann_id>", methods=["DELETE"])
@admin_required
def dean_delete_announcement(ann_id):
    try:
        supabase = current_app.supabase
        ann_res = supabase.table("announcements").select("*").eq("id", ann_id).eq("is_global", True).execute()
        if not ann_res.data:
            return format_response(message="الإعلان غير موجود", success=False, status_code=404)
        
        supabase.table("announcements").delete().eq("id", ann_id).execute()
        return format_response(message="تم حذف الإعلان")
    except Exception as e:
        return format_response(message=str(e), success=False, status_code=500)


@dean_bp.route("/departments", methods=["POST"])
@admin_required
@validate_json_data(["name", "code"])
def create_department(data):
    """إنشاء قسم جديد"""
    try:
        supabase = current_app.supabase
        existing_dept_res = supabase.table("departments").select("id").eq("code", data["code"]).execute()
        if existing_dept_res.data:
            return format_response(
                message="يوجد قسم آخر بنفس الرمز", success=False, status_code=400
            )

        department_res = (
            supabase.table("departments")
            .insert(
                {
                    "name": data["name"],
                    "code": data["code"],
                    "description": data.get("description", ""),
                }
            )
            .execute()
        )

        return format_response(
            data=department_res.data[0],
            message="تم إنشاء القسم بنجاح",
            status_code=201,
        )

    except Exception as e:
        return format_response(
            message=f"حدث خطأ: {str(e)}", success=False, status_code=500
        )


@dean_bp.route("/departments/<int:dept_id>", methods=["PUT"])
@admin_required
@validate_json_data(["name", "code"])
def update_department(data, dept_id):
    """تحديث بيانات القسم"""
    try:
        supabase = current_app.supabase
        
        existing_dept_res = (
            supabase.table("departments")
            .select("id")
            .neq("id", dept_id)
            .or_("name.eq." + data['name'] + ",code.eq." + data['code'])
            .execute()
        )
        if existing_dept_res.data:
            return format_response(
                message="يوجد قسم آخر بنفس الاسم أو الرمز",
                success=False,
                status_code=400,
            )

        department_res = (
            supabase.table("departments")
            .update(
                {
                    "name": data["name"],
                    "code": data["code"],
                    "description": data.get("description"),
                }
            )
            .eq("id", dept_id)
            .execute()
        )

        return format_response(
            data=department_res.data[0], message="تم تحديث القسم بنجاح"
        )

    except Exception as e:
        return format_response(
            message=f"حدث خطأ: {str(e)}", success=False, status_code=500
        )


@dean_bp.route("/departments/<int:dept_id>", methods=["DELETE"])
@admin_required
def delete_department(dept_id):
    """حذف القسم"""
    try:
        supabase = current_app.supabase
        
        users_count_res = supabase.table("users").select("id", count="exact").eq("department_id", dept_id).execute()
        rooms_count_res = supabase.table("rooms").select("id", count="exact").eq("department_id", dept_id).execute()

        if users_count_res.count > 0 or rooms_count_res.count > 0:
            return format_response(
                message="لا يمكن حذف القسم لوجود مستخدمين أو قاعات مرتبطة به",
                success=False,
                status_code=400,
            )

        supabase.table("departments").delete().eq("id", dept_id).execute()

        return format_response(message="تم حذف القسم بنجاح")

    except Exception as e:
        return format_response(
            message=f"حدث خطأ: {str(e)}", success=False, status_code=500
        )


@dean_bp.route("/users", methods=["GET"])
@user_management_required
def get_users():
    """الحصول على جميع المستخدمين"""
    try:
        supabase = current_app.supabase
        
        # Fetch users without joining departments
        users_res = supabase.table("users").select("*").neq("role", "dean").execute()
        
        # Fetch departments to map department_id to department name
        departments_res = supabase.table("departments").select("id, name").execute()
        departments_dict = {dept["id"]: dept["name"] for dept in departments_res.data}
        
        # Add department name to each user
        for user in users_res.data:
            if user.get("department_id"):
                user["department"] = {"name": departments_dict.get(user["department_id"], "Unknown")}
            else:
                user["department"] = {"name": "No Department"}
        
        return format_response(data=users_res.data, message="تم جلب المستخدمين بنجاح")

    except Exception as e:
        print(f"ERROR in get_users: {str(e)}")
        import traceback
        traceback.print_exc()
        return format_response(
            message=f"حدث خطأ: {str(e)}", success=False, status_code=500
        )


@dean_bp.route("/users", methods=["POST"])
@user_management_required
@validate_json_data(["username", "email", "password", "full_name", "role"])
def create_user(data):
    """إنشاء مستخدم جديد"""
    try:
        supabase = current_app.supabase
        
        existing_user_res = (
            supabase.table("users")
            .select("id")
            .or_("username.eq." + data['username'] + ",email.eq." + data['email'])
            .execute()
        )
        if existing_user_res.data:
            return format_response(
                message="يوجد مستخدم آخر بنفس اسم المستخدم أو البريد الإلكتروني",
                success=False,
                status_code=400,
            )

        if data["role"] not in ["dean", "department_head", "supervisor"]:
            return format_response(
                message="نوع المستخدم غير صحيح", success=False, status_code=400
            )

        if data["role"] != "dean":
            if not data.get("department_id"):
                return format_response(
                    message="يجب اختيار القسم لهذا الدور",
                    success=False,
                    status_code=400,
                )
            
            department_res = supabase.table("departments").select("id").eq("id", data["department_id"]).execute()
            if not department_res.data:
                return format_response(
                    message="القسم المحدد غير موجود", success=False, status_code=400
                )

        user_data = {
            "username": data["username"],
            "email": data["email"],
            "full_name": data["full_name"],
            "role": data["role"],
            "department_id": data.get("department_id")
            if data["role"] != "dean"
            else None,
        }
        
        user = create_user_model(user_data)

        return format_response(
            data=user, message="تم إنشاء المستخدم بنجاح", status_code=201
        )

    except Exception as e:
        return format_response(
            message=f"حدث خطأ: {str(e)}", success=False, status_code=500
        )


@dean_bp.route("/users/<int:user_id>", methods=["DELETE"])
@user_management_required
def delete_user(user_id):
    """حذف مستخدم"""
    try:
        supabase = current_app.supabase
        user_res = supabase.table("users").select("role").eq("id", user_id).execute()
        if not user_res.data:
            return format_response(message="المستخدم غير موجود", success=False, status_code=404)

        if user_res.data[0]["role"] == "dean":
            return format_response(
                message="لا يمكن حذف حساب العميد", success=False, status_code=400
            )

        supabase.table("users").delete().eq("id", user_id).execute()

        return format_response(message="تم حذف المستخدم بنجاح")

    except Exception as e:
        return format_response(
            message=f"حدث خطأ: {str(e)}", success=False, status_code=500
        )


@dean_bp.route("/statistics", methods=["GET"])
@admin_required
def get_statistics():
    """إحصائيات عامة للعميد"""
    try:
        supabase = current_app.supabase
        
        departments_count = supabase.table("departments").select("id", count="exact").execute().count
        users_count = supabase.table("users").select("id", count="exact").neq("role", "dean").execute().count
        rooms_count = supabase.table("rooms").select("id", count="exact").execute().count
        department_heads_count = supabase.table("users").select("id", count="exact").eq("role", "department_head").execute().count
        supervisors_count = supabase.table("users").select("id", count="exact").eq("role", "supervisor").execute().count

        stats = {
            "total_departments": departments_count,
            "total_users": users_count,
            "total_rooms": rooms_count,
            "department_heads": department_heads_count,
            "supervisors": supervisors_count,
        }

        return format_response(data=stats, message="تم جلب الإحصائيات بنجاح")

    except Exception as e:
        return format_response(
            message=f"حدث خطأ: {str(e)}", success=False, status_code=500
        )


@dean_bp.route("/cleanup-expired-announcements", methods=["POST"])
@admin_required
def cleanup_expired_announcements():
    """تنظيف الإعلانات المنتهية الصلاحية وحذفها من قاعدة البيانات"""
    try:
        supabase = current_app.supabase
        now = datetime.now().isoformat()
        
        # البحث عن الإعلانات المنتهية الصلاحية
        expired_anns_res = supabase.table("announcements").select("id, title, expires_at").execute()
        
        # تصفية الإعلانات المنتهية يدوياً
        expired_announcements = []
        for ann in expired_anns_res.data:
            if ann.get("expires_at") and ann["expires_at"] < now:
                expired_announcements.append(ann)
        
        if not expired_announcements:
            return format_response(
                data={"deleted_count": 0, "deleted_announcements": []},
                message="لا توجد إعلانات منتهية الصلاحية"
            )
        
        expired_ids = [ann["id"] for ann in expired_announcements]
        
        # حذف الإعلانات المنتهية
        for ann_id in expired_ids:
            supabase.table("announcements").delete().eq("id", ann_id).execute()
        
        return format_response(
            data={
                "deleted_count": len(expired_announcements),
                "deleted_announcements": expired_announcements
            },
            message=f"تم حذف {len(expired_announcements)} إعلان منتهي الصلاحية بنجاح"
        )
        
    except Exception as e:
        return format_response(
            message=f"حدث خطأ أثناء تنظيف الإعلانات: {str(e)}", 
            success=False, 
            status_code=500
        )


@dean_bp.route("/users/<int:user_id>", methods=["PATCH"])
@user_management_required
def update_user_partial(user_id):
    """تحديث جزئي لمستخدم (PATCH)"""
    try:
        supabase = current_app.supabase
        data = request.get_json() or {}

        # Fetch target user
        target_res = supabase.table("users").select("*").eq("id", user_id).execute()
        if not target_res.data:
            return format_response(message="المستخدم غير موجود", success=False, status_code=404)
        target_user = target_res.data[0]

        # Determine current user and permissions
        from flask_jwt_extended import get_jwt_identity
        username = get_jwt_identity()
        current_user = get_user_by_username(username)
        if not current_user:
            return format_response(message="المستخدم الحالي غير موجود", success=False, status_code=401)

        # Supervisors cannot update users
        if current_user.get("role") == "supervisor":
            return format_response(message="ليس لديك صلاحية لتعديل المستخدمين", success=False, status_code=403)

        # Department heads can only update users within their department
        if current_user.get("role") == "department_head" and target_user.get("department_id") != current_user.get("department_id"):
            return format_response(message="لا يمكنك تعديل مستخدمين خارج قسمك", success=False, status_code=403)

        # Only dean can change role or department
        if ("role" in data or "department_id" in data) and current_user.get("role") != "dean":
            return format_response(message="فقط العميد يمكنه تغيير الدور أو القسم", success=False, status_code=403)

        # Prevent promoting someone to dean
        if data.get("role") == "dean":
            return format_response(message="لا يمكن تعيين دور العميد عبر هذه الواجهة", success=False, status_code=400)

        update_data = {}

        # Validate username/email uniqueness if provided
        if "username" in data and data["username"] and data["username"] != target_user.get("username"):
            existing_res = supabase.table("users").select("id").neq("id", user_id).eq("username", data["username"]).execute()
            if existing_res.data:
                return format_response(message="يوجد مستخدم آخر بنفس اسم المستخدم", success=False, status_code=400)
            update_data["username"] = data["username"]

        if "email" in data and data["email"] and data["email"] != target_user.get("email"):
            existing_res = supabase.table("users").select("id").neq("id", user_id).eq("email", data["email"]).execute()
            if existing_res.data:
                return format_response(message="يوجد مستخدم آخر بنفس البريد الإلكتروني", success=False, status_code=400)
            update_data["email"] = data["email"]

        if "full_name" in data and data["full_name"] and data["full_name"] != target_user.get("full_name"):
            update_data["full_name"] = data["full_name"]

        if "role" in data and data["role"] and data["role"] != target_user.get("role"):
            if data["role"] not in ["dean", "department_head", "supervisor"]:
                return format_response(message="نوع المستخدم غير صحيح", success=False, status_code=400)
            update_data["role"] = data["role"]

        if "department_id" in data:
            # For dean role department_id is stored as None
            if data.get("department_id") in [None, ""]:
                update_data["department_id"] = None
            else:
                # verify department exists
                dept_res = supabase.table("departments").select("id").eq("id", data["department_id"]).execute()
                if not dept_res.data:
                    return format_response(message="القسم المحدد غير موجود", success=False, status_code=400)
                update_data["department_id"] = data["department_id"]

        if "is_active" in data:
            update_data["is_active"] = bool(data.get("is_active"))

        if "password" in data and data.get("password"):
            from models import set_password
            update_data["password_hash"] = set_password(data["password"])

        if not update_data:
            return format_response(data=target_user, message="لم يتم تحديث أي بيانات")

        updated_res = supabase.table("users").update(update_data).eq("id", user_id).execute()

        return format_response(data=updated_res.data[0] if updated_res.data else {}, message="تم تحديث المستخدم بنجاح")

    except Exception as e:
        import traceback
        traceback.print_exc()
        return format_response(message=f"حدث خطأ: {str(e)}", success=False, status_code=500)