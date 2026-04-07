from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('user', '0037_remove_galleryvideo'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[],  # table already dropped via raw SQL in 0033
            state_operations=[
                migrations.DeleteModel(name='Video'),
            ],
        ),
    ]
