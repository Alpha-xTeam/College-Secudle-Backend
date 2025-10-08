from flask import Blueprint, request, send_file, current_app
from flask_jwt_extended import jwt_required, get_jwt_identity
from models import get_room_by_code, get_schedules_by_room_id, get_all_departments, log_general_page_usage
from utils.qr_generator import generate_room_qr
from utils.helpers import format_response
import os

public_bp = Blueprint("public", __name__)


@public_bp.route("/room/<room_code>", methods=["GET"])
def get_room_info(room_code):
    """الحصول على معلومات القاعة (عام - بدون تسجيل دخول)"""
    try:
        supabase = current_app.supabase
        room_res = (
            supabase.table("rooms")
            .select("*, department:departments(name)")
            .eq("code", room_code)
            .eq("is_active", True)
            .execute()
        )

        if not room_res.data:
            return format_response(
                message="القاعة غير موجودة", success=False, status_code=404
            )

        return format_response(
            data=room_res.data[0], message="تم جلب معلومات القاعة بنجاح"
        )

    except Exception as e:
        return format_response(
            message=f"حدث خطأ: {str(e)}", success=False, status_code=500
        )


@public_bp.route("/room/<room_code>/schedule", methods=["GET"])
def get_room_schedule(room_code):
    """الحصول على جدول القاعة حسب نوع الدراسة (عام - بدون تسجيل دخول)"""
    try:
        supabase = current_app.supabase
        room_res = (
            supabase.table("rooms")
            .select("*, department:departments(name)")
            .eq("code", room_code)
            .eq("is_active", True)
            .execute()
        )

        if not room_res.data:
            return format_response(
                message="القاعة غير موجودة", success=False, status_code=404
            )
        room = room_res.data[0]

        study_type = request.args.get("study_type")

        if not study_type or study_type not in ["morning", "evening"]:
            return format_response(
                message="نوع الدراسة مطلوب (morning أو evening)",
                success=False,
                status_code=400,
            )

        # Get regular schedules
        from datetime import datetime
        today = datetime.now().date().strftime("%Y-%m-%d")
        
        schedules_res = (
            supabase.table("schedules")
            .select("*")
            .eq("study_type", study_type)
            .eq("is_active", True)
            .eq("room_id", room["id"])
            .order("day_of_week")
            .order("academic_stage")
            .order("start_time")
            .execute()
        )

        # Process schedules to determine what should be displayed
        from datetime import datetime
        today = datetime.now().date()
        display_schedules = []
        
        # Get multiple doctors for each schedule first
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
                    if doctor_name:  # Only add non-empty names
                        if sd.get('is_primary'):
                            primary_doctor = doctor_name
                        doctor_names.append(doctor_name)
                
                schedule["multiple_doctors_names"] = doctor_names
                schedule["primary_doctor_name"] = primary_doctor
                schedule["has_multiple_doctors"] = len(doctor_names) > 1
            else:
                # No multiple doctors, set default values
                schedule["multiple_doctors_names"] = []
                schedule["primary_doctor_name"] = None
                schedule["has_multiple_doctors"] = False
        
        # Process schedules to determine what should be displayed
        for schedule in schedules_res.data:
            # إذا كانت المحاضرة مؤجلة، لا تضفها إطلاقاً إلى اليوم الأصلي ولا تظهر إلا في اليوم المؤجل فقط
            if schedule.get("is_postponed") and schedule.get("postponed_date"):
                continue
            # Check if this is a schedule that was moved into this room temporarily
            elif schedule.get("is_temporary_move_in") and schedule.get("original_schedule_id"):
                original_schedule_res = (
                    supabase.table("schedules")
                    .select("room_id, day_of_week, start_time, end_time, move_reason, original_booking_date")
                    .eq("id", schedule["original_schedule_id"])
                    .execute()
                )
                if original_schedule_res.data:
                    original_schedule = original_schedule_res.data[0]
                    schedule["is_moved_in_display"] = True
                    schedule["original_room_id"] = original_schedule.get("room_id")
                    schedule["original_day_of_week"] = original_schedule.get("day_of_week")
                    schedule["original_start_time"] = original_schedule.get("start_time")
                    schedule["original_end_time"] = original_schedule.get("end_time")
                    schedule["move_reason"] = original_schedule.get("move_reason")
                    schedule["original_booking_date"] = original_schedule.get("original_booking_date")

                    # Fetch original room name
                    if schedule.get("original_room_id"):
                        original_room_res = (
                            supabase.table("rooms")
                            .select("name, code")
                            .eq("id", schedule["original_room_id"])
                            .execute()
                        )
                        if original_room_res.data:
                            schedule["original_room_name"] = original_room_res.data[0].get("name", "")
                            schedule["original_room_code"] = original_room_res.data[0].get("code", "")
                display_schedules.append(schedule)
            # Regular schedule for this room with no postponement or move
            else:
                schedule["is_postponed_today"] = False
                display_schedules.append(schedule)

        organized_schedule = {}
        days_order = [
            "sunday",
            "monday",
            "tuesday",
            "wednesday",
            "thursday",
            "friday",
            "saturday",
        ]
        stages_order = ["first", "second", "third", "fourth"]

        for day in days_order:
            organized_schedule[day] = {}
            for stage in stages_order:
                organized_schedule[day][stage] = []

        # أولاً: أضف جميع المحاضرات غير المؤجلة بشكل طبيعي
        for schedule in display_schedules:
            if not (schedule.get("is_postponed") and schedule.get("postponed_date") and schedule.get("postponed_start_time") and schedule.get("postponed_end_time")):
                day_of_week = schedule["day_of_week"].lower()
                schedule["stage"] = schedule["academic_stage"]
                if day_of_week in organized_schedule:
                    organized_schedule[day_of_week][schedule["academic_stage"]].append(schedule)

        # ثانياً: أضف جميع المحاضرات المؤجلة في اليوم المؤجل فقط
        for schedule in display_schedules:
            if schedule.get("is_postponed") and schedule.get("postponed_date") and schedule.get("postponed_start_time") and schedule.get("postponed_end_time"):
                # أضف المحاضرة المؤجلة فقط إذا كانت القاعة الحالية هي القاعة المؤجلة إليها
                if schedule.get("postponed_to_room_id") == room["id"]:
                    from datetime import datetime
                    postponed_date = schedule["postponed_date"]
                    days_order = [
                        "sunday",
                        "monday",
                        "tuesday",
                        "wednesday",
                        "thursday",
                        "friday",
                        "saturday",
                    ]
                    date_obj = datetime.strptime(postponed_date, "%Y-%m-%d")
                    target_day = days_order[date_obj.weekday()]
                    schedule["stage"] = schedule["academic_stage"]
                    if target_day in organized_schedule:
                        organized_schedule[target_day][schedule["academic_stage"]].append(schedule)

        response_data = {
            "room": {
                "name": room["name"],
                "code": room["code"],
                "department_name": room["department"]["name"],
                "capacity": room["capacity"],
            },
            "study_type": study_type,
            "schedule": organized_schedule
        }

        return format_response(data=response_data, message="تم جلب الجدول بنجاح")

    except Exception as e:
        import traceback
        traceback.print_exc()
        return format_response(
            message=f"An unexpected error occurred: {str(e)}", success=False, status_code=500
        )


