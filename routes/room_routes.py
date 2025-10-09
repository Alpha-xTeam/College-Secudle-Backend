from flask import Blueprint, request, send_file, current_app
from flask_jwt_extended import jwt_required, get_jwt_identity
from models import get_user_by_username
from utils.helpers import (
    department_access_required,
    validate_json_data,
    format_response,
    get_user_department_filter,
    validate_time_format,
    validate_day_of_week,
    validate_study_type,
    validate_academic_stage,
)
from utils.qr_generator import generate_room_qr, delete_room_qr
import os
import io

room_bp = Blueprint("rooms", __name__)


@room_bp.route("/", methods=["GET"], strict_slashes=False)
@jwt_required()
def get_rooms():
    """الحصول على جميع القاعات"""
    try:
        supabase = current_app.supabase
        username = get_jwt_identity()
        user = get_user_by_username(username)

        if not user:
            return format_response(
                message="المستخدم غير موجود", success=False, status_code=404
            )

        # Fetch rooms without joining departments
        query = supabase.table("rooms").select("*").eq("is_active", True)

        # Allow 'dean' and 'owner' to view all rooms. Other roles must be tied to a department.
        if user["role"] not in ["dean", "owner"]:
            if not user.get("department_id"):
                return format_response(
                    message="المستخدم غير مرتبط بقسم",
                    success=False,
                    status_code=403,
                )
            query = query.eq("department_id", user["department_id"])

        rooms_res = query.execute()
        
        # Fetch departments to map department_id to department name (defensive: table may not exist)
        departments_dict = {}
        try:
            departments_res = supabase.table("departments").select("id, name").execute()
            if departments_res and getattr(departments_res, 'data', None):
                departments_dict = {dept["id"]: dept["name"] for dept in departments_res.data}
        except Exception:
            departments_dict = {}
        
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


@room_bp.route("/", methods=["POST"])
@jwt_required()
def create_room():
    """إنشاء قاعة جديدة"""
    try:
        supabase = current_app.supabase
        data = request.get_json()
        if not data:
            return format_response(
                message="لم يتم توفير بيانات", success=False, status_code=400
            )

        required_fields = ["name", "code"]
        for field in required_fields:
            if field not in data or not data[field]:
                return format_response(
                    message=f"الحقل المطلوب مفقود: {field}",
                    success=False,
                    status_code=400,
                )

        username = get_jwt_identity()
        user = get_user_by_username(username)

        if not user:
            return format_response(
                message="المستخدم غير موجود", success=False, status_code=404
            )

        if user["role"] not in ["owner", "dean", "department_head", "supervisor"]:
            return format_response(
                message="صلاحيات غير كافية", success=False, status_code=403
            )

        existing_room_res = (
            supabase.table("rooms").select("id").eq("code", data["code"]).execute()
        )
        if existing_room_res.data:
            return format_response(
                message="رمز القاعة موجود مسبقاً", success=False, status_code=400
            )

        # Determine department assignment:
        # - department_head and supervisor default to their own department
        # - dean and owner may create rooms for any department or leave it unspecified
        department_id = None
        if user["role"] in ["department_head", "supervisor"]:
            department_id = user["department_id"]
        else:
            department_id = data.get("department_id")

        if not department_id and user["role"] not in ["dean", "owner"]:
            # Only dean/owner may omit department_id
            return format_response(
                message="معرف القسم مطلوب", success=False, status_code=400
            )

        # Handle capacity: convert empty string to None
        capacity = data.get("capacity")
        if capacity == "" or capacity is None:
            capacity = None
        else:
            try:
                capacity = int(capacity)
            except (ValueError, TypeError):
                return format_response(
                    message="السعة يجب أن تكون رقماً صحيحاً",
                    success=False,
                    status_code=400,
                )

        room_res = (
            supabase.table("rooms")
            .insert(
                {
                    "name": data["name"],
                    "code": data["code"],
                    "department_id": department_id,
                    "capacity": capacity,
                    "description": data.get("description", ""),
                }
            )
            .execute()
        )
        room = room_res.data[0]

        qr_error_msg = None
        try:
            qr_path = generate_room_qr(room["code"], room["id"])
            if qr_path:
                supabase.table("rooms").update({"qr_code_path": qr_path}).eq(
                    "id", room["id"]
                ).execute()
                room["qr_code_path"] = qr_path
            else:
                qr_error_msg = "فشل في توليد باركود القاعة."
        except Exception as qr_error:
            qr_error_msg = f"خطأ في توليد باركود القاعة: {str(qr_error)}"

        response_data = {
            "id": room["id"],
            "name": room["name"],
            "code": room["code"],
            "department_id": room["department_id"],
            "capacity": room["capacity"],
            "description": room["description"],
            "qr_code_path": room.get("qr_code_path"),
        }
        if qr_error_msg:
            response_data["qr_error"] = qr_error_msg

        return format_response(
            data=response_data, message="تم إنشاء القاعة بنجاح", status_code=201
        )

    except Exception as e:
        return format_response(
            message=f"فشل في إنشاء القاعة: {str(e)}",
            success=False,
            status_code=500,
        )


@room_bp.route("/<int:room_id>", methods=["GET"])
@jwt_required()
def get_room(room_id):
    """الحصول على قاعة واحدة"""
    try:
        supabase = current_app.supabase
        username = get_jwt_identity()
        user = get_user_by_username(username)

        if not user:
            return format_response(
                message="المستخدم غير موجود", success=False, status_code=404
            )

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

        if user["role"] == "supervisor":
            if not user.get("department_id"):
                return format_response(
                    message="المشرف غير مرتبط بقسم",
                    success=False,
                    status_code=403,
                )
            if room["department_id"] != user["department_id"]:
                return format_response(
                    message="لا يمكنك الوصول لهذه القاعة",
                    success=False,
                    status_code=403,
                )
        elif user["role"] not in ["dean", "owner"] and room["department_id"] != user["department_id"]:
            return format_response(
                message="لا يمكنك الوصول لهذه القاعة",
                success=False,
                status_code=403,
            )

        # Add department name to room (defensive)
        if room.get("department_id"):
            try:
                department_res = supabase.table("departments").select("name").eq("id", room["department_id"]).execute()
                if department_res and getattr(department_res, 'data', None):
                    room["department"] = {"name": department_res.data[0]["name"]}
                else:
                    room["department"] = {"name": "Unknown"}
            except Exception:
                room["department"] = {"name": "Unknown"}
        else:
            room["department"] = {"name": "No Department"}

        return format_response(data=room, message="تم جلب القاعة بنجاح")

    except Exception as e:
        return format_response(
            message=f"حدث خطأ: {str(e)}", success=False, status_code=500
        )


@room_bp.route("/<int:room_id>", methods=["PUT"])
@jwt_required()
def update_room(room_id):
    """تحديث بيانات القاعة"""
    try:
        supabase = current_app.supabase
        data = request.get_json()
        if not data:
            return format_response(
                message="لم يتم توفير بيانات", success=False, status_code=400
            )

        username = get_jwt_identity()
        user = get_user_by_username(username)

        if not user:
            return format_response(
                message="المستخدم غير موجود", success=False, status_code=404
            )

        room_res = supabase.table("rooms").select("*").eq("id", room_id).execute()
        if not room_res.data:
            return format_response(
                message="القاعة غير موجودة", success=False, status_code=404
            )
        room = room_res.data[0]

        if user["role"] == "supervisor":
            if room["department_id"] != user["department_id"]:
                return format_response(
                    message="لا يمكنك تعديل هذه القاعة",
                    success=False,
                    status_code=403,
                )
        elif user["role"] != "dean" and room["department_id"] != user["department_id"]:
            return format_response(
                message="لا يمكنك تعديل هذه القاعة",
                success=False,
                status_code=403,
            )

        update_data = {}
        if "name" in data:
            update_data["name"] = data["name"]
        if "capacity" in data:
            update_data["capacity"] = data["capacity"]
        if "description" in data:
            update_data["description"] = data["description"]

        if update_data:
            updated_room_res = (
                supabase.table("rooms")
                .update(update_data)
                .eq("id", room_id)
                .execute()
            )
            return format_response(
                data=updated_room_res.data[0], message="تم تحديث القاعة بنجاح"
            )
        else:
            return format_response(data=room, message="لم يتم تحديث أي بيانات")

    except Exception as e:
        return format_response(
            message=f"فشل في تحديث القاعة: {str(e)}",
            success=False,
            status_code=500,
        )


@room_bp.route("/<int:room_id>", methods=["DELETE"])
@jwt_required()
def delete_room(room_id):
    """حذف القاعة"""
    try:
        supabase = current_app.supabase
        username = get_jwt_identity()
        user = get_user_by_username(username)

        if not user:
            return format_response(
                message="المستخدم غير موجود", success=False, status_code=404
            )

        room_res = supabase.table("rooms").select("*").eq("id", room_id).execute()
        if not room_res.data:
            return format_response(
                message="القاعة غير موجودة", success=False, status_code=404
            )
        room = room_res.data[0]

        if user["role"] == "supervisor":
            if room["department_id"] != user["department_id"]:
                return format_response(
                    message="لا يمكنك حذف هذه القاعة",
                    success=False,
                    status_code=403,
                )
        elif user["role"] != "dean" and room["department_id"] != user["department_id"]:
            return format_response(
                message="لا يمكنك حذف هذه القاعة",
                success=False,
                status_code=403,
            )

        # حذف جميع البيانات المرتبطة بالقاعة بالترتيب الصحيح
        try:
            # 1. جلب جميع الجداول المرتبطة بالقاعة في أي حقل
            schedules_res = supabase.table("schedules").select("id, moved_to_schedule_id").or_(
                f"room_id.eq.{room_id},original_room_id.eq.{room_id},postponed_to_room_id.eq.{room_id}"
            ).execute()
            schedule_ids = [s["id"] for s in schedules_res.data] if schedules_res.data else []
            
            # أضف moved_to_schedule_id إذا كان موجوداً
            for s in schedules_res.data:
                if s.get("moved_to_schedule_id"):
                    schedule_ids.append(s["moved_to_schedule_id"])
            
            # إزالة التكرارات
            schedule_ids = list(set(schedule_ids))
            
            # 2. حذف schedule_doctors للجداول المرتبطة
            if schedule_ids:
                for schedule_id in schedule_ids:
                    try:
                        supabase.table("schedule_doctors").delete().eq("schedule_id", schedule_id).execute()
                    except Exception as sd_err:
                        print(f"خطأ في حذف schedule_doctors للجدول {schedule_id}: {str(sd_err)}")
            
            # 3. nullify أي references إلى هذه schedules
            for schedule_id in schedule_ids:
                try:
                    supabase.table("schedules").update({"moved_to_schedule_id": None}).eq("moved_to_schedule_id", schedule_id).execute()
                    supabase.table("schedules").update({"original_schedule_id": None}).eq("original_schedule_id", schedule_id).execute()
                except Exception as ref_err:
                    print(f"خطأ في nullify references للجدول {schedule_id}: {str(ref_err)}")
            
            # 4. حذف الإعلانات المرتبطة بالقاعة
            try:
                supabase.table("announcements").delete().eq("room_id", room_id).execute()
            except Exception as ann_err:
                print(f"خطأ في حذف الإعلانات: {str(ann_err)}")
            
            # 5. حذف الجداول (schedules)
            if schedule_ids:
                for schedule_id in schedule_ids:
                    try:
                        supabase.table("schedules").delete().eq("id", schedule_id).execute()
                    except Exception as sch_err:
                        print(f"خطأ في حذف الجدول {schedule_id}: {str(sch_err)}")
            
            # 6. حذف ملف QR إن وجد
            if room.get("qr_code_path"):
                try:
                    delete_room_qr(room["qr_code_path"])
                except Exception as qr_err:
                    print(f"خطأ في حذف QR: {str(qr_err)}")
            
            # 7. حذف القاعة نفسها
            supabase.table("rooms").delete().eq("id", room_id).execute()
            
            return format_response(message="تم حذف القاعة بنجاح")
            
        except Exception as delete_err:
            return format_response(
                message=f"فشل في حذف القاعة: {str(delete_err)}", 
                success=False, 
                status_code=500
            )

    except Exception as e:
        return format_response(
            message=f"حدث خطأ: {str(e)}", success=False, status_code=500
        )


