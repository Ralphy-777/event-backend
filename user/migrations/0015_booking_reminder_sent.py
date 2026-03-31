from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('user', '0014_review'),
    ]

    operations = [
        migrations.AddField(
            model_name='booking',
            name='reminder_sent',
            field=models.BooleanField(default=False),
        ),
    ]
