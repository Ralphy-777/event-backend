from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('user', '0039_merge_0032_emaildeliverylog_0038_delete_video'),
    ]

    operations = [
        migrations.AddField(
            model_name='booking',
            name='accepted_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
