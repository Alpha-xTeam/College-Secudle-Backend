from flask import Blueprint, request, jsonify, current_app
import pandas as pd
import uuid
import random
from datetime import datetime
from models import create_student, update_student, get_student_by_id, get_students_by_section_and_stage, get_schedules_by_section_and_stage, get_all_student_ids, delete_student, search_students, get_all_departments, get_student_full_schedule
from models import get_supabase # Assuming get_supabase is needed for direct schedule queries
from flask_jwt_extended import jwt_required, get_jwt_identity
from flask_cors import cross_origin
from utils.helpers import get_current_user, department_access_required

# Helper function to generate a unique 4-digit student ID
def generate_unique_4_digit_id():
    supabase = get_supabase()
    while True:
        # Generate a random 4-digit number (0000-9999)
        new_id = str(random.randint(0, 9999)).zfill(4)
        # Check if the ID already exists in the database
        response = supabase.table('students').select('student_id').eq('student_id', new_id).execute()
        if not response.data:
            return new_id

def get_department_id_by_name(department_name):
    departments = get_all_departments()
    for dept in departments:
        if dept.get('name') == department_name or dept.get('code') == department_name:
            return dept.get('id')
    return None

def convert_stage_to_text(stage):
    """Convert numeric stage to text format"""
    stage_map = {
        '1': 'first',
        '2': 'second', 
        '3': 'third',
        '4': 'fourth'
    }
    return stage_map.get(str(stage).lower(), str(stage).lower())

def convert_study_type_to_english(study_type):
    """Convert Arabic study type to English"""
    type_map = {
        'صباحي': 'morning',
        'مسائي': 'evening'
    }
    return type_map.get(study_type.lower(), study_type.lower())

def get_academic_year():
    """Get current academic year based on date (September 17th is start of academic year)"""
    now = datetime.now()
    current_year = now.year
    current_month = now.month
    current_day = now.day
    
    # Academic year starts on September 17th
    academic_year_start_month = 9
    academic_year_start_day = 17
    
    if (current_month > academic_year_start_month) or \
       (current_month == academic_year_start_month and current_day >= academic_year_start_day):
        # After September 17th, academic year is current_year - (current_year + 1)
        academic_year = f"{current_year}_{current_year + 1}"
    else:
        # Before September 17th, academic year is (current_year - 1) - current_year
        academic_year = f"{current_year - 1}_{current_year}"
    
    return academic_year

student_bp = Blueprint('student_bp', __name__)

@student_bp.route('/upload_students_excel', methods=['POST'])
@jwt_required()
@cross_origin()
def upload_students_excel():
    current_user = get_current_user()
    if not current_user:
        return jsonify({'error': 'User not authenticated'}), 401
    
    # Get department_id from current user (assuming department_head role)
    user_department_id = current_user.get('department_id')
    if not user_department_id:
        return jsonify({'error': 'User department not found'}), 400

    if 'file' not in request.files:
        return jsonify({'error': 'No file part in the request'}), 400
    file = request.files['file']
    stage_from_form = request.form.get('stage')
    study_type_from_form = request.form.get('study_type')

    if not stage_from_form:
        return jsonify({'error': 'Stage not provided in the form data'}), 400
    if not study_type_from_form:
        return jsonify({'error': 'Study type not provided in the form data'}), 400

    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400
    if file and file.filename.endswith(('.xlsx', '.xls')):
        try:
            # Get all existing student IDs before processing the new file
            existing_student_ids = set(get_all_student_ids())
            uploaded_student_ids = set()

            df = pd.read_excel(file)
            students_data = []
            for index, row in df.iterrows():
                student_name = row.get('name') or row.get('Name')
                student_section = row.get('section') or row.get('Section')
                student_group = row.get('group') or row.get('Group')
                student_stage = convert_stage_to_text(stage_from_form)  # Convert to text format
                student_study_type = convert_study_type_to_english(row.get('study_type') or row.get('Study Type') or study_type_from_form)

                # Optional student_id from Excel for updates
                excel_student_id = row.get('student_id') or row.get('Student ID')

                if not all([student_name, student_section, student_group]):
                    return jsonify({'error': f'Missing data in row {index + 2}: name, section, or group'}), 400

                student_data = {
                    'name': student_name,
                    'section': student_section,
                    'group': student_group,
                    'academic_stage': student_stage,
                    'department_id': user_department_id,  # Use department from current user
                    'department_head_id': current_user.get('id')  # Record which department head uploaded this student
                }

                if student_study_type:
                    student_data['study_type'] = student_study_type

                if excel_student_id:
                    # Attempt to update existing student
                    existing_student = get_student_by_id(str(excel_student_id))
                    if existing_student:
                        # Ensure department_head_id is updated to current uploader as well
                        student_data['department_head_id'] = current_user.get('id')
                        update_student(str(excel_student_id), student_data)
                        students_data.append({'student_id': str(excel_student_id), **student_data})
                        uploaded_student_ids.add(str(excel_student_id))
                    else:
                        return jsonify({'error': f'Student with ID {excel_student_id} not found for update in row {index + 2}'}), 404
                else:
                    # Create new student with generated ID
                    # WARNING: 4-digit IDs have limited uniqueness (0000-9999). Collisions are possible in large datasets.
                    new_student_id = generate_unique_4_digit_id()
                    student_data['student_id'] = new_student_id
                    # Ensure department_head_id is set for new students
                    student_data['department_head_id'] = current_user.get('id')
                    create_student(student_data)
                    students_data.append(student_data)
                    uploaded_student_ids.add(new_student_id)
            
            # Delete students not present in the uploaded Excel file
            for student_id_to_delete in existing_student_ids - uploaded_student_ids:
                delete_student(student_id_to_delete)

            return jsonify({'message': 'Students data uploaded successfully', 'students': students_data}), 200
        except Exception as e:
            return jsonify({'error': str(e)}), 500
    return jsonify({'error': 'Invalid file type, please upload an Excel file'}), 400

