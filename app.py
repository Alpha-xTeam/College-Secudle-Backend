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

    # Enable CORS for API routes using configured allowed origins
    # Read allowed origins from config (comma separated)
    raw_origins = app.config.get('CORS_ORIGINS', '') or ''
    allowed_origins = [o.strip() for o in raw_origins.split(',') if o.strip()]
    # Initialize flask-cors with the list (avoid wildcard when using credentials)
    CORS(app, resources={r"/api/*": {"origins": allowed_origins or []}}, supports_credentials=True)

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

    # --- Early preflight handler (register BEFORE blueprints) ---
    @app.before_request
    def handle_preflight_early():
        try:
            if request.method == "OPTIONS":
                # Log that we handled an early preflight so we can diagnose 500s
                app.logger.debug("Handling early CORS preflight for %s", request.path)
                response = jsonify()
                origin = request.headers.get('Origin')
                if origin and (('*' in allowed_origins) or origin in allowed_origins):
                    response.headers.add("Access-Control-Allow-Origin", origin if '*' not in allowed_origins else '*')
                else:
                    if allowed_origins:
                        response.headers.add("Access-Control-Allow-Origin", allowed_origins[0])
                response.headers.add('Access-Control-Allow-Headers', "Content-Type,Authorization,apikey,Access-Control-Allow-Headers,Origin,Accept,X-Requested-With")
                response.headers.add('Access-Control-Allow-Methods', "GET,PUT,POST,PATCH,DELETE,OPTIONS")
                response.headers.add('Access-Control-Allow-Credentials', 'true')
                return response
        except Exception as e:
            # If anything goes wrong while handling preflight, log and return a safe preflight response
            app.logger.exception("Exception while handling preflight: %s", e)
            safe = jsonify()
            if allowed_origins:
                safe.headers.add("Access-Control-Allow-Origin", allowed_origins[0])
            safe.headers.add('Access-Control-Allow-Headers', "Content-Type,Authorization,apikey,Access-Control-Allow-Headers,Origin,Accept,X-Requested-With")
            safe.headers.add('Access-Control-Allow-Methods', "GET,PUT,POST,PATCH,DELETE,OPTIONS")
            safe.headers.add('Access-Control-Allow-Credentials', 'true')
            return safe

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
    
    # NOTE: early preflight handler was registered before blueprint registration to avoid
    # running any blueprint-level before_request handlers that might raise during preflight.

    # Add CORS headers to all responses
    @app.after_request
    def add_cors_headers(response):
        origin = request.headers.get('Origin')
        # Prefer echoing the request Origin when allowed (required for credentials)
        if origin and (('*' in allowed_origins) or origin in allowed_origins):
            response.headers['Access-Control-Allow-Origin'] = origin if '*' not in allowed_origins else '*'
        else:
            # Fallback to first configured origin or keep wildcard if configured
            if allowed_origins:
                response.headers.setdefault('Access-Control-Allow-Origin', allowed_origins[0])
            else:
                response.headers.setdefault('Access-Control-Allow-Origin', '*')
        response.headers.setdefault("Access-Control-Allow-Headers", "Content-Type,Authorization,apikey,Access-Control-Allow-Headers,Origin,Accept,X-Requested-With")
        response.headers.setdefault("Access-Control-Allow-Methods", "GET,PUT,POST,PATCH,DELETE,OPTIONS")
        response.headers.setdefault("Access-Control-Allow-Credentials", "true")
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
        resp = jsonify({'error': 'Internal server error'})
        # Make sure CORS headers are present on error responses so browsers can read them
        origin = request.headers.get('Origin')
        if origin and (('*' in allowed_origins) or origin in allowed_origins):
            resp.headers['Access-Control-Allow-Origin'] = origin if '*' not in allowed_origins else '*'
        else:
            if allowed_origins:
                resp.headers.setdefault('Access-Control-Allow-Origin', allowed_origins[0])
            else:
                resp.headers.setdefault('Access-Control-Allow-Origin', '*')
        resp.headers.setdefault('Access-Control-Allow-Headers', "Content-Type,Authorization,apikey,Access-Control-Allow-Headers,Origin,Accept,X-Requested-With")
        resp.headers.setdefault('Access-Control-Allow-Methods', "GET,PUT,POST,PATCH,DELETE,OPTIONS")
        resp.headers.setdefault('Access-Control-Allow-Credentials', "true")
        return resp, 500

    # Catch-all exception handler: ensure CORS headers and log exception
    @app.errorhandler(Exception)
    def handle_exception(e):
        app.logger.exception('Unhandled exception during request: %s', e)
        resp = jsonify({'error': 'Internal server error'})
        origin = request.headers.get('Origin')
        if origin and (('*' in allowed_origins) or origin in allowed_origins):
            resp.headers['Access-Control-Allow-Origin'] = origin if '*' not in allowed_origins else '*'
        else:
            if allowed_origins:
                resp.headers.setdefault('Access-Control-Allow-Origin', allowed_origins[0])
            else:
                resp.headers.setdefault('Access-Control-Allow-Origin', '*')
        resp.headers.setdefault('Access-Control-Allow-Headers', "Content-Type,Authorization,apikey,Access-Control-Allow-Headers,Origin,Accept,X-Requested-With")
        resp.headers.setdefault('Access-Control-Allow-Methods', "GET,PUT,POST,PATCH,DELETE,OPTIONS")
        resp.headers.setdefault('Access-Control-Allow-Credentials', "true")
        return resp, 500
    
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