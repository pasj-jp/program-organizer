from django.db.models.signals import post_delete, pre_delete
from django.dispatch import receiver

from .models import Presentation, Session


@receiver(pre_delete, sender=Presentation)
def remember_session_before_presentation_delete(sender, instance, **kwargs):
    instance._deleted_session_id = Presentation.objects.filter(pk=instance.pk).values_list('session_id', flat=True).first()


@receiver(post_delete, sender=Presentation)
def update_session_after_presentation_delete(sender, instance, **kwargs):
    session_id = getattr(instance, '_deleted_session_id', instance.session_id)
    if session_id:
        session = Session.objects.filter(pk=session_id).first()
        if session:
            session.recalculate_end_time()
            session.recalculate_program_numbers()
