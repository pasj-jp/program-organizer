from django.db import migrations


def assign_rooms(apps, schema_editor):
    Room = apps.get_model('program', 'Venue')
    Session = apps.get_model('program', 'Session')
    Presentation = apps.get_model('program', 'Presentation')
    for room in Room.objects.all().order_by('pk'):
        meeting_ids = set(Session.objects.filter(venue_id=room.pk, annual_meeting_id__isnull=False)
                          .values_list('annual_meeting_id', flat=True))
        meeting_ids.update(Presentation.objects.filter(venue_id=room.pk, session__annual_meeting_id__isnull=False)
                           .values_list('session__annual_meeting_id', flat=True))
        for index, meeting_id in enumerate(sorted(meeting_ids)):
            if index == 0:
                room.annual_meeting_id = meeting_id
                room.save(update_fields=['annual_meeting'])
                target_room = room
            else:
                target_room = Room.objects.create(name=room.name, annual_meeting_id=meeting_id)
            Session.objects.filter(venue_id=room.pk, annual_meeting_id=meeting_id).update(venue_id=target_room.pk)
            Presentation.objects.filter(venue_id=room.pk, session__annual_meeting_id=meeting_id).update(
                venue_id=target_room.pk)


class Migration(migrations.Migration):
    dependencies = [('program', '0010_alter_venue_options_venue_annual_meeting_and_more')]

    operations = [migrations.RunPython(assign_rooms, migrations.RunPython.noop)]