@room_bp.route("/<int:room_id>/schedules", methods=["GET"])
@jwt_required()
def get_room_schedules(room_id):
    """الحصول على جداول قاعة معينة"""
    try:
        supabase = current_app.supabase
        username = get_jwt_identity()
        user = get_user_by_username(username)

        if not user:
            return format_response(
                message="المستخدم غير موجود", success=False, status_code=404
            )

        room_res = supabase.table("rooms").select("*").eq("id", room_id).execute()
        if not room_res.data:
            return format_response(
                message="القاعة غير موجودة", success=False, status_code=404
            )
        room = room_res.data[0]

        if user["role"] == "supervisor":
            if not user.get("department_id"):
                return format_response(
                    message="المشرف غير مرتبط بقسم",
                    success=False,
                    status_code=403,
                )
            if room["department_id"] != user["department_id"]:
                return format_response(
                    message="لا يمكنك الوصول لهذه القاعة",
                    success=False,
                    status_code=403,
                )
        elif user["role"] not in ["dean", "owner"] and room["department_id"] != user["department_id"]:
            return format_response(
                message="لا يمكنك الوصول لهذه القاعة",
                success=False,
                status_code=403,
            )

        # Get all schedules for this room, including those moved in
        schedules_res = (
            supabase.table("schedules")
            .select("*, rooms!schedules_room_id_fkey(name, code), doctors!fk_doctor(name)") # Select room and doctor info using fk_doctor relationship
            .eq("room_id", room_id)
            .eq("is_active", True)
            .execute()
        )
        
        print(f"DEBUG: Retrieved schedules for room {room_id}: {schedules_res.data}")  # Debug log

        display_schedules = []
        from datetime import datetime, date

        today = date.today()

        for schedule in schedules_res.data:
            # If it's a temporary move-in, it should always be displayed as temporary
            if schedule.get("is_temporary_move_in"):
                # Check if the temporary move-in date is today or in the future
                # Assuming 'postponed_date' is used for the date of the temporary move-in
                if schedule.get("postponed_date"):
                    temp_move_date = datetime.strptime(schedule["postponed_date"], "%Y-%m-%d").date()
                    if temp_move_date >= today:
                        schedule["is_postponed_today"] = (temp_move_date == today)
                        display_schedules.append(schedule)
                else:
                    # If no postponed_date for a temporary_move_in, display it anyway
                    display_schedules.append(schedule)
            elif schedule.get("is_moved_out") and schedule.get("is_postponed"):
                # Do not append this schedule to display_schedules as it's been postponed and moved out
                pass
            else:
                # Regular schedules (not moved in, not moved out, and not postponed/moved out)
                display_schedules.append(schedule)

        return format_response(data=display_schedules, message="تم جلب الجداول بنجاح")

    except Exception as e:
        print(f"Error fetching room schedules: {str(e)}")
        import traceback
        traceback.print_exc()
        return format_response(
            message=f"حدث خطأ: {str(e)}", success=False, status_code=500
        )


@room_bp.route("/<int:room_id>/schedules", methods=["POST"])
@jwt_required()
def create_schedule(room_id):
    """إنشاء جدول جديد للقاعة"""
    try:
        supabase = current_app.supabase
        username = get_jwt_identity()
        user = get_user_by_username(username)

        if not user:
            return format_response(
                message="المستخدم غير موجود", success=False, status_code=404
            )

        # Allow owners to manage schedules as well as deans and department heads
        if user["role"] not in ["dean", "owner", "department_head", "supervisor"]:
            return format_response(
                message="ليس لديك صلاحية لهذا الإجراء",
                success=False,
                status_code=403,
            )

        if not request.is_json:
            return format_response(
                message="البيانات يجب أن تكون بصيغة JSON",
                success=False,
                status_code=400,
            )

        data = request.get_json()
        
        # Validate lecture type and grouping
        lecture_type = data.get("lecture_type", "نظري")  # Default to theoretical if not provided
        if lecture_type not in ["نظري", "عملي"]:
            return format_response(
                message="نوع المحاضرة غير صحيح (نظري أو عملي)",
                success=False,
                status_code=400,
            )
        
        # Convert Arabic to English for database
        db_lecture_type = "theoretical" if lecture_type == "نظري" else "practical"
        
        # Validate section/group based on lecture type
        if lecture_type == "نظري":
            section = data.get("section", 1)  # Default to section 1
            academic_stage = data.get("academic_stage", "")
            # If the academic stage is 'second' allow a third section
            allowed_sections = [1, 2, 3] if academic_stage == 'second' else [1, 2]
            if section is not None and section not in allowed_sections:
                return format_response(
                    message=f"الشعبة يجب أن تكون {' أو '.join(map(str, allowed_sections))} للمحاضرات النظرية",
                    success=False,
                    status_code=400,
                )
            group = None
        elif lecture_type == "عملي":
            group = data.get("group", "A")  # Default to group A
            if group is not None and group not in ["A", "B", "C", "D", "E"]:
                return format_response(
                    message="الكروب يجب أن يكون A, B, C, D, أو E للمحاضرات العملية",
                    success=False,
                    status_code=400,
                )
            section = None
        
        # Support both legacy and new doctor assignment methods
        use_multiple_doctors = data.get("use_multiple_doctors", False)
        doctor_ids = []  # Initialize to avoid unbound variable
        
        if use_multiple_doctors:
            # New multiple doctors system
            required_fields = [
                "study_type",
                "academic_stage",
                "day_of_week",
                "start_time",
                "end_time",
                "subject_name",
                "doctor_ids",  # Multiple doctors
            ]
            
            # Validate doctor_ids
            doctor_ids = data.get("doctor_ids", [])
            if not doctor_ids or len(doctor_ids) == 0:
                return format_response(
                    message="يجب اختيار دكتور واحد على الأقل",
                    success=False,
                    status_code=400,
                )
        else:
            # Legacy single doctor/instructor system
            required_fields = [
                "study_type",
                "academic_stage",
                "day_of_week",
                "start_time",
                "end_time",
                "subject_name",
                "instructor_name",
            ]
            
            # Check if we have instructor_name or doctor_id
            if not data.get("instructor_name") and not data.get("doctor_id"):
                return format_response(
                    message="يجب تحديد اسم المدرس أو اختيار دكتور",
                    success=False,
                    status_code=400,
                )
        
        missing_fields = [
            field for field in required_fields if field not in data or not data[field]
        ]

        if missing_fields:
            return format_response(
                message=f'الحقول التالية مطلوبة: {", ".join(missing_fields)}',
                success=False,
                status_code=400,
            )

        room_res = supabase.table("rooms").select("*").eq("id", room_id).execute()
        if not room_res.data:
            return format_response(
                message="القاعة غير موجودة", success=False, status_code=404
            )
        room = room_res.data[0]

        # Dean and Owner can manage schedules across all departments
        if user["role"] not in ["dean", "owner"] and room["department_id"] != user["department_id"]:
            return format_response(
                message="لا يمكنك إدارة جداول هذه القاعة",
                success=False,
                status_code=403,
            )

        if not validate_study_type(data["study_type"]):
            return format_response(
                message="نوع الدراسة غير صحيح", success=False, status_code=400
            )

        if not validate_academic_stage(data["academic_stage"]):
            return format_response(
                message="المرحلة الدراسية غير صحيحة",
                success=False,
                status_code=400,
            )

        if not validate_day_of_week(data["day_of_week"]):
            return format_response(
                message="يوم الأسبوع غير صحيح", success=False, status_code=400
            )

        if not validate_time_format(data["start_time"]) or not validate_time_format(
            data["end_time"]
        ):
            return format_response(
                message="صيغة الوقت غير صحيحة (استخدم HH:MM)",
                success=False,
                status_code=400,
            )

        # Validate instructor/doctor information based on mode
        if use_multiple_doctors:
            # Validate all doctor IDs exist
            for doctor_id in doctor_ids:
                doctor_res = supabase.table("doctors").select("id, name").eq("id", doctor_id).execute()
                if not doctor_res.data:
                    return format_response(
                        message=f"الدكتور برقم {doctor_id} غير موجود",
                        success=False,
                        status_code=400,
                    )
        else:
            # Legacy validation for instructor_name
            if data.get("instructor_name") and (not data["instructor_name"] or not data["instructor_name"].strip()):
                return format_response(
                    message="اسم المدرس مطلوب", success=False, status_code=400
                )
            
            # Validate doctor_id if provided
            if data.get("doctor_id"):
                doctor_res = supabase.table("doctors").select("id, name").eq("id", data["doctor_id"]).execute()
                if not doctor_res.data:
                    return format_response(
                        message="الدكتور المحدد غير موجود",
                        success=False,
                        status_code=400,
                    )

        from datetime import datetime

        try:
            start_time = datetime.strptime(data["start_time"], "%H:%M").time()
            end_time = datetime.strptime(data["end_time"], "%H:%M").time()
        except ValueError:
            return format_response(
                message="صيغة الوقت غير صحيحة، يجب أن تكون بصيغة HH:MM (مثال: 08:30)",
                success=False,
                status_code=400,
            )

        if start_time >= end_time:
            return format_response(
                message="وقت البداية يجب أن يكون قبل وقت النهاية",
                success=False,
                status_code=400,
            )

        # Check for conflicting schedules
        conflicting_schedule_res = (
            supabase.table("schedules")
            .select("*")
            .eq("room_id", room_id)
            .eq("study_type", data["study_type"])
            .eq("day_of_week", data["day_of_week"])
            .eq("is_active", True)
            .lt("start_time", data['end_time'])
            .gt("end_time", data['start_time'])
            .neq("end_time", data['start_time'])  # استثناء الحالات المتتالية
            .neq("start_time", data['end_time'])  # استثناء الحالات المتتالية
            .execute()
        )

        if conflicting_schedule_res.data:
            # Return conflicting schedule details to frontend for user action
            return format_response(
                message="يوجد تداخل مع محاضرة أخرى في نفس القاعة والوقت. يرجى تغيير توقيت المحاضرة الأصلية أو مكانها.",
                success=False,
                status_code=409,  # Conflict
                data=conflicting_schedule_res.data[0]
            )

        # Check doctor availability if doctors are specified
        if use_multiple_doctors and doctor_ids:
            # Check doctor availability for each doctor
            for doctor_id in doctor_ids:
                doctor_conflict_res = (
                    supabase.table("schedule_doctors")
                    .select("""
                        schedules!schedule_doctors_schedule_id_fkey(
                            id, study_type, day_of_week, start_time, end_time
                        )
                    """)
                    .eq("doctor_id", doctor_id)
                    .execute()
                )
                
                for schedule_doctor in doctor_conflict_res.data:
                    schedule = schedule_doctor.get('schedules')
                    if schedule:
                        # Parse schedule times to handle comparison correctly
                        try:
                            sched_start = datetime.strptime(schedule['start_time'], "%H:%M:%S").time()
                            sched_end = datetime.strptime(schedule['end_time'], "%H:%M:%S").time()
                        except ValueError:
                            # Fallback to %H:%M if no seconds
                            sched_start = datetime.strptime(schedule['start_time'], "%H:%M").time()
                            sched_end = datetime.strptime(schedule['end_time'], "%H:%M").time()
                        
                        if (schedule['study_type'] == data['study_type'] and
                            schedule['day_of_week'] == data['day_of_week'] and
                            sched_start < end_time and
                            sched_end > start_time and
                            sched_end != start_time and
                            sched_start != end_time):
                            
                            doctor_info = supabase.table("doctors").select("name").eq("id", doctor_id).execute()
                            doctor_name = doctor_info.data[0]['name'] if doctor_info.data else 'غير معروف'
                            return format_response(
                                message=f"الدكتور {doctor_name} لديه تداخل في هذا الوقت مع محاضرة أخرى",
                                success=False,
                                status_code=400,
                            )
        elif data.get("doctor_id"):
            # Check single doctor availability in schedules table
            doctor_conflict_res = (
                supabase.table("schedules")
                .select("*")
                .eq("doctor_id", data["doctor_id"])
                .eq("study_type", data["study_type"])
                .eq("day_of_week", data["day_of_week"])
                .eq("is_active", True)
                .lt("start_time", data['end_time'])
                .gt("end_time", data['start_time'])
                .neq("end_time", data['start_time'])
                .neq("start_time", data['end_time'])
                .execute()
            )
            
            if doctor_conflict_res.data:
                doctor_info = supabase.table("doctors").select("name").eq("id", data["doctor_id"]).execute()
                doctor_name = doctor_info.data[0]['name'] if doctor_info.data else 'غير معروف'
                return format_response(
                    message=f"الدكتور {doctor_name} لديه تداخل في هذا الوقت مع محاضرة أخرى",
                    success=False,
                    status_code=400,
                )
            
            # Also check in schedule_doctors table for multiple doctor schedules
            doctor_conflict_res_multi = (
                supabase.table("schedule_doctors")
                .select("""
                    schedules!schedule_doctors_schedule_id_fkey(
                        id, study_type, day_of_week, start_time, end_time
                    )
                """)
                .eq("doctor_id", data["doctor_id"])
                .execute()
            )
            
            for schedule_doctor in doctor_conflict_res_multi.data:
                schedule = schedule_doctor.get('schedules')
                if schedule:
                    # Parse schedule times to handle comparison correctly
                    try:
                        sched_start = datetime.strptime(schedule['start_time'], "%H:%M:%S").time()
                        sched_end = datetime.strptime(schedule['end_time'], "%H:%M:%S").time()
                    except ValueError:
                        # Fallback to %H:%M if no seconds
                        sched_start = datetime.strptime(schedule['start_time'], "%H:%M").time()
                        sched_end = datetime.strptime(schedule['end_time'], "%H:%M").time()
                    
                    if (schedule['study_type'] == data['study_type'] and
                        schedule['day_of_week'] == data['day_of_week'] and
                        sched_start < end_time and
                        sched_end > start_time and
                        sched_end != start_time and
                        sched_start != end_time):
                        
                        doctor_info = supabase.table("doctors").select("name").eq("id", data["doctor_id"]).execute()
                        doctor_name = doctor_info.data[0]['name'] if doctor_info.data else 'غير معروف'
                        return format_response(
                            message=f"الدكتور {doctor_name} لديه تداخل في هذا الوقت مع محاضرة أخرى",
                            success=False,
                            status_code=400,
                        )

        # Create regular schedule
        schedule_data = {
            "room_id": room_id,
            "department_id": room["department_id"], # Add department_id
            "study_type": data["study_type"],
            "academic_stage": data["academic_stage"],
            "day_of_week": data["day_of_week"],
            "start_time": data["start_time"],
            "end_time": data["end_time"],
            "subject_name": data["subject_name"],
            "notes": data.get("notes", ""),
            "lecture_type": db_lecture_type,
            "section_number": section,
            "group_letter": group,
            "is_active": True
        }
        
        # Handle instructor/doctor information based on mode
        if use_multiple_doctors:
            # For multiple doctors, we'll set instructor_name to the primary doctor's name
            primary_doctor_id = data.get("primary_doctor_id") or doctor_ids[0]
            primary_doctor_res = supabase.table("doctors").select("name").eq("id", primary_doctor_id).execute()
            if primary_doctor_res.data:
                schedule_data["instructor_name"] = primary_doctor_res.data[0]["name"]
            else:
                schedule_data["instructor_name"] = "متعدد المدرسين"  # "Multiple instructors"
        else:
            # Legacy system - use instructor_name directly
            if data.get("instructor_name"):
                schedule_data["instructor_name"] = data["instructor_name"].strip()
            
            # If doctor_id is provided, also set it
            if data.get("doctor_id"):
                schedule_data["doctor_id"] = data["doctor_id"]
                # If instructor_name not provided, get it from doctor
                if not data.get("instructor_name"):
                    doctor_res = supabase.table("doctors").select("name").eq("id", data["doctor_id"]).execute()
                    if doctor_res.data:
                        schedule_data["instructor_name"] = doctor_res.data[0]["name"]
                    else:
                        return format_response(
                            message="الدكتور المحدد غير موجود",
                            success=False,
                            status_code=400,
                        )
        
        schedule_res = (
            supabase.table("schedules")
            .insert(schedule_data)
            .execute()
        )
        
        if not schedule_res.data:
            return format_response(
                message="فشل في إنشاء الجدول",
                success=False,
                status_code=500,
            )
        
        schedule = schedule_res.data[0]
        
        # Handle multiple doctors if applicable
        if use_multiple_doctors:
            from models import add_doctors_to_schedule
            primary_doctor_id = data.get("primary_doctor_id") or doctor_ids[0]
            schedule_doctors = add_doctors_to_schedule(schedule["id"], doctor_ids, primary_doctor_id)
            
            # Add doctor information to response
            from models import get_schedule_doctors
            schedule_with_doctors = get_schedule_doctors(schedule["id"])
            schedule["schedule_doctors"] = schedule_with_doctors
            
            return format_response(
                data=schedule,
                message="تم إنشاء الجدول بعدة دكاترة بنجاح",
                status_code=201,
            )

        # For single doctor case
        return format_response(
            data=schedule,
            message="تم إنشاء الجدول بنجاح",
            status_code=201,
        )

    except Exception as e:
        print(f"ERROR in create_schedule: {str(e)}")
        import traceback
        traceback.print_exc()
        return format_response(
            message=f"حدث خطأ: {str(e)}", success=False, status_code=500
        )


