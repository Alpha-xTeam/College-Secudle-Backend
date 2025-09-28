from flask import Blueprint, request, current_app
from flask_jwt_extended import jwt_required
from models import create_user as create_user_model
from utils.helpers import (
    department_access_required,
    validate_json_data,
    format_response,
    get_user_department_filter,
)
from datetime import datetime

dept_bp = Blueprint("department", __name__)


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


@dept_bp.route("/supervisors", methods=["GET"])
@department_access_required
def get_supervisors(user):
    """الحصول على المشرفين في القسم (رئيس القسم فقط)"""
    try:
        if user["role"] != "department_head":
            return format_response(
                message="هذه الوظيفة متاحة لرئيس القسم فقط",
                success=False,
                status_code=403,
            )

        supabase = current_app.supabase
        supervisors_res = (
            supabase.table("users")
            .select("*")
            .eq("department_id", user["department_id"])
            .eq("role", "supervisor")
            .execute()
        )

        return format_response(
            data=supervisors_res.data, message="تم جلب المشرفين بنجاح"
        )

    except Exception as e:
        return format_response(
            message=f"حدث خطأ: {str(e)}", success=False, status_code=500
        )


@dept_bp.route("/supervisors", methods=["POST"])
@department_access_required
@validate_json_data(["username", "email", "password", "full_name"])
def create_supervisor(data, user):
    """إنشاء مشرف جديد (رئيس القسم فقط)"""
    try:
        if user["role"] != "department_head":
            return format_response(
                message="هذه الوظيفة متاحة لرئيس القسم فقط",
                success=False,
                status_code=403,
            )

        supabase = current_app.supabase
        existing_user_res = (
            supabase.table("users")
            .select("id")
            .or_(f"username.eq.{data['username']},email.eq.{data['email']}")
            .execute()
        )
        if existing_user_res.data:
            return format_response(
                message="يوجد مستخدم آخر بنفس اسم المستخدم أو البريد الإلكتروني",
                success=False,
                status_code=400,
            )

        supervisor_data = {
            "username": data["username"],
            "email": data["email"],
            "full_name": data["full_name"],
            "role": "supervisor",
            "department_id": user["department_id"],
            "is_active": data.get("is_active", True),
            "password": data["password"],
        }

        supervisor = create_user_model(supervisor_data)

        return format_response(
            data=supervisor, message="تم إنشاء المشرف بنجاح", status_code=201
        )

    except Exception as e:
        return format_response(
            message=f"حدث خطأ: {str(e)}", success=False, status_code=500
        )


@dept_bp.route("/supervisors/<int:supervisor_id>", methods=["DELETE"])
@department_access_required
def delete_supervisor(user, supervisor_id):
    """حذف مشرف (رئيس القسم فقط)"""
    try:
        if user["role"] != "department_head":
            return format_response(
                message="هذه الوظيفة متاحة لرئيس القسم فقط",
                success=False,
                status_code=403,
            )

        supabase = current_app.supabase
        supervisor_res = (
            supabase.table("users")
            .select("id")
            .eq("id", supervisor_id)
            .eq("role", "supervisor")
            .eq("department_id", user["department_id"])
            .execute()
        )

        if not supervisor_res.data:
            return format_response(
                message="المشرف غير موجود أو لا ينتمي لقسمك",
                success=False,
                status_code=404,
            )

        supabase.table("users").delete().eq("id", supervisor_id).execute()

        return format_response(message="تم حذف المشرف بنجاح")

    except Exception as e:
        return format_response(
            message=f"حدث خطأ: {str(e)}", success=False, status_code=500
        )


