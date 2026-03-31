@echo off
echo ========================================
echo Create Django Superuser
echo ========================================
echo.
echo This will create an admin account for Django admin panel.
echo.
echo IMPORTANT: Use your email as username
echo.
pause

python manage.py createsuperuser

echo.
echo ========================================
echo Superuser created!
echo ========================================
echo.
echo You can now login at: http://localhost:8000/admin
echo.
pause
