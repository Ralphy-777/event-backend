from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model

User = get_user_model()

class Command(BaseCommand):
    help = 'Create an organizer user'

    def handle(self, *args, **kwargs):
        email = 'organizer@event.com'
        password = 'ralphy2003'
        
        if User.objects.filter(email=email).exists():
            self.stdout.write(self.style.WARNING('Organizer user already exists'))
            return
        
        user = User.objects.create_user(
            username=email,
            email=email,
            password=password,
            first_name='Event',
            last_name='Organizer'
        )
        user.is_organizer = True
        user.save()
        
        self.stdout.write(self.style.SUCCESS(f'Organizer user created successfully!'))
        self.stdout.write(self.style.SUCCESS(f'Email: {email}'))
        self.stdout.write(self.style.SUCCESS(f'Password: {password}'))
