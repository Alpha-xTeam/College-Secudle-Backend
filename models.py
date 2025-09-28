from supabase import Client
from flask import current_app
import bcrypt
import hashlib

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
    # Filter schedules based on lecture type and student attributes
    # For theoretical lectures: match section_number with student section
    # For practical lectures: match group_letter with student group
    response = (
        supabase.table('schedules').select('*, rooms!schedules_room_id_fkey(name, code), doctors!fk_doctor(name)')
        .eq('academic_stage', stage)
        .eq('study_type', study_type)
        .eq('is_active', True)
        .or_(
            f'and(lecture_type.eq.نظري,section_number.eq.{section})',
            f'and(lecture_type.eq.عملي,group_letter.eq.{group})'
        )
        .execute()
    )
    return response.data

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

def create_doctor(data: dict):
    supabase = get_supabase()
    response = supabase.table('doctors').insert(data).execute()
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

def search_students(query: str):
    supabase = get_supabase()
    # Search by student_id (exact match) or name (case-insensitive partial match)
    response = (
        supabase.table('students').select('*')
        .or_(f'student_id.eq.{query},name.ilike.%{query}%')
        .execute()
    )
    return response.data

def get_student_full_schedule(student_id: str):
    student = get_student_by_id(student_id)
    if not student:
        return None

    student_section = student.get('section')
    student_stage = student.get('academic_stage')
    student_group = student.get('group')
    student_study_type = student.get('study_type')

    if not student_section or not student_stage or not student_group or not student_study_type:
        return None # Or raise an error, depending on desired behavior

    # Use the modified function to get schedules by section, stage, group, and study_type
    schedule_data = get_schedules_by_section_and_stage(student_section, student_stage, student_group, student_study_type)
    return schedule_data