@room_bp.route("/<int:room_id>/schedules/multi-doctor", methods=["POST"])
@department_access_required
@validate_json_data(["study_type", "academic_stage", "day_of_week", "start_time", "end_time", "subject_name"])
def create_schedule_with_multiple_doctors(data, user, room_id):
    """إنشاء جدول جديد مع دعم عدة دكاترة"""
    try:
        supabase = current_app.supabase
        room_res = supabase.table("rooms").select("*").eq("id", room_id).execute()
        if not room_res.data:
            return format_response(
                message="القاعة غير موجودة", success=False, status_code=404
            )
        room = room_res.data[0]

        if user["role"] != "dean" and room["department_id"] != user["department_id"]:
            return format_response(
                message="لا يمكنك إدارة جداول هذه القاعة",
                success=False,
                status_code=403,
            )

        if not validate_time_format(data["start_time"]) or not validate_time_format(data["end_time"]):
            return format_response(
                message="صيغة الوقت غير صحيحة (استخدم HH:MM)",
                success=False,
                status_code=400,
            )

        from datetime import datetime

        try:
            start_time = datetime.strptime(data["start_time"], "%H:%M").time()
            end_time = datetime.strptime(data["end_time"], "%H:%M").time()
        except ValueError:
            return format_response(
                message="صيغة الوقت غير صحيحة، يجب أن تكون بصيغة HH:MM (مثال: 08:30)",
                success=False,
                status_code=400,
            )

        if start_time >= end_time:
            return format_response(
                message="وقت البداية يجب أن يكون قبل وقت النهاية",
                success=False,
                status_code=400,
            )

        # Check for conflicting schedules
        conflicting_schedule_res = (
            supabase.table("schedules")
            .select("*")
            .eq("room_id", room_id)
            .eq("study_type", data["study_type"])
            .eq("day_of_week", data["day_of_week"])
            .eq("is_active", True)
            .lt("start_time", data['end_time'])
            .gt("end_time", data['start_time'])
            .neq("end_time", data['start_time'])  # استثناء الحالات المتتالية
            .neq("start_time", data['end_time'])  # استثناء الحالات المتتالية
            .execute()
        )

        if conflicting_schedule_res.data:
            return format_response(
                message="يوجد تداخل مع جدول آخر في نفس الوقت",
                success=False,
                status_code=400,
            )

        # Validate lecture type and grouping
        lecture_type = data.get("lecture_type", "نظري")  # Default to theoretical if not provided
        if lecture_type not in ["نظري", "عملي"]:
            return format_response(
                message="نوع المحاضرة غير صحيح (نظري أو عملي)",
                success=False,
                status_code=400,
            )
        
        # Convert Arabic to English for database
        db_lecture_type = "theoretical" if lecture_type == "نظري" else "practical"
        
        # Validate section/group based on lecture type
        if lecture_type == "نظري":
            section = data.get("section", 1)  # Default to section 1
            academic_stage = data.get("academic_stage", "")
            # If the academic stage is 'second' allow a third section
            allowed_sections = [1, 2, 3] if academic_stage == 'second' else [1, 2]
            if section is not None and section not in allowed_sections:
                return format_response(
                    message=f"الشعبة يجب أن تكون {' أو '.join(map(str, allowed_sections))} للمحاضرات النظرية",
                    success=False,
                    status_code=400,
                )
            group = None
        elif lecture_type == "عملي":
            group = data.get("group", "A")  # Default to group A
            if group is not None and group not in ["A", "B", "C", "D", "E"]:
                return format_response(
                    message="الكروب يجب أن يكون A, B, C, D, أو E للمحاضرات العملية",
                    success=False,
                    status_code=400,
                )
            section = None

        # Handle multiple doctors
        doctor_ids = data.get("doctor_ids", [])
        primary_doctor_id = data.get("primary_doctor_id")
        
        if not doctor_ids:
            return format_response(
                message="يجب اختيار دكتور واحد على الأقل",
                success=False,
                status_code=400,
            )
        
        # Validate doctor IDs
        for doctor_id in doctor_ids:
            doctor_res = supabase.table("doctors").select("id").eq("id", doctor_id).execute()
            if not doctor_res.data:
                return format_response(
                    message=f"الدكتور برقم {doctor_id} غير موجود",
                    success=False,
                    status_code=400,
                )
        
        # Check doctor availability for each doctor
        for doctor_id in doctor_ids:
            # Check in schedule_doctors table
            doctor_conflict_res = (
                supabase.table("schedule_doctors")
                .select("""
                    schedules!schedule_doctors_schedule_id_fkey(
                        id, study_type, day_of_week, start_time, end_time
                    )
                """)
                .eq("doctor_id", doctor_id)
                .execute()
            )
            
            for schedule_doctor in doctor_conflict_res.data:
                schedule = schedule_doctor.get('schedules')
                if schedule:
                    # Parse schedule times to handle comparison correctly
                    try:
                        sched_start = datetime.strptime(schedule['start_time'], "%H:%M:%S").time()
                        sched_end = datetime.strptime(schedule['end_time'], "%H:%M:%S").time()
                    except ValueError:
                        # Fallback to %H:%M if no seconds
                        sched_start = datetime.strptime(schedule['start_time'], "%H:%M").time()
                        sched_end = datetime.strptime(schedule['end_time'], "%H:%M").time()
                    
                    if (schedule['study_type'] == data['study_type'] and
                        schedule['day_of_week'] == data['day_of_week'] and
                        sched_start < end_time and
                        sched_end > start_time and
                        sched_end != start_time and
                        sched_start != end_time):
                        
                        doctor_info = supabase.table("doctors").select("name").eq("id", doctor_id).execute()
                        doctor_name = doctor_info.data[0]['name'] if doctor_info.data else 'غير معروف'
                        return format_response(
                            message=f"الدكتور {doctor_name} لديه تداخل في هذا الوقت مع محاضرة أخرى",
                            success=False,
                            status_code=400,
                        )
            
            # Also check in schedules table for legacy single doctor schedules
            doctor_conflict_res_legacy = (
                supabase.table("schedules")
                .select("*")
                .eq("doctor_id", doctor_id)
                .eq("study_type", data["study_type"])
                .eq("day_of_week", data["day_of_week"])
                .eq("is_active", True)
                .lt("start_time", data['end_time'])
                .gt("end_time", data['start_time'])
                .neq("end_time", data['start_time'])
                .neq("start_time", data['end_time'])
                .execute()
            )
            
            if doctor_conflict_res_legacy.data:
                doctor_info = supabase.table("doctors").select("name").eq("id", doctor_id).execute()
                doctor_name = doctor_info.data[0]['name'] if doctor_info.data else 'غير معروف'
                return format_response(
                    message=f"الدكتور {doctor_name} لديه تداخل في هذا الوقت مع محاضرة أخرى",
                    success=False,
                    status_code=400,
                )

        use_multiple_doctors = True

        # Create schedule
        schedule_data = {
            "room_id": room_id,
            "department_id": room["department_id"],
            "study_type": data["study_type"],
            "academic_stage": data["academic_stage"],
            "day_of_week": data["day_of_week"],
            "start_time": data["start_time"],
            "end_time": data["end_time"],
            "subject_name": data["subject_name"],
            "notes": data.get("notes", ""),
            "lecture_type": db_lecture_type,
            "section_number": section,
            "group_letter": group,
            "is_active": True
        }
        
        # Handle instructor/doctor information based on mode
        if use_multiple_doctors:
            # For multiple doctors, we'll set instructor_name to the primary doctor's name
            primary_doctor_id = data.get("primary_doctor_id") or doctor_ids[0]
            primary_doctor_res = supabase.table("doctors").select("name").eq("id", primary_doctor_id).execute()
            if primary_doctor_res.data:
                schedule_data["instructor_name"] = primary_doctor_res.data[0]["name"]
            else:
                schedule_data["instructor_name"] = "متعدد المدرسين"  # "Multiple instructors"
        else:
            # Legacy system - use instructor_name directly
            if data.get("instructor_name"):
                schedule_data["instructor_name"] = data["instructor_name"].strip()
            
            # If doctor_id is provided, also set it
            if data.get("doctor_id"):
                schedule_data["doctor_id"] = data["doctor_id"]
                # If instructor_name not provided, get it from doctor
                if not data.get("instructor_name"):
                    doctor_res = supabase.table("doctors").select("name").eq("id", data["doctor_id"]).execute()
                    if doctor_res.data:
                        schedule_data["instructor_name"] = doctor_res.data[0]["name"]
                    else:
                        return format_response(
                            message="الدكتور المحدد غير موجود",
                            success=False,
                            status_code=400,
                        )
        
        schedule_res = (
            supabase.table("schedules")
            .insert(schedule_data)
            .execute()
        )
        
        if not schedule_res.data:
            return format_response(
                message="فشل في إنشاء الجدول",
                success=False,
                status_code=500,
            )
        
        schedule = schedule_res.data[0]
        
        # Handle multiple doctors if applicable
        if use_multiple_doctors:
            from models import add_doctors_to_schedule
            primary_doctor_id = data.get("primary_doctor_id") or doctor_ids[0]
            schedule_doctors = add_doctors_to_schedule(schedule["id"], doctor_ids, primary_doctor_id)
            
            # Add doctor information to response
            from models import get_schedule_doctors
            schedule_with_doctors = get_schedule_doctors(schedule["id"])
            schedule["schedule_doctors"] = schedule_with_doctors
            
            return format_response(
                data=schedule,
                message="تم إنشاء الجدول بعدة دكاترة بنجاح",
                status_code=201,
            )

    except Exception as e:
        print(f"ERROR in create_schedule: {str(e)}")
        import traceback
        traceback.print_exc()
        return format_response(
            message=f"حدث خطأ: {str(e)}", success=False, status_code=500
        )


