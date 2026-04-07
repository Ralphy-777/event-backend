from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('user', '0035_galleryvideo'),
    ]

    operations = [
        migrations.AlterField(
            model_name='galleryvideo',
            name='video_file',
            field=models.FileField(blank=True, null=True, upload_to='gallery_videos/', help_text='Upload MP4 video file'),
        ),
    ]
