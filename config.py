import os
from datetime import timedelta

class Config:
    # Supabase Configuration
    SUPABASE_URL = os.environ.get("SUPABASE_URL") or "https://fhuisvaznaruxoxvvpjz.supabase.co"
    SUPABASE_KEY = os.environ.get("SUPABASE_KEY") or "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImZodWlzdmF6bmFydXhveHZ2cGp6Iiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc1NTUwNjM5MCwiZXhwIjoyMDcxMDgyMzkwfQ.Q_OzURvFjm0ubM4SP9LhjZPSOkrbh_IGczWbXY8LKcQ"
    
    # JWT Configuration
    JWT_SECRET_KEY = os.environ.get('JWT_SECRET_KEY') or 'your-secret-key-here-change-in-production'
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(hours=24)
    
    # Application Configuration
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-secret-key'
    
    # QR Code Configuration
    QR_CODE_FOLDER = 'static/qrcodes'
    FRONTEND_URL = 'https://www.it-college.zone.id'
    
    # File Upload Configuration
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB max file size