@dept_bp.route("/supervisors/<int:supervisor_id>", methods=["PUT"])
@department_access_required
@validate_json_data(["username", "email", "full_name"])
def update_supervisor(data, user, supervisor_id):
    """تحديث مشرف (رئيس القسم فقط)"""
    try:
        if user["role"] != "department_head":
            return format_response(
                message="هذه الوظيفة متاحة لرئيس القسم فقط",
                success=False,
                status_code=403,
            )

        supabase = current_app.supabase
        supervisor_res = (
            supabase.table("users")
            .select("id")
            .eq("id", supervisor_id)
            .eq("role", "supervisor")
            .eq("department_id", user["department_id"])
            .execute()
        )

        if not supervisor_res.data:
            return format_response(
                message="المشرف غير موجود أو لا ينتمي لقسمك",
                success=False,
                status_code=404,
            )

        existing_user_res = (
            supabase.table("users")
            .select("id")
            .neq("id", supervisor_id)
            .or_(f"username.eq.{data['username']},email.eq.{data['email']}")
            .execute()
        )
        if existing_user_res.data:
            return format_response(
                message="يوجد مستخدم آخر بنفس اسم المستخدم أو البريد الإلكتروني",
                success=False,
                status_code=400,
            )

        update_data = {
            "username": data["username"],
            "email": data["email"],
            "full_name": data["full_name"],
        }

        if data.get("password"):
            from models import set_password
            update_data["password_hash"] = set_password(data["password"])

        if "is_active" in data:
            update_data["is_active"] = data["is_active"]

        updated_supervisor_res = (
            supabase.table("users")
            .update(update_data)
            .eq("id", supervisor_id)
            .execute()
        )

        return format_response(
            data=updated_supervisor_res.data[0], message="تم تحديث المشرف بنجاح"
        )

    except Exception as e:
        return format_response(
            message=f"حدث خطأ: {str(e)}", success=False, status_code=500
        )


@dept_bp.route("/rooms", methods=["GET"])
@department_access_required
def get_rooms(user):
    """الحصول على قاعات القسم"""
    try:
        supabase = current_app.supabase
        dept_filter = get_user_department_filter(user)

        query = supabase.table("rooms").select("*").eq("is_active", True)
        if dept_filter:
            query = query.eq("department_id", dept_filter)

        rooms_res = query.execute()
        
        # Fetch departments to map department_id to department name
        departments_res = supabase.table("departments").select("id, name").execute()
        departments_dict = {dept["id"]: dept["name"] for dept in departments_res.data}
        
        # Add department name to each room
        for room in rooms_res.data:
            if room.get("department_id"):
                room["department"] = {"name": departments_dict.get(room["department_id"], "Unknown")}
            else:
                room["department"] = {"name": "No Department"}

        return format_response(data=rooms_res.data, message="تم جلب القاعات بنجاح")

    except Exception as e:
        return format_response(
            message=f"حدث خطأ: {str(e)}", success=False, status_code=500
        )


@dept_bp.route("/rooms/<int:room_id>", methods=["GET"])
@department_access_required
def get_room(user, room_id):
    """الحصول على قاعة واحدة"""
    try:
        supabase = current_app.supabase
        room_res = (
            supabase.table("rooms")
            .select("*")
            .eq("id", room_id)
            .execute()
        )

        if not room_res.data:
            return format_response(
                message="القاعة غير موجودة", success=False, status_code=404
            )

        room = room_res.data[0]
        if user["role"] != "dean" and room["department_id"] != user["department_id"]:
            return format_response(
                message="لا يمكنك الوصول لهذه القاعة", success=False, status_code=403
            )

        # Add department name to room
        if room.get("department_id"):
            department_res = supabase.table("departments").select("name").eq("id", room["department_id"]).execute()
            if department_res.data:
                room["department"] = {"name": department_res.data[0]["name"]}
            else:
                room["department"] = {"name": "Unknown"}
        else:
            room["department"] = {"name": "No Department"}

        return format_response(data=room, message="تم جلب القاعة بنجاح")

    except Exception as e:
        return format_response(
            message=f"حدث خطأ: {str(e)}", success=False, status_code=500
        )


