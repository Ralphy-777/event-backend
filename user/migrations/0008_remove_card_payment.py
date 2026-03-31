# Generated migration to remove card payment fields

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('user', '0007_eventtype'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='user',
            name='saved_card_number',
        ),
        migrations.AlterField(
            model_name='user',
            name='preferred_payment_method',
            field=models.CharField(
                choices=[('Cash', 'Cash'), ('GCash', 'GCash')],
                default='Cash',
                max_length=50
            ),
        ),
    ]