@room_bp.route("/<int:room_id>/schedules/<int:schedule_id>", methods=["PUT"])
@jwt_required()
def update_schedule(room_id, schedule_id):
    """تحديث جدول القاعة مع دعم عدة دكاترة"""
    try:
        supabase = current_app.supabase
        username = get_jwt_identity()
        user = get_user_by_username(username)

        if not user:
            return format_response(
                message="المستخدم غير موجود", success=False, status_code=404
            )

        # Owner should be able to update schedules as well
        if user["role"] not in ["dean", "owner", "department_head", "supervisor"]:
            return format_response(
                message="ليس لديك صلاحية لهذا الإجراء",
                success=False,
                status_code=403,
            )

        if not request.is_json:
            return format_response(
                message="البيانات يجب أن تكون بصيغة JSON",
                success=False,
                status_code=400,
            )

        data = request.get_json()
        print(f"DEBUG: Received data for update: {data}")  # Debug log
        
        if "subject_name" not in data:
            return format_response(
                message="اسم المادة مطلوب", success=False, status_code=400
            )

        # Validate lecture type and grouping for updates
        lecture_type = data.get("lecture_type", "نظري")  # Default to theoretical if not provided
        if lecture_type not in ["نظري", "عملي"]:
            return format_response(
                message="نوع المحاضرة غير صحيح (نظري أو عملي)",
                success=False,
                status_code=400,
            )
        
        # Convert Arabic to English for database
        db_lecture_type = "theoretical" if lecture_type == "نظري" else "practical"
        
        # Validate section/group based on lecture type
        if lecture_type == "نظري":
            section = data.get("section", 1)  # Default to section 1
            academic_stage = data.get("academic_stage", "")
            allowed_sections = [1, 2, 3] if academic_stage == 'second' else [1, 2]
            if section is not None and section not in allowed_sections:
                return format_response(
                    message=f"الشعبة يجب أن تكون {' أو '.join(map(str, allowed_sections))} للمحاضرات النظرية",
                    success=False,
                    status_code=400,
                )
            group = None
        elif lecture_type == "عملي":
            group = data.get("group", "A")  # Default to group A
            if group is not None and group not in ["A", "B", "C", "D", "E"]:
                return format_response(
                    message="الكروب يجب أن يكون A, B, C, D, أو E للمحاضرات العملية",
                    success=False,
                    status_code=400,
                )
            section = None
        
        use_multiple_doctors = data.get("use_multiple_doctors", False)
        
        username = get_jwt_identity()
        user = get_user_by_username(username)

        if not user:
            return format_response(
                message="المستخدم غير موجود", success=False, status_code=404
            )

        room_res = supabase.table("rooms").select("*").eq("id", room_id).execute()
        if not room_res.data:
            return format_response(
                message="القاعة غير موجودة", success=False, status_code=404
            )
        room = room_res.data[0]

        schedule_res = (
            supabase.table("schedules")
            .select("*")
            .eq("id", schedule_id)
            .eq("room_id", room_id)
            .execute()
        )
        if not schedule_res.data:
            return format_response(
                message="الجدول غير موجود", success=False, status_code=404
            )

        current_schedule = schedule_res.data[0]

        if user["role"] not in ["dean", "owner"] and room["department_id"] != user["department_id"]:
            return format_response(
                message="لا يمكنك تعديل جداول هذه القاعة",
                success=False,
                status_code=403,
            )

        update_data = {"subject_name": data["subject_name"]}

        # Handle room_id change
        if "room_id" in data and data["room_id"] != room_id:
            new_room_id = data["room_id"]
            new_room_res = supabase.table("rooms").select("*").eq("id", new_room_id).eq("is_active", True).execute()
            if not new_room_res.data:
                return format_response(
                    message="القاعة الجديدة غير موجودة أو غير نشطة", success=False, status_code=400
                )
            
            # Conflict check in the new room
            conflicting_schedule_in_new_room_res = (
                supabase.table("schedules")
                .select("id")
                .eq("room_id", new_room_id)
                .eq("study_type", current_schedule["study_type"])
                .eq("day_of_week", current_schedule["day_of_week"])
                .eq("is_active", True)
                .lt("start_time", current_schedule['end_time'])
                .gt("end_time", current_schedule['start_time'])
                .execute()
            )

            if conflicting_schedule_in_new_room_res.data:
                return format_response(
                    message="القاعة الجديدة مشغولة في هذا الوقت",
                    success=False,
                    status_code=400,
                )
            
            update_data["room_id"] = new_room_id

        # Handle legacy instructor_name for backward compatibility
        if "instructor_name" in data:
            update_data["instructor_name"] = data["instructor_name"].strip() if data["instructor_name"] else ""
        
        # Handle single doctor mode
        if not use_multiple_doctors and "doctor_id" in data:
            update_data["doctor_id"] = data["doctor_id"]
            # Update instructor_name for backward compatibility when doctor_id changes
            if data["doctor_id"]:
                doctor_name_res = supabase.table("doctors").select("name").eq("id", data["doctor_id"]).execute()
                if doctor_name_res.data:
                    update_data["instructor_name"] = doctor_name_res.data[0]["name"]
            else:
                update_data["instructor_name"] = ""
            
        if "notes" in data:
            update_data["notes"] = data.get("notes")

        # Determine study_type and day_of_week for conflict checks
        check_study_type = data.get("study_type", current_schedule["study_type"])
        check_day_of_week = data.get("day_of_week", current_schedule["day_of_week"])

        if "start_time" in data and "end_time" in data:
            if not validate_time_format(
                data["start_time"]
            ) or not validate_time_format(data["end_time"]):
                return format_response(
                    message="صيغة الوقت غير صحيحة (استخدم HH:MM)",
                    success=False,
                    status_code=400,
                )

            from datetime import datetime

            try:
                start_time = datetime.strptime(data["start_time"], "%H:%M").time()
                end_time = datetime.strptime(data["end_time"], "%H:%M").time()
            except ValueError:
                return format_response(
                    message="صيغة الوقت غير صحيحة، يجب أن تكون بصيغة HH:MM (مثال: 08:30)",
                    success=False,
                    status_code=400,
                )

            if start_time >= end_time:
                return format_response(
                    message="وقت البداية يجب أن يكون قبل وقت النهاية",
                    success=False,
                    status_code=400,
                )

            # Check for conflicting schedules in room
            conflicting_schedule_res = (
                supabase.table("schedules")
                .select("id")
                .eq("room_id", room_id)
                .eq("study_type", check_study_type)
                .eq("day_of_week", check_day_of_week)
                .eq("is_active", True)
                .neq("id", schedule_id) # Exclude current schedule from conflict check
                .lt("start_time", data['end_time'])
                .gt("end_time", data['start_time'])
                .execute()
            )

            if conflicting_schedule_res.data:
                return format_response(
                    message="يوجد تداخل مع جدول آخر في نفس الوقت",
                    success=False,
                    status_code=400,
                )

            update_data["start_time"] = data["start_time"]
            update_data["end_time"] = data["end_time"]

        # Check doctor availability if doctor changed
        if use_multiple_doctors:
            doctor_ids = data.get("doctor_ids", [])
            for doctor_id in doctor_ids:
                doctor_conflict_res = (
                    supabase.table("schedule_doctors")
                    .select("""
                        schedules!schedule_doctors_schedule_id_fkey(
                            id, study_type, day_of_week, start_time, end_time
                        )
                    """)
                    .eq("doctor_id", doctor_id)
                    .execute()
                )
                
                for schedule_doctor in doctor_conflict_res.data:
                    schedule = schedule_doctor.get('schedules')
                    if (schedule and 
                        schedule['id'] != schedule_id and  # Exclude current schedule
                        schedule['study_type'] == check_study_type and
                        schedule['day_of_week'] == check_day_of_week):
                        
                        # Parse schedule times to handle comparison correctly
                        try:
                            sched_start = datetime.strptime(schedule['start_time'], "%H:%M:%S").time()
                            sched_end = datetime.strptime(schedule['end_time'], "%H:%M:%S").time()
                        except ValueError:
                            # Fallback to %H:%M if no seconds
                            sched_start = datetime.strptime(schedule['start_time'], "%H:%M").time()
                            sched_end = datetime.strptime(schedule['end_time'], "%H:%M").time()
                        
                        # Use new times if updating, else current
                        check_start = start_time if "start_time" in data else datetime.strptime(current_schedule['start_time'], "%H:%M").time()
                        check_end = end_time if "end_time" in data else datetime.strptime(current_schedule['end_time'], "%H:%M").time()
                        
                        if (sched_start < check_end and
                            sched_end > check_start):
                            
                            doctor_info = supabase.table("doctors").select("name").eq("id", doctor_id).execute()
                            doctor_name = doctor_info.data[0]['name'] if doctor_info.data else 'غير معروف'
                            return format_response(
                                message=f"الدكتور {doctor_name} لديه تداخل في هذا الوقت مع محاضرة أخرى",
                                success=False,
                                status_code=400,
                            )
        else:
            # Check single doctor availability
            if data.get("doctor_id") and data["doctor_id"] != current_schedule.get("doctor_id"):
                doctor_conflict_res = (
                    supabase.table("schedules")
                    .select("id, doctors!fk_doctor(name)")
                    .eq("doctor_id", data["doctor_id"])
                    .eq("study_type", check_study_type)
                    .eq("day_of_week", check_day_of_week)
                    .eq("is_active", True)
                    .neq("id", schedule_id) # Exclude current schedule from conflict check
                    .lt("start_time", data.get('end_time', current_schedule['end_time']))
                    .gt("end_time", data.get('start_time', current_schedule['start_time']))
                    .execute()
                )
                
                if doctor_conflict_res.data:
                    doctor_name = doctor_conflict_res.data[0].get('doctors', {}).get('name', 'غير معروف') if doctor_conflict_res.data else 'غير معروف'
                    return format_response(
                        message=f"الدكتور {doctor_name} لديه تداخل في هذا الوقت مع محاضرة أخرى",
                        success=False,
                        status_code=400,
                    )

        # Update lecture type and grouping fields
        if 'lecture_type' in data or db_lecture_type:
            update_data["lecture_type"] = db_lecture_type or "theoretical"
            update_data["section_number"] = section if section is not None else (1 if db_lecture_type == "theoretical" else None)
            update_data["group_letter"] = group if group is not None else ("A" if db_lecture_type == "practical" else None)
            print(f"DEBUG: Updating lecture fields - type: {db_lecture_type}, section: {section}, group: {group}")  # Debug log

        # Update the schedule
        updated_schedule_res = (
            supabase.table("schedules")
            .update(update_data)
            .eq("id", schedule_id)
            .execute()
        )
        
        # Handle multiple doctors update
        if use_multiple_doctors:
            from models import add_doctors_to_schedule
            doctor_ids = data.get("doctor_ids", [])
            primary_doctor_id = data.get("primary_doctor_id") or (doctor_ids[0] if doctor_ids else None)
            
            # Update doctors in junction table
            add_doctors_to_schedule(schedule_id, doctor_ids, primary_doctor_id)
            
            # Update instructor_name for backward compatibility
            if primary_doctor_id:
                primary_doctor_res = supabase.table("doctors").select("name").eq("id", primary_doctor_id).execute()
                if primary_doctor_res.data:
                    update_data["instructor_name"] = primary_doctor_res.data[0]["name"]
                else:
                    update_data["instructor_name"] = "متعدد المدرسين"  # "Multiple instructors"
            else:
                update_data["instructor_name"] = "متعدد المدرسين"  # "Multiple instructors"
                
            # Apply the instructor_name update
            if "instructor_name" in update_data:
                supabase.table("schedules").update({"instructor_name": update_data["instructor_name"]}).eq("id", schedule_id).execute()
        else:
            # For single doctor mode, remove any existing multiple doctor entries
            # and ensure the schedule uses the single doctor_id field
            supabase.table('schedule_doctors').delete().eq('schedule_id', schedule_id).execute()

        # Get updated schedule with doctors for response
        from models import get_schedule_doctors
        updated_schedule = updated_schedule_res.data[0]
        if use_multiple_doctors:
            schedule_doctors = get_schedule_doctors(schedule_id)
            updated_schedule["schedule_doctors"] = schedule_doctors

        return format_response(
            data=updated_schedule, message="تم تحديث الجدول بنجاح"
        )

    except Exception as e:
        return format_response(
            message=f"حدث خطأ: {str(e)}", success=False, status_code=500
        )


