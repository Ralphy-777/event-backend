from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('user', '0023_booking_payment_deadline'),
    ]

    operations = [
        migrations.AddField(
            model_name='booking',
            name='time_slot',
            field=models.CharField(
                max_length=20,
                default='morning',
                choices=[('morning', 'Morning'), ('afternoon', 'Afternoon'), ('whole_day', 'Whole Day')],
            ),
        ),
    ]