@public_bp.route("/room/<room_code>/qr", methods=["GET"])
@jwt_required()
def get_room_qr(room_code):
    """تحميل QR Code الخاص بالقاعة (محمية)"""
    try:
        supabase = current_app.supabase
        username = get_jwt_identity()
        user_res = supabase.table("users").select("id").eq("username", username).execute()
        if not user_res.data:
            return format_response(
                message="يجب تسجيل الدخول أولاً", success=False, status_code=401
            )

        room_res = (
            supabase.table("rooms")
            .select("*")
            .eq("code", room_code)
            .eq("is_active", True)
            .execute()
        )

        if not room_res.data:
            return format_response(
                message="القاعة غير موجودة", success=False, status_code=404
            )
        room = room_res.data[0]

        if not room["qr_code_path"] or not os.path.exists(room["qr_code_path"]):
            new_qr_path = generate_room_qr(room["code"], room["id"])
            if not new_qr_path or not os.path.exists(new_qr_path):
                return format_response(
                    message="تعذّر إنشاء QR Code لهذه القاعة",
                    success=False,
                    status_code=500,
                )
            
            supabase.table("rooms").update({"qr_code_path": new_qr_path}).eq("id", room["id"]).execute()
            room["qr_code_path"] = new_qr_path


        return send_file(
            room["qr_code_path"],
            as_attachment=True,
            download_name=f"room_{room_code}_qr.png",
        )

    except Exception as e:
        return format_response(
            message=f"حدث خطأ: {str(e)}", success=False, status_code=500
        )


