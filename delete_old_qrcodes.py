import os
import glob
from app import create_app

# Create app context
app = create_app()
with app.app_context():
    # Get the QR codes directory
    backend_dir = os.path.dirname(os.path.abspath(__file__))
    qr_folder = os.path.join(backend_dir, 'static', 'qrcodes')
    
    print(f"Looking for QR codes in: {qr_folder}")
    
    if os.path.exists(qr_folder):
        # Find all PNG files (QR codes)
        qr_files = glob.glob(os.path.join(qr_folder, "room_*_qr.png"))
        
        print(f"Found {len(qr_files)} QR code files to delete")
        
        # Delete all QR code files
        deleted_count = 0
        for qr_file in qr_files:
            try:
                os.remove(qr_file)
                print(f"Deleted: {os.path.basename(qr_file)}")
                deleted_count += 1
            except Exception as e:
                print(f"Error deleting {qr_file}: {e}")
        
        print(f"\nDeleted {deleted_count} QR code files")
        
        # Update database to remove QR paths
        supabase = app.supabase
        try:
            # Set all qr_code_path to null
            result = supabase.table("rooms").update({"qr_code_path": None}).neq("id", 0).execute()
            print(f"Updated {len(result.data)} room records to remove QR paths")
        except Exception as e:
            print(f"Error updating database: {e}")
            
        print("\nAll old QR codes have been deleted.")
        print("New QR codes will be generated with the correct URL when needed.")
        
    else:
        print(f"QR codes directory does not exist: {qr_folder}")