@room_bp.route("/<int:room_id>/schedules/<int:schedule_id>", methods=["DELETE"])
@department_access_required
def delete_schedule(user, room_id, schedule_id):
    """حذف جدول من القاعة"""
    try:
        supabase = current_app.supabase
        room_res = supabase.table("rooms").select("*").eq("id", room_id).execute()
        if not room_res.data:
            return format_response(
                message="القاعة غير موجودة", success=False, status_code=404
            )
        room = room_res.data[0]

        schedule_res = (
            supabase.table("schedules")
            .select("*")
            .eq("id", schedule_id)
            .eq("room_id", room_id)
            .execute()
        )
        if not schedule_res.data:
            return format_response(
                message="الجدول غير موجود", success=False, status_code=404
            )
        schedule = schedule_res.data[0]

        if user["role"] not in ["dean", "owner"] and room["department_id"] != user["department_id"]:
            return format_response(
                message="لا يمكنك حذف جداول هذه القاعة",
                success=False,
                status_code=403,
            )

        # Clean up postponement relationships before deleting
        # Nullify moved_to_schedule_id references that point to this schedule
        supabase.table("schedules").update({"moved_to_schedule_id": None}).eq("moved_to_schedule_id", schedule_id).execute()
        
        # Nullify original_schedule_id references that point to this schedule
        supabase.table("schedules").update({"original_schedule_id": None}).eq("original_schedule_id", schedule_id).execute()
        
        # If this schedule has a moved_to_schedule_id, delete the temporary schedule it points to
        if schedule.get("moved_to_schedule_id"):
            supabase.table("schedules").delete().eq("id", schedule["moved_to_schedule_id"]).execute()

        supabase.table("schedules").delete().eq("id", schedule_id).execute()

        return format_response(message="تم حذف الجدول بنجاح")

    except Exception as e:
        return format_response(
            message=f"حدث خطأ: {str(e)}", success=False, status_code=500
        )





@room_bp.route("/<int:room_id>/qr", methods=["GET"])
@jwt_required()
def get_room_qr(room_id):
    """عرض QR Code للقاعة"""
    try:
        supabase = current_app.supabase
        username = get_jwt_identity()
        user = get_user_by_username(username)

        if not user:
            return format_response(
                message="المستخدم غير موجود", success=False, status_code=404
            )

        room_res = supabase.table("rooms").select("*").eq("id", room_id).execute()
        if not room_res.data:
            return format_response(
                message="القاعة غير موجودة", success=False, status_code=404
            )
        room = room_res.data[0]

        if user["role"] not in ["dean", "owner"] and room["department_id"] != user["department_id"]:
            return format_response(
                message="لا يمكنك الوصول لهذه القاعة",
                success=False,
                status_code=403,
            )

        if not room["qr_code_path"] or not os.path.exists(room["qr_code_path"]):
            qr_path = generate_room_qr(room["code"], room["id"])
            if qr_path:
                supabase.table("rooms").update({"qr_code_path": qr_path}).eq(
                    "id", room["id"]
                ).execute()
                room["qr_code_path"] = qr_path
            else:
                return format_response(
                    message="فشل في إنشاء QR Code",
                    success=False,
                    status_code=500,
                )

        return send_file(room["qr_code_path"], mimetype="image/png")

    except Exception as e:
        return format_response(
            message=f"حدث خطأ: {str(e)}", success=False, status_code=500
        )


@room_bp.route("/<int:room_id>/regenerate-qr", methods=["POST"])
@jwt_required()
def regenerate_room_qr(room_id):
    """إعادة إنشاء QR Code للقاعة"""
    try:
        supabase = current_app.supabase
        username = get_jwt_identity()
        user = get_user_by_username(username)


        if not user:
            return format_response(
                message="المستخدم غير موجود", success=False, status_code=404
            )

        if user["role"] not in ["owner", "dean", "department_head", "supervisor"]:
            return format_response(
                message="صلاحيات غير كافية", success=False, status_code=403
            )

        room_res = supabase.table("rooms").select("*").eq("id", room_id).execute()
        if not room_res.data:
            return format_response(
                message="القاعة غير موجودة", success=False, status_code=404
            )
        room = room_res.data[0]

        if user["role"] not in ["dean", "owner"] and room["department_id"] != user["department_id"]:
            return format_response(
                message="لا يمكنك إعادة إنشاء QR Code لهذه القاعة",
                success=False,
                status_code=403,
            )

        if room["qr_code_path"] and os.path.exists(room["qr_code_path"]):
            try:
                delete_room_qr(room["qr_code_path"])
            except:
                pass

        qr_path = generate_room_qr(room["code"], room["id"])
        if qr_path:
            supabase.table("rooms").update({"qr_code_path": qr_path}).eq(
                "id", room["id"]
            ).execute()

            return format_response(
                message="تم إعادة إنشاء QR Code بنجاح",
                data={"qr_code_path": qr_path},
            )
        else:
            return format_response(
                message="فشل في إنشاء QR Code",
                success=False,
                status_code=500,
            )

    except Exception as e:
        return format_response(
            message=f"حدث خطأ: {str(e)}", success=False, status_code=500
        )


