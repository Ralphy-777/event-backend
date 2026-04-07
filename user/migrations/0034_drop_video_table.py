from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('user', '0033_rebuild_video_table'),
    ]

    operations = [
        # Table dropped via raw SQL in 0033. State deletion handled in 0038.
    ]
