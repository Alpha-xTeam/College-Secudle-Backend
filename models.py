from supabase import Client
from flask import current_app
import bcrypt
import hashlib
import random

def get_supabase() -> Client:
    return current_app.supabase

# --- User Model Functions ---
def get_user_by_username(username: str):
    supabase = get_supabase()
    response = supabase.table('users').select('*').eq('username', username).execute()
    return response.data[0] if response.data else None

def get_user_by_email(email: str):
    supabase = get_supabase()
    response = supabase.table('users').select('*').eq('email', email).execute()
    return response.data[0] if response.data else None

def create_user(data: dict):
    supabase = get_supabase()
    password = data.pop('password')
    password_hash = set_password(password)
    data['password_hash'] = password_hash
    response = supabase.table('users').insert(data).execute()
    return response.data[0] if response.data else None

def check_password(password_hash: str, password: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode('utf-8'), password_hash.encode('utf-8'))
    except Exception:
        return password_hash == hashlib.sha256(password.encode('utf-8')).hexdigest()

def set_password(password: str) -> str:
    try:
        return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt(rounds=12)).decode('utf-8')
    except Exception:
        return hashlib.sha256(password.encode('utf-8')).hexdigest()

# --- Department Model Functions ---
def get_all_departments():
    supabase = get_supabase()
    response = supabase.table('departments').select('*').execute()
    return response.data

# --- Room Model Functions ---
def get_room_by_code(code: str):
    supabase = get_supabase()
    response = supabase.table('rooms').select('*').eq('code', code).execute()
    return response.data[0] if response.data else None

# --- Schedule Model Functions ---
def get_schedules_by_room_id(room_id: int):
    supabase = get_supabase()
    response = supabase.table('schedules').select('*').eq('room_id', room_id).execute()
    return response.data

def get_schedules_by_section_and_stage(section: str, stage: str, group: str, study_type: str):
    supabase = get_supabase()
    # Fetch candidate schedules filtered by stage and study_type server-side,
    # then apply Python-side filtering for section/group to correctly express
    # (section IS NULL OR section = student_section) AND (group IS NULL OR group = student_group).
    response = (
        supabase.table('schedules')
        .select('*, rooms!schedules_room_id_fkey(name, code), doctors!fk_doctor(name)')
        .eq('academic_stage', stage)
        .eq('study_type', study_type)
        .eq('is_active', True)
        .execute()
    )

    if not response.data:
        return []

    candidates = response.data

    def matches_section(sched_section, sched_section_number, student_section):
        # Treat NULL/None schedule section as a wildcard match
        if sched_section is None and sched_section_number is None:
            return True
        # Compare by string field first
        if sched_section is not None:
            return str(sched_section).strip().lower() == str(student_section or '').strip().lower()
        # Otherwise compare numeric section number if available
        try:
            if sched_section_number is not None and student_section is not None:
                return int(sched_section_number) == int(student_section)
        except Exception:
            pass
        return False

    def matches_group(sched_group, sched_group_letter, student_group):
        # Treat NULL/None schedule group as a wildcard match (applies to all groups)
        if sched_group is None and sched_group_letter is None:
            return True
        # Compare explicit group field first
        if sched_group is not None:
            return str(sched_group).strip().lower() == str(student_group or '').strip().lower()
        # Compare group_letter (single letter) second
        if sched_group_letter is not None:
            return str(sched_group_letter).strip().upper() == str(student_group or '').strip().upper()
        return False

    filtered = [
        s for s in candidates
        if matches_section(s.get('section'), s.get('section_number'), section)
        and matches_group(s.get('group'), s.get('group_letter'), group)
    ]

    # Enrich each schedule with schedule_doctors (primary + assistants) and
    # ensure instructor_name is filled from primary doctor when missing.
    for s in filtered:
        try:
            sd = get_schedule_doctors(s.get('id')) or []
            # attach raw schedule_doctors to the schedule object
            s['schedule_doctors'] = sd

            primary = None
            assistants = []
            for entry in sd:
                # Each entry may contain nested doctors info under 'doctors'
                doc = None
                if isinstance(entry, dict):
                    if entry.get('doctors') and isinstance(entry.get('doctors'), dict):
                        doc = entry['doctors'].get('name')
                    else:
                        # Some responses may include a flat doctor_name
                        doc = entry.get('doctor_name') or entry.get('name')
                if entry.get('is_primary'):
                    primary = doc or primary
                else:
                    if doc:
                        assistants.append(doc)

            s['primary_doctor_name'] = primary
            s['assistants'] = assistants

            # Fallback: if legacy instructor_name is empty, use primary doctor's name
            if not s.get('instructor_name') and primary:
                s['instructor_name'] = primary

            # Canonical display fields for frontend convenience
            # Prefer postponed times/room when present
            s['start_display'] = s.get('postponed_start_time') or s.get('start_time') or ''
            s['end_display'] = s.get('postponed_end_time') or s.get('end_time') or ''
            s['display_room_name'] = (
                s.get('postponed_room_name')
                or s.get('postponed_to_room_id') and None
                or s.get('room_name')
                or (s.get('rooms') and s.get('rooms').get('name'))
                or s.get('room')
                or ''
            )
        except Exception as e:
            # Best-effort enrichment; do not fail the whole request because of enrichment issues
            try:
                current_app.logger.warning(f'get_schedules_by_section_and_stage: failed enriching schedule {s.get("id")}: {e}')
            except Exception:
                # ignore logging failures
                pass

    return filtered

