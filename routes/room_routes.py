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
        lecture_type = data.get("lecture_type")
        if not lecture_type or lecture_type not in ["نظري", "عملي"]:
            return format_response(
                message="نوع المحاضرة مطلوب (نظري أو عملي)",
                success=False,
                status_code=400,
            )
        
        # Validate section/group based on lecture type
        if lecture_type == "نظري":
            section = data.get("section")
            if not section or section not in [1, 2]:
                return format_response(
                    message="الشعبة مطلوبة للمحاضرات النظرية (1 أو 2)",
                    success=False,
                    status_code=400,
                )
            group = None
        elif lecture_type == "عملي":
            group = data.get("group")
            if not group or group not in ["A", "B", "C", "D"]:
                return format_response(
                    message="الكروب مطلوب للمحاضرات العملية (A, B, C, أو D)",
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
            "lecture_type": lecture_type,
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

        return format_response(
            data=schedule_res.data[0] if schedule_res.data else None,
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
            "is_active": True,
        }
        
        # Set instructor_name based on primary doctor or multiple doctors
        if primary_doctor_id:
            primary_doctor_res = supabase.table("doctors").select("name").eq("id", primary_doctor_id).execute()
            if primary_doctor_res.data:
                schedule_data["instructor_name"] = primary_doctor_res.data[0]["name"]
            else:
                schedule_data["instructor_name"] = "متعدد المدرسين"  # "Multiple instructors"
        else:
            schedule_data["instructor_name"] = "متعدد المدرسين"  # "Multiple instructors"

        schedule_res = supabase.table("schedules").insert(schedule_data).execute()
        schedule = schedule_res.data[0]

        # Add doctors to junction table
        from models import add_doctors_to_schedule
        schedule_doctors = add_doctors_to_schedule(schedule["id"], doctor_ids, primary_doctor_id)

        # Get complete schedule with doctors for response
        from models import get_schedule_doctors
        schedule_with_doctors = get_schedule_doctors(schedule["id"])
        schedule["schedule_doctors"] = schedule_with_doctors

        return format_response(
            data=schedule, message="تم إنشاء الجدول بعدة دكاترة بنجاح", status_code=201
        )

    except Exception as e:
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
        if "subject_name" not in data:
            return format_response(
                message="اسم المادة مطلوب", success=False, status_code=400
            )

        # Validate lecture type and grouping for updates
        lecture_type = data.get("lecture_type")
        if lecture_type:
            if lecture_type not in ["نظري", "عملي"]:
                return format_response(
                    message="نوع المحاضرة غير صحيح (نظري أو عملي)",
                    success=False,
                    status_code=400,
                )
            
            # Validate section/group based on lecture type
            if lecture_type == "نظري":
                section = data.get("section")
                if section is not None and section not in [1, 2]:
                    return format_response(
                        message="الشعبة يجب أن تكون 1 أو 2 للمحاضرات النظرية",
                        success=False,
                        status_code=400,
                    )
                group = None
            elif lecture_type == "عملي":
                group = data.get("group")
                if group is not None and group not in ["A", "B", "C", "D"]:
                    return format_response(
                        message="الكروب يجب أن يكون A, B, C, أو D للمحاضرات العملية",
                        success=False,
                        status_code=400,
                    )
                section = None

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

        if user["role"] != "dean" and room["department_id"] != user["department_id"]:
            return format_response(
                message="لا يمكنك تعديل جداول هذه القاعة",
                success=False,
                status_code=403,
            )

        # Validate doctor data based on mode
        use_multiple_doctors = data.get("use_multiple_doctors", False)
        
        if use_multiple_doctors:
            doctor_ids = data.get("doctor_ids", [])
            if not doctor_ids or len(doctor_ids) == 0:
                return format_response(
                    message="يجب اختيار دكتور واحد على الأقل", success=False, status_code=400
                )
            
            # Validate all doctor IDs exist
            for doctor_id in doctor_ids:
                doctor_res = supabase.table("doctors").select("id").eq("id", doctor_id).execute()
                if not doctor_res.data:
                    return format_response(
                        message=f"الدكتور برقم {doctor_id} غير موجود",
                        success=False,
                        status_code=400,
                    )
        else:
            # Single doctor mode
            if "doctor_id" not in data or not data["doctor_id"]:
                return format_response(
                    message="يجب اختيار مدرس", success=False, status_code=400
                )
            
            doctor_res = supabase.table("doctors").select("id").eq("id", data["doctor_id"]).execute()
            if not doctor_res.data:
                return format_response(
                    message="المدرس المحدد غير موجود",
                    success=False,
                    status_code=400,
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
            current_schedule = schedule_res.data[0]

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

            # Check for conflicting schedules
            current_schedule = schedule_res.data[0]
            check_study_type = data.get("study_type", current_schedule["study_type"])
            check_day_of_week = data.get("day_of_week", current_schedule["day_of_week"])
            
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
            
            # Check doctor availability for the new time if changing doctors
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
                            
                            if (sched_start < end_time and
                                sched_end > start_time):
                                
                                doctor_info = supabase.table("doctors").select("name").eq("id", doctor_id).execute()
                                doctor_name = doctor_info.data[0]['name'] if doctor_info.data else 'غير معروف'
                                return format_response(
                                    message=f"الدكتور {doctor_name} لديه تداخل في هذا الوقت مع محاضرة أخرى",
                                    success=False,
                                    status_code=400,
                                )
        else:
            # Check single doctor availability
            if data.get("doctor_id") and data["doctor_id"] != schedule_res.data[0].get("doctor_id"):
                doctor_conflict_res = (
                    supabase.table("schedules")
                    .select("id, doctors!fk_doctor(name)")
                    .eq("doctor_id", data["doctor_id"])
                    .eq("study_type", check_study_type)
                    .eq("day_of_week", check_day_of_week)
                    .eq("is_active", True)
                    .neq("id", schedule_id) # Exclude current schedule from conflict check
                    .lt("start_time", data['end_time'])
                    .gt("end_time", data['start_time'])
                    .execute()
                )
                
                if doctor_conflict_res.data:
                    doctor_name = doctor_conflict_res.data[0].get('doctors', {}).get('name', 'غير معروف') if doctor_conflict_res.data else 'غير معروف'
                    return format_response(
                        message=f"الدكتور {doctor_name} لديه تداخل في هذا الوقت مع محاضرة أخرى",
                        success=False,
                        status_code=400,
                    )

            if conflicting_schedule_res.data:
                return format_response(
                    message="يوجد تداخل مع جدول آخر في نفس الوقت",
                    success=False,
                    status_code=400,
                )

            update_data["start_time"] = data["start_time"]
            update_data["end_time"] = data["end_time"]

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
            .select("id")
            .eq("id", schedule_id)
            .eq("room_id", room_id)
            .execute()
        )
        if not schedule_res.data:
            return format_response(
                message="الجدول غير موجود", success=False, status_code=404
            )

        if user["role"] != "dean" and room["department_id"] != user["department_id"]:
            return format_response(
                message="لا يمكنك حذف جداول هذه القاعة",
                success=False,
                status_code=403,
            )

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

        if user["role"] != "dean" and room["department_id"] != user["department_id"]:
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

        if user["role"] not in ["dean", "department_head", "supervisor"]:
            return format_response(
                message="صلاحيات غير كافية", success=False, status_code=403
            )

        room_res = supabase.table("rooms").select("*").eq("id", room_id).execute()
        if not room_res.data:
            return format_response(
                message="القاعة غير موجودة", success=False, status_code=404
            )
        room = room_res.data[0]

        if user["role"] != "dean" and room["department_id"] != user["department_id"]:
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

        # Create an announcement for the postponed lecture
        announcement_title = f"إعلان تأجيل محاضرة: {original_schedule['subject_name']}"
        announcement_body = (
            f"تم تأجيل محاضرة {original_schedule['subject_name']} للمدرس {original_schedule['instructor_name']} "
            f"التي كانت في القاعة {original_schedule['room_id']} يوم {original_schedule['day_of_week']} "
            f"من الساعة {original_schedule['start_time']} إلى {original_schedule['end_time']}. "
            f"الموعد الجديد: {data['postponed_date']} في القاعة {data['postponed_to_room_id']} "
            f"من الساعة {data['postponed_start_time']} إلى {data['postponed_end_time']}. "
            f"السبب: {data['postponed_reason']}."
        )

        # Fetch original room code for announcement
        original_room_code_res = supabase.table("rooms").select("code").eq("id", original_schedule['room_id']).execute()
        original_room_code = original_room_code_res.data[0]['code'] if original_room_code_res.data else original_schedule['room_id']

        # Fetch new room code for announcement
        new_room_code_res = supabase.table("rooms").select("code").eq("id", data['postponed_to_room_id']).execute()
        new_room_code = new_room_code_res.data[0]['code'] if new_room_code_res.data else data['postponed_to_room_id']

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

        announcement_body_with_codes = (
            f"تم تأجيل محاضرة {original_schedule['subject_name']} للمدرس {original_schedule['instructor_name']} "
            f"التي كانت في القاعة {original_room_code} يوم {arabic_day_of_week} "
            f"من الساعة {original_schedule['start_time']} إلى {original_schedule['end_time']}. "
            f"الموعد الجديد: {data['postponed_date']} في القاعة {new_room_code} "
            f"من الساعة {data['postponed_start_time']} إلى {data['postponed_end_time']}. "
            f"السبب: {data['postponed_reason']}."
        )

        announcement_data = {
            "title": announcement_title,
            "body": announcement_body_with_codes,
            "is_global": True, # Make it global for now, or link to department_id if needed
            "is_active": True,
            "department_id": original_schedule.get('department_id') # Link to original schedule's department
        }
        
        # Ensure department_id is fetched for original_schedule
        if not original_schedule.get('department_id'):
            original_room_dept_res = supabase.table("rooms").select("department_id").eq("id", original_schedule['room_id']).execute()
            if original_room_dept_res.data:
                announcement_data['department_id'] = original_room_dept_res.data[0]['department_id']

        supabase.table("announcements").insert(announcement_data).execute()

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

        if user["role"] not in ["dean", "department_head", "supervisor"]:
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

                # Check for conflicting schedules
                conflicting_schedule_res = (
                    supabase.table("schedules")
                    .select("*")
                    .eq("room_id", room_id)
                    .eq("study_type", row["study_type"])
                    .eq("day_of_week", row["day_of_week"])
                    .eq("is_active", True)
                    .lt("start_time", str(row['end_time']))
                    .gt("end_time", str(row['start_time']))
                    .neq("end_time", str(row['start_time']))  # استثناء الحالات المتتالية
                    .neq("start_time", str(row['end_time']))  # استثناء الحالات المتتالية
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
                    "start_time": str(row["start_time"]),
                    "end_time": str(row["end_time"]),
                    "subject_name": row["subject_name"],
                    "instructor_name": instructor_name,  # Always save the name for display
                    "notes": str(row.get("notes")) if pd.notna(row.get("notes")) else "",
                    "section": str(row["section"]).strip() if pd.notna(row.get("section")) and str(row["section"]).strip() else None,  # Handle section
                    "group": str(row["group"]).strip() if pd.notna(row.get("group")) and str(row["group"]).strip() else None,    # Handle group
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

        if user["role"] != "dean": # Only dean can upload general schedule
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
                        "section": str(row["section"]).strip() if pd.notna(row.get("section")) and str(row["section"]).strip() else None,  # Handle section
                        "group": str(row["group"]).strip() if pd.notna(row.get("group")) and str(row["group"]).strip() else None,    # Handle group
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
        if FPDF is None:
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

        if user["role"] not in ["dean", "department_head", "supervisor"]:
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

        # Delete all schedules for this room
        supabase.table("schedules").delete().eq("room_id", room_id).execute()

        return format_response(message="تم حذف جميع جداول القاعة بنجاح")

    except Exception as e:
        return format_response(
            message=f"حدث خطأ: {str(e)}", success=False, status_code=500
        )