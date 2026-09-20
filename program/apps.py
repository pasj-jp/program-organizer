from django.apps import AppConfig

class ProgramConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'program'
    verbose_name = 'プログラム編成'

    def ready(self):
        from . import signals  # noqa: F401