def get_schedules_by_doctor_id(doctor_id: int):
    supabase = get_supabase()
    response = supabase.table('schedules').select('*, rooms!schedules_room_id_fkey(name, code), doctors!fk_doctor(name)').eq('doctor_id', doctor_id).execute()
    return response.data

# --- Announcement Model Functions ---
def get_all_announcements():
    supabase = get_supabase()
    response = supabase.table('announcements').select('*').execute()
    return response.data

# --- Doctor Model Functions ---
def get_all_doctors():
    supabase = get_supabase()
    response = supabase.table('doctors').select('*, departments!doctors_department_id_fkey(name)').execute()
    return response.data

def get_doctor_by_id(doctor_id: int):
    supabase = get_supabase()
    response = supabase.table('doctors').select('*, departments!doctors_department_id_fkey(name)').eq('id', doctor_id).execute()
    return response.data[0] if response.data else None

def get_doctor_by_name(name: str):
    supabase = get_supabase()
    response = supabase.table('doctors').select('*, departments!doctors_department_id_fkey(name)').eq('name', name).execute()
    return response.data[0] if response.data else None

# Helper: generate unique 4-digit doctor_code
def _generate_unique_doctor_code(supabase: Client, max_attempts: int = 20000) -> int:
    """Generate a unique 4-digit integer (1000-9999) that does not exist in doctors.doctor_code
    or in students.student_id (as text).
    """
    attempts = 0
    while attempts < max_attempts:
        attempts += 1
        code = random.randint(1000, 9999)
        try:
            # Check doctors table
            resp = supabase.table('doctors').select('id').eq('doctor_code', code).limit(1).execute()
            if resp.data:
                continue
            # Also ensure no student uses this code (student_id stored as text/string)
            resp2 = supabase.table('students').select('student_id').eq('student_id', str(code)).limit(1).execute()
            if resp2.data:
                continue
            return code
        except Exception:
            # If DB check fails for some reason, allow a few more attempts before propagating
            continue
    raise Exception('Unable to generate unique 4-digit doctor_code after %d attempts' % max_attempts)

