from datetime import date, datetime, timedelta

from django.db import migrations


def restore_session_end_times(apps, schema_editor):
    Session = apps.get_model('program', 'Session')
    Presentation = apps.get_model('program', 'Presentation')
    for session in Session.objects.all():
        count = Presentation.objects.filter(session_id=session.pk).count()
        duration = count * session.minutes_per_presentation if count else session.empty_duration_minutes
        end_time = None
        if session.start_time and duration:
            end_time = (datetime.combine(session.date or date.today(), session.start_time)
                        + timedelta(minutes=duration)).time()
        if session.end_time != end_time:
            Session.objects.filter(pk=session.pk).update(end_time=end_time)


class Migration(migrations.Migration):
    dependencies = [('program', '0012_keep_withdrawn_program_numbers')]

    operations = [migrations.RunPython(restore_session_end_times, migrations.RunPython.noop)]