@public_bp.route("/departments", methods=["GET"])
def get_departments_public():
    """الحصول على قائمة الأقسام (محمية)"""
    try:
        departments = get_all_departments()
        return format_response(data=departments, message="تم جلب الأقسام بنجاح")

    except Exception as e:
        return format_response(
            message=f"حدث خطأ: {str(e)}", success=False, status_code=500
        )


@public_bp.route("/departments/summary", methods=["GET"])
def get_departments_summary():
    """إرجاع ملخص عن الأقسام: عدد القاعات، عدد الدكاترة، اسم رئيس القسم، وقائمة القاعات مع السعة واسم ملف QR (عام - بدون تسجيل دخول)"""
    try:
        supabase = current_app.supabase
        departments_res = supabase.table("departments").select("*").execute()
        if not departments_res.data:
            return format_response(data=[], message="لا توجد أقسام");

        summary = []
        import os
        for dept in departments_res.data:
            dept_id = dept.get("id")
            # Rooms for this department
            rooms_res = (
                supabase.table("rooms")
                .select("id,name,code,capacity,qr_code_path")
                .eq("department_id", dept_id)
                .eq("is_active", True)
                .execute()
            )
            rooms = []
            if rooms_res.data:
                for r in rooms_res.data:
                    qr_path = r.get("qr_code_path")
                    qr_filename = os.path.basename(qr_path) if qr_path else None
                    rooms.append({
                        "id": r.get("id"),
                        "name": r.get("name"),
                        "code": r.get("code"),
                        "capacity": r.get("capacity"),
                        "qr_filename": qr_filename,
                    })

            # Count doctors in dept
            doctors_count_res = (
                supabase.table("doctors").select("id", count="exact").eq("department_id", dept_id).execute()
            )
            doctors_count = doctors_count_res.count if doctors_count_res is not None else 0

            # Find department head name (user with role department_head)
            head_res = (
                supabase.table("users").select("full_name").eq("department_id", dept_id).eq("role", "department_head").limit(1).execute()
            )
            head_name = None
            if head_res and head_res.data:
                head_name = head_res.data[0].get("full_name")

            summary.append({
                "id": dept_id,
                "name": dept.get("name"),
                "head_name": head_name,
                "doctors_count": doctors_count,
                "rooms": rooms,
            })

        return format_response(data=summary, message="تم جلب ملخص الأقسام بنجاح")

    except Exception as e:
        import traceback
        traceback.print_exc()
        return format_response(message=f"حدث خطأ: {str(e)}", success=False, status_code=500)


@public_bp.route("/search/rooms", methods=["GET"])
def search_rooms():
    """البحث في القاعات (محمية)"""
    try:
        supabase = current_app.supabase
        query = request.args.get("q", "").strip()
        department_id = request.args.get("department_id")

        rooms_query = supabase.table("rooms").select("*, department:departments(name)").eq("is_active", True)

        if query:
            rooms_query = rooms_query.or_(
                f"name.ilike.%{query}%,code.ilike.%{query}%"
            )

        if department_id:
            rooms_query = rooms_query.eq("department_id", department_id)

        rooms_res = rooms_query.limit(20).execute()

        return format_response(data=rooms_res.data, message="تم البحث بنجاح")

    except Exception as e:
        return format_response(
            message=f"حدث خطأ: {str(e)}", success=False, status_code=500
        )