def create_doctor(data: dict):
    supabase = get_supabase()
    # Ensure a unique 4-digit doctor_code is assigned when not explicitly provided
    if 'doctor_code' not in data or data.get('doctor_code') in (None, '', 0):
        try:
            data['doctor_code'] = _generate_unique_doctor_code(supabase)
        except Exception as e:
            # If generation fails, log and continue without setting the code (DB migration should have made column not-null)
            try:
                current_app.logger.error(f'create_doctor: failed to generate doctor_code: {e}')
            except Exception:
                pass
            # Re-raise to prevent inserting invalid nulls for a not-null column
            raise

    response = supabase.table('doctors').insert(data).execute()
    return response.data[0] if response.data else None

def update_doctor(doctor_id: int, data: dict):
    supabase = get_supabase()
    response = supabase.table('doctors').update(data).eq('id', doctor_id).execute()
    return response.data[0] if response.data else None

def delete_doctor(doctor_id: int):
    supabase = get_supabase()
    response = supabase.table('doctors').delete().eq('id', doctor_id).execute()
    return response.data[0] if response.data else None

# --- Schedule-Doctor Junction Functions ---
def add_doctors_to_schedule(schedule_id: int, doctor_ids: list, primary_doctor_id: int = None):
    """Add multiple doctors to a schedule"""
    supabase = get_supabase()
    
    # First, remove existing doctors for this schedule
    supabase.table('schedule_doctors').delete().eq('schedule_id', schedule_id).execute()
    
    # Add new doctors
    schedule_doctors_data = []
    for doctor_id in doctor_ids:
        schedule_doctors_data.append({
            'schedule_id': schedule_id,
            'doctor_id': doctor_id,
            'is_primary': doctor_id == primary_doctor_id
        })
    
    if schedule_doctors_data:
        response = supabase.table('schedule_doctors').insert(schedule_doctors_data).execute()
        return response.data
    return []

def get_schedule_doctors(schedule_id: int):
    """Get all doctors for a specific schedule"""
    supabase = get_supabase()
    response = (
        supabase.table('schedule_doctors')
        .select('*, doctors!schedule_doctors_doctor_id_fkey(id, name)')
        .eq('schedule_id', schedule_id)
        .order('is_primary', desc=True)
        .execute()
    )
    return response.data

def get_doctor_schedules_with_colleagues(doctor_id: int):
    """Get all schedules for a doctor including colleague information"""
    supabase = get_supabase()
    response = (
        supabase.table('schedule_doctors')
        .select('''
            schedule_id,
            is_primary,
            schedules!schedule_doctors_schedule_id_fkey(
                id, subject_name, day_of_week, start_time, end_time,
                study_type, academic_stage,
                rooms!schedules_room_id_fkey(name, code)
            )
        ''')
        .eq('doctor_id', doctor_id)
        .execute()
    )
    return response.data

def remove_doctor_from_schedule(schedule_id: int, doctor_id: int):
    """Remove a specific doctor from a schedule"""
    supabase = get_supabase()
    response = (
        supabase.table('schedule_doctors')
        .delete()
        .eq('schedule_id', schedule_id)
        .eq('doctor_id', doctor_id)
        .execute()
    )
    return response.data

# --- Student Model Functions ---
def get_student_by_id(student_id: str):
    supabase = get_supabase()
    response = supabase.table('students').select('*').eq('student_id', student_id).execute()
    return response.data[0] if response.data else None

