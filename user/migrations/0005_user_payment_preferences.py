# Generated migration for payment preferences

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('user', '0004_auto_20260303_1856'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='preferred_payment_method',
            field=models.CharField(
                choices=[('Cash', 'Cash'), ('GCash', 'GCash'), ('Card', 'Card')],
                default='Cash',
                max_length=50
            ),
        ),
        migrations.AddField(
            model_name='user',
            name='saved_card_number',
            field=models.CharField(blank=True, max_length=16, null=True),
        ),
    ]
