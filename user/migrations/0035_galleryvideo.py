from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('user', '0034_drop_video_table'),
    ]

    operations = [
        migrations.CreateModel(
            name='GalleryVideo',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(max_length=200)),
                ('video_file', models.FileField(upload_to='gallery_videos/', help_text='Upload MP4 video file')),
                ('thumbnail', models.ImageField(blank=True, null=True, upload_to='gallery_thumbnails/', help_text='Optional thumbnail image')),
                ('description', models.TextField(blank=True)),
                ('category', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='gallery_videos', to='user.eventtype')),
                ('order', models.IntegerField(default=0, help_text='Lower number = appears first')),
                ('is_active', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
            ],
            options={
                'verbose_name': 'Gallery Video',
                'verbose_name_plural': 'Gallery Videos',
                'ordering': ['order', '-created_at'],
            },
        ),
    ]
