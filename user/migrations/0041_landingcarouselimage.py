from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('user', '0040_booking_accepted_at'),
    ]

    operations = [
        migrations.CreateModel(
            name='LandingCarouselImage',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(max_length=150)),
                ('subtitle', models.TextField(blank=True)),
                ('image', models.ImageField(blank=True, null=True, upload_to='landing_carousel/')),
                ('image_url', models.URLField(blank=True, help_text='Paste an image URL if direct upload is unavailable.', max_length=500)),
                ('display_order', models.PositiveIntegerField(default=0)),
                ('is_active', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'verbose_name': 'Landing Carousel Image',
                'verbose_name_plural': 'Landing Carousel Images',
                'ordering': ['display_order', 'id'],
            },
        ),
    ]
