"""
Script to synchronize instructor_name with doctor_id for existing schedules.
This fixes the issue where schedules have updated doctor_id but still show old instructor_name.
"""

from models import get_supabase

def sync_instructor_names():
    """Synchronize instructor_name field with doctor_id for all schedules"""
    supabase = get_supabase()
    
    print("Starting instructor_name synchronization...")
    
    # Get all active schedules with doctor_id
    schedules_res = supabase.table('schedules').select('id, doctor_id, instructor_name').eq('is_active', True).is_('doctor_id', 'not.null').execute()
    
    if not schedules_res.data:
        print("No schedules with doctor_id found.")
        return
    
    updated_count = 0
    error_count = 0
    
    for schedule in schedules_res.data:
        schedule_id = schedule['id']
        doctor_id = schedule['doctor_id']
        current_instructor_name = schedule['instructor_name']
        
        try:
            # Get the actual doctor name from the doctors table
            doctor_res = supabase.table('doctors').select('name').eq('id', doctor_id).execute()
            
            if doctor_res.data:
                actual_doctor_name = doctor_res.data[0]['name']
                
                # Check if instructor_name needs updating
                if current_instructor_name != actual_doctor_name:
                    # Update the instructor_name
                    update_res = supabase.table('schedules').update({
                        'instructor_name': actual_doctor_name
                    }).eq('id', schedule_id).execute()
                    
                    if update_res.data:
                        print(f"Schedule {schedule_id}: Updated instructor_name from '{current_instructor_name}' to '{actual_doctor_name}'")
                        updated_count += 1
                    else:
                        print(f"Schedule {schedule_id}: Failed to update")
                        error_count += 1
                else:
                    print(f"Schedule {schedule_id}: Already synchronized ('{current_instructor_name}')")
            else:
                print(f"Schedule {schedule_id}: Doctor {doctor_id} not found")
                error_count += 1
                
        except Exception as e:
            print(f"Schedule {schedule_id}: Error - {str(e)}")
            error_count += 1
    
    print(f"\nSynchronization complete:")
    print(f"- Updated: {updated_count} schedules")
    print(f"- Errors: {error_count} schedules")
    print(f"- Total processed: {len(schedules_res.data)} schedules")

def sync_multiple_doctors_instructor_names():
    """Synchronize instructor_name for schedules with multiple doctors"""
    supabase = get_supabase()
    
    print("\nStarting multiple doctors instructor_name synchronization...")
    
    # Get all schedule_doctors entries with primary doctors
    schedule_doctors_res = supabase.table('schedule_doctors').select('schedule_id, doctor_id, is_primary, doctors!schedule_doctors_doctor_id_fkey(name)').eq('is_primary', True).execute()
    
    if not schedule_doctors_res.data:
        print("No primary doctors found in schedule_doctors table.")
        return
    
    updated_count = 0
    error_count = 0
    
    for schedule_doctor in schedule_doctors_res.data:
        schedule_id = schedule_doctor['schedule_id']
        doctor_name = schedule_doctor['doctors']['name'] if schedule_doctor['doctors'] else None
        
        if not doctor_name:
            print(f"Schedule {schedule_id}: No doctor name found")
            error_count += 1
            continue
        
        try:
            # Get current schedule
            schedule_res = supabase.table('schedules').select('instructor_name').eq('id', schedule_id).execute()
            
            if schedule_res.data:
                current_instructor_name = schedule_res.data[0]['instructor_name']
                
                # Update instructor_name to primary doctor's name
                if current_instructor_name != doctor_name:
                    update_res = supabase.table('schedules').update({
                        'instructor_name': doctor_name
                    }).eq('id', schedule_id).execute()
                    
                    if update_res.data:
                        print(f"Schedule {schedule_id}: Updated instructor_name from '{current_instructor_name}' to '{doctor_name}' (primary doctor)")
                        updated_count += 1
                    else:
                        print(f"Schedule {schedule_id}: Failed to update")
                        error_count += 1
                else:
                    print(f"Schedule {schedule_id}: Already synchronized with primary doctor ('{doctor_name}')")
            else:
                print(f"Schedule {schedule_id}: Schedule not found")
                error_count += 1
                
        except Exception as e:
            print(f"Schedule {schedule_id}: Error - {str(e)}")
            error_count += 1
    
    print(f"\nMultiple doctors synchronization complete:")
    print(f"- Updated: {updated_count} schedules")
    print(f"- Errors: {error_count} schedules")
    print(f"- Total processed: {len(schedule_doctors_res.data)} schedules")

if __name__ == "__main__":
    try:
        # Sync single doctor schedules
        sync_instructor_names()
        
        # Sync multiple doctor schedules
        sync_multiple_doctors_instructor_names()
        
        print("\n✅ Synchronization completed successfully!")
        
    except Exception as e:
        print(f"❌ Error during synchronization: {str(e)}")
        import traceback
        traceback.print_exc()