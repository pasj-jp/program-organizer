from django.db import migrations
from django.db.models import F


def backfill(apps, schema_editor):
    Presentation = apps.get_model('program', 'Presentation')
    Presentation.objects.filter(session_id__isnull=False).update(confirmed_category=F('category_first'))


class Migration(migrations.Migration):
    dependencies = [('program', '0015_presentation_confirmed_category_sessionchair_and_more')]
    operations = [migrations.RunPython(backfill, migrations.RunPython.noop)]
