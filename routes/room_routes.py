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

try:
    from fpdf import FPDF
except ImportError:
    FPDF = None

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

        if user["role"] != "dean":
            if not user.get("department_id"):
                return format_response(
                    message="المستخدم غير مرتبط بقسم",
                    success=False,
                    status_code=403,
                )
            query = query.eq("department_id", user["department_id"])

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

        if user["role"] not in ["dean", "department_head", "supervisor"]:
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

        if user["role"] in ["department_head", "supervisor"]:
            department_id = user["department_id"]
        else:
            department_id = data.get("department_id")

        if not department_id:
            return format_response(
                message="معرف القسم مطلوب", success=False, status_code=400
            )

        room_res = (
            supabase.table("rooms")
            .insert(
                {
                    "name": data["name"],
                    "code": data["code"],
                    "department_id": department_id,
                    "capacity": data.get("capacity"),
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
        elif user["role"] != "dean" and room["department_id"] != user["department_id"]:
            return format_response(
                message="لا يمكنك الوصول لهذه القاعة",
                success=False,
                status_code=403,
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

        if room["qr_code_path"]:
            try:
                delete_room_qr(room["qr_code_path"])
            except:
                pass

        supabase.table("schedules").delete().eq("room_id", room_id).execute()
        supabase.table("rooms").delete().eq("id", room_id).execute()

        return format_response(message="تم حذف القاعة بنجاح")

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
        elif user["role"] != "dean" and room["department_id"] != user["department_id"]:
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

        # إثراء كل جدول ببيانات المحاضرين
        from backend.models import get_schedule_doctors
        for schedule in schedules_res.data:
            schedule_doctors = get_schedule_doctors(schedule["id"])
            schedule["schedule_doctors"] = schedule_doctors
            
            # إنشاء قائمة بأسماء المحاضرين للعرض
            if schedule_doctors:
                doctor_names = []
                primary_doctor = None
                for sd in schedule_doctors:
                    doctor_name = sd.get('doctors', {}).get('name', '')
                    if doctor_name:  # إضافة الأسماء غير الفارغة فقط
                        if sd.get('is_primary'):
                            primary_doctor = doctor_name
                        doctor_names.append(doctor_name)
                
                schedule["multiple_doctors_names"] = doctor_names
                schedule["primary_doctor_name"] = primary_doctor
                schedule["has_multiple_doctors"] = len(doctor_names) > 1
            else:
                # لا توجد محاضرين متعددين، تعيين القيم الافتراضية
                schedule["multiple_doctors_names"] = []
                schedule["primary_doctor_name"] = None
                schedule["has_multiple_doctors"] = False
            
            # ملء حقل instructor_name إذا كان فارغاً باستخدام اسم المحاضر الأساسي
            if not schedule.get("instructor_name") and schedule.get("primary_doctor_name"):
                schedule["instructor_name"] = schedule["primary_doctor_name"]

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

        if user["role"] not in ["dean", "department_head", "supervisor"]:
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

        if user["role"] != "dean" and room["department_id"] != user["department_id"]:
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