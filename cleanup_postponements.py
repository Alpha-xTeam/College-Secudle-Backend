from datetime import datetime, date
import os
from supabase import create_client, Client

# Initialize Supabase client
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    print("Error: SUPABASE_URL or SUPABASE_KEY environment variables are not set.")
    exit(1)

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def cleanup_postponements():
    print(f"[{datetime.now()}] Starting postponement cleanup...")
    
    today = date.today()

    try:
        # 1. Find original schedules whose postponement date has passed
        # These are schedules where is_postponed is True, and postponed_date is in the past
        # We also need their moved_to_schedule_id to delete the temporary entry
        past_postponements_res = (
            supabase.table("schedules")
            .select("id, moved_to_schedule_id, postponed_date")
            .eq("is_postponed", True)
            .lt("postponed_date", today.isoformat()) # postponed_date is before today
            .execute()
        )
        
        schedules_to_revert = past_postponements_res.data
        
        if not schedules_to_revert:
            print("No past postponed schedules found to revert.")
            return

        print(f"Found {len(schedules_to_revert)} schedules to revert.")

        for original_schedule in schedules_to_revert:
            original_schedule_id = original_schedule["id"]
            moved_to_schedule_id = original_schedule.get("moved_to_schedule_id")

            # 2. Revert the original schedule
            print(f"Reverting original schedule ID: {original_schedule_id}")
            revert_data = {
                "is_postponed": False,
                "is_moved_out": False,
                "postponed_date": None,
                "postponed_to_room_id": None,
                "postponed_reason": None,
                "postponed_start_time": None,
                "postponed_end_time": None,
                "original_booking_date": None, # Clear this as well
                "moved_to_schedule_id": None # Clear the link
            }
            supabase.table("schedules").update(revert_data).eq("id", original_schedule_id).execute()
            print(f"Original schedule {original_schedule_id} reverted.")

            # 3. Delete the corresponding temporary move-in schedule
            if moved_to_schedule_id:
                print(f"Deleting temporary schedule ID: {moved_to_schedule_id}")
                supabase.table("schedules").delete().eq("id", moved_to_schedule_id).execute()
                print(f"Temporary schedule {moved_to_schedule_id} deleted.")
            
            # Also handle cases where original_schedule_id is linked to a temporary_move_in
            # This covers scenarios where the temporary_move_in might not have been directly linked via moved_to_schedule_id
            # (e.g., if the original schedule was deleted or not properly linked)
            supabase.table("schedules").delete().eq("is_temporary_move_in", True).eq("original_schedule_id", original_schedule_id).execute()
            print(f"Cleaned up any remaining temporary move-in schedules linked to {original_schedule_id}.")

        print(f"[{datetime.now()}] Postponement cleanup completed successfully.")

    except Exception as e:
        print(f"[{datetime.now()}] Error during postponement cleanup: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    cleanup_postponements()