@room_bp.route("/<int:room_id>/schedules/<int:schedule_id>/postpone", methods=["PUT"])
@jwt_required()
def postpone_schedule(room_id, schedule_id):
    """تأجيل محاضرة إلى تاريخ ووقت وقاعة جديدة"""
    try:
        supabase = current_app.supabase
        username = get_jwt_identity()
        user = get_user_by_username(username)

        if not user:
            return format_response(
                message="المستخدم غير موجود", success=False, status_code=404
            )

        # Allow owners to postpone schedules as well as deans and department heads
        if user["role"] not in ["dean", "owner", "department_head", "supervisor"]:
            return format_response(
                message="ليس لديك صلاحية لهذا الإجراء",
                success=False,
                status_code=403,
            )

        if not request.is_json:
            return format_response(
                message="البيانات يجب أن تكون بصيغة JSON",
                success=False,
                status_code=400,
            )

        data = request.get_json()
        
        # Validate required fields for postponement
        required_fields = [
            "postponed_date", 
            "postponed_to_room_id", 
            "postponed_reason",
            "postponed_start_time",
            "postponed_end_time"
        ]
        for field in required_fields:
            if field not in data or not data[field]:
                return format_response(
                    message=f"الحقل المطلوب مفقود: {field}",
                    success=False,
                    status_code=400,
                )
        
        # Additional validation for date format
        from datetime import datetime
        try:
            postponed_date_obj = datetime.strptime(data["postponed_date"], "%Y-%m-%d").date()
        except ValueError:
            return format_response(
                message="صيغة التاريخ غير صحيحة، يجب أن تكون بصيغة YYYY-MM-DD",
                success=False,
                status_code=400,
            )
        
        # Additional validation for time formats
        try:
            datetime.strptime(data["postponed_start_time"], "%H:%M")
            datetime.strptime(data["postponed_end_time"], "%H:%M")
        except ValueError:
            return format_response(
                message="صيغة الوقت غير صحيحة، يجب أن تكون بصيغة HH:MM",
                success=False,
                status_code=400,
            )

        # Fetch the original schedule details
        original_schedule_res = (
            supabase.table("schedules")
            .select("*")
            .eq("id", schedule_id)
            .eq("room_id", room_id)
            .execute()
        )
        
        if not original_schedule_res.data:
            return format_response(
                message="الجدول الأصلي غير موجود",
                success=False,
                status_code=404
            )
        original_schedule = original_schedule_res.data[0]

        # Check if the postponed room exists and is active
        postponed_room_res = (
            supabase.table("rooms")
            .select("*")
            .eq("id", data["postponed_to_room_id"])
            .eq("is_active", True)
            .execute()
        )
        
        if not postponed_room_res.data:
            return format_response(
                message="القاعة المؤقتة غير موجودة أو غير نشطة",
                success=False,
                status_code=400
            )

        # Check for conflicts in the postponed room at the specified time
        conflicting_schedule_res = (
            supabase.table("schedules")
            .select("*")
            .eq("room_id", data["postponed_to_room_id"])
            .eq("day_of_week", original_schedule["day_of_week"]) # Use original day of week for conflict check
            .eq("is_active", True)
            .execute()
        )
        
        # Filter conflicts in Python since Supabase query builder has limitations
        conflicts = []
        if conflicting_schedule_res.data:
            new_start = data["postponed_start_time"]
            new_end = data["postponed_end_time"]
            for existing_schedule in conflicting_schedule_res.data:
                from datetime import datetime
                # تحويل الأوقات إلى كائنات وقت
                fmt = "%H:%M"
                try:
                    new_start_time = datetime.strptime(new_start, fmt).time()
                    new_end_time = datetime.strptime(new_end, fmt).time()
                    existing_start_time = datetime.strptime(existing_schedule["start_time"], fmt).time()
                    existing_end_time = datetime.strptime(existing_schedule["end_time"], fmt).time()
                except Exception as e:
                    print(f"[ERROR] فشل تحويل الوقت: {e}")
                    continue

                # تحقق التداخل الفعلي مع استثناء الحالات المتتالية
                if (
                    (new_start_time < existing_end_time and new_end_time > existing_start_time)
                    and not (new_start_time == existing_end_time or new_end_time == existing_start_time)
                ):
                    conflicts.append(existing_schedule)
        
        if conflicts:
            return format_response(
                message="يوجد تعارض مع محاضرة أخرى في القاعة المؤقتة وفي نفس الوقت",
                success=False,
                status_code=409,  # Conflict
                data=conflicts[0]
            )

        # جلب معلومات القسمين
        original_room_info = supabase.table("rooms").select("code", "department_id").eq("id", original_schedule['room_id']).execute()
        new_room_info = supabase.table("rooms").select("code", "department_id").eq("id", data['postponed_to_room_id']).execute()
        original_room_code = original_room_info.data[0]['code'] if original_room_info.data else original_schedule['room_id']
        new_room_code = new_room_info.data[0]['code'] if new_room_info.data else data['postponed_to_room_id']
        original_dept_id = original_room_info.data[0]['department_id'] if original_room_info.data else original_schedule.get('department_id')
        new_dept_id = new_room_info.data[0]['department_id'] if new_room_info.data else None

        # Only allow non-dean/non-owner users to postpone schedules within their department
        if user["role"] not in ["dean", "owner"]:
            if original_dept_id and original_dept_id != user.get("department_id"):
                return format_response(
                    message="لا يمكنك تأجيل جدول خارج قسمك",
                    success=False,
                    status_code=403,
                )

        # جلب اسم القسمين
        original_dept_name = None
        new_dept_name = None
        if original_dept_id:
            try:
                dept_res = supabase.table("departments").select("name").eq("id", original_dept_id).execute()
                if dept_res and getattr(dept_res, 'data', None):
                    original_dept_name = dept_res.data[0]['name']
            except Exception:
                original_dept_name = None
        if new_dept_id:
            try:
                dept_res2 = supabase.table("departments").select("name").eq("id", new_dept_id).execute()
                if dept_res2 and getattr(dept_res2, 'data', None):
                    new_dept_name = dept_res2.data[0]['name']
            except Exception:
                new_dept_name = None

        day_name_arabic_map = {
            "sunday": "الأحد",
            "monday": "الاثنين",
            "tuesday": "الثلاثاء",
            "wednesday": "الأربعاء",
            "thursday": "الخميس",
            "friday": "الجمعة",
            "saturday": "السبت"
        }
        arabic_day_of_week = day_name_arabic_map.get(original_schedule['day_of_week'].lower(), original_schedule['day_of_week'])

        # جمع معلومات المحاضرين وتحضير بيانات الإعلان
        from models import get_schedule_doctors
        schedule_doctors = get_schedule_doctors(original_schedule['id']) if original_schedule.get('id') else []
        instructors = []
        primary_instructor = original_schedule.get('instructor_name')
        if schedule_doctors:
            for sd in schedule_doctors:
                name = sd.get('doctors', {}).get('name') or sd.get('doctors', {}).get('full_name')
                if name:
                    instructors.append(name)
                    if sd.get('is_primary'):
                        primary_instructor = name

        lecture_type = original_schedule.get('lecture_type', '')
        lecture_type_display = 'نظري' if lecture_type == 'theoretical' else ('عملي' if lecture_type == 'practical' else lecture_type)

        announcement_title = f"تأجيل - {original_schedule.get('subject_name', 'محاضرة')}"

        ann_meta = {
            "type": "postponement",
            "subject_name": original_schedule.get('subject_name'),
            "instructors": instructors or [original_schedule.get('instructor_name')],
            "primary_instructor": primary_instructor,
            "lecture_type": lecture_type,
            "lecture_type_display": lecture_type_display,
            "original_room": {"id": original_schedule.get('room_id'), "code": original_room_code},
            "new_room": {"id": data['postponed_to_room_id'], "code": new_room_code},
            "original_department": {"id": original_dept_id, "name": original_dept_name},
            "new_department": {"id": new_dept_id, "name": new_dept_name},
            "postponed_date": data['postponed_date'],
            "postponed_start_time": data['postponed_start_time'],
            "postponed_end_time": data['postponed_end_time'],
            "postponed_reason": data['postponed_reason'],
            "original_schedule_id": original_schedule.get('id'),
            "moved_by": username,
        }

        # Create a new temporary schedule entry in the target room
        new_temporary_schedule_data = {
            "room_id": data["postponed_to_room_id"],
            "study_type": original_schedule["study_type"],
            "academic_stage": original_schedule["academic_stage"],
            "day_of_week": postponed_date_obj.strftime("%A").lower(), # Day of week for the postponed date
            "start_time": data["postponed_start_time"],
            "end_time": data["postponed_end_time"],
            "subject_name": original_schedule["subject_name"],
            "instructor_name": original_schedule["instructor_name"],
            "notes": original_schedule["notes"],
            "is_active": True,
            "is_temporary_move_in": True, # Mark as a temporary move-in
            "original_schedule_id": original_schedule["id"], # Link to the original schedule
            "original_room_id": original_schedule["room_id"], # Store original room ID
            "original_booking_date": data["postponed_date"], # Use the specific postponed_date as the original booking date for the temporary move
            "original_start_time": original_schedule["start_time"], # Store original start time
            "original_end_time": original_schedule["end_time"], # Store original end time
            "move_reason": data["postponed_reason"] # Store the reason
        }

        new_temporary_schedule_res = supabase.table("schedules").insert(new_temporary_schedule_data).execute()
        new_temporary_schedule = new_temporary_schedule_res.data[0]

        # نسخ بيانات المحاضرين إلى الجدول المؤقت الجديد
        if schedule_doctors:
            for sd in schedule_doctors:
                supabase.table("schedule_doctors").insert({
                    "schedule_id": new_temporary_schedule["id"],
                    "doctor_id": sd["doctor_id"],
                    "is_primary": sd["is_primary"]
                }).execute()

        # Update the original schedule to mark it as moved out and link to the new temporary schedule
        update_original_schedule_data = {
            "is_moved_out": True,
            "moved_to_schedule_id": new_temporary_schedule["id"],
            "is_postponed": True, # Keep this for backward compatibility if needed
            "postponed_date": data["postponed_date"], # Store the postponed date in original for reference
            "postponed_to_room_id": data["postponed_to_room_id"], # Store the postponed room in original for reference
            "postponed_reason": data["postponed_reason"], # Store the reason in original for reference
            "postponed_start_time": data["postponed_start_time"], # Store the postponed start time in original for reference
            "postponed_end_time": data["postponed_end_time"] # Store the postponed end time in original for reference
        }
        
        supabase.table("schedules").update(update_original_schedule_data).eq("id", schedule_id).execute()

        # تحديد هل النقل بين قسمين مختلفين أم نفس القسم
        is_cross_department = original_dept_id != new_dept_id and new_dept_id is not None

        # إنشاء إعلانين دائماً: واحد للقاعة المنقولة إليها وآخر للقاعة المنقولة منها
        # إعلان للقاعة المنقولة إليها
        dest_dept_for_ann = new_dept_id or original_dept_id
        
        body_to_lines = ["تم تأجيل محاضرة مؤقتاً إلى قاعتكم:", ""]
        body_to_lines.append(f"📚 المادة: {original_schedule.get('subject_name')}")
        body_to_lines.append(f"👨‍🏫 المحاضر: {primary_instructor or 'غير محدد'}")
        body_to_lines.append(f"📖 نوع المحاضرة: {lecture_type_display}")
        body_to_lines.append("")
        body_to_lines.append(f"🏫 القاعة الأصلية: {original_room_code}")
        if original_dept_name and new_dept_name and original_dept_name != new_dept_name:
            body_to_lines.append(f"🏢 القسم الأصلي: {original_dept_name}")
        
        body_to_lines.append(f"🏫 القاعة الجديدة: {new_room_code}")
        if original_dept_name and new_dept_name and original_dept_name != new_dept_name:
            body_to_lines.append(f"🏢 القسم الجديد: {new_dept_name}")
        
        body_to_lines.append("")
        body_to_lines.append(f"📅 التاريخ: {data['postponed_date']} ({arabic_day_of_week})")
        body_to_lines.append(f"⏰ الوقت: من {data['postponed_start_time']} إلى {data['postponed_end_time']}")
        body_to_lines.append(f"📝 السبب: {data.get('postponed_reason')}")
        
        if instructors and len(instructors) > 1:
            assistants = [n for n in instructors if n != primary_instructor]
            if assistants:
                body_to_lines.append(f"👥 المساعدون: {', '.join(assistants)}")
        
        body_to = "\n".join(body_to_lines)

        supabase.table("announcements").insert({
            "title": announcement_title,
            "body": body_to,
            "is_global": False,
            "is_active": True,
            "department_id": dest_dept_for_ann,
            "starts_at": f"{data['postponed_date']} {data['postponed_start_time']}",
            "expires_at": f"{data['postponed_date']} {data['postponed_end_time']}",
            "meta": ann_meta,
        }).execute()

        # إعلان للقاعة المنقولة منها
        from_dept_for_ann = original_dept_id
        
        body_from_lines = ["تأجلت محاضرتكم مؤقتاً إلى قاعة أخرى:", ""]
        body_from_lines.append(f"📚 المادة: {original_schedule.get('subject_name')}")
        body_from_lines.append(f"👨‍🏫 المحاضر: {primary_instructor or 'غير محدد'}")
        body_from_lines.append(f"📖 نوع المحاضرة: {lecture_type_display}")
        body_from_lines.append("")
        body_from_lines.append(f"🏫 القاعة الأصلية: {original_room_code}")
        if original_dept_name and new_dept_name and original_dept_name != new_dept_name:
            body_from_lines.append(f"🏢 القسم الأصلي: {original_dept_name}")
        
        body_from_lines.append(f"🏫 القاعة الجديدة: {new_room_code}")
        if original_dept_name and new_dept_name and original_dept_name != new_dept_name:
            body_from_lines.append(f"🏢 القسم الجديد: {new_dept_name}")
        
        body_from_lines.append("")
        body_from_lines.append(f"📅 التاريخ: {data['postponed_date']} ({arabic_day_of_week})")
        body_from_lines.append(f"⏰ الوقت: من {data['postponed_start_time']} إلى {data['postponed_end_time']}")
        body_from_lines.append(f"📝 السبب: {data.get('postponed_reason')}")
        
        if instructors and len(instructors) > 1:
            assistants = [n for n in instructors if n != primary_instructor]
            if assistants:
                body_from_lines.append(f"👥 المساعدون: {', '.join(assistants)}")
        
        body_from = "\n".join(body_from_lines)

        supabase.table("announcements").insert({
            "title": announcement_title,
            "body": body_from,
            "is_global": False,
            "is_active": True,
            "department_id": from_dept_for_ann,
            "starts_at": f"{data['postponed_date']} {data['postponed_start_time']}",
            "expires_at": f"{data['postponed_date']} {data['postponed_end_time']}",
            "meta": ann_meta,
        }).execute()

        return format_response(
            data=new_temporary_schedule,
            message="تم نقل المحاضرة مؤقتاً بنجاح إلى القاعة الجديدة.",
            status_code=200,
        )

    except Exception as e:
        print(f"Error postponing schedule: {str(e)}")
        import traceback
        traceback.print_exc()
        return format_response(
            message=f"حدث خطأ في الخادم أثناء تأجيل الجدول: {str(e)}", success=False, status_code=500
        )


