import os
import tempfile

from django.conf import settings
from django.core.files.storage import FileSystemStorage
from django.utils.deconstruct import deconstructible


@deconstructible
class ProceedingsStorage(FileSystemStorage):
    @property
    def base_location(self):
        return settings.PROCEEDINGS_ROOT

    @property
    def location(self):
        return os.path.abspath(self.base_location)

    def get_available_name(self, name, max_length=None):
        # Keep the program code unchanged on replacement.
        return name

    def _save(self, name, content):
        destination = self.path(name)
        os.makedirs(os.path.dirname(destination), exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=os.path.dirname(destination), delete=False) as output:
                temporary = output.name
                for chunk in content.chunks():
                    output.write(chunk)
            os.replace(temporary, destination)
        finally:
            if temporary and os.path.exists(temporary):
                os.unlink(temporary)
        return name
