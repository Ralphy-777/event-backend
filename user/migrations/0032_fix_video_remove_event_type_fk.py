from django.db import migrations, models
import django.db.models.deletion


def copy_event_type_to_category(apps, schema_editor):
    Video = apps.get_model('user', 'Video')
    for video in Video.objects.all():
        if not video.category_id and video.event_type_id:
            video.category_id = video.event_type_id
            video.save(update_fields=['category'])


class Migration(migrations.Migration):

    dependencies = [
        ('user', '0031_video_category_fk'),
    ]

    operations = [
        migrations.RunPython(copy_event_type_to_category, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name='video',
            name='event_type',
        ),
        migrations.AlterField(
            model_name='video',
            name='category',
            field=models.ForeignKey(
                blank=True,
                help_text='Select the category/event type this video belongs to',
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='videos',
                to='user.eventtype',
            ),
        ),
    ]