@dept_bp.route("/schedules/<int:room_id>", methods=["GET"])
@department_access_required
def get_room_schedules(user, room_id):
    """الحصول على جداول قاعة معينة"""
    try:
        supabase = current_app.supabase
        room_res = supabase.table("rooms").select("id, department_id").eq("id", room_id).execute()
        if not room_res.data:
            return format_response(
                message="القاعة غير موجودة", success=False, status_code=404
            )

        room = room_res.data[0]
        if user["role"] != "dean" and room["department_id"] != user["department_id"]:
            return format_response(
                message="لا يمكنك الوصول لهذه القاعة", success=False, status_code=403
            )

        schedules_res = (
            supabase.table("schedules")
            .select("*, rooms!schedules_room_id_fkey(name, code), doctors!fk_doctor(name)")
            .eq("room_id", room_id)
            .eq("is_active", True)
            .execute()
        )

        # Get multiple doctors for each schedule
        from models import get_schedule_doctors
        for schedule in schedules_res.data:
            schedule_doctors = get_schedule_doctors(schedule["id"])
            schedule["schedule_doctors"] = schedule_doctors
            
            # Create a list of doctor names for display
            if schedule_doctors:
                doctor_names = []
                primary_doctor = None
                for sd in schedule_doctors:
                    doctor_name = sd.get('doctors', {}).get('name', '')
                    if sd.get('is_primary'):
                        primary_doctor = doctor_name
                    doctor_names.append(doctor_name)
                
                schedule["multiple_doctors_names"] = doctor_names
                schedule["primary_doctor_name"] = primary_doctor
                schedule["has_multiple_doctors"] = len(doctor_names) > 1

        # Check for postponements today and in the future
        from datetime import datetime
        # Use simple date comparison without timezone for now
        today = datetime.now().date()
        
        # List to store schedules that should be displayed (original or postponed)
        display_schedules = []
        
        # Process schedules to determine what should be displayed
        for schedule in schedules_res.data:
            # Check if this schedule has a postponement
            if schedule.get("is_postponed") and schedule.get("postponed_date"):
                postponed_date = datetime.strptime(schedule["postponed_date"], "%Y-%m-%d").date()
                # Check if the postponement is today or in the future
                if postponed_date >= today:
                    # Add postponement info to the schedule
                    schedule["is_postponed_today"] = (postponed_date == today)
                    schedule["postponed_to_room_id"] = schedule.get("postponed_to_room_id")
                    schedule["postponed_reason"] = schedule.get("postponed_reason")
                    schedule["postponed_start_time"] = schedule.get("postponed_start_time")
                    schedule["postponed_end_time"] = schedule.get("postponed_end_time")
                    # Add the postponed date for frontend processing
                    schedule["postponed_full_date"] = schedule.get("postponed_date")
                    
                    # Get the name of the postponed room if available
                    if schedule.get("postponed_to_room_id"):
                        postponed_room_res = (
                            supabase.table("rooms")
                            .select("name, code")
                            .eq("id", schedule["postponed_to_room_id"])
                            .execute()
                        )
                        if postponed_room_res.data:
                            schedule["postponed_room_name"] = postponed_room_res.data[0].get("name", "")
                            schedule["postponed_room_code"] = postponed_room_res.data[0].get("code", "")
                    
                    # For both future and today's postponements, show only one card - the original schedule with postponement details
                    display_schedules.append(schedule)
                else:
                    schedule["is_postponed_today"] = False
                    # Show original schedule if postponement date has passed
                    display_schedules.append(schedule)
            else:
                schedule["is_postponed_today"] = False
                # Show original schedule if no postponement
                display_schedules.append(schedule)

        return format_response(data=display_schedules, message="تم جلب الجداول بنجاح")

    except Exception as e:
        return format_response(
            message=f"حدث خطأ: {str(e)}", success=False, status_code=500
        )





@dept_bp.route("/statistics", methods=["GET"])
@department_access_required
def get_department_statistics(user):
    """إحصائيات القسم"""
    try:
        supabase = current_app.supabase
        dept_filter = get_user_department_filter(user)

        if dept_filter:
            # إحصائيات قسم محدد
            total_rooms = supabase.table("rooms").select("id", count="exact").eq("department_id", dept_filter).eq("is_active", True).execute().count
            
            # Get room IDs for the department first
            dept_rooms_res = supabase.table("rooms").select("id").eq("department_id", dept_filter).execute()
            room_ids = [r['id'] for r in dept_rooms_res.data]
            
            if room_ids:
                total_schedules = supabase.table("schedules").select("id", count="exact").eq("is_active", True).in_("room_id", room_ids).execute().count
            else:
                total_schedules = 0
            stats = {
                "total_rooms": total_rooms,
                "total_schedules": total_schedules,
            }

            if user["role"] == "department_head":
                stats["total_supervisors"] = (
                    supabase.table("users")
                    .select("id", count="exact")
                    .eq("department_id", dept_filter)
                    .eq("role", "supervisor")
                    .eq("is_active", True)
                    .execute()
                    .count
                )
        else:
            # إحصائيات شاملة للعميد
            stats = {
                "total_rooms": supabase.table("rooms").select("id", count="exact").eq("is_active", True).execute().count,
                "total_schedules": supabase.table("schedules").select("id", count="exact").eq("is_active", True).execute().count,
            }

        return format_response(data=stats, message="تم جلب الإحصائيات بنجاح")
    except Exception as e:
        return format_response(
            message=f"حدث خطأ: {str(e)}", success=False, status_code=500
        )


