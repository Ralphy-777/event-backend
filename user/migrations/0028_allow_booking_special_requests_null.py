from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('user', '0027_fix_booking_special_requests_nulls'),
    ]

    operations = [
        migrations.AlterField(
            model_name='booking',
            name='special_requests',
            field=models.TextField(blank=True, null=True, default=''),
        ),
    ]
