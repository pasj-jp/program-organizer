from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('program', '0008_session_empty_duration_minutes')]

    operations = [
        migrations.AddField(
            model_name='session',
            name='board_order',
            field=models.PositiveIntegerField(default=0, verbose_name='編成画面の表示順'),
        ),
    ]
