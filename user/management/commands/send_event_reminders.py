from datetime import datetime, timedelta

from django.core.management.base import BaseCommand

from user.mailer import send_html_email
from user.models import Booking


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
            send_html_email(
                subject=f'Reminder: Your {booking.event_type} event is in 3 hours',
                html_body=(
                    f'<h2>Your event starts in 3 hours</h2>'
                    f'<p>Hi {booking.user.first_name}, this is a reminder that your upcoming event is starting soon.</p>'
                    f'<ul>'
                    f'<li><strong>Event:</strong> {booking.event_type}</li>'
                    f'<li><strong>Date:</strong> {booking.date.strftime("%B %d, %Y")}</li>'
                    f'<li><strong>Time:</strong> {booking.time.strftime("%I:%M %p")}</li>'
                    f'<li><strong>Location:</strong> {booking.location}</li>'
                    f'<li><strong>Guests:</strong> {booking.capacity}</li>'
                    f'</ul>'
                    f'<p>Please make sure everything is ready. We look forward to hosting your event.</p>'
                ),
                recipient_list=[booking.user.email],
                plain_text=(
                    f'Hi {booking.user.first_name},\n\n'
                    f'This is a reminder that your upcoming event is starting soon.\n\n'
                    f'Event: {booking.event_type}\n'
                    f'Date: {booking.date.strftime("%B %d, %Y")}\n'
                    f'Time: {booking.time.strftime("%I:%M %p")}\n'
                    f'Location: {booking.location}\n'
                    f'Guests: {booking.capacity}\n\n'
                    f'Please make sure everything is ready. We look forward to hosting your event.\n\n'
                    f'EventPro Team'
                ),
                sync=True,
                fail_silently=False,
            )

            booking.reminder_sent = True
            booking.save()
            count += 1
            self.stdout.write(f'Reminder sent to {booking.user.email} for booking #{booking.id}')

        self.stdout.write(self.style.SUCCESS(f'Done. {count} reminder(s) sent.'))
