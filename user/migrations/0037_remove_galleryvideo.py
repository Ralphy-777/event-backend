from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('user', '0036_galleryvideo_allow_blank_video'),
    ]

    operations = [
        migrations.DeleteModel(
            name='GalleryVideo',
        ),
    ]