@dept_bp.route("/announcements", methods=["POST"])
@department_access_required
@validate_json_data(["title", "body"])
def dept_create_announcement(data, user):
    """إنشاء إعلان جديد في قسم المستخدم (رئيس القسم أو المشرف)"""
    try:
        if user["role"] not in ["department_head", "supervisor"]:
            return format_response(
                message="هذه الوظيفة متاحة لرئيس القسم أو المشرف فقط",
                success=False,
                status_code=403,
            )
        supabase = current_app.supabase
        ann_data = {
            "department_id": user["department_id"],
            "title": data["title"],
            "body": data["body"],
            "is_global": False,
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
        return format_response(message=f"حدث خطأ: {str(e)}", success=False, status_code=500)


@dept_bp.route("/announcements", methods=["GET"])
@department_access_required
def dept_get_announcements(user):
    """جلب إعلانات القسم (للعاملين في القسم)"""
    try:
        supabase = current_app.supabase
        
        # تنظيف الإعلانات المنتهية الصلاحية أولاً
        cleanup_expired_announcements_logic(supabase)
        
        now = datetime.now().isoformat()

        # جلب الإعلانات غير المنتهية فقط
        anns_res = (
            supabase.table("announcements")
            .select("*")
            .eq("department_id", user["department_id"])
            .or_(f"expires_at.is.null,expires_at.gt.{now}")
            .order("created_at", desc=True)
            .execute()
        )
        return format_response(data=anns_res.data, message="تم جلب الإعلانات")
    except Exception as e:
        return format_response(message=str(e), success=False, status_code=500)


@dept_bp.route("/announcements/<int:ann_id>", methods=["PUT"])
@department_access_required
def dept_update_announcement(user, ann_id):
    """تحديث إعلان في قسم المستخدم (رئيس القسم أو المشرف)"""
    try:
        if user["role"] not in ["department_head", "supervisor"]:
            return format_response(
                message="هذه الوظيفة متاحة لرئيس القسم أو المشرف فقط",
                success=False,
                status_code=403,
            )
        supabase = current_app.supabase
        ann_res = (
            supabase.table("announcements")
            .select("id")
            .eq("id", ann_id)
            .eq("department_id", user["department_id"])
            .execute()
        )
        if not ann_res.data:
            return format_response(
                message="الإعلان غير موجود", success=False, status_code=404
            )

        data = request.get_json() or {}
        update_data = {}
        if "title" in data:
            update_data["title"] = data["title"]
        if "body" in data:
            update_data["body"] = data["body"]
        if "is_active" in data:
            update_data["is_active"] = bool(data["is_active"])
        if "expires_at" in data:
            update_data["expires_at"] = data["expires_at"]

        if update_data:
            update_res = (
                supabase.table("announcements")
                .update(update_data)
                .eq("id", ann_id)
                .execute()
            )
            return format_response(data=update_res.data[0], message="تم تحديث الإعلان")
        else:
            return format_response(data=ann_res.data[0], message="لم يتم تحديث أي بيانات")
    except Exception as e:
        return format_response(message=str(e), success=False, status_code=500)


@dept_bp.route("/announcements/<int:ann_id>", methods=["DELETE"])
@department_access_required
def dept_delete_announcement(user, ann_id):
    """حذف إعلان في قسم المستخدم (رئيس القسم أو المشرف)"""
    try:
        if user["role"] not in ["department_head", "supervisor"]:
            return format_response(
                message="هذه الوظيفة متاحة لرئيس القسم أو المشرف فقط",
                success=False,
                status_code=403,
            )
        supabase = current_app.supabase
        ann_res = (
            supabase.table("announcements")
            .select("id")
            .eq("id", ann_id)
            .eq("department_id", user["department_id"])
            .execute()
        )
        if not ann_res.data:
            return format_response(
                message="الإعلان غير موجود", success=False, status_code=404
            )

        supabase.table("announcements").delete().eq("id", ann_id).execute()
        return format_response(message="تم حذف الإعلان")
    except Exception as e:
        return format_response(message=str(e), success=False, status_code=500)