from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('user', '0032_fix_video_remove_event_type_fk'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunSQL(
                    sql="DROP TABLE IF EXISTS user_video CASCADE;",
                    reverse_sql="",
                ),
            ],
            state_operations=[],  # leave state alone — 0034 will delete it
        ),
    ]