@public_bp.route("/room/<room_code>/view", methods=["GET"])
def view_room_schedule(room_code):
    """عرض جدول القاعة بشكل مباشر (بدون تسجيل دخول)"""
    try:
        supabase = current_app.supabase
        room_res = (
            supabase.table("rooms")
            .select("*, department:departments(name)")
            .eq("code", room_code)
            .eq("is_active", True)
            .execute()
        )

        if not room_res.data:
            return format_response(
                message="القاعة غير موجودة", success=False, status_code=404
            )
        room = room_res.data[0]

        # Get regular schedules
        schedules_res = (
            supabase.table("schedules")
            .select("*")
            .eq("room_id", room["id"])
            .eq("is_active", True)
            .order("day_of_week")
            .order("academic_stage")
            .order("start_time")
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
                    if doctor_name:  # Only add non-empty names
                        if sd.get('is_primary'):
                            primary_doctor = doctor_name
                        doctor_names.append(doctor_name)
                
                schedule["multiple_doctors_names"] = doctor_names
                schedule["primary_doctor_name"] = primary_doctor
                schedule["has_multiple_doctors"] = len(doctor_names) > 1
            else:
                # No multiple doctors, set default values
                schedule["multiple_doctors_names"] = []
                schedule["primary_doctor_name"] = None
                schedule["has_multiple_doctors"] = False

        organized_schedule = {}
        days_order = [
            "sunday",
            "monday",
            "tuesday",
            "wednesday",
            "thursday",
            "friday",
            "saturday",
        ]
        stages_order = ["first", "second", "third", "fourth"]

        for day in days_order:
            organized_schedule[day] = {}
            for stage in stages_order:
                organized_schedule[day][stage] = []

        # Process regular schedules
        for schedule in schedules_res.data:
            day_of_week = schedule["day_of_week"].lower()
            if day_of_week in organized_schedule:
                organized_schedule[day_of_week][
                    schedule["academic_stage"]
                ].append(schedule)

        room_data = {
            "id": room["id"],
            "name": room["name"],
            "code": room["code"],
            "department_name": room["department"]["name"],
            "capacity": room["capacity"],
            "description": room["description"],
            "qr_code_path": room["qr_code_path"],
            "is_active": room["is_active"],
            "created_at": room["created_at"],
        }

        return format_response(
            data={"room": room_data, "schedule": organized_schedule},
            message=f"تم جلب جدول القاعة {room['name']} بنجاح",
        )
    except Exception as e:
        return format_response(
            message=f"حدث خطأ: {str(e)}", success=False, status_code=500
        )


@public_bp.route("/room/<room_code>/announcements", methods=["GET"])
def get_room_announcements(room_code):
    """الحصول على إعلانات قسم القاعة (عام - بدون تسجيل دخول)"""
    try:
        supabase = current_app.supabase
        
        # Step 1: Get department_id from room_code
        room_res = (
            supabase.table("rooms")
            .select("department_id")
            .eq("code", room_code)
            .eq("is_active", True)
            .single()
            .execute()
        )

        # Check for errors after fetching room data
        if not hasattr(room_res, 'data'):
            return format_response(message="Failed to fetch room data or invalid response.", success=False, status_code=500)

        if not room_res.data:
            return format_response(
                message=f"Room with code '{room_code}' not found.", success=False, status_code=404
            )

        department_id = room_res.data.get("department_id")

        # Step 2: Build the query for announcements
        query = supabase.table("announcements").select("*").eq("is_active", True)

        if department_id:
            query = query.or_(f"is_global.eq.True,department_id.eq.{department_id}")
        else:
            # If no department is associated with the room, only fetch global announcements
            query = query.eq("is_global", True)
        
        # Step 3: Execute the query
        announcements_res = query.order("created_at", desc=True).limit(50).execute()

        if not hasattr(announcements_res, 'data'):
            return format_response(message="Failed to fetch announcements or invalid response.", success=False, status_code=500)

        # Step 4: Return the response
        return format_response(
            data=announcements_res.data, message="تم جلب الإعلانات بنجاح"
        )

    except Exception as e:
        # General catch-all for any other unexpected errors
        import traceback
        traceback.print_exc()
        return format_response(
            message=f"An unexpected error occurred: {str(e)}", success=False, status_code=500
        )

@public_bp.route("/department/<int:department_id>/weekly-schedule/<stage>/<study_type>", methods=["GET"])
def get_full_weekly_schedule(department_id, stage, study_type):
    """
    جلب الجدول الأسبوعي الكامل لمرحلة ونوع دراسة معين في قسم.
    """
    try:
        supabase = current_app.supabase
        
        # Query to get all schedules for the given department, stage, and study type
        # Include all postponement related fields
        query = (
            supabase.table("schedules")
            .select("id,day_of_week,start_time,end_time,subject_name,instructor_name,is_postponed,postponed_date,postponed_start_time,postponed_end_time,postponed_to_room_id,is_moved_out,is_temporary_move_in,original_schedule_id,room:rooms!schedules_room_id_fkey(name,code),group,group_letter,section,section_number")
            .eq("department_id", department_id)
            .eq("academic_stage", stage)
            .eq("study_type", study_type)
            .eq("is_active", True)
            .order("day_of_week")
            .order("start_time")
            .execute()
        )

        if not query.data:
            return format_response(data={}, message="لا توجد بيانات جدول متاحة لهذه المرحلة.")

        # Get multiple doctors for each schedule
        from models import get_schedule_doctors
        for schedule in query.data:
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

        # Filter and organize data
        schedule_by_day = {}
        days_order = ["sunday", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday"]
        
        for day in days_order:
            schedule_by_day[day] = []

        for item in query.data:
            # If it's an original schedule that has been moved out AND postponed, DO NOT include it
            if item.get("is_moved_out") and item.get("is_postponed"):
                continue
            
            # If it's a temporary move-in, use its postponed details for display
            if item.get("is_temporary_move_in"):
                # Fetch the room name/code for the postponed_to_room_id if available
                postponed_room_name = "N/A"
                postponed_room_code = "N/A"
                if item.get("postponed_to_room_id"):
                    room_res = supabase.table("rooms").select("name,code").eq("id", item["postponed_to_room_id"]).execute()
                    if room_res.data:
                        postponed_room_name = room_res.data[0].get("name")
                        postponed_room_code = room_res.data[0].get("code")

                schedule_item = {
                    "id": item.get("id"),
                    "subject_name": item.get("subject_name"),
                    "instructor_name": item.get("instructor_name"),
                    "room_name": postponed_room_name, # Use postponed room name
                    "room_code": postponed_room_code, # Use postponed room code
                    "start_time": item.get("postponed_start_time"), # Use postponed start time
                    "end_time": item.get("postponed_end_time"), # Use postponed end time
                    "day_of_week": item.get("day_of_week"), # This should be the day of the postponed date
                    "is_postponed": True, # Mark as postponed for frontend
                    "postponed_date": item.get("postponed_date"),
                    "postponed_start_time": item.get("postponed_start_time"),
                    "postponed_end_time": item.get("postponed_end_time"),
                    "postponed_to_room_id": item.get("postponed_to_room_id"),
                    "is_temporary_move_in": True,
                    "original_schedule_id": item.get("original_schedule_id"),
                    # Include grouping/section info if present
                    "group": item.get("group"),
                    "group_letter": item.get("group_letter"),
                    "section": item.get("section"),
                    "section_number": item.get("section_number"),
                    # Include multiple doctors data
                    "multiple_doctors_names": item.get("multiple_doctors_names", []),
                    "primary_doctor_name": item.get("primary_doctor_name"),
                    "has_multiple_doctors": item.get("has_multiple_doctors", False),
                }
                # Ensure the day of week for the temporary move-in is correct based on postponed_date
                from datetime import datetime
                if item.get("postponed_date"):
                    date_obj = datetime.strptime(item["postponed_date"], "%Y-%m-%d")
                    schedule_item["day_of_week"] = days_order[date_obj.weekday()]

            else: # Regular schedule
                schedule_item = {
                    "id": item.get("id"),
                    "subject_name": item.get("subject_name"),
                    "instructor_name": item.get("instructor_name"),
                    "room_name": item.get("room", {}).get("name") if item.get("room") else "N/A",
                    "room_code": item.get("room", {}).get("code") if item.get("room") else "N/A",
                    "start_time": item.get("start_time"),
                    "end_time": item.get("end_time"),
                    "day_of_week": item.get("day_of_week"),
                    "is_postponed": False, # Explicitly mark as not postponed
                    "is_moved_out": False, # Explicitly mark as not moved out
                    # Include grouping/section info if present
                    "group": item.get("group"),
                    "group_letter": item.get("group_letter"),
                    "section": item.get("section"),
                    "section_number": item.get("section_number"),
                    # Include multiple doctors data
                    "multiple_doctors_names": item.get("multiple_doctors_names", []),
                    "primary_doctor_name": item.get("primary_doctor_name"),
                    "has_multiple_doctors": item.get("has_multiple_doctors", False),
                }
            
            day = schedule_item.get("day_of_week")
            if day and day in schedule_by_day:
                schedule_by_day[day].append(schedule_item)

        return format_response(data=schedule_by_day, message="تم جلب الجدول الأسبوعي بنجاح.")

    except Exception as e:
        print(f"Error fetching full weekly schedule: {str(e)}")
        import traceback
        traceback.print_exc()
        return format_response(
            message=f"حدث خطأ في الخادم: {str(e)}", success=False, status_code=500
        )


@public_bp.route('/log/student', methods=['POST'])
def log_student_usage():
    """Log when a student uses the General page by submitting their student ID.

    Accepts JSON: { studentId: string, name?: string, meta?: object }
    This endpoint is intentionally public (no auth) because General page can be used anonymously.
    """
    try:
        data = request.get_json(force=True) or {}
        student_id = data.get('studentId') or data.get('student_id')
        student_name = data.get('name') or data.get('student_name')
        meta = data.get('meta') or {}
        if not student_id:
            return format_response(message='studentId is required', success=False, status_code=400)

        record = log_general_page_usage(student_id, student_name, page='general', meta=meta)
        return format_response(data=record, message='Logged student usage')
    except Exception as e:
        return format_response(message=f'Failed to log usage: {str(e)}', success=False, status_code=500)