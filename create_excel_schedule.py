import openpyxl

def create_excel_file(filename="test_upload_schedule.xlsx"):
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Schedule"

    # Add headers
    headers = ["room_code", "study_type", "academic_stage", "day_of_week", "start_time", "end_time", "subject_name", "instructor_name", "section", "group"]
    sheet.append(headers)

    # Add sample data with valid room codes, study types, academic stages, sections, and groups
    data = [
        ["CS-A", "morning", "first", "Monday", "08:00", "09:00", "Calculus I", "Dr. Smith", "1", "A"],
        ["CS-A", "morning", "first", "Monday", "09:00", "10:00", "Physics I", "Dr. Jones", "1", "A"],
        ["CS-B", "evening", "second", "Tuesday", "10:00", "11:00", "Chemistry", "Dr. Davis", "2", "B"],
        ["CS-B", "evening", "second", "Tuesday", "11:00", "12:00", "Biology", "Dr. Brown", "2", "B"],
        ["CS-C", "morning", "third", "Wednesday", "13:00", "14:00", "History", "Dr. White", "1", "A"],
        ["CS-C", "morning", "third", "Wednesday", "14:00", "15:00", "Literature", "Dr. Green", "1", "A"],
        ["CS-A", "morning", "first", "Thursday", "08:00", "09:00", "Mathematics", "Dr. Ahmed", None, None],  # Example with null section/group for common classes
    ]

    for row_data in data:
        sheet.append(row_data)

    workbook.save(filename)
    print(f"Excel file '{filename}' created successfully.")

if __name__ == "__main__":
    create_excel_file("C:\\Users\\Admin\\Desktop\\My Projects\\college-schedule-system\\backend\\test_upload_schedule.xlsx")
