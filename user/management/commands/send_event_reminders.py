from django.core.management.base import BaseCommand
from django.core.mail import send_mail
from django.conf import settings
from django.utils import timezone
from user.models import Booking
from datetime import datetime, timedelta


class Command(BaseCommand):
    help = 'Send email reminders for events happening in the next 3 hours'

    def handle(self, *args, **kwargs):
        now = datetime.now()
        reminder_window_start = now + timedelta(hours=3)
        reminder_window_end = now + timedelta(hours=3, minutes=10)

        upcoming = Booking.objects.filter(
            status='confirmed',
            reminder_sent=False,
            date=reminder_window_start.date(),
            time__gte=reminder_window_start.time(),
            time__lte=reminder_window_end.time(),
        )

        count = 0
        for booking in upcoming:
            event_datetime = datetime.combine(booking.date, booking.time)
            send_mail(
                subject=f'⏰ Reminder: Your {booking.event_type} event is in 3 hours!',
                message=(
                    f'Hi {booking.user.first_name},\n\n'
                    f'This is a reminder that your upcoming event is starting soon!\n\n'
                    f'📅 Event: {booking.event_type}\n'
                    f'📆 Date: {booking.date.strftime("%B %d, %Y")}\n'
                    f'🕐 Time: {booking.time.strftime("%I:%M %p")}\n'
                    f'📍 Location: {booking.location}\n'
                    f'👥 Guests: {booking.capacity}\n\n'
                    f'Please make sure everything is ready. We look forward to hosting your event!\n\n'
                    f'— EventPro Team'
                ),
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[booking.user.email],
                fail_silently=False,
            )

            booking.reminder_sent = True
            booking.save()
            count += 1
            self.stdout.write(f'Reminder sent to {booking.user.email} for booking #{booking.id}')

        self.stdout.write(self.style.SUCCESS(f'Done. {count} reminder(s) sent.'))
