from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('user', '0022_contactmessage'),
    ]

    operations = [
        migrations.AddField(
            model_name='booking',
            name='payment_deadline',
            field=models.DateTimeField(null=True, blank=True),
        ),
        migrations.AddField(
            model_name='booking',
            name='cancel_reason',
            field=models.TextField(blank=True, default=''),
        ),
    ]
