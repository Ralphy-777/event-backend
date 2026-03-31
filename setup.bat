@echo off
echo ========================================
echo SPDATA Backend Setup Script
echo ========================================
echo.

echo Step 1: Installing Python dependencies...
pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo ERROR: Failed to install dependencies
    pause
    exit /b 1
)
echo.

echo Step 2: Creating database migrations...
python manage.py makemigrations
if %errorlevel% neq 0 (
    echo ERROR: Failed to create migrations
    pause
    exit /b 1
)
echo.

echo Step 3: Applying database migrations...
python manage.py migrate
if %errorlevel% neq 0 (
    echo ERROR: Failed to apply migrations
    pause
    exit /b 1
)
echo.

echo Step 4: Creating superuser for admin panel...
echo Please enter admin credentials:
python manage.py createsuperuser
echo.

echo ========================================
echo Setup Complete!
echo ========================================
echo.
echo You can now:
echo 1. Start the Django server: python manage.py runserver
echo 2. Access admin panel at: http://localhost:8000/admin
echo 3. Create organizer accounts from admin panel
echo.
pause
