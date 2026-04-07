from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('user', '0025_remove_eventpricing'),
    ]

    operations = [
        migrations.AddField(
            model_name='eventtype',
            name='max_invited_emails',
            field=models.IntegerField(default=50),
        ),
        migrations.AddField(
            model_name='booking',
            name='special_requests',
            field=models.TextField(blank=True, default=''),
        ),
    ]
