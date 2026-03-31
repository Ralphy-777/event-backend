import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')
django.setup()

from user.models import User

# Delete existing organizer if exists
User.objects.filter(email='organizer@event.com').delete()

# Create organizer
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

print("=" * 50)
print("ORGANIZER CREATED SUCCESSFULLY!")
print("=" * 50)
print(f"Email: {user.email}")
print(f"Password: rapica123")
print(f"Is Organizer: {user.is_organizer}")
print(f"Is Staff: {user.is_staff}")
print("=" * 50)
print("\nLogin at: http://localhost:3000/signin")
print("Select 'Organizer' tab")
print("=" * 50)
