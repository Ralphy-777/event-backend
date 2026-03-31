import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')
django.setup()

from user.models import EventType

# Create default event types
default_events = [
    {
        'event_type': 'Wedding',
        'price': 5000,
        'max_capacity': 50,
        'people_per_table': 5,
        'description': 'Perfect for wedding celebrations',
        'is_active': True
    },
    {
        'event_type': 'Birthday',
        'price': 5000,
        'max_capacity': 50,
        'people_per_table': 5,
        'description': 'Celebrate your special day',
        'is_active': True
    },
    {
        'event_type': 'Christening',
        'price': 5000,
        'max_capacity': 50,
        'people_per_table': 5,
        'description': 'Baptism and christening events',
        'is_active': True
    },
    {
        'event_type': 'Conference',
        'price': 7000,
        'max_capacity': 100,
        'people_per_table': 10,
        'description': 'Professional conference setup',
        'is_active': True
    },
    {
        'event_type': 'Corporate Event',
        'price': 7000,
        'max_capacity': 100,
        'people_per_table': 10,
        'description': 'Corporate meetings and events',
        'is_active': True
    }
]

print("Setting up Event Types...")
for event_data in default_events:
    event, created = EventType.objects.get_or_create(
        event_type=event_data['event_type'],
        defaults=event_data
    )
    if created:
        print(f"[+] Created: {event.event_type}")
    else:
        print(f"[-] Already exists: {event.event_type}")

print("\nEvent Types setup complete!")
print("You can now manage event types in Django Admin at http://localhost:8000/admin")
