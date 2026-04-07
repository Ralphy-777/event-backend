from django.db import migrations, models
import django.db.models.deletion


def copy_event_type_to_category(apps, schema_editor):
    Video = apps.get_model('user', 'Video')

    for video in Video.objects.all():
        event_type_id = getattr(video, 'event_type_id', None)
        if event_type_id and not getattr(video, 'category_id', None):
            video.category_id = event_type_id
            video.save(update_fields=['category'])


class Migration(migrations.Migration):

    dependencies = [
        ('user', '0030_video_fk_eventtype_add_image_url'),
    ]

    operations = [
        migrations.AddField(
            model_name='video',
            name='category',
            field=models.ForeignKey(
                blank=True,
                help_text='Select the category/event type this video belongs to',
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='video_categories',
                to='user.eventtype',
            ),
        ),
        migrations.RunPython(copy_event_type_to_category, migrations.RunPython.noop),
    ]
