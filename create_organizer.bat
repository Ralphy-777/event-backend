@echo off
echo ========================================
echo Creating Organizer Account
echo ========================================
echo.
echo Email: organizer@event.com
echo Password: rapica123
echo.

python manage.py shell -c "from user.models import User; User.objects.filter(email='organizer@event.com').delete(); user = User.objects.create_user(username='organizer@event.com', email='organizer@event.com', password='rapica123', first_name='Event', last_name='Organizer', is_organizer=True, is_staff=True); print('Organizer created successfully!')"

echo.
echo ========================================
echo Organizer Account Created!
echo ========================================
echo.
echo Login Details:
echo Email: organizer@event.com
echo Password: rapica123
echo.
echo Access:
echo - Web Dashboard: http://localhost:3000/signin (select Organizer tab)
echo - Admin Panel: http://localhost:8000/organizer-admin
echo.
pause