@room_bp.route("/<int:room_id>/schedules/upload", methods=["POST"])
@jwt_required()
def upload_weekly_schedule(room_id):
    """تحميل جدول أسبوعي من ملف Excel"""
    try:
        supabase = current_app.supabase
        username = get_jwt_identity()
        user = get_user_by_username(username)

        if not user:
            return format_response(
                message="المستخدم غير موجود", success=False, status_code=404
            )

        # Owner can delete all schedules for a room as well
        if user["role"] not in ["dean", "owner", "department_head", "supervisor"]:
            return format_response(
                message="ليس لديك صلاحية لهذا الإجراء",
                success=False,
                status_code=403,
            )

        # Check if the request contains a file
        if "file" not in request.files:
            return format_response(
                message="لم يتم إرسال ملف",
                success=False,
                status_code=400,
            )

        file = request.files["file"]
        
        # Check if the file is empty
        if file.filename == "":
            return format_response(
                message="الملف فارغ",
                success=False,
                status_code=400,
            )

        # Check file extension
        if not file.filename.endswith((".xlsx", ".xls")):
            return format_response(
                message="صيغة الملف غير مدعومة. يرجى تحميل ملف Excel بصيغة .xlsx أو .xls",
                success=False,
                status_code=400,
            )

        # Save file temporarily
        import os
        import tempfile
        import pandas as pd
        
        # Create a temporary file
        temp_dir = tempfile.mkdtemp()
        temp_file_path = os.path.join(temp_dir, file.filename)
        file.save(temp_file_path)

        # Read Excel file
        try:
            df = pd.read_excel(temp_file_path)
        except Exception as e:
            # Clean up temp file
            os.remove(temp_file_path)
            os.rmdir(temp_dir)
            return format_response(
                message=f"خطأ في قراءة ملف Excel: {str(e)}",
                success=False,
                status_code=400,
            )

        # Clean up temp file
        os.remove(temp_file_path)
        os.rmdir(temp_dir)

        # Validate required columns
        required_columns = [
            "study_type",
            "academic_stage",
            "day_of_week",
            "start_time",
            "end_time",
            "subject_name",
            "instructor_name",
            "section",    # New required column for section
            "group",     # New required column for group
        ]
        
        missing_columns = [col for col in required_columns if col not in df.columns]
        if missing_columns:
            return format_response(
                message=f"الملف مفقود به الأعمدة التالية: {', '.join(missing_columns)}",
                success=False,
                status_code=400,
            )

        # Validate room exists
        room_res = supabase.table("rooms").select("*").eq("id", room_id).execute()
        if not room_res.data:
            return format_response(
                message="القاعة غير موجودة", success=False, status_code=404
            )
        room = room_res.data[0]

        if user["role"] != "dean" and room["department_id"] != user["department_id"]:
            return format_response(
                message="لا يمكنك إدارة جداول هذه القاعة",
                success=False,
                status_code=403,
            )

        # Get IDs of schedules to be deleted
        schedules_to_delete_res = supabase.table("schedules").select("id").eq("room_id", room_id).execute()
        schedules_to_delete_ids = [s["id"] for s in schedules_to_delete_res.data]

        if schedules_to_delete_ids:
            # Nullify moved_to_schedule_id references to schedules in this room
            supabase.table("schedules").update({"moved_to_schedule_id": None}).in_("moved_to_schedule_id", schedules_to_delete_ids).execute()
            
            # Nullify original_schedule_id references to schedules in this room
            supabase.table("schedules").update({"original_schedule_id": None}).in_("original_schedule_id", schedules_to_delete_ids).execute()
        # Delete all existing schedules for this room before uploading new ones
        supabase.table("schedules").delete().eq("room_id", room_id).execute()

        # Process each row in the Excel file
        created_schedules = []
        errors = []
        warnings = []  # For non-critical issues like doctor name not found
        
        # Get all doctors once to avoid repeated database calls
        from models import get_all_doctors
        all_doctors = get_all_doctors()
        doctor_name_to_id = {doctor['name'].strip().lower(): doctor['id'] for doctor in all_doctors}
        
        for index, row in df.iterrows():
            try:
                # Check for NaN values in critical fields
                if pd.isna(row["start_time"]):
                    errors.append(f"الصف {index + 2}: وقت البدء مفقود أو غير صالح")
                    continue
                if pd.isna(row["end_time"]):
                    errors.append(f"الصف {index + 2}: وقت الانتهاء مفقود أو غير صالح")
                    continue
                if pd.isna(row["subject_name"]):
                    errors.append(f"الصف {index + 2}: اسم المادة مفقود أو غير صالح")
                    continue
                if pd.isna(row["instructor_name"]):
                    errors.append(f"الصف {index + 2}: اسم المدرس مفقود أو غير صالح")
                    continue

                # Validate data
                if not validate_study_type(row["study_type"]):
                    errors.append(f"الصف {index + 2}: نوع الدراسة غير صحيح")
                    continue

                if not validate_academic_stage(row["academic_stage"]):
                    errors.append(f"الصف {index + 2}: المرحلة الدراسية غير صحيحة")
                    continue

                if not validate_day_of_week(row["day_of_week"]):
                    errors.append(f"الصف {index + 2}: يوم الأسبوع غير صحيح")
                    continue

                if not validate_time_format(row["start_time"]) or not validate_time_format(row["end_time"]):
                    errors.append(f"الصف {index + 2}: صيغة الوقت غير صحيحة (استخدم HH:MM)")
                    continue

                if not row.get("instructor_name") or not str(row["instructor_name"]).strip():
                    errors.append(f"الصف {index + 2}: اسم المدرس مطلوب")
                    continue
                
                instructor_name = str(row["instructor_name"]).strip()
                # Check if doctor name exists in database
                doctor_id = doctor_name_to_id.get(instructor_name.lower())
                if not doctor_id:
                    # Try exact case-sensitive match as fallback
                    exact_match = next((doc['id'] for doc in all_doctors if doc['name'].strip() == instructor_name), None)
                    if exact_match:
                        doctor_id = exact_match
                    else:
                        warnings.append(f"الصف {index + 2}: اسم المدرس '{instructor_name}' غير موجود في قاعدة البيانات. سيتم حفظ الاسم كنص فقط.")

                from datetime import datetime

                # Convert time columns from Excel number format to HH:MM string format
                # Excel stores time as a fraction of a day. Pandas reads it as float.
                # Convert to datetime object, then format to HH:MM string.
                try:
                    # Check if the time is already a string (e.g., '08:30')
                    if isinstance(row["start_time"], (int, float)):
                        start_time_excel = pd.to_datetime(row["start_time"], unit='D', origin='1899-12-30') # Excel's epoch
                        start_time_str = start_time_excel.strftime("%H:%M")
                    else: # Assume it's already a string, apply padding logic
                        start_time_str = str(row["start_time"])
                        if len(start_time_str) == 4 and start_time_str[1] == ':': # e.g., "8:30"
                            start_time_str = "0" + start_time_str

                    if isinstance(row["end_time"], (int, float)):
                        end_time_excel = pd.to_datetime(row["end_time"], unit='D', origin='1899-12-30') # Excel's epoch
                        end_time_str = end_time_excel.strftime("%H:%M")
                    else: # Assume it's already a string, apply padding logic
                        end_time_str = str(row["end_time"])
                        if len(end_time_str) == 4 and end_time_str[1] == ':': # e.g., "8:30"
                            end_time_str = "0" + end_time_str

                except Exception as e:
                    errors.append(f"الصف {index + 2}: خطأ في تحويل الوقت من Excel - {str(e)}")
                    continue

                # Now use start_time_str and end_time_str for validation and insertion
                if not validate_time_format(start_time_str) or not validate_time_format(end_time_str):
                    errors.append(f"الصف {index + 2}: صيغة الوقت غير صحيحة (استخدم HH:MM)")
                    continue

                try:
                    start_time = datetime.strptime(start_time_str, "%H:%M").time()
                    end_time = datetime.strptime(end_time_str, "%H:%M").time()
                except ValueError:
                    errors.append(f"الصف {index + 2}: صيغة الوقت غير صحيحة، يجب أن تكون بصيغة HH:MM (مثال: 08:30)")
                    continue

                if start_time >= end_time:
                    errors.append(f"الصف {index + 2}: وقت البداية يجب أن يكون قبل وقت النهاية")
                    continue

                # Determine lecture type, section/group for this row
                lecture_type_row = str(row.get("lecture_type", "نظري")).strip() or "نظري"
                db_lecture_type = "theoretical" if lecture_type_row == "نظري" else "practical"
                if lecture_type_row == "نظري":
                    section = int(row.get("section", 1)) if pd.notna(row.get("section")) else 1
                    group = None
                else:
                    group = str(row.get("group", "A")).strip() if pd.notna(row.get("group")) else "A"
                    section = None

                # Check for conflicting schedules using the parsed start/end time strings
                # (previous conditional builder removed) - build below using explicit fields
                # Build a proper query using start_time_str and end_time_str
                conflicting_schedule_res = (
                    supabase.table("schedules")
                    .select("*")
                    .eq("room_id", room_id)
                    .eq("study_type", row["study_type"]) 
                    .eq("day_of_week", row["day_of_week"]) 
                    .eq("is_active", True)
                    .lt("start_time", end_time_str)
                    .gt("end_time", start_time_str)
                    .execute()
                )

                if conflicting_schedule_res.data:
                    errors.append(f"الصف {index + 2}: يوجد تداخل مع محاضرة أخرى في نفس القاعة والوقت")
                    continue

                # Create schedule
                schedule_data = {
                    "room_id": room_id,
                    "department_id": room["department_id"], # Add department_id
                    "study_type": row["study_type"].lower(),
                    "academic_stage": row["academic_stage"].lower(),
                    "day_of_week": row["day_of_week"],
                    "start_time": start_time_str,
                    "end_time": end_time_str,
                    "subject_name": row["subject_name"],
                    "instructor_name": instructor_name,  # Always save the name for display
                    "notes": str(row.get("notes")) if pd.notna(row.get("notes")) else "",
                    "lecture_type": db_lecture_type,
                    "section_number": section,
                    "group_letter": group,
                    "is_active": True
                }
                
                # Add doctor_id if doctor name was found in database
                if doctor_id:
                    schedule_data["doctor_id"] = doctor_id
                
                schedule_res = supabase.table("schedules").insert(schedule_data).execute()
                created_schedules.append(schedule_res.data[0] if schedule_res.data else None)
                
            except Exception as e:
                errors.append(f"الصف {index + 2}: خطأ في معالجة البيانات - {str(e)}")
                continue

        # Prepare response
        response_data = {
            "created_count": len(created_schedules),
            "created_schedules": created_schedules,
            "errors": errors,
            "error_count": len(errors),
            "warnings": warnings,
            "warning_count": len(warnings)
        }
        
        if errors and warnings:
            return format_response(
                data=response_data,
                message=f"تم إنشاء {len(created_schedules)} جدول بنجاح، لكن حدثت {len(errors)} أخطاء و {len(warnings)} تحذيرات",
                success=True,
                status_code=201,
            )
        elif errors:
            return format_response(
                data=response_data,
                message=f"تم إنشاء {len(created_schedules)} جدول بنجاح، لكن حدثت {len(errors)} أخطاء",
                success=True,
                status_code=201,
            )
        elif warnings:
            return format_response(
                data=response_data,
                message=f"تم إنشاء {len(created_schedules)} جدول بنجاح، مع {len(warnings)} تحذيرات",
                success=True,
                status_code=201,
            )
        else:
            return format_response(
                data=response_data,
                message=f"تم إنشاء {len(created_schedules)} جدول بنجاح",
                status_code=201,
            )

    except Exception as e:
        print(f"ERROR in upload_weekly_schedule: {str(e)}")
        import traceback
        traceback.print_exc()
        return format_response(
            message=f"حدث خطأ: {str(e)}", success=False, status_code=500
        )


@room_bp.route("/schedules/upload-general", methods=["POST"])
@jwt_required()
def upload_general_weekly_schedule():
    """تحميل جدول أسبوعي عام من ملف Excel لجميع القاعات"""
    try:
        supabase = current_app.supabase
        username = get_jwt_identity()
        user = get_user_by_username(username)

        if not user:
            return format_response(
                message="المستخدم غير موجود", success=False, status_code=404
            )

        # Allow owner or dean to upload a general weekly schedule
        if user["role"] not in ["dean", "owner"]:
            return format_response(
                message="ليس لديك صلاحية لهذا الإجراء",
                success=False,
                status_code=403,
            )

        if "file" not in request.files:
            return format_response(
                message="لم يتم إرسال ملف",
                success=False,
                status_code=400,
            )

        file = request.files["file"]
        
        if file.filename == "":
            return format_response(
                message="الملف فارغ",
                success=False,
                status_code=400,
            )

        if not file.filename.endswith((".xlsx", ".xls")):
            return format_response(
                message="صيغة الملف غير مدعومة. يرجى تحميل ملف Excel بصيغة .xlsx أو .xls",
                success=False,
                status_code=400,
            )

        import os
        import tempfile
        import pandas as pd
        
        temp_dir = tempfile.mkdtemp()
        temp_file_path = os.path.join(temp_dir, file.filename)
        file.save(temp_file_path)

        try:
            df = pd.read_excel(temp_file_path)
        except Exception as e:
            os.remove(temp_file_path)
            os.rmdir(temp_dir)
            return format_response(
                message=f"خطأ في قراءة ملف Excel: {str(e)}",
                success=False,
                status_code=400,
            )

        os.remove(temp_file_path)
        os.rmdir(temp_dir)

        required_columns = [
            "room_code", # New required column for room identification
            "study_type",
            "academic_stage",
            "day_of_week",
            "start_time",
            "end_time",
            "subject_name",
            "instructor_name",
            "department_name", # Add this new column
            "section",    # New required column for section
            "group",     # New required column for group
        ]
        
        missing_columns = [col for col in required_columns if col not in df.columns]
        if missing_columns:
            return format_response(
                message=f"الملف مفقود به الأعمدة التالية: {', '.join(missing_columns)}",
                success=False,
                status_code=400,
            )

        created_schedules = []
        errors = []
        warnings = []  # For non-critical issues like doctor name not found
        
        # Get all doctors once to avoid repeated database calls
        from models import get_all_doctors
        all_doctors = get_all_doctors()
        doctor_name_to_id = {doctor['name'].strip().lower(): doctor['id'] for doctor in all_doctors}
        
        # Group schedules by room_code
        schedules_by_room = {}
        for index, row in df.iterrows():
            room_code = str(row["room_code"]).strip()
            if room_code not in schedules_by_room:
                schedules_by_room[room_code] = []
            schedules_by_room[room_code].append((index, row))

        for room_code, rows_data in schedules_by_room.items():
            # Get room_id from room_code
            room_res = supabase.table("rooms").select("id").eq("code", room_code).execute()
            if not room_res.data:
                errors.append(f"رمز القاعة '{room_code}' غير موجود في النظام. تم تخطي الجداول المرتبطة به.")
                for index, _ in rows_data:
                    errors.append(f"الصف {index + 2}: رمز القاعة غير صالح")
                continue
            room_id = room_res.data[0]["id"]

            # Delete all existing schedules for this room before uploading new ones
            # This ensures a clean slate for each room's schedule
            schedules_to_delete_res = supabase.table("schedules").select("id").eq("room_id", room_id).execute()
            schedules_to_delete_ids = [s["id"] for s in schedules_to_delete_res.data]
            if schedules_to_delete_ids:
                supabase.table("schedules").update({"moved_to_schedule_id": None}).in_("moved_to_schedule_id", schedules_to_delete_ids).execute()
                supabase.table("schedules").update({"original_schedule_id": None}).in_("original_schedule_id", schedules_to_delete_ids).execute()
            supabase.table("schedules").delete().eq("room_id", room_id).execute()

            for index, row in rows_data:
                try:
                    if pd.isna(row["start_time"]):
                        errors.append(f"الصف {index + 2} (القاعة {room_code}): وقت البدء مفقود أو غير صالح")
                        continue
                    if pd.isna(row["end_time"]):
                        errors.append(f"الصف {index + 2} (القاعة {room_code}): وقت الانتهاء مفقود أو غير صالح")
                        continue
                    if pd.isna(row["subject_name"]):
                        errors.append(f"الصف {index + 2} (القاعة {room_code}): اسم المادة مفقود أو غير صالح")
                        continue
                    if pd.isna(row["instructor_name"]):
                        errors.append(f"الصف {index + 2} (القاعة {room_code}): اسم المدرس مفقود أو غير صالح")
                        continue

                    if not validate_study_type(row["study_type"]):
                        errors.append(f"الصف {index + 2} (القاعة {room_code}): نوع الدراسة غير صحيح")
                        continue

                    if not validate_academic_stage(row["academic_stage"]):
                        errors.append(f"الصف {index + 2} (القاعة {room_code}): المرحلة الدراسية غير صحيحة")
                        continue

                    if not validate_day_of_week(row["day_of_week"]):
                        errors.append(f"الصف {index + 2} (القاعة {room_code}): يوم الأسبوع غير صحيح")
                        continue

                    if not validate_time_format(row["start_time"]) or not validate_time_format(row["end_time"]):
                        errors.append(f"الصف {index + 2} (القاعة {room_code}): صيغة الوقت غير صحيحة (استخدم HH:MM)")
                        continue

                    if not str(row.get("instructor_name", "")).strip():
                        errors.append(f"الصف {index + 2} (القاعة {room_code}): اسم المدرس مطلوب")
                        continue
                    
                    instructor_name = str(row["instructor_name"]).strip()
                    # Check if doctor name exists in database
                    doctor_id = doctor_name_to_id.get(instructor_name.lower())
                    if not doctor_id:
                        # Try exact case-sensitive match as fallback
                        exact_match = next((doc['id'] for doc in all_doctors if doc['name'].strip() == instructor_name), None)
                        if exact_match:
                            doctor_id = exact_match
                        else:
                            warnings.append(f"الصف {index + 2} (القاعة {room_code}): اسم المدرس '{instructor_name}' غير موجود في قاعدة البيانات. سيتم حفظ الاسم كنص فقط.")

                    from datetime import datetime

                    try:
                        start_time = datetime.strptime(str(row["start_time"]), "%H:%M").time()
                        end_time = datetime.strptime(str(row["end_time"]), "%H:%M").time()
                    except ValueError:
                        errors.append(f"الصف {index + 2} (القاعة {room_code}): صيغة الوقت غير صحيحة، يجب أن تكون بصيغة HH:MM (مثال: 08:30)")
                        continue

                    if start_time >= end_time:
                        errors.append(f"الصف {index + 2} (القاعة {room_code}): وقت البداية يجب أن يكون قبل وقت النهاية")
                        continue

                    # Get department_id from department_name
                    department_name = str(row.get("department_name", "")).strip()
                    department_id = None
                    if department_name:
                        department_res = supabase.table("departments").select("id").eq("name", department_name).execute()
                        if department_res.data:
                            department_id = department_res.data[0]["id"]
                        else:
                            errors.append(f"الصف {index + 2} (القاعة {room_code}): اسم القسم '{department_name}' غير موجود في النظام. تم تخطي هذا الصف.")
                            continue # Skip this row if department not found
                    else:
                        errors.append(f"الصف {index + 2} (القاعة {room_code}): اسم القسم مفقود.")
                        continue

                    # Determine lecture type and grouping for this row
                    lecture_type_row = str(row.get("lecture_type", "نظري")).strip() or "نظري"
                    db_lecture_type = "theoretical" if lecture_type_row == "نظري" else "practical"
                    if lecture_type_row == "نظري":
                        try:
                            section = int(row.get("section", 1)) if pd.notna(row.get("section")) else 1
                        except Exception:
                            section = 1
                        group = None
                    else:
                        group = str(row.get("group", "A")).strip() if pd.notna(row.get("group")) else "A"
                        section = None

                    start_time_str = str(row["start_time"])
                    end_time_str = str(row["end_time"])

                    schedule_data = {
                        "room_id": room_id,
                        "study_type": row["study_type"].lower(),
                        "academic_stage": row["academic_stage"].lower(),
                        "day_of_week": row["day_of_week"],
                        "start_time": str(row["start_time"]),
                        "end_time": str(row["end_time"]),
                        "subject_name": row["subject_name"],
                        "instructor_name": instructor_name,  # Always save the name for display
                        "notes": str(row.get("notes")) if pd.notna(row.get("notes")) else "",
                        "lecture_type": db_lecture_type,
                        "section_number": section,
                        "group_letter": group,
                        "is_active": True,
                        "department_id": department_id, # Add department_id here
                    }
                    
                    # Add doctor_id if doctor name was found in database
                    if doctor_id:
                        schedule_data["doctor_id"] = doctor_id
                    
                    schedule_res = supabase.table("schedules").insert(schedule_data).execute()
                    if schedule_res.data:
                        created_schedules.append({**schedule_res.data[0], "room_code": room_code})
                    else:
                        errors.append(f"الصف {index + 2} (القاعة {room_code}): فشل في إنشاء الجدول")
                    
                except Exception as e:
                    errors.append(f"الصف {index + 2} (القاعة {room_code}): خطأ في معالجة البيانات - {str(e)}")
                    continue

        response_data = {
            "created_count": len(created_schedules),
            "created_schedules": created_schedules,
            "errors": errors,
            "error_count": len(errors),
            "warnings": warnings,
            "warning_count": len(warnings)
        }
        
        if errors and warnings:
            return format_response(
                data=response_data,
                message=f"تم إنشاء {len(created_schedules)} جدول بنجاح، لكن حدثت {len(errors)} أخطاء و {len(warnings)} تحذيرات",
                success=True,
                status_code=201,
            )
        elif errors:
            return format_response(
                data=response_data,
                message=f"تم إنشاء {len(created_schedules)} جدول بنجاح، لكن حدثت {len(errors)} أخطاء",
                success=True,
                status_code=201,
            )
        elif warnings:
            return format_response(
                data=response_data,
                message=f"تم إنشاء {len(created_schedules)} جدول بنجاح، مع {len(warnings)} تحذيرات",
                success=True,
                status_code=201,
            )
        else:
            return format_response(
                data=response_data,
                message=f"تم إنشاء {len(created_schedules)} جدول بنجاح",
                status_code=201,
            )

    except Exception as e:
        print(f"ERROR in upload_general_weekly_schedule: {str(e)}")
        import traceback
        traceback.print_exc()
        return format_response(
            message=f"حدث خطأ: {str(e)}", success=False, status_code=500
        )