@student_bp.route('/get_student_schedule/<string:student_id>', methods=['GET'])
def get_student_schedule(student_id):
    student = get_student_by_id(student_id)
    if not student:
        return jsonify({'error': 'Student not found'}), 404

    student_section = student.get('section')
    student_stage = student.get('academic_stage')
    student_group = student.get('group')
    student_study_type = student.get('study_type')

    if not student_section or not student_stage or not student_group or not student_study_type:
        return jsonify({'error': 'Student section, stage, group, or study type information missing'}), 500

    # Use the new function to get schedules by section, stage, group, and study_type
    schedule_data = get_schedules_by_section_and_stage(student_section, student_stage, student_group, student_study_type)
    
    # Add multiple doctors processing
    if schedule_data:
        from models import get_schedule_doctors
        for schedule in schedule_data:
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
    
    if schedule_data:
        return jsonify({'student_schedule': schedule_data}), 200
    else:
        return jsonify({'message': 'No schedule found for this student based on section and stage'}), 404

@student_bp.route('/get_student_full_schedule/<string:student_id>', methods=['GET'])
def get_student_full_schedule_route(student_id):
    schedule_data = get_student_full_schedule(student_id)
    
    # Add multiple doctors processing
    if schedule_data:
        from models import get_schedule_doctors
        for schedule in schedule_data:
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
    
    if schedule_data:
        return jsonify({'student_schedule': schedule_data}), 200
    else:
        return jsonify({'message': 'No schedule found for this student or student not found'}), 404

@student_bp.route('/get_student_by_id/<string:student_id>', methods=['GET'])
def get_student_by_id_route(student_id):
    student = get_student_by_id(student_id)
    if student:
        return jsonify(student), 200
    else:
        return jsonify({'error': 'Student not found'}), 404

@student_bp.route('/search_students', methods=['GET'])
@department_access_required
def search_students_route(user):
    """Search students. Department-heads and supervisors will see only students from their department."""
    query = request.args.get('query')
    if not query:
        return jsonify({'error': 'Query parameter is missing'}), 400

    # Determine department filter based on user role
    dept_filter = None
    if user.get('role') in ['department_head', 'supervisor']:
        dept_filter = user.get('department_id')

    students = search_students(query, department_id=dept_filter)
    if students:
        return jsonify({'students': students}), 200
    else:
        return jsonify({'students': [] , 'message': 'No students found matching the query'}), 200

@student_bp.route('/all', methods=['GET'])
def get_all_students():
    supabase = get_supabase()
    response = supabase.table('students').select('*').execute()
    if response.data:
        return jsonify({'students': response.data}), 200
    else:
        return jsonify({'message': 'No students found'}), 404

@student_bp.route('/export_students', methods=['GET'])
@jwt_required()
@cross_origin()
def export_students():
    current_user = get_current_user()
    if not current_user:
        return jsonify({'error': 'User not authenticated'}), 401
    
    # Get department_id from current user (assuming department_head role)
    user_department_id = current_user.get('department_id')
    
    if not user_department_id:
        return jsonify({'error': 'User department not found'}), 400

    # Get filter parameters
    stage_filter = request.args.get('stage')
    study_type_filter = request.args.get('study_type')
    
    supabase = get_supabase()
    
    # Build query with filters
    query = supabase.table('students').select('*').eq('department_id', user_department_id)
    
    if stage_filter:
        stage_text = convert_stage_to_text(stage_filter)  # Convert to text format
        query = query.eq('academic_stage', stage_text)
    
    if study_type_filter:
        study_type_english = convert_study_type_to_english(study_type_filter)
        query = query.eq('study_type', study_type_english)
    
    response = query.execute()
    
    if response.data:
        # Get department name for display
        departments = get_all_departments()
        dept_name_map = {dept['id']: dept['name'] for dept in departments}
        
        # Add department name to each student
        for student in response.data:
            student['department_name'] = dept_name_map.get(student.get('department_id'), 'غير محدد')
        
        return jsonify({'students': response.data}), 200
    else:
        return jsonify({'message': 'No students found'}), 404
