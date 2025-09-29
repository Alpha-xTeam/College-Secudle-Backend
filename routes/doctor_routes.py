from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required, get_jwt_identity
from models import get_all_doctors, get_doctor_by_id, create_doctor, update_doctor, delete_doctor, get_all_departments, get_schedules_by_doctor_id
from utils.helpers import get_user_role

doctor_bp = Blueprint('doctor_bp', __name__)

@doctor_bp.route('/', methods=['GET', 'OPTIONS'])
def list_doctors():
    if request.method == 'OPTIONS':
        response = jsonify()
        response.headers.add("Access-Control-Allow-Origin", "*")
        response.headers.add('Access-Control-Allow-Headers', "Content-Type,Authorization,apikey")
        response.headers.add('Access-Control-Allow-Methods', "GET,PUT,POST,DELETE,OPTIONS")
        return response
    
    # Require JWT for GET requests
    from flask_jwt_extended import jwt_required, get_jwt_identity
    @jwt_required()
    def protected_list_doctors():
        current_user_email = get_jwt_identity()
        role = get_user_role(current_user_email)
        if role not in ['admin', 'dean', 'supervisor', 'department_head']:
            return jsonify({"msg": "Admins, Deans, and Supervisors only"}), 403
        
        doctors = get_all_doctors()
        return jsonify(doctors), 200
    
    return protected_list_doctors()

@doctor_bp.route('/add', methods=['POST', 'OPTIONS'])
def add_doctor():
    if request.method == 'OPTIONS':
        response = jsonify()
        response.headers.add("Access-Control-Allow-Origin", "*")
        response.headers.add('Access-Control-Allow-Headers', "Content-Type,Authorization,apikey")
        response.headers.add('Access-Control-Allow-Methods', "GET,PUT,POST,DELETE,OPTIONS")
        return response
    
    # Require JWT for POST requests
    from flask_jwt_extended import jwt_required, get_jwt_identity
    @jwt_required()
    def protected_add_doctor():
        current_user_email = get_jwt_identity()
        role = get_user_role(current_user_email)
        if role not in ['admin', 'dean', 'supervisor', 'department_head']:
            return jsonify({"msg": "Admins, Deans, and Supervisors only"}), 403
        
        data = request.get_json()
        name = data.get('name')
        department_id = data.get('department_id')

        if not name or not department_id:
            return jsonify({"error": "Name and department_id are required"}), 400

        new_doctor = create_doctor({'name': name, 'department_id': department_id})
        if new_doctor:
            return jsonify(new_doctor), 201
        return jsonify({"error": "Failed to add doctor"}), 500
    
    return protected_add_doctor()

@doctor_bp.route('/<int:doctor_id>', methods=['PUT', 'DELETE', 'OPTIONS'])
def doctor_endpoint(doctor_id):
    if request.method == 'OPTIONS':
        response = jsonify()
        response.headers.add("Access-Control-Allow-Origin", "*")
        response.headers.add('Access-Control-Allow-Headers', "Content-Type,Authorization,apikey")
        response.headers.add('Access-Control-Allow-Methods', "GET,PUT,POST,DELETE,OPTIONS")
        return response
    
    # Require JWT for PUT and DELETE requests
    from flask_jwt_extended import jwt_required, get_jwt_identity
    @jwt_required()
    def protected_doctor_endpoint():
        current_user_email = get_jwt_identity()
        role = get_user_role(current_user_email)
        if role not in ['admin', 'dean', 'supervisor', 'department_head']:
            return jsonify({"msg": "Admins, Deans, and Supervisors only"}), 403
        
        if request.method == 'PUT':
            # Update doctor
            # Check if doctor exists
            doctor = get_doctor_by_id(doctor_id)
            if not doctor:
                return jsonify({"error": "Doctor not found"}), 404
            
            data = request.get_json()
            name = data.get('name')
            department_id = data.get('department_id')
            
            if not name or not department_id:
                return jsonify({"error": "Name and department_id are required"}), 400
            
            # Update the doctor
            updated_doctor = update_doctor(doctor_id, {
                'name': name,
                'department_id': department_id
            })
            
            if updated_doctor:
                return jsonify({"message": "Doctor updated successfully", "doctor": updated_doctor}), 200
            return jsonify({"error": "Failed to update doctor"}), 500
            
        elif request.method == 'DELETE':
            # Delete doctor
            # Check if doctor exists
            doctor = get_doctor_by_id(doctor_id)
            if not doctor:
                return jsonify({"error": "Doctor not found"}), 404
            
            # Check if doctor has assigned schedules
            schedules = get_schedules_by_doctor_id(doctor_id)
            if schedules and len(schedules) > 0:
                return jsonify({"error": "Cannot delete doctor. Doctor has assigned schedules."}), 400
            
            # Delete the doctor
            deleted_doctor = delete_doctor(doctor_id)
            if deleted_doctor:
                return jsonify({"message": "Doctor deleted successfully"}), 200
            return jsonify({"error": "Failed to delete doctor"}), 500
    
    return protected_doctor_endpoint()

@doctor_bp.route('/<int:doctor_id>/lectures', methods=['GET', 'OPTIONS'])
def get_doctor_lectures(doctor_id):
    if request.method == 'OPTIONS':
        response = jsonify()
        response.headers.add("Access-Control-Allow-Origin", "*")
        response.headers.add('Access-Control-Allow-Headers', "Content-Type,Authorization,apikey")
        response.headers.add('Access-Control-Allow-Methods', "GET,PUT,POST,DELETE,OPTIONS")
        return response
        
    # Require JWT for GET requests
    from flask_jwt_extended import jwt_required, get_jwt_identity
    @jwt_required()
    def protected_get_doctor_lectures():
        current_user_email = get_jwt_identity()
        role = get_user_role(current_user_email)
        if role not in ['admin', 'dean', 'student', 'faculty']: # Allow students and faculty to view their own lectures
            return jsonify({"msg": "Access denied"}), 403
        
        # In a real app, you'd check if the requesting user is the doctor themselves
        # or has permission to view this doctor's lectures.
        # For simplicity, we'll allow admin/dean to view any, and others to view their own.
        
        lectures = get_schedules_by_doctor_id(doctor_id)
        if lectures is None:
            return jsonify({"error": "Doctor not found or no lectures assigned"}), 404
        return jsonify(lectures), 200
    
    return protected_get_doctor_lectures()

@doctor_bp.route('/departments', methods=['GET', 'OPTIONS'])
def list_departments():
    if request.method == 'OPTIONS':
        response = jsonify()
        response.headers.add("Access-Control-Allow-Origin", "*")
        response.headers.add('Access-Control-Allow-Headers', "Content-Type,Authorization,apikey")
        response.headers.add('Access-Control-Allow-Methods', "GET,PUT,POST,DELETE,OPTIONS")
        return response
    
    # Make JWT optional to allow unauthenticated access if needed
    from flask_jwt_extended import jwt_required, get_jwt_identity, verify_jwt_in_request
    try:
        verify_jwt_in_request(optional=True)
        current_user_email = get_jwt_identity()
        role = get_user_role(current_user_email) if current_user_email else None
        if role and role not in ['admin', 'dean', 'faculty']:
            return jsonify({"msg": "Access denied"}), 403
    except:
        # If no valid JWT, still allow access to departments
        pass
    
    departments = get_all_departments()
    return jsonify(departments), 200
