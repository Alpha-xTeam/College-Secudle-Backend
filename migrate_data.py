import sqlite3
from supabase import create_client, Client
import os

# --- Supabase Configuration ---
SUPABASE_URL = "https://fhuisvaznaruxoxvvpjz.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImZodWlzdmF6bmFydXhveHZ2cGp6Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NTU1MDYzOTAsImV4cCI6MjA3MTA4MjM5MH0.p0WPY2XxTqWsIt8xSsF4nep39P-Gb5fQBOmT-rP8TCY"
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# --- Local SQLite Database Configuration ---
DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'instance', 'database.db')

def migrate_table(table_name, column_names, supabase_table_name):
    """Migrates data from a local SQLite table to a Supabase table."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute(f"SELECT * FROM {table_name}")
        rows = cursor.fetchall()
        
        data_to_insert = []
        for row in rows:
            row_dict = dict(zip(column_names, row))
            # Convert datetime objects to ISO 8601 strings
            for key, value in row_dict.items():
                if 'created_at' in key or 'updated_at' in key or 'starts_at' in key or 'expires_at' in key:
                    if value:
                        row_dict[key] = value
            data_to_insert.append(row_dict)
            
        if data_to_insert:
            # Supabase client uses the table name to insert data
            response = supabase.table(supabase_table_name).insert(data_to_insert).execute()
            err = getattr(response, 'error', None)
            if err:
                print(f"Error migrating {table_name}: {err}")
            else:
                print(f"Successfully migrated {len(rows)} rows to {supabase_table_name}")
        else:
            print(f"No data to migrate for {table_name}")
            
    except Exception as e:
        print(f"An error occurred during migration of {table_name}: {e}")
    finally:
        if conn:
            conn.close()

if __name__ == "__main__":
    # --- Migrate Departments ---
    migrate_table(
        'departments', 
        ['id', 'name', 'code', 'description', 'is_active', 'created_at', 'updated_at'],
        'departments'
    )
    
    # --- Migrate Users ---
    # Note: Password hashes are migrated as is. Ensure the hashing algorithm is compatible.
    migrate_table(
        'users',
        ['id', 'username', 'email', 'password_hash', 'full_name', 'role', 'department_id', 'is_active', 'created_at', 'updated_at'],
        'users'
    )
    
    # --- Migrate Rooms ---
    migrate_table(
        'rooms',
        ['id', 'name', 'code', 'department_id', 'capacity', 'description', 'qr_code_path', 'is_active', 'created_at', 'updated_at'],
        'rooms'
    )
    
    # --- Migrate Schedules ---
    migrate_table(
        'schedules',
        ['id', 'room_id', 'study_type', 'academic_stage', 'day_of_week', 'start_time', 'end_time', 'subject_name', 'instructor_name', 'notes', 'is_active', 'is_temporary', 'created_at', 'updated_at'],
        'schedules'
    )
    
    # --- Migrate Announcements ---
    migrate_table(
        'announcements',
        ['id', 'department_id', 'title', 'body', 'is_global', 'is_active', 'created_at', 'starts_at', 'expires_at'],
        'announcements'
    )
