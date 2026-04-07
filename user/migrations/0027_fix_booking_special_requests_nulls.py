from django.db import migrations, models


def backfill_special_requests(apps, schema_editor):
    Booking = apps.get_model('user', 'Booking')
    Booking.objects.filter(special_requests__isnull=True).update(special_requests='')


class Migration(migrations.Migration):

    dependencies = [
        ('user', '0026_eventtype_max_invited_emails_booking_special_requests'),
    ]

    operations = [
        migrations.RunPython(backfill_special_requests, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='booking',
            name='special_requests',
            field=models.TextField(blank=True, default=''),
        ),
    ]