def create_student(data: dict):
    supabase = get_supabase()
    # Check for conflict: student_id must not equal any doctor's doctor_code
    student_id = data.get('student_id')
    if student_id is not None:
        try:
            # Compare as text: if student_id is numeric string, compare to doctor_code as text
            resp = supabase.table('doctors').select('id').eq('doctor_code', int(student_id) if str(student_id).isdigit() else None).execute()
            if resp.data:
                raise ValueError('student_id conflicts with an existing doctor code')
            # Additional safe check by string compare in case student_id is string of digits
            resp2 = supabase.table('doctors').select('id').eq('doctor_code', int(student_id) if str(student_id).isdigit() else None).execute()
            if resp2.data:
                raise ValueError('student_id conflicts with an existing doctor code')
        except ValueError:
            # re-raise known conflict
            raise
        except Exception:
            # If DB check failed (e.g., student_id non-numeric), do a string check
            try:
                resp3 = supabase.table('doctors').select('id').execute()
                if resp3.data:
                    for d in resp3.data:
                        # defensive: compare string forms
                        if str(d.get('doctor_code', '')) == str(student_id):
                            raise ValueError('student_id conflicts with an existing doctor code')
            except Exception:
                # If all checks fail due to DB issues, allow insert to proceed and let DB triggers handle conflicts
                pass

    response = supabase.table('students').insert(data).execute()
    return response.data[0] if response.data else None

def update_student(student_id: str, data: dict):
    supabase = get_supabase()
    response = supabase.table('students').update(data).eq('student_id', student_id).execute()
    return response.data[0] if response.data else None

def get_students_by_section_and_stage(section: str, stage: str):
    supabase = get_supabase()
    response = supabase.table('students').select('*').eq('section', section).eq('academic_stage', stage).execute()
    return response.data

def get_all_student_ids():
    supabase = get_supabase()
    response = supabase.table('students').select('student_id').execute()
    return [item['student_id'] for item in response.data] if response.data else []

def delete_student(student_id: str):
    supabase = get_supabase()
    response = supabase.table('students').delete().eq('student_id', student_id).execute()
    return response.data[0] if response.data else None

def search_students(query: str, department_id: int = None):
    """Search students by student_id or name. If department_id is provided, limit results to that department."""
    supabase = get_supabase()
    # Build base query
    req = supabase.table('students').select('*')
    if department_id:
        # Limit to department
        req = req.eq('department_id', department_id)

    # Search by student_id (exact match) or name (case-insensitive partial match)
    req = req.or_(f'student_id.eq.{query},name.ilike.%{query}%')
    response = req.execute()
    return response.data

def get_student_full_schedule(student_id: str):
    student = get_student_by_id(student_id)
    if not student:
        return None

    student_section = student.get('section')
    student_stage = student.get('academic_stage')
    # Support both 'group' and 'group_name' fields (some parts of the app use one or the other)
    student_group = student.get('group') or student.get('group_name')
    student_study_type = student.get('study_type')

    # --- Normalization helpers ---
    def normalize_stage(value):
        if value is None:
            return None
        s = str(value).strip()
        # Map numeric or Arabic labels to English enum values
        stage_map = {
            '1': 'first', 'المرحلة الأولى': 'first', 'الاولى': 'first', 'first': 'first',
            '2': 'second', 'المرحلة الثانية': 'second', 'الثانية': 'second', 'second': 'second',
            '3': 'third', 'المرحلة الثالثة': 'third', 'الثالثة': 'third', 'third': 'third',
            '4': 'fourth', 'المرحلة الرابعة': 'fourth', 'الرابعة': 'fourth', 'fourth': 'fourth'
        }
        return stage_map.get(s.lower(), stage_map.get(s, s))

    def normalize_study_type(value):
        if value is None:
            return None
        t = str(value).strip()
        type_map = {
            'صباحي': 'morning', 'صباح': 'morning', 'morning': 'morning',
            'مسائي': 'evening', 'مساء': 'evening', 'evening': 'evening'
        }
        return type_map.get(t.lower(), type_map.get(t, t))

    # Normalize stage and study_type before querying schedules
    normalized_stage = normalize_stage(student_stage)
    normalized_study_type = normalize_study_type(student_study_type)

    # If the normalization changed values, update local student dict for clarity
    student['academic_stage_normalized'] = normalized_stage
    student['study_type_normalized'] = normalized_study_type

    # Use the modified function to get schedules by section, stage, group, and study_type
    schedule_data = get_schedules_by_section_and_stage(student_section, normalized_stage, student_group, normalized_study_type)
    return schedule_data