@room_bp.route("/<int:room_id>/schedules/download-pdf", methods=["GET"])
@jwt_required()
def download_schedule_pdf(room_id):
    """تنزيل الجدول الأسبوعي لقاعة معينة كملف PDF"""
    try:
        # Import FPDF locally to avoid top-level import issues
        try:
            try:
                from fpdf import FPDF
            except Exception:
                # fpdf (fpdf2) may not be installed in the environment used by static analysis
                # Raise a clear runtime error so deployment logs show an actionable message
                raise RuntimeError(
                    "The 'fpdf' package is required for PDF export. Install it with: pip install fpdf2"
                )
        except Exception:
            return format_response(
                message="مكتبة PDF غير متوفرة. يرجى الاتصال بالمسؤول",
                success=False,
                status_code=500
            )
        supabase = current_app.supabase
        username = get_jwt_identity()
        user = get_user_by_username(username)

        if not user:
            return format_response(
                message="المستخدم غير موجود", success=False, status_code=404
            )

        room_res = supabase.table("rooms").select("*").eq("id", room_id).execute()
        if not room_res.data:
            return format_response(
                message="القاعة غير موجودة", success=False, status_code=404
            )
        room = room_res.data[0]

        # Authorization check (similar to get_room_schedules)
        if user["role"] == "supervisor":
            if not user.get("department_id"):
                return format_response(
                    message="المشرف غير مرتبط بقسم",
                    success=False,
                    status_code=403,
                )
            if room["department_id"] != user["department_id"]:
                return format_response(
                    message="لا يمكنك الوصول لهذه القاعة",
                    success=False,
                    status_code=403,
                )
        elif user["role"] != "dean" and room["department_id"] != user["department_id"]:
            return format_response(
                message="لا يمكنك الوصول لهذه القاعة",
                success=False,
                status_code=403,
            )

        # Fetch schedules for the room
        schedules_res = (
            supabase.table("schedules")
            .select("*")
            .eq("room_id", room_id)
            .eq("is_active", True)
            .order("day_of_week", desc=False) # Order by day
            .order("start_time", desc=False) # Then by time
            .execute()
        )
        schedules = schedules_res.data

        # Prepare data for PDF
        # Group schedules by day of the week
        schedules_by_day = {
            "sunday": [], "monday": [], "tuesday": [], "wednesday": [],
            "thursday": [], "friday": [], "saturday": []
        }
        for schedule in schedules:
            day = schedule["day_of_week"].lower()
            if day in schedules_by_day:
                schedules_by_day[day].append(schedule)

        # Arabic day names mapping
        day_name_arabic_map = {
            "sunday": "الأحد",
            "monday": "الاثنين",
            "tuesday": "الثلاثاء",
            "wednesday": "الأربعاء",
            "thursday": "الخميس",
            "friday": "الجمعة",
            "saturday": "السبت"
        }

        # PDF Generation using FPDF
        pdf = FPDF()
        pdf.add_page()

        # Add Arabic font (requires font file, e.g., Arial.ttf)
        # For simplicity, I'll assume a basic font that supports Arabic or use a placeholder.
        # In a real scenario, you'd need to provide a .ttf font file that supports Arabic.
        # Example: pdf.add_font('Arial', '', 'Arial.ttf', uni=True)
        # For now, using a generic font and hoping for the best or using English for content.
        # Given the context, I should try to use Arabic. I'll use a common approach for FPDF with Arabic.
        # This usually involves a font that supports Unicode and right-to-left text.
        # I'll add a note about font installation.

        # Note: For Arabic support, you need to add a Unicode font that supports Arabic characters.
        # Example: pdf.add_font('Amiri', '', 'Amiri-Regular.ttf', uni=True)
        # You would need to place 'Amiri-Regular.ttf' in a location FPDF can find,
        # or specify the full path. For this example, I'll use a placeholder font
        # and add a comment for the user.
        
        # For demonstration, I'll use a standard font and note the Arabic font requirement.
        pdf.add_font('DejaVu', '', 'DejaVuSansCondensed.ttf', uni=True) # A common font for FPDF with Unicode
        pdf.set_font('DejaVu', '', 14)
        
        # Set right-to-left for Arabic text
        pdf.set_rtl(True)

        pdf.cell(0, 10, txt=f"الجدول الأسبوعي للقاعة: {room['code']} ({room['name']})", ln=True, align='C')
        pdf.ln(10)

        # Table Headers
        pdf.set_font('DejaVu', '', 12)
        col_widths = [30, 30, 30, 40, 40, 40] # Adjust as needed
        headers = ["اليوم", "وقت البدء", "وقت الانتهاء", "المادة", "المدرس", "نوع الدراسة"]

        # Print headers
        for i, header in enumerate(headers):
            pdf.cell(col_widths[i], 10, txt=header, border=1, align='C')
        pdf.ln()

        # Table Content
        pdf.set_font('DejaVu', '', 10)
        for day_key, day_arabic_name in day_name_arabic_map.items():
            if schedules_by_day[day_key]:
                pdf.cell(0, 10, txt=f"اليوم: {day_arabic_name}", ln=True, align='R')
                for schedule in schedules_by_day[day_key]:
                    row_data = [
                        "", # Day column is handled by the day header
                        schedule["start_time"],
                        schedule["end_time"],
                        schedule["subject_name"],
                        schedule["instructor_name"],
                        schedule["study_type"]
                    ]
                    for i, data in enumerate(row_data):
                        pdf.cell(col_widths[i], 10, txt=str(data), border=1, align='C')
                    pdf.ln()
            else:
                pdf.cell(0, 10, txt=f"اليوم: {day_arabic_name} - لا توجد جداول", ln=True, align='R')
            pdf.ln(5) # Small space between days

        # Output PDF
        pdf_output = io.BytesIO()
        pdf.output(pdf_output)
        pdf_output.seek(0)

        return send_file(
            pdf_output,
            mimetype="application/pdf",
            as_attachment=True,
            download_name=f"schedule_{room['code']}.pdf"
        )

    except Exception as e:
        print(f"ERROR in download_schedule_pdf: {str(e)}")
        import traceback
        traceback.print_exc()
        return format_response(
            message=f"حدث خطأ: {str(e)}", success=False, status_code=500
        )

@room_bp.route("/<int:room_id>/schedules/all", methods=["DELETE"])
@jwt_required()
def delete_all_schedules(room_id):
    """حذف جميع الجداول لقاعة معينة"""
    try:
        supabase = current_app.supabase
        username = get_jwt_identity()
        user = get_user_by_username(username)

        if not user:
            return format_response(
                message="المستخدم غير موجود", success=False, status_code=404
            )

        # Allow owners to upload weekly schedules for a room as well
        if user["role"] not in ["dean", "owner", "department_head", "supervisor"]:
            return format_response(
                message="ليس لديك صلاحية لهذا الإجراء",
                success=False,
                status_code=403,
            )

        # Check if room exists
        room_res = supabase.table("rooms").select("*").eq("id", room_id).execute()
        if not room_res.data:
            return format_response(
                message="القاعة غير موجودة", success=False, status_code=404
            )
        room = room_res.data[0]

        # Check user authorization
        if user["role"] != "dean" and room["department_id"] != user["department_id"]:
            return format_response(
                message="لا يمكنك حذف جداول هذه القاعة",
                success=False,
                status_code=403,
            )

        # Get IDs of schedules to be deleted
        schedules_to_delete_res = supabase.table("schedules").select("id").eq("room_id", room_id).execute()
        schedules_to_delete_ids = [s["id"] for s in schedules_to_delete_res.data]

        if schedules_to_delete_ids:
            # Nullify moved_to_schedule_id references to schedules in this room
            supabase.table("schedules").update({"moved_to_schedule_id": None}).in_("moved_to_schedule_id", schedules_to_delete_ids).execute()
            
            # Nullify original_schedule_id references to schedules in this room
            supabase.table("schedules").update({"original_schedule_id": None}).in_("original_schedule_id", schedules_to_delete_ids).execute()
        # Delete all existing schedules for this room
        supabase.table("schedules").delete().eq("room_id", room_id).execute()

        return format_response(message="تم حذف جميع جداول القاعة بنجاح")

    except Exception as e:
        return format_response(
            message=f"حدث خطأ: {str(e)}", success=False, status_code=500
        )