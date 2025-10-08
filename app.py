from flask import Flask, jsonify, redirect, request
from flask_jwt_extended import JWTManager
from config import Config
from supabase import create_client, Client
from routes.auth_routes import auth_bp
from routes.dean_routes import dean_bp
from routes.department_routes import dept_bp
from routes.room_routes import room_bp
from routes.public_routes import public_bp
from routes.admin_routes import admin_bp
from routes.student_routes import student_bp
from routes.doctor_routes import doctor_bp # New import
from routes.owner_routes import owner_bp
import os
from flask_cors import CORS

def create_required_folders():
    """إنشاء المجلدات المطلوبة للتطبيق"""
    # إنشاء مجلد QR codes
    qr_folder = Config.QR_CODE_FOLDER
    if not os.path.exists(qr_folder):
        os.makedirs(qr_folder)
        print(f"Created QR codes folder: {qr_folder}")

def create_app():
    """إنشاء التطبيق وإعداده"""
    app = Flask(__name__)
    app.config.from_object(Config)

    # Enable CORS for API routes (explicit init via flask_cors to cover error responses and preflight)
    CORS(app, resources={r"/api/*": {"origins": "*"}}, supports_credentials=True)

    # Configure file upload limits
    app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size
    
    # Initialize extensions
    jwt = JWTManager(app)
    
    # Initialize Supabase
    supabase_url = app.config["SUPABASE_URL"]
    supabase_key = app.config["SUPABASE_KEY"]
    supabase: Client = create_client(supabase_url, supabase_key)
    app.supabase = supabase
    
    # إنشاء المجلدات المطلوبة
    create_required_folders()
    
    # Register blueprints
    app.register_blueprint(auth_bp, url_prefix='/api/auth')
    app.register_blueprint(dean_bp, url_prefix='/api/dean')
    app.register_blueprint(dept_bp, url_prefix='/api/department')
    app.register_blueprint(room_bp, url_prefix='/api/rooms')
    app.register_blueprint(public_bp, url_prefix='/api/public')
    app.register_blueprint(admin_bp, url_prefix='/api/admin')
    app.register_blueprint(student_bp, url_prefix='/api/students')
    app.register_blueprint(doctor_bp, url_prefix='/api/doctors') # New blueprint registration
    app.register_blueprint(owner_bp, url_prefix='/api/owner')
    
    # Global OPTIONS handler for preflight requests
    @app.before_request
    def handle_preflight():
        if request.method == "OPTIONS":
            response = jsonify()
            response.headers.add("Access-Control-Allow-Origin", "*")
            response.headers.add('Access-Control-Allow-Headers', "Content-Type,Authorization,apikey,Access-Control-Allow-Headers,Origin,Accept,X-Requested-With")
            response.headers.add('Access-Control-Allow-Methods', "GET,PUT,POST,PATCH,DELETE,OPTIONS")
            response.headers.add('Access-Control-Allow-Credentials', 'true')
            return response

    # Add CORS headers to all responses
    @app.after_request
    def add_cors_headers(response):
        if "Access-Control-Allow-Origin" not in response.headers:
            response.headers.add("Access-Control-Allow-Origin", "*")
        if "Access-Control-Allow-Headers" not in response.headers:
            response.headers.add("Access-Control-Allow-Headers", "Content-Type,Authorization,apikey,Access-Control-Allow-Headers,Origin,Accept,X-Requested-With")
        if "Access-Control-Allow-Methods" not in response.headers:
            response.headers.add("Access-Control-Allow-Methods", "GET,PUT,POST,PATCH,DELETE,OPTIONS")
        if "Access-Control-Allow-Credentials" not in response.headers:
            response.headers.add("Access-Control-Allow-Credentials", "true")
        return response
    
    # Root route for testing
    @app.route('/')
    def root():
        return jsonify({
            'message': 'College Schedule System API',
            'version': '1.0',
            'endpoints': {
                'login': '/api/auth/login',
                'rooms': '/api/rooms/',
                'public_room': '/api/public/room/<room_code>',
                'qr_code': '/api/public/room/<room_code>/qr',
                'schedule_view': '/room/<room_code>'
            },
            'status': 'running'
        })
    
    # Error handlers
    @app.errorhandler(404)
    def not_found(error):
        return jsonify({'error': 'Resource not found'}), 404
    
    @app.errorhandler(500)
    def internal_error(error):
        return jsonify({'error': 'Internal server error'}), 500
    
    # JWT error handlers
    @jwt.expired_token_loader
    def expired_token_callback(jwt_header, jwt_payload):
        return jsonify({'error': 'Token has expired'}), 401
    
    @jwt.invalid_token_loader
    def invalid_token_callback(error):
        return jsonify({'error': 'Invalid token'}), 401
    
    @jwt.unauthorized_loader
    def missing_token_callback(error):
        return jsonify({'error': 'Authorization token is required'}), 401
    
    return app

if __name__ == '__main__':
    # إنشاء مجلد QR إذا لم يكن موجوداً
    qr_folder = os.path.join(os.getcwd(), 'static', 'qrcodes')
    if not os.path.exists(qr_folder):
        os.makedirs(qr_folder)
    
    # إخفاء لوجات werkzeug (طلبات HTTP) من الكونسول
    import logging
    log = logging.getLogger('werkzeug')
    log.setLevel(logging.ERROR)
    app = create_app()
    app.run(host='0.0.0.0', debug=True, port=5000)