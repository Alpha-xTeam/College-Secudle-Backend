@echo off
echo ========================================
echo      اختبار الضغط على النظام
echo ========================================
echo.

REM التحقق من وجود Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ❌ Python غير مثبت على النظام
    pause
    exit /b 1
)

REM التحقق من وجود الملف
if not exist "simple_stress_test.py" (
    echo ❌ ملف الاختبار غير موجود
    pause
    exit /b 1
)

echo 🚀 بدء اختبار الضغط...
echo.

REM تشغيل الاختبار مع معاملات افتراضية
python simple_stress_test.py --url http://localhost:5000 --requests 800

echo.
echo ✅ انتهى الاختبار
echo 📋 راجع النتائج أعلاه لتقييم أداء النظام
echo.
pause