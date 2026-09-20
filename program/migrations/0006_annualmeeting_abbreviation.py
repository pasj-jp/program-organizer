from django.db import migrations, models
import django.core.validators


def fill_abbreviations(apps, schema_editor):
    AnnualMeeting = apps.get_model('program', 'AnnualMeeting')
    for meeting in AnnualMeeting.objects.all():
        meeting.abbreviation = f'meeting-{meeting.pk}'
        meeting.save(update_fields=['abbreviation'])


class Migration(migrations.Migration):
    dependencies = [('program', '0005_session_minutes_per_presentation')]

    operations = [
        migrations.AddField(
            model_name='annualmeeting',
            name='abbreviation',
            field=models.CharField(max_length=50, null=True, verbose_name='略称'),
        ),
        migrations.RunPython(fill_abbreviations, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='annualmeeting',
            name='abbreviation',
            field=models.CharField(help_text='編成ページのURLに使います（例: PASJ2026）。', max_length=50, unique=True, validators=[django.core.validators.RegexValidator('^[A-Za-z0-9_-]+$', '半角英数字、ハイフン、アンダースコアで入力してください。')], verbose_name='略称'),
        ),
    ]
