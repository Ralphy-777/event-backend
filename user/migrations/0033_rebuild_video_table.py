from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('user', '0032_fix_video_remove_event_type_fk'),
    ]

    operations = [
        migrations.RunSQL(
            sql="DROP TABLE IF EXISTS user_video CASCADE;",
            reverse_sql="",
        ),
    ]
