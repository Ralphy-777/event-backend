@echo off
echo ========================================
echo SPDATA Database Initialization
echo ========================================
echo.

echo This script will:
echo 1. Delete existing migrations
echo 2. Create fresh migrations
echo 3. Apply migrations to MySQL database
echo 4. Create a superuser account
echo.
echo WARNING: This will reset your database!
echo.
set /p confirm="Continue? (y/n): "
if /i not "%confirm%"=="y" (
    echo Cancelled.
    pause
    exit /b 0
)
echo.

echo Step 1: Cleaning old migrations...
if exist "user\migrations\0*.py" (
    del /q "user\migrations\0*.py"
    echo Old migrations deleted.
) else (
    echo No old migrations found.
)
echo.

echo Step 2: Creating fresh migrations...
python manage.py makemigrations user
if %errorlevel% neq 0 (
    echo ERROR: Failed to create migrations
    pause
    exit /b 1
)
echo.

echo Step 3: Applying migrations to database...
python manage.py migrate
if %errorlevel% neq 0 (
    echo ERROR: Failed to apply migrations
    echo.
    echo Make sure:
    echo - XAMPP MySQL is running
    echo - Database 'spdata_db' exists
    echo - MySQL credentials in settings.py are correct
    pause
    exit /b 1
)
echo.

echo Step 4: Creating superuser...
echo.
echo Please enter superuser details:
echo (This will be your admin account)
echo.
python manage.py createsuperuser
echo.

echo ========================================
echo Database Initialized Successfully!
echo ========================================
echo.
echo Next steps:
echo 1. Start server: python manage.py runserver
echo 2. Go to http://localhost:8000/admin
echo 3. Login with your superuser credentials
echo 4. Create an organizer account:
echo    - Click Users ^> Add User
echo    - Fill in details
echo    - Check "Is organizer" checkbox
echo    - Save
echo.
pause
