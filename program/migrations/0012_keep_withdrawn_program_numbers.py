from django.db import migrations


def renumber_including_withdrawn(apps, schema_editor):
    Session = apps.get_model('program', 'Session')
    Presentation = apps.get_model('program', 'Presentation')
    assignments = []
    for session in Session.objects.exclude(code__isnull=True).exclude(code=''):
        talks = Presentation.objects.filter(session_id=session.pk).order_by(
            'session_order', 'submission_number', 'pk')
        for position, talk in enumerate(talks, start=1):
            assignments.append((talk.pk, f'{session.code}{position:02d}'))

    numbers = [number for _, number in assignments]
    if len(numbers) != len(set(numbers)):
        raise ValueError('生成されるプログラム番号がセッション間で重複します。')
    coded_session_ids = Session.objects.exclude(code__isnull=True).exclude(code='').values_list('pk', flat=True)
    conflicts = Presentation.objects.exclude(session_id__in=coded_session_ids).filter(
        program_number__in=numbers).exists()
    if conflicts:
        raise ValueError('既存の手動プログラム番号と重複します。')

    Presentation.objects.filter(session_id__in=coded_session_ids).update(program_number=None)
    for pk, number in assignments:
        Presentation.objects.filter(pk=pk).update(program_number=number)


class Migration(migrations.Migration):
    dependencies = [('program', '0011_assign_rooms_to_meetings')]

    operations = [migrations.RunPython(renumber_including_withdrawn, migrations.RunPython.noop)]
