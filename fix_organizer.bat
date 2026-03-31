@echo off
echo ========================================
echo Checking and Creating Organizer
echo ========================================
echo.

python manage.py shell << EOF
from user.models import User
from django.contrib.auth.hashers import make_password

# Check if user exists
try:
    user = User.objects.get(email='organizer@event.com')
    print(f'User exists: {user.email}')
    print(f'Is organizer: {user.is_organizer}')
    print(f'Is staff: {user.is_staff}')
    print('Updating password...')
    user.set_password('rapica123')
    user.is_organizer = True
    user.is_staff = True
    user.save()
    print('Password updated!')
except User.DoesNotExist:
    print('User does not exist. Creating...')
    user = User.objects.create_user(
        username='organizer@event.com',
        email='organizer@event.com',
        password='rapica123',
        first_name='Event',
        last_name='Organizer'
    )
    user.is_organizer = True
    user.is_staff = True
    user.save()
    print('Organizer created!')

print('')
print('Login Details:')
print('Email: organizer@event.com')
print('Password: rapica123')
EOF

echo.
echo ========================================
echo Done!
echo ========================================
echo.
echo You can now login at:
echo http://localhost:3000/signin
echo.
pause
