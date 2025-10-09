from flask import Blueprint, request, current_app
from flask_jwt_extended import jwt_required, get_jwt_identity
from models import get_user_by_username
from utils.helpers import format_response
import os
import tempfile
import pandas as pd
import uuid

admin_bp = Blueprint("admin", __name__)

@admin_bp.route("/students/upload", methods=["POST"])
@jwt_required()
def upload_students_excel():
    """Uploads an Excel file containing student data and populates the students table."""
    try:
        supabase = current_app.supabase
        username = get_jwt_identity()
        user = get_user_by_username(username)

        if not user or user["role"] not in ["dean", "owner"]:
            return format_response(
                message="ليس لديك صلاحية لهذا الإجراء",
                success=False,
                status_code=403,
            )

        if "file" not in request.files:
            return format_response(
                message="لم يتم إرسال ملف",
                success=False,
                status_code=400,
            )

        file = request.files["file"]
        if file.filename == "":
            return format_response(
                message="الملف فارغ",
                success=False,
                status_code=400,
            )

        if not file.filename.endswith((".xlsx", ".xls")):
            return format_response(
                message="صيغة الملف غير مدعومة. يرجى تحميل ملف Excel بصيغة .xlsx أو .xls",
                success=False,
                status_code=400,
            )

        temp_dir = tempfile.mkdtemp()
        temp_file_path = os.path.join(temp_dir, file.filename)
        file.save(temp_file_path)

        try:
            df = pd.read_excel(temp_file_path)
        except Exception as e:
            return format_response(
                message=f"خطأ في قراءة ملف Excel: {str(e)}",
                success=False,
                status_code=400,
            )
        finally:
            os.remove(temp_file_path)
            os.rmdir(temp_dir)

        required_columns = ["name", "section", "academic_stage", "study_type"]
        missing_columns = [col for col in required_columns if col not in df.columns]
        if missing_columns:
            return format_response(
                message=f"الملف مفقود به الأعمدة التالية: {', '.join(missing_columns)}",
                success=False,
                status_code=400,
            )

        created_students_count = 0
        errors = []

        for index, row in df.iterrows():
            try:
                student_name = str(row["name"]).strip()
                student_section = str(row["section"]).strip()
                academic_stage = str(row["academic_stage"]).strip()
                study_type = str(row["study_type"]).strip()

                if not student_name or not student_section or not academic_stage or not study_type:
                    errors.append(f"الصف {index + 2}: بيانات الطالب غير مكتملة (الاسم، الشعبة، المرحلة، نوع الدراسة)")
                    continue
                
                # Validate academic_stage against allowed values
                allowed_stages = ["first", "second", "third", "fourth"]
                if academic_stage.lower() not in allowed_stages:
                    errors.append(f"الصف {index + 2}: المرحلة الأكاديمية غير صالحة '{academic_stage}'. يجب أن تكون إحدى: {', '.join(allowed_stages)}")
                    continue

                # Validate study_type against allowed values
                allowed_study_types = ["morning", "evening"]
                if study_type.lower() not in allowed_study_types:
                    errors.append(f"الصف {index + 2}: نوع الدراسة غير صالح '{study_type}'. يجب أن يكون إحدى: {', '.join(allowed_study_types)}")
                    continue

                # Generate unique student_id
                unique_student_id = str(uuid.uuid4())

                student_data = {
                    "student_id": unique_student_id,
                    "name": student_name,
                    "section": student_section,
                    "academic_stage": academic_stage.lower(),
                    "study_type": study_type.lower(),
                }

                supabase.table("students").insert(student_data).execute()
                created_students_count += 1

            except Exception as e:
                errors.append(f"الصف {index + 2}: خطأ في معالجة بيانات الطالب - {str(e)}")
                continue

        return format_response(
            data={
                "created_students_count": created_students_count,
                "errors": errors,
                "error_count": len(errors),
            },
            message="تم تحميل بيانات الطلاب بنجاح مع بعض الأخطاء" if errors else "تم تحميل بيانات الطلاب بنجاح",
            status_code=200 if not errors else 207, # 207 Multi-Status if there are errors
        )

    except Exception as e:
        import traceback
        traceback.print_exc()
        return format_response(
            message=f"حدث خطأ في الخادم: {str(e)}", success=False, status_code=500
        